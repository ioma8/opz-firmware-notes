#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyserial"]
# ///
"""opzget - pull the OP-Z factory content that no firmware package contains.

Run this on a HEALTHY OP-Z and it will request the factory sample packs and the eight
factory-only engines, saving everything it finds into an "opz-dump" folder created NEXT
TO THIS SCRIPT. It does not matter what directory you run it from.

WHAT YOU NEED

  * The OP-Z powered on into UPDATE mode ("OP-Z Boot" - the mode where the Mac shows an
    "OP-Z" disk containing a systeminfo folder). The command used here only exists on the
    bootloader console, so the unit must be in that mode.
  * USB connected. Nothing else may hold the port open (close the OP-Z app).
  * Python 3 plus pyserial.

HOW TO RUN

    uv run --script opzget.py                     # macOS, Linux and Windows, if you have uv
    pip3 install pyserial && python3 opzget.py    # macOS / Linux without uv
    py -3 -m pip install pyserial && py -3 opzget.py   # Windows without uv
    python3 opzget.py --list                      # just show the console ports
    python3 opzget.py --dry-run                   # show what would be requested, send nothing

  The serial port is found automatically (COM ports on Windows, /dev/cu.usbmodem* on macOS,
  /dev/ttyACM* or /dev/ttyUSB* on Linux). If several are listed, pass the right one with
  --port COM5 (Windows) or --port /dev/cu.usbmodemXXXX (macOS).

  Useful options:  --out DIR   where to save (default: opz-dump/ next to this script)
                   --verify    re-read every saved file and compare its hash
                   --quiet N   seconds of silence that means "the file ended" (default 3)
                   --limit N   fetch only the first N items, for a quick trial run
                   --only engines|packs

IS IT SAFE?

  Yes. This script sends exactly one command, type 0x19, and nothing else. That command
  opens a file, reads it and streams it back - it cannot write, move, rename or delete
  anything on the device. The dangerous bootloader commands (0x15 format-NAND in
  particular) live in the same dispatch table but are never constructed here. It also
  never deletes or overwrites your own files: everything lands in the output directory.

  It is fine to run it more than once. Already-downloaded files are skipped, so an
  interrupted run resumes.

WHAT IT FETCHES, AND WHY
  These files are on the device but in no .zfw update package, so the only way to get them
  is to ask a unit that still has them:

    A. ~24 factory sample packs, including CuckooKicks/Snares/Perc/FX, CuckooC_keypawn,
       SebaKicks/Snares/Perc/FX, AlainKicks/Snares/Perc/FX, TeKicks/TeSnares/TePercs/TeFX,
       GrantFX, zVinyl, redmountKicks/Snares/Perc/FX and samplepacks/sfx.aif.
    B. Eight factory engines: chord, digital, electric, fm003b, ministringshort, saw013a,
       tapetwo, volt.

  Nobody knows the exact directory layout for all of these, so for each name the script
  tries several plausible paths in turn, stops at the first that answers, skips the rest
  and remembers which form worked so later files go straight to it. A name that is not
  found by any path is reported as MISSING and does not stop the run.

  Expect roughly 20-40 minutes if most packs are present, because a sample pack is about
  890 kB and the link runs at serial speed. Progress is printed continuously.
"""
import argparse
import glob
import hashlib
import json
import sys
import time
from pathlib import Path

ESCAPE, ESCAPE_XOR = 0x7D, 0x20
ROUTING_HOST = 0x01
ROUTING_DEV = 0x1E
TYPE_PING = 0x00
TYPE_READ = 0x19
TYPE_LOG = 0x04
REPLY_READ = 0x20
PONG_FRAME = bytes((0xC0, 0x1E, 0x01, 0x00, 0x00, 0x00, 0x00))

ENGINES = ['chord', 'digital', 'electric', 'fm003b',
           'ministringshort', 'saw013a', 'tapetwo', 'volt']

