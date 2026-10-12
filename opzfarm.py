#!/usr/bin/env python3
"""OP-Z unattended firmware decode farm (restart-safe, self-healing).

Each cycle stages ONE crafted probe, ejects, and captures the console: the
bootloader decrypts the archive, prints the decrypted 0x300 name field, fails the
.zip check and aborts.  A leaking window therefore cannot also complete the
upgrade, so the medium does NOT come back on its own -- one power cycle per
window is the real cost (see FIRMWARE_ANALYSIS.md 65 and 66).

What was wrong before the review-2 patch (see 66.1-66.5) and is fixed here:
  * craft() spliced ciphertext at 0x400+idx with no 16-byte alignment, so every
    window at a non-multiple of 16 decrypted to pseudorandom bytes -- and
    re-reading the same probe reproduced them, which looked like verification;
  * parse_cycle() copied raw stream bytes, never undid the 7D escape, and stopped
    only on the rare 'C0 2E 04' routing, so a following frame header (routing 0x1E
    is the COMMON one, 151/170 in the genuine capture) could be absorbed;
  * advance() moved an interval forward when a probe produced nothing, silently
    deleting unknown bytes;
  * GROUND_TRUTH mixed in bytes read at unaligned offsets, so the farm asserted
    and re-derived its own garbage.
Each byte now also gets provenance (st["reads"], plus the cycle's raw capture).
"""
import glob, json, re, subprocess, sys, time, traceback
from pathlib import Path
import serial

SRC = Path('/Users/jakubkolcar/projects/customs/opz-firmware-notes/z_firmware_1_2_45.zfw')
VOL = Path('/Volumes/OP-Z')
def volpath():
    import glob as _g
    c = [p for p in _g.glob('/Volumes/OP-Z*') if (Path(p)/'systeminfo').is_dir()]
    return Path(c[0]) if c else None
F, WIN, ZIP_LEN = 0x400, 256, 1490575
FRAME_MAX = 128        # device log-message payload ceiling (measured, see 66.3)
LEAK_PREFIX = b'failed to find .zip file in '
TICK = 4               # tick bytes before the log text in a frame payload
MASKED = [True]        # never auto-flipped any more: the mask is what lets a NUL
                       # inside the first block print at all (see handle_mismatch)
MASK_DELTA = [1]       # IV is XORed by this value; the caller must undo the SAME one.
                       # It is a free choice, not a constant: a true byte equal to the
                       # delta becomes 0x00 and stops the print, so picking a delta that
                       # avoids the block's values makes block 0 fully readable (66.13).
LAST = {"leaks": 0, "truncated": 0, "marker": 0}   # last parse_cycle() outcome, for provenance
STATE = Path('/tmp/opzfarm_state.json')
MAP   = Path('/tmp/opzfarm_map.json')
LOG   = Path('/tmp/opzfarm.log')
DURABLE_LOG = Path.home() / '.opz-decode' / 'opzfarm.log'   # survives reboots
MAXC  = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
N     = int(sys.argv[2]) if len(sys.argv) > 2 else 1


# ---- ground truth recovered from verified hardware reads -------------------
# (offset, expected byte).  HARDWARE VERIFIED 2026-10-10 by the first ALIGNED read
# through the corrected decoder (raws/w0_masked_20261010-193009.bin):
#
#   50 4b 03 04 14 00 | 00 00 | 08 00 | 62 70 | 7f 54 | 47 9c 68 3c | c9 00
#   PK\x03\x04 ver=20  flags=0  DEFLATE  time    date=2022-03-31  crc32       csize..
#
# i.e. an ordinary zip local header with method 8 (Deflate) and a real build date.
# The previous constant (`... c0 1e 04 00 00 00 49 fb be 94 19 5b`) was WRONG: it
# contained NUL bytes, and a parser that stops on NUL cannot have produced it, so it
# was a hand-pasted value -- which is why a console frame header (c0 1e 04) sat in
# the middle of a supposedly observed payload and why the whole 'nameless archive /
# no central directory / flags 0x1ec0 / method 4' chain downstream was fiction
# (see 66.8 and 66.12).
def ground_truth():
    gt = {}
    hdr = bytes([0x50,0x4b,0x03,0x04,0x14,0x00,0x00,0x00,0x08,0x00,0x62,0x70,
                 0x7f,0x54,0x47,0x9c,0x68,0x3c,0xc9,0x00])
    for i,b in enumerate(hdr): gt[i]=b
    return gt