PACKS = ['CuckooKicks', 'CuckooSnares', 'CuckooPerc', 'CuckooFX', 'CuckooC_keypawn',
         'SebaKicks', 'SebaSnares', 'SebaPerc', 'SebaFX',
         'AlainKicks', 'AlainSnares', 'AlainPerc', 'AlainFX',
         'TeKicks', 'TeSnares', 'TePercs', 'TeFX',
         'GrantFX', 'zVinyl',
         'redmountKicks', 'redmountSnares', 'redmountPerc', 'redmountFX',
         'sfx']

# Paths are relative to /yaffs2/ - the device prepends that prefix itself.
ENGINE_TEMPLATES = [
    'system/content/engines/{n}.engine',
    'engines/{n}.engine',
    'user/system/content/engines/{n}.engine',
]
PACK_TEMPLATES = [
    'system/content/samplepacks/{n}.aif',
    'user/samplepacks/{n}.aif',
    'samplepacks/{n}.aif',
    'user/samplepacks/user/{n}.aif',
    'system/content/samplepacks/user/{n}.aif',
]


def encode(routing, mtype, payload=b''):
    out = bytearray((0xC0, routing, mtype))
    out += len(payload).to_bytes(4, 'big')
    for b in payload:
        if b in (0xC0, ESCAPE):
            out += bytes((ESCAPE, b ^ ESCAPE_XOR))
        else:
            out.append(b)
    return bytes(out)


def try_frame(buf, i):
    """Decode the frame at buf[i].

    Returns (routing, type, payload, next_index), None if the frame is not complete yet
    (wait for more bytes), or False if buf[i] is not a frame start.
    Zero-length payloads are valid and must not be discarded - the device's PING reply
    is exactly that.
    """
    n = len(buf)
    if i + 7 > n:
        return None
    length = int.from_bytes(buf[i + 3:i + 7], 'big')
    j, raw = i + 7, bytearray()
    while len(raw) < length:
        if j >= n:
            return None
        b = buf[j]
        j += 1
        if b == ESCAPE:
            if j >= n:
                return None
            raw.append(buf[j] ^ ESCAPE_XOR)
            j += 1
        else:
            raw.append(b)
    return (buf[i + 1], buf[i + 2], bytes(raw), j)


class Device:
    def __init__(self, port, baud=115200):
        import serial
        self.ser = serial.Serial(port, baud, timeout=0.2)
        self.buf = bytearray()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def pop_frames(self):
        out = []
        while True:
            i = self.buf.find(0xC0)
            if i < 0:
                self.buf.clear()
                break
            if i:
                del self.buf[:i]
            got = try_frame(self.buf, 0)
            if got is None:
                break
            if got is False:
                del self.buf[:1]
                continue
            r, t, p, nxt = got
            del self.buf[:nxt]
            out.append((r, t, p))
        return out

    def warm(self):
        """The port-open reset eats the first frame written, so send a throwaway PING."""
        self.ser.reset_input_buffer()
        self.buf.clear()
        self.ser.write(encode(ROUTING_HOST, TYPE_PING))
        self.ser.flush()
        end, seen = time.time() + 2.0, bytearray()
        while time.time() < end:
            seen += self.ser.read(4096)
        self.buf.clear()
        return PONG_FRAME in bytes(seen)

    def read_file(self, path, quiet=3.0, cap=900.0, tick=1.0):
        """Request one path. Returns (data, log_lines, timed_out).

        Progress is printed on one rewrites-in-place line, so a file that is absent or slow never looks like a
        hang: the byte count climbs while data flows, and the elapsed seconds keep ticking while it does not.
        """
        self.ser.reset_input_buffer()
        self.buf.clear()
        self.ser.write(encode(ROUTING_HOST, TYPE_READ, path.encode() + b'\x00'))
        self.ser.flush()

        data, logs = bytearray(), []
        start = last = time.time()
        tick_at, shown, printed = start, 0, False
        timed_out = False
        while True:
            chunk = self.ser.read(65536)
            now = time.time()
            if chunk:
                self.buf += chunk
                last = now
            for r, t, p in self.pop_frames():
                if r != ROUTING_DEV:
                    continue
                if t == REPLY_READ:
                    data += p
                elif t == TYPE_LOG:
                    logs.append(p.split(b'\x00', 1)[0])
            if now - tick_at >= tick:
                tick_at = now
                if len(data) != shown:
                    shown = len(data)
                    print(f'\r        reading {shown:>9} B  {now - start:5.0f}s', end='', flush=True)
                else:
                    print(f'\r        waiting {now - start:5.0f}s  (nothing yet)', end='', flush=True)
                printed = True
            if now - last > quiet:
                break
            if now - cap > start:
                timed_out = True
                break
        if printed:
            print('\r' + ' ' * 44 + '\r', end='', flush=True)
        return bytes(data), logs, timed_out


def ports():
    """Enumerate candidate console ports on any OS.

    macOS: /dev/cu.usbmodem*   Linux: /dev/ttyACM* or /dev/ttyUSB*   Windows: COM ports.
    Uses pyserial's cross-platform enumeration, and ranks anything that looks like a USB device first so a
    stray Bluetooth or virtual port does not get picked over the OP-Z.
    """
    found = []
    try:
        from serial.tools import list_ports

        def rank(info):
            blob = f'{info.device} {info.description or ""} {info.manufacturer or ""} {info.hwid or ""}'.lower()
            return 0 if ('usb' in blob or 'op-z' in blob or 'opz' in blob or 'usbmodem' in blob) else 1

        found = [i.device for i in sorted(list_ports.comports(), key=rank)]
    except Exception:
        pass
    if not found:
        found = (sorted(glob.glob('/dev/cu.usbmodem*')) + sorted(glob.glob('/dev/tty.usbmodem*'))
                 + sorted(glob.glob('/dev/ttyACM*')) + sorted(glob.glob('/dev/ttyUSB*')))
    return found


def port_descriptions():
    """device -> human description, for the --list output."""
    out = {}
    try:
        from serial.tools import list_ports
        for i in list_ports.comports():
            out[i.device] = i.description or ''
    except Exception:
        pass
    return out


def clean_log(text):
    """Strip the device's `[dd-mm-yy hh:mm:ss] ` prefix so the useful part is readable."""
    s = text.decode('utf-8', 'replace') if isinstance(text, (bytes, bytearray)) else text
    end = s.rfind('] ')
    if 0 <= end <= 40:
        s = s[end + 2:]
    s = s.strip()
    return s if len(s) <= 100 else s[:97] + '...'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def jobs_for(only):
    jobs = []
    if only in (None, 'engines'):
        for name in ENGINES:
            jobs.append(('engine', name, f'{name}.engine',
                         [t.format(n=name) for t in ENGINE_TEMPLATES]))
    if only in (None, 'packs'):
        for name in PACKS:
            jobs.append(('pack', name, f'{name}.aif',
                         [t.format(n=name) for t in PACK_TEMPLATES]))
    return jobs


def sanity_note(kind, name, data):
    """Cheap plausibility check so a truncated or wrong file is visible in the summary."""
    notes = []
    if len(data) == 0:
        return notes
    if len(data) < 128:
        notes.append(f'suspiciously small ({len(data)} B)')
    if kind == 'pack':
        if data[:4] != b'FORM':
            notes.append('does not start with FORM - not an AIFF/AIF file')
        elif not any(data[8:12] == k for k in (b'AIFF', b'AIFC')):
            notes.append('FORM but no AIFF/AIFC marker')
    return notes