GROUND_TRUTH = ground_truth()

def verify_ground_truth(st):
    """Return (checked, mismatches) comparing recovered bytes to known-good reads."""
    checked = 0; bad = []
    for off, want in GROUND_TRUTH.items():
        got = st["bytes"].get(str(off))
        if got is None: continue
        checked += 1
        if got != want: bad.append((off, got, want))
    return checked, bad


# ---- single instance guard: two farms writing the same state would corrupt it ----
import fcntl
_lock_fh = None
def acquire_lock():
    global _lock_fh
    _lock_fh = open('/tmp/opzfarm.lock', 'w')
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another farm already holds the lock -- exiting", flush=True)
        sys.exit(0)
    _lock_fh.write(str(__import__('os').getpid())); _lock_fh.flush()

def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    for path in (LOG, DURABLE_LOG):
        try: open(path, 'a').write(line + "\n")
        except Exception: pass

def port():
    p = glob.glob('/dev/cu.usbmodem*')
    return p[0] if p else None

def _open_port(p, timeout=1):
    """Open the console, or raise.  `serial.Serial(None)` succeeds but yields a
    *closed* object, so a bare reopen can hand back a dead handle and blind the
    whole capture -- fail loudly instead."""
    if not p: raise serial.SerialException('no console port present')
    return serial.Serial(p, 115200, timeout=timeout)

CAP_SECS = 45          # the device reads within ~3 s of the eject; 300 s was pure wait