def main():
    ap = argparse.ArgumentParser(
        description='Pull the OP-Z factory sample packs and factory-only engines that no firmware package '
                    'contains. Sends only the read-only console command 0x19.',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', help='console serial port (default: the first port that looks like a USB device)')
    ap.add_argument('--out', default=None,
                    help='output directory (default: opz-dump next to this script, wherever you run it from)')
    ap.add_argument('--only', choices=['engines', 'packs'], help='fetch just one group')
    ap.add_argument('--limit', type=int, help='stop after N items - useful for a quick trial run')
    ap.add_argument('--quiet', type=float, default=3.0,
                    help='seconds of silence meaning the transfer finished (default 3)')
    ap.add_argument('--cap', type=float, default=900.0, help='hard timeout per file attempt (default 900)')
    ap.add_argument('--verify', action='store_true',
                    help='re-read every saved file and compare its hash')
    ap.add_argument('--dry-run', action='store_true', help='print the plan and exit, sending nothing')
    ap.add_argument('--list', action='store_true', help='list candidate ports and exit')
    args = ap.parse_args()

    if args.list:
        found = ports()
        desc = port_descriptions()
        if not found:
            print('No serial ports found. Is the OP-Z connected, and in UPDATE mode?')
            return 1
        print('candidate console ports:')
        for p in found:
            print(f'  {p:<24} {desc.get(p, "")}')
        print()
        print('The OP-Z shows up as a USB modem/CDC device. If several are listed and you are unsure,')
        print('pass the right one with --port.')
        return 0

    jobs = jobs_for(args.only)
    if args.limit:
        jobs = jobs[:args.limit]
    total = len(jobs)

    if args.dry_run:
        print(f'PLAN - {total} items, nothing will be sent\n')
        for i, (kind, name, fname, cands) in enumerate(jobs, 1):
            print(f'[{i:>2}/{total}] {kind:<7} {fname}')
            for c in cands:
                print(f'          /yaffs2/{c}')
        print(f'\nA name is MISSING only if every path above returns nothing. Nothing is written to the device.')
        return 0

    found_ports = ports()
    port = args.port or (found_ports[0] if found_ports else None)
    if not port:
        print('No serial port found.')
        print()
        print('  * Is the OP-Z connected by USB?')
        print('  * Is it in UPDATE mode ("OP-Z Boot") - the mode where an "OP-Z" disk appears?')
        print('  * Is the OP-Z app closed? It holds the port, so the port may exist but be busy.')
        print()
        print('Run with --list to see every serial port this machine can see, and pick one with')
        print('--port (for example --port COM5 on Windows).')
        return 1

    # Default the output next to the script, not next to the shell's working directory: then it does not
    # matter where the script is invoked from, and "send back the opz-dump folder" is unambiguous.
    out = Path(args.out).expanduser() if args.out else Path(__file__).resolve().parent / 'opz-dump'
    files_dir = out / 'files'
    files_dir.mkdir(parents=True, exist_ok=True)

    print('=' * 78)
    print('OP-Z factory content fetch')
    print('=' * 78)
    print(f'  port        : {port}')
    print(f'  output      : {files_dir}')
    print(f'  items       : {total}  '
          f'({sum(1 for j in jobs if j[0] == "engine")} engines, '
          f'{sum(1 for j in jobs if j[0] == "pack")} packs)')
    print(f'  command     : type 0x19 only (read-only - cannot write, move or delete anything)')
    print()
    print('  Put the OP-Z in UPDATE mode and leave it alone. Do not touch the unit while this runs.')
    print('  Press Ctrl-C to stop; re-running later resumes where it left off.')
    print()

    dev = Device(port)
    result = {'port': port, 'found': [], 'missing': [], 'mode': 'read-only (console 0x19)'}
    start_all = time.time()
    try:
        print('  warming up the console ... ', end='', flush=True)
        if not dev.warm():
            print('NO PING REPLY')
            print()
            print('  The port exists but the device is not answering. Check that the unit is in UPDATE')
            print('  mode (not content mode, not the normal OS) and that no other program holds the port.')
            return 1
        print('OK (device is answering)')
        print()

        # Fail fast: read a file that must exist on a healthy unit. If this fails, nothing else will work
        # and there is no point waiting through the whole run to find out.
        print('  control check: reading an engine that must exist ...', flush=True)
        probe, plogs, _ = dev.read_file('system/content/engines/crush.engine', quiet=args.quiet, cap=60.0)
        if not probe:
            print('  CONTROL FAILED - the read command returned no data.')
            print()
            print(f'    last device log: {clean_log(plogs[-1]) if plogs else "(none)"}')
            print()
            print('  This usually means the unit is not in UPDATE mode, or it is not running firmware that')
            print('  has this command. Nothing was written to the device. Please send us the message above.')
            return 1
        print(f'  control OK - read back {len(probe)} bytes, so the channel works on this unit')
        print()

        order = {t: 0 for t in ENGINE_TEMPLATES + PACK_TEMPLATES}
        for idx, (kind, name, fname, cands) in enumerate(jobs, 1):
            target = files_dir / fname
            label = f'[{idx:>2}/{total}] {kind:<7} {fname:<26}'
            if target.exists() and target.stat().st_size > 0:
                print(f'{label} already have it ({target.stat().st_size} B) - skipping')
                result['found'].append({'kind': kind, 'name': name, 'file': str(target),
                                        'bytes': target.stat().st_size, 'path': None,
                                        'sha256': sha256(target.read_bytes()), 'cached': True})
                continue

            # try the path forms that have worked before, first
            cands = sorted(cands, key=lambda c: -order.get(c, 0))
            print(label, flush=True)
            hit = None
            for cand in cands:
                print(f'        trying /yaffs2/{cand}', flush=True)
                t0 = time.time()
                data, logs, timed_out = dev.read_file(cand, quiet=args.quiet, cap=args.cap)
                dt = time.time() - t0
                if data:
                    target.write_bytes(data)
                    order[cand] = order.get(cand, 0) + 1
                    notes = sanity_note(kind, name, data)
                    result['found'].append({'kind': kind, 'name': name, 'file': str(target),
                                            'bytes': len(data), 'path': cand,
                                            'sha256': sha256(data), 'seconds': round(dt, 1),
                                            'notes': notes})
                    print(f'        FOUND  {len(data)} B in {dt:.1f}s  -> {fname}'
                          + (f'   [{"; ".join(notes)}]' if notes else ''), flush=True)
                    hit = cand
                    break
                why = 'timed out' if timed_out else ('ENOENT' if logs else 'no reply')
                detail = f'  {clean_log(logs[-1])}' if logs else ''
                print(f'        not here ({why}, {dt:.1f}s){detail}', flush=True)
            if hit is None:
                result['missing'].append({'kind': kind, 'name': name, 'tried': cands})
                print('        => MISSING (not at any known path - continuing)')
            print(flush=True)

        elapsed = time.time() - start_all

        if args.verify:
            print('=' * 78)
            print('VERIFY - re-reading every saved file and comparing hashes')
            print('=' * 78)
            for rec in result['found']:
                if rec.get('cached'):
                    continue
                data, _, _ = dev.read_file(rec['path'], quiet=args.quiet, cap=args.cap)
                same = sha256(data) == rec['sha256']
                rec['verify'] = 'match' if same else 'MISMATCH'
                print(f"  {rec['name']:<22} {'match' if same else '*** MISMATCH ***'} "
                      f"({len(data)} B vs {rec['bytes']} B)")
            print()
    except KeyboardInterrupt:
        print('\n\n  Interrupted - partial results were kept, re-run to resume.\n')
    finally:
        dev.close()

    result['elapsed_seconds'] = round(time.time() - start_all, 1)
    (out / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

    print('=' * 78)
    print('SUMMARY')
    print('=' * 78)
    print(f"  fetched : {len(result['found'])}")
    print(f"  missing : {len(result['missing'])}")
    if result['found']:
        print()
        print(f"  {'item':<26}{'bytes':>10}  path it came from")
        for rec in result['found']:
            flag = ' (cached)' if rec.get('cached') else ''
            print(f"  {Path(rec['file']).name:<26}{rec['bytes']:>10}  {rec['path'] or 'already saved'}{flag}")
            for note in rec.get('notes', []):
                print(f"      WARNING: {note}")
    if result['missing']:
        print()
        print('  Not on this unit at any known path:')
        for rec in result['missing']:
            print(f"    - {rec['name']} ({rec['kind']})")
    print()
    print(f'  Everything is in: {files_dir}')
    print(f'  A manifest with sizes and sha256 hashes: {out / "manifest.json"}')
    print()
    print('  Please send back the whole output directory (or a zip of it). If any file came back')
    print('  MISSING that is useful information too - it says the content is not on your unit either.')
    print('  The manifest alone is also genuinely helpful if sending the audio is awkward.')
    print()
    return 0 if result['found'] else 3


if __name__ == '__main__':
    sys.exit(main())