def wait_vol(timeout=3600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if volpath() is not None:
                return True
        except Exception: pass
        time.sleep(1)
    return False

def align16(idx):
    """The window actually readable for a requested offset (66.1)."""
    return idx - (idx % 16)


def craft(idx, mask_first=None):
    if mask_first is None: mask_first = MASKED[0]
    """Crafted probe for the window at `idx`.

    CBC: name field block 0 is D(C) XOR IV, and the payload chain is continuous, so
    the window MUST start on a 16-byte boundary (idx is aligned here).  A splice at
    a non-multiple of 16 makes D() pseudorandom -- the bug behind 66.1.

    XORing the IV by 0x01 shifts that first block, so a NUL inside the first 16
    bytes prints as 0x01 and no longer truncates the leak.  Callers un-shift those
    bytes (see parse_cycle).  Note the window is still capped at ~65 bytes by the
    device's log buffer (66.3)."""
    idx = align16(idx)
    d = SRC.read_bytes(); s = F + idx
    win = d[s:s+WIN]
    if len(win) < WIN:                     # near the end of the payload: clip and zero-pad
        win = win + bytes(WIN - len(win))
    out = bytearray(d[0:0x400])
    iv = bytearray(d[s-16:s])
    if mask_first:
        dl = MASK_DELTA[0]
        for i in range(16): iv[i] ^= dl
    out[0x70:0x80] = iv
    out[0x300:0x400] = win
    out += d[0x400:0x420]
    return bytes(out)


def stage_cycle(vol, targets):
    """Clean the volume and write the crafted probes plus the genuine archive.
    Returns the number of probe files written.  Shared by main() and the tests."""
    n = 0
    try:
        for f in vol.iterdir():
            if f.name != 'systeminfo' and f.is_file(): f.unlink()
    except Exception as e:
        log(f"clean err {e}")
    import os as _os
    _os.environ['COPYFILE_DISABLE'] = '1'      # stop macOS writing "._" sidecars
    for i, (s, e) in enumerate(targets):
        (vol / f"z_firmware_probe_{i:03d}.zfw").write_bytes(craft(s)); n += 1
    # The bootloader reads only the FIRST matching candidate per scan (it aborts the
    # update on the first failure), so extra probes are pure waste -- and every file
    # written on macOS also spawns a "._" AppleDouble sidecar whose name contains
    # "firmware" too, so it is compared as well.  Keep the volume minimal.
    (vol / 'z_firmware_z_1_2_45.zfw').write_bytes(SRC.read_bytes())
    try:
        for f in list(vol.iterdir()):
            if f.name.startswith('._'): f.unlink()
    except Exception: pass
    subprocess.run(['sync'])
    return n

def normalize_pending(st):
    """Every interval must START on a readable 16-byte boundary.

    craft() aligns the window it reads, but the leaked bytes are filed at
    `interval_start + i`, so an unaligned interval start would shift a whole window
    by up to 15 bytes -- the same class of error as 66.1, one level up.  Snapping a
    start DOWN can only re-read bytes already known, never invent any."""
    out = []
    for s, e in st["pending"]:
        s = align16(s)
        if e > s and [s, e] not in out: out.append([s, e])
    st["pending"] = out
    return st


def migrate(st):
    """Drop every byte whose contiguous run did not start on a 16-byte boundary.

    The pre-review map was 308 of 327 bytes (94%) at unaligned offsets, i.e. the
    product of misaligned reads, so keeping it would poison the rebuild (66.1).
    The dropped ranges go back on the worklist, aligned.  Returns bytes dropped."""
    known = sorted(int(k) for k in st["bytes"])
    if not known: return 0
    runs, s, p = [], known[0], known[0]
    for o in known[1:]:
        if o == p + 1: p = o
        else: runs.append((s, p + 1)); s = o; p = o
    runs.append((s, p + 1))
    dropped = 0
    for a, b in runs:
        if a % 16 == 0: continue
        for o in range(a, b):
            st["bytes"].pop(str(o), None); dropped += 1
        st["pending"].append([align16(a), b])
    return dropped


def load():
    if STATE.exists():
        try:
            st = json.loads(STATE.read_text())
            if "reads" not in st:              # pre-review state: rebuild it
                d = migrate(st)
                st["reads"] = []
                st["migrated"] = f"review-2: dropped {d} unaligned byte(s)"
                log(f"migrating pre-review state: dropped {d} byte(s) read at unaligned offsets")
                normalize_pending(st)
                save(st)
            return normalize_pending(st)
        except Exception: pass
    # Seed the worklist as one interval per window rather than one big interval,
    # otherwise the first cycles issue only 1, 2, 3... probes and throughput ramps slowly.
    pend = [[i, min(i + WIN, ZIP_LEN)] for i in range(0, ZIP_LEN, WIN)]
    return {"pending": pend, "bytes": {}, "reads": [], "cycles": 0, "miss": 0}

def save(st):
    blob = json.dumps(st)
    STATE.write_text(blob)
    MAP.write_text(json.dumps(st["bytes"]))
    # durable copy: /tmp is cleared on reboot, so keep progress in ~/.opz-decode too
    try:
        d = Path.home() / '.opz-decode'
        if d.is_dir():
            (d / 'opzfarm_state.json').write_text(blob)
            (d / 'opzfarm_map.json').write_text(json.dumps(st["bytes"]))
    except Exception:
        pass

def frames(buf):
    """Decode the console stream into (routing, type, payload) frames.

    A frame is C0 routing type len_be32 payload, with 0x7D escaping the next byte as
    byte^0x20.  The length is honoured, which is the whole point: the old parser
    copied raw bytes and stopped only at 'C0 2E 04', but routing 0x1E is the COMMON
    log routing (151 of 170 frames in the genuine capture), so a frame header could
    be absorbed into a window and shift every later offset (66.2).

    Reference implementation with a self-test: ~/.opz-decode/toolkit/opzframe.py.
    Kept inline because the farm must stay self-contained under launchd."""
    ES, EX, n = 0x7D, 0x20, len(buf)
    i, out = 0, []
    while i < n:
        if buf[i] != 0xC0: i += 1; continue
        if i + 7 > n: break
        ln = int.from_bytes(buf[i+3:i+7], 'big')
        if ln == 0 or ln > n - i - 7: i += 1; continue
        j, raw = i + 7, bytearray()
        while len(raw) < ln and j < n:
            b = buf[j]; j += 1
            if b == ES and j < n: raw.append(buf[j] ^ EX); j += 1
            else: raw.append(b)
        out.append((buf[i+1], buf[i+2], bytes(raw)))
        i = j
    return out


def parse_cycle(buf, targets, masked=None):
    if masked is None: masked = MASKED[0]
    """Return ({offset: byte}, set(probe indices), total bytes recovered).

    Frames are decoded first (escapes undone), so a leak window is exactly the text
    of its own frame.  A probe is tracked across messages: the 'detected encrypted
    file /z_firmware_probe_NNN.zfw' frame opens it, the following 'failed to find
    .zip file in ...' frame closes it.

    Truncation matters: the device's log payload tops out at FRAME_MAX (128) bytes
    (66.3), and a capped frame's last byte is the buffer's NUL, NOT a NUL in the
    window -- so a terminator is only recorded when the frame was NOT capped.
    Otherwise a byte that was never observed would be invented as 0x00."""
    st_bytes, produced, got = {}, set(), 0
    LAST["leaks"] = LAST["truncated"] = LAST["marker"] = 0
    cur = None
    for routing, typ, p in frames(buf):
        m = re.search(rb'detected encrypted file /z_firmware_probe_(\d+)', p)
        if m:
            j = int(m.group(1))
            cur = j if j < len(targets) else None
            continue
        if cur is None: continue
        k = p.find(LEAK_PREFIX)
        if k < 0: continue
        hay = p[k+len(LEAK_PREFIX):]
        capped = len(p) >= FRAME_MAX
        term = hay.endswith(b'\x00')
        data = hay[:-1] if term else hay
        # A capped message was truncated by the logger, which appends a '..' marker:
        # measured on EVERY capped leak in the captures (3/3) and on no short one, with
        # the byte arithmetic closing exactly -- 4 tick + 58 text + 63 data + 2 marker
        # + 1 NUL = 128, the ceiling.  So those two bytes are not payload and are dropped.
        if capped and data.endswith(b'..'):
            data = data[:-2]
            LAST["marker"] += 1
        s, e = targets[cur]
        if s >= ZIP_LEN:            # worklist beyond the payload: nothing to read
            cur = None; continue
        produced.add(cur)
        LAST["leaks"] += 1
        if capped: LAST["truncated"] += 1
        for off, b in enumerate(data):
            if s + off >= ZIP_LEN: break
            st_bytes[str(s + off)] = (b ^ MASK_DELTA[0]) if (masked and off < 16) else b
        got += min(len(data), max(0, ZIP_LEN - s))
        # Only a frame that stopped short of the cap ended on a real NUL, and that
        # byte is then proven data (the delta itself inside the masked first block).
        if term and not capped and s + len(data) < e:
            pos = s + len(data)
            st_bytes[str(pos)] = (MASK_DELTA[0] if (len(data) < 16) else 0x00) if masked else 0x00
        cur = None                  # one leak per probe
    return st_bytes, produced, got



def advance(st, targets, nb, produced):
    """Move the worklist forward for one cycle. Shared by main() and the tests.

    A probe that produced NOTHING keeps its interval: the old code advanced the
    start by one, which silently deleted that byte from the worklist -- the saved
    state was already missing 19,20,21,82,83,84 and 1490323-1490325 (66.5)."""
    for i, (s, e) in enumerate(targets):
        st["pending"] = [iv for iv in st["pending"] if iv != [s, e]]
        if i in produced:
            ln = max((int(k) - s for k in nb if s <= int(k) < e), default=-1) + 1
            rem = s + ln
            if rem < e: st["pending"].append([rem, e])
        else:
            st["miss"] += 1
            st["pending"].append([s, e])
    return st


def record_read(st, targets, produced, masked):
    """Provenance for one cycle: which windows, in which cycle, under which mask,
    and how many leaks were truncated by the log buffer.  Bounded (one entry per
    cycle) and cross-referenced by the raw capture /tmp/opzcap_cycleNNNN.bin, so
    any byte in the map can be traced to the console evidence that produced it."""
    st.setdefault("reads", []).append({
        "cycle": st.get("cycles"), "masked": bool(masked),
        "targets": [list(t) for t in targets], "produced": sorted(produced),
        "leaks": LAST["leaks"], "truncated": LAST["truncated"], "marker": LAST["marker"],
        "capture": f"/tmp/opzcap_cycle{st.get('cycles', 0):04d}.bin",
    })
    if len(st["reads"]) > 5000: del st["reads"][:-5000]
    return st


def zipwalk_ok():
    """Run the assembler and return (ok, detail, desync_offset).

    Byte coverage cannot prove the map is RIGHT: a misparsed leak would shift every
    later offset and still reach 99%, producing a corrupt archive reported as success.
    A zip must satisfy a strict chain, so opzassemble walks it and prints ZIPWALK,
    and the report is gated on that.  Returns (None, ...) if the walk could not run.
    """
    try:
        r = subprocess.run([sys.executable, '/tmp/opzassemble.py'],
                           capture_output=True, text=True, timeout=900)
    except Exception as e:
        return None, f'assembler failed to run: {e!r}', -1
    line = next((l for l in (r.stdout or '').splitlines() if l.startswith('ZIPWALK:')), None)
    if line is None:
        return None, 'assembler printed no ZIPWALK line', -1
    if line.startswith('ZIPWALK: OK'):
        return True, line[len('ZIPWALK: '):], -1
    m = re.search(r'^ZIPWALK: FAIL at (\d+) \((.*)\)$', line)
    return False, (m.group(2) if m else line), (int(m.group(1)) if m else 0)


MIN_COVERAGE = 0.99   # never claim success on a partial map

def write_report(st):
    """Completion step: assemble the payload, analyse it and write the report."""
    import subprocess
    out = [ "OP-Z firmware decode report", "===========================",
            f"generated {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"payload bytes recovered : {len(st['bytes'])}/{ZIP_LEN} ({100*len(st['bytes'])/ZIP_LEN:.2f}%)",
            f"cycles run              : {st.get('cycles')}  misses={st.get('miss')}", "" ]
    # sys.executable, not a hardcoded venv path: the venv lives in /tmp and may have
    # been rebuilt by run.sh, and a stale path here would fail at the finish line.
    for name, cmd in (("assemble", [sys.executable,'/tmp/opzassemble.py']),
                      ("analyse",  [sys.executable,'/tmp/opzanalyze.py'])):
        out.append(f"-- {name} --")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            out.append((r.stdout or r.stderr).strip())
        except Exception as e:
            out.append(f"failed: {e!r}")
        out.append("")
    Path('/tmp/OPZ_DECODE_REPORT.txt').write_text("\n".join(out) + "\n")
    log(f"report written to /tmp/OPZ_DECODE_REPORT.txt")
    try: Path('/Users/jakubkolcar/.opz-decode/OPZ_DECODE_REPORT.txt').write_text("\n".join(out) + "\n")
    except Exception: pass


def handle_mismatch(st, bad):
    """React to a ground-truth mismatch: drop the wrong bytes and re-queue their
    (aligned) range, so the map is never poisoned.

    The mask is deliberately NOT flipped any more.  It is what makes a NUL inside
    the first block print at all, and the old auto-fallback to unmasked probes was
    a reaction to a GROUND_TRUTH set that itself contained misaligned garbage
    (66.1) -- so a real device condition would have permanently disabled the
    feature that makes leaks readable.  Never stops the farm.  Returns 'retry'."""
    for o, g, w in bad:
        st["bytes"].pop(str(o), None)
    lo = min(o for o, _, _ in bad); hi = max(o for o, _, _ in bad) + 1
    st["pending"].append([align16(lo), hi])
    return 'retry'


def _read_all(ser, secs, reopen=None):
    """Read for `secs`, tolerating a dead port: on a read error, close and (if a
    reopen callable is given) open a fresh handle, so a USB re-enumeration mid-cycle
    cannot blind the rest of the capture.  Returns the bytes read.

    pyserial's `Serial(None)` is a *closed* object that does not raise, so a reopen
    must be checked for `is_open`: otherwise the loop accepts a dead handle, every
    read raises PortNotOpenError, and it spins logging garbage for the whole window
    -- losing the entire console capture, which is the only thing a cycle exists to
    get.  The reopen is retried with a sleep and the failure is logged once per
    outage rather than once per iteration."""
    buf = b""; t0 = time.time(); reported = False
    while time.time() - t0 < secs:
        try:
            if ser is None or not getattr(ser, 'is_open', False):
                raise serial.SerialException('port is not open')
            buf += ser.read(8192)
            reported = False
        except Exception as e:
            if not reported:
                log(f"serial read failed ({e!r}); reopening port")
                reported = True
            try:
                if ser is not None: ser.close()
            except Exception: pass
            ser = None
            if reopen is None: break
            for _ in range(20):
                if time.time() - t0 >= secs: break      # never outlast the window
                try: ser = reopen()
                except Exception: ser = None
                if ser is not None and getattr(ser, 'is_open', False): break
                ser = None; time.sleep(0.5)
            if ser is None:
                log("could not reopen the console port; capture ended early"); break
        if b'successfully upgraded' in buf:
            time.sleep(4); break
    return buf, ser

def main():
    acquire_lock()
    st = load()
    import hashlib as _h
    try: _src = _h.sha256(open(__file__,'rb').read()).hexdigest()[:8]
    except Exception: _src = 'unknown'
    log(f"[src={_src}] === farm start: cycles={st['cycles']} known={len(st['bytes'])}B pending={len(st['pending'])} N={N} masked={MASKED[0]} ===")
    while st["cycles"] < MAXC and st["pending"]:
        try:
            if not wait_vol(timeout=90):
                # Root SCSI media-load.  There is no passwordless sudoers rule unless
                # the user ran OP-Z-unstick.command, so report the real outcome rather
                # than claiming an attempt that cannot work.
                try:
                    r = subprocess.run(['sudo','-n','/tmp/opzload'], capture_output=True, timeout=60)
                    log(f"SCSI media-load (root) rc={r.returncode}; waiting for the medium")
                except Exception as e:
                    log(f"SCSI media-load unavailable ({e!r}); waiting for the medium")
                if not wait_vol(timeout=600):
                    log("still no medium; continuing to wait"); continue
            time.sleep(2)
            # value order: the trailing central directory first, then by offset
            st["pending"].sort(key=lambda iv: (0 if iv[0] >= ZIP_LEN - 4096 else 1, iv[0]))
            targets = st["pending"][:N]
            vol = volpath() or VOL
            stage_cycle(vol, targets)
            ser = None
            p = port()
            if p:
                try:
                    ser = serial.Serial(p, 115200, timeout=1)
                    ser.reset_input_buffer()
                except Exception as e: log(f"serial err {e}")
            for _try in range(4):
                ej = subprocess.run(['diskutil', 'eject', str(vol)], capture_output=True, text=True)
                if 'ejected' in (ej.stdout + ej.stderr) or not vol.is_dir(): break
                log(f"eject attempt {_try+1} did not eject ({(ej.stdout+ej.stderr).strip()[:80]}); retrying")
                time.sleep(1.5)
            buf, ser = _read_all(ser, CAP_SECS,
                                 reopen=(lambda: _open_port(port())))
            if ser:
                try: ser.close()
                except Exception: pass
            st["cycles"] += 1
            # keep every raw capture: the cycle log only says HOW MANY probes
            # leaked, and diagnosing through-put needs the device's own words.
            try:
                Path(f"/tmp/opzcap_cycle{st['cycles']:04d}.bin").write_bytes(buf)
                if st["cycles"] > 40: Path(f"/tmp/opzcap_cycle{st['cycles']-40:04d}.bin").unlink(missing_ok=True)
            except Exception: pass
            nb, produced, got = parse_cycle(buf, targets)
            st["bytes"].update(nb)
            advance(st, targets, nb, produced)
            normalize_pending(st)   # an interval MUST start on a readable boundary, or the
                                    # whole window is filed up to 15 bytes off (66.14)
            record_read(st, targets, produced, MASKED[0])
            checked, bad = verify_ground_truth(st)
            if bad:
                log(f"GROUND TRUTH MISMATCH ({len(bad)} bytes): " +
                    ", ".join(f"@{o}: got 0x{g:02x} want 0x{w:02x}" for o,g,w in bad[:6]))
                handle_mismatch(st, bad)
            else:
                log(f"ground truth: {checked}/{len(GROUND_TRUTH)} known bytes match")
            up = b'successfully upgraded' in buf
            rate = len(produced) / max(1, len(targets))
            if st["cycles"] >= 3 and rate < 0.5:
                log(f"WARNING: only {len(produced)}/{len(targets)} staged probes produced a leak this cycle "
                    f"(cumulative misses={st['miss']}). The device may not be reading every firmware file in one "
                    f"boot; if this persists the worklist advances ~1 byte per probe and the decode will crawl.")
            log(f"cycle {st['cycles']}: probes_leaked={len(produced)}/{len(targets)} new={got}B "
                f"known={len(st['bytes'])}B pending={len(st['pending'])} misses={st['miss']} "
                f"truncated={LAST['truncated']}/{LAST['leaks']} marker={LAST['marker']} "
                f"upgrade={'YES' if up else 'no'}")
            save(st)
        except Exception:
            log("cycle exception:\n" + traceback.format_exc()[:1500])
            time.sleep(10)
    cov = len(st["bytes"]) / ZIP_LEN
    if not st["pending"] and cov >= MIN_COVERAGE:
        ok, detail, off = zipwalk_ok()
        if ok:
            save(st)
            write_report(st)
        else:
            # A structurally invalid payload at high coverage means the map has a
            # desync or a hole inside a header.  Re-queue that region and keep going
            # rather than writing a report that claims success.
            log(f"REFUSING to report: coverage is {cov*100:.1f}% but the payload is not a valid zip "
                f"({detail} at {off}); re-queueing {max(0,off-64)}..{min(ZIP_LEN,off+512)}")
            st["pending"].append([max(0, off - 64), min(ZIP_LEN, off + 512)])
            save(st)
    elif not st["pending"]:
        log(f"worklist empty but coverage is only {cov*100:.1f}% -- NOT reporting (would be a false success)")
    log("farm stopped")


if __name__ == "__main__":
    main()
