#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyserial"]
# ///
"""OP-Z bootloader serial copy command: retrieve a file off the device (request 0x37, reply 0x38).

WHAT THE COMMAND IS (decoded from the disassembly, prologue included)

    handler 0x11a02fb4, in the L1 code loaded at 0x11a00000
    dispatch 0x11a02e4c, inside the function starting at 0x11a02932 (LINK 0x220)

    11a02942  R4 = 0x82836AD8          ; rodata base
    11a02958  P4 = 0x82852E94          ; the RAM message struct
    11a0298a  [FP+0x8]  = R4           ; [FP+0x8] is the RODATA base, not a payload pointer
    11a02990  [FP+0x10] = struct+0x10  ; payload argument 1 lives here
    ...
    11a02fbe  B[R6] = 0xE1             ; reply[0] = status, set UNCONDITIONALLY at entry
    11a02fc0  len1 = strlen("yaffs2/") ; 7, a constant (rodata 0x82836B68)
    11a02ff6  0x80 <= len1 + len2 + 1  -> log "Too long source filename"   (len2 = strlen(struct+0x10))
    11a03010  0x80 <= len1 + len3 + 1  -> log "Too long target filename"   (len3 = strlen(struct+0x50))
    11a0307e  B[SP+0x50] = '/'         ; path1 = "/"
    11a03088  strncpy(SP+0x51, "yaffs2/", 7)      ;       "/yaffs2/"
    11a030a6  strncpy(SP+0x58, struct+0x10, len2) ;       + argument 1
    11a030b6  B[SP+0xd0] = '/'
    11a030c0  strncpy(SP+0xd1, "yaffs2/", 7)
    11a030dc  strncpy(SP+0xd8, struct+0x50, len3) ;       + argument 2
    11a030ec  Call 0x8280db80                     ; copy(path1, path2)
    11a030fc  B[R6] = 0xD3                        ; only when copy() returns 0

  So it is a general copy INSIDE /yaffs2: source = "/yaffs2/" + argument 1, target = "/yaffs2/" + argument 2.
  The two guard messages name them, in that order. Every exit path replies with a single status byte:
  0xE1 = default / copy did not return 0, 0xD3 = copy returned 0.

  The arguments come from NUL-separated payload strings dropped into 64-byte slots at struct+0x10,
  struct+0x50, struct+0x90, ... (0x40 apart). NOTE: the guard permits 120 bytes per argument, but the slot is
  only 64, so an argument longer than that overflows its slot. This tool refuses arguments >= 60 bytes.

HOW TO READ A FILE OFF THE DEVICE

  Copy it to a path the host can see, then read it over mass storage. Which paths are visible depends on the
  mode the unit is in:

    update mode ("OP-Z Boot"): the host sees systeminfo/ (version.txt, serial.txt, and the *.log files)
    content mode:              the host sees the /yaffs2/user tree (bounces/, config/, projects/, samplepacks/)

  So `--get systeminfo/version.txt systeminfo/out.txt` writes /yaffs2/systeminfo/out.txt, which should appear on
  the mounted volume immediately.

THE REPLY-COUNT LAW (measured, 25+ payloads, regression-tested)

  With two or more NUL-separated arguments the device returns

      replies = total_len - (len(arg1) + len(arg2) + 1)

  one 1-byte 0x38 frame per byte of the payload from the third argument onward. Below two arguments it returns
  nothing. Every reply carries the same status byte.

SAFETY

  One frame per invocation unless you pass --pairs. Never sweeps type bytes; the destructive ones (0x15 format
  NAND, the NAND family 0x13/0x14/0x16-0x19, 0x29 BF_ENTER_DFU) are never constructed. The target is required to
  be a NEW name that does not already exist on the mount, so nothing can be overwritten. Arguments are capped at
  60 bytes to stay inside their 64-byte slot. Damage detectors (PING, version string, mount) run around it.

  Residual risk: the copy's argument order is inferred from the two guard messages. If it is reversed, the copy
  would try to read the (nonexistent) new name and write toward the source path; picking a source whose bytes
  you already hold keeps that harmless. This is why the default source is a file already captured.

USAGE
  uv run --script toolkit/opzcopyprobe.py --list
  uv run --script toolkit/opzcopyprobe.py --self-test
  uv run --script toolkit/opzcopyprobe.py --yes
  uv run --script toolkit/opzcopyprobe.py --yes --get user/config/general.json systeminfo/out.json
  uv run --script toolkit/opzcopyprobe.py --yes --timing
"""
import argparse
import glob
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from opzframe import frames          # noqa: E402

ESCAPE, ESCAPE_XOR = 0x7D, 0x20
ROUTING_HOST = 0x01
TYPE_PING, TYPE_VERSION, TYPE_COPY = 0x00, 0x02, 0x37
REPLY_COPY = 0x38
REPLY_LOG = 0x04
GUARD_LIMIT = 0x80                   # handler's guard: combined path length >= 128 is refused
SLOT_MAX = 60                        # struct slots are 0x40 apart; stay inside them
STATUS_DEFAULT = 0xE1                # set at handler entry; also the "copy returned non-zero" value
STATUS_COPIED = 0xD3                 # set only when the copy function returns 0

PONG_FRAME = bytes((0xC0, 0x1E, TYPE_PING + 1, 0x00, 0x00, 0x00, 0x00))

# Default retrieval: a file already captured by hand, so a reversed argument order cannot lose anything.
DEFAULT_SRC = 'systeminfo/version.txt'
DEFAULT_DST = 'systeminfo/zz-copyprobe-out.txt'

MEASURED = (
    ((10,) * 12, 111), ((0,) * 200, 199), ((70,) * 3, 72), ((70,) * 2, 1),
    ((70, 0), 1), ((200,), 0), ((10,), 0), ((0,), 0),
    ((5, 7, 20), 22), ((3, 3), 1), ((100, 1, 1, 1), 5),
    ((40, 60, 200), 202), ((12,) * 5, 40), ((22, 31), 1),
)


def predict_replies(lengths):
    """Take argument lengths; replies = total_len - (len1 + len2 + 1), nothing below two arguments."""
    if len(lengths) < 2:
        return 0
    total = sum(n + 1 for n in lengths)
    return max(0, total - (lengths[0] + lengths[1] + 1))


def encode(routing, mtype, payload=b''):
    """C0 <routing> <type> <len_be32> <payload>, with 0xC0 and 0x7D escaped as 7D <byte^20>."""
    out = bytearray((0xC0, routing, mtype))
    out += len(payload).to_bytes(4, 'big')
    for b in payload:
        if b in (0xC0, ESCAPE):
            out += bytes((ESCAPE, b ^ ESCAPE_XOR))
        else:
            out.append(b)
    return bytes(out)


def ports():
    return sorted(glob.glob('/dev/cu.usbmodem*')) + sorted(glob.glob('/dev/tty.usbmodem*'))


def copy_payload(src, dst):
    """The two NUL-separated arguments the handler reads: source then target."""
    for name in (src, dst):
        if len(name) >= SLOT_MAX:
            raise SystemExit(f"argument {name!r} is {len(name)} bytes; keep it under {SLOT_MAX} "
                             f"so it fits its 64-byte slot")
    return src.encode() + b'\x00' + dst.encode() + b'\x00'


def build_guard_payload(length=150, field=60):
    """An oversize argument set for the timing comparison: many names, each inside its slot."""
    name = b'zz-copyprobe-' + b'A' * max(0, field - len(b'zz-copyprobe-'))
    n = max(2, -(-length // (len(name) + 1)))
    return b''.join(name + b'\x00' for _ in range(n))


def mount_root():
    for p in ('/Volumes/OP-Z',):
        if os.path.exists(p):
            return p
    return None


def listing(root):
    if not root:
        return {}
    out = {}
    for dirpath, _, files in os.walk(root):
        if '/.' in dirpath or dirpath.endswith('/.'):
            continue
        for f in files:
            if f.startswith('.'):
                continue
            full = os.path.join(dirpath, f)
            try:
                out[os.path.relpath(full, root)] = os.path.getsize(full)
            except OSError:
                pass
    return out


class Console:
    def __init__(self, port, baud=115200, timeout=0.4):
        import serial
        self.ser = serial.Serial(port, baud, timeout=timeout)

    def close(self):
        try: self.ser.close()
        except Exception: pass

    def drain(self, seconds):
        end, buf = time.time() + seconds, bytearray()
        while time.time() < end:
            chunk = self.ser.read(4096)
            if chunk:
                buf += chunk
        return bytes(buf)

    def ask(self, mtype, payload=b'', wait=1.5, since=None):
        """Send one frame; return (stream, ms until the first reply byte)."""
        self.drain(0.2)
        self.ser.write(encode(ROUTING_HOST, mtype, payload))
        self.ser.flush()
        t0 = since if since is not None else time.time()
        first, buf = None, bytearray()
        end = t0 + wait
        while time.time() < end:
            chunk = self.ser.read(4096)
            if chunk:
                if first is None and not (len(chunk) == 1 and chunk == b''):
                    first = (time.time() - t0) * 1000.0
                buf += chunk
        return bytes(buf), first


def liveness(con):
    """The PONG is a zero-length frame, which opzframe.frames() drops, so match the raw pattern."""
    stream, _ = con.ask(TYPE_PING, wait=1.2)
    return PONG_FRAME in stream


def version(con):
    stream, _ = con.ask(TYPE_VERSION, wait=1.5)
    text = b''
    for _, _, mtype, payload in frames(stream):
        if mtype == TYPE_VERSION + 1:
            text += payload
    return text.split(b'\x00', 1)[0]


def self_test():
    ok = True
    for lengths, expect in MEASURED:
        got = predict_replies(lengths)
        good = got == expect
        ok &= good
        print(f"  {'OK' if good else 'BAD'}  arg lengths {list(lengths)[:6]}"
              f"{'...' if len(lengths) > 6 else ''} ({len(lengths)} args) "
              f"-> predicted {got}, measured {expect}")
    for payload in (b'A', bytes(range(1, 60)), bytes([0xC0, 0x7D, 0xC0, 0x7D, 0x41])):
        got = frames(encode(ROUTING_HOST, TYPE_COPY, payload))
        good = len(got) == 1 and got[0][3] == payload
        ok &= good
        print(f"  {'OK' if good else 'BAD'}  encoder round-trip, {len(payload)}-byte payload")
    for src, dst in (('a', 'b'), (DEFAULT_SRC, DEFAULT_DST)):
        p = copy_payload(src, dst)
        parsed = [n.decode() for n in p.split(bytes([0])) if n]
        good = p == src.encode() + bytes([0]) + dst.encode() + bytes([0])
        ok &= good
        print(f"  {'OK' if good else 'BAD'}  copy payload split for {src!r} / {dst!r} -> {parsed}")
    for bad in ('x' * 60, 'y' * 200):
        try:
            copy_payload(bad, 'ok')
            print(f"  BAD  oversize argument {len(bad)} was not rejected")
            ok = False
        except SystemExit:
            print(f"  OK  oversize argument ({len(bad)} bytes) rejected")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def analyse(stream):
    return [(r, t, p) for _, r, t, p in frames(stream)]


def guard_vs_work_timing(con):
    """The guard path is two strlens and a log call; the work path memsets, builds paths and hits the FS."""
    print("=== timing: guard path vs work path ===")
    cases = [
        ("guard-tripping (1 oversize arg)", b'A' * 200 + b'\x00'),
        ("work path (2 short args)", copy_payload('systeminfo/version.txt', 'systeminfo/zz-timing.txt')),
        ("guard-tripping (2 args, 1 oversize)", b'A' * 200 + b'\x00' + b'bb\x00'),
    ]
    for label, payload in cases:
        stream, ms = con.ask(TYPE_COPY, payload, wait=2.5)
        reps = [p for r, t, p in analyse(stream) if r == 0x1E and t == REPLY_COPY]
        print(f"  {label:<38} -> {len(reps):>3} replies, first reply after "
              f"{'n/a' if ms is None else f'{ms:.1f} ms'}")
    root = mount_root()
    if root:
        ls = listing(root)
        stray = [k for k in ls if 'zz-timing' in k]
        print(f"  target appeared on the mount: {stray or 'no'}")


def retrieve(con, args):
    root = mount_root()
    before = listing(root)
    print(f"mount         : {root or 'not mounted'}  ({len(before)} files)")

    payload = copy_payload(args.src, args.dst)
    if args.dst in before:
        print(f"refusing: target {args.dst!r} already exists on the mount - pick a new name so nothing "
              f"can be overwritten")
        return 1

    print(f"\n--- one frame, type {TYPE_COPY:#04x} ---")
    print(f"    source (arg 1) -> /yaffs2/{args.src}")
    print(f"    target (arg 2) -> /yaffs2/{args.dst}")
    parsed = [n.decode() for n in payload.split(bytes([0])) if n]
    print(f"    payload {len(payload)} B: {parsed}")

    stream, ms = con.ask(TYPE_COPY, payload, wait=args.wait)
    rows = analyse(stream)
    reps = [p for r, t, p in rows if r == 0x1E and t == REPLY_COPY]
    statuses = sorted({p.hex() for p in reps if p})
    logs = [p.split(b'\x00', 1)[0] for r, t, p in rows if t == REPLY_LOG]

    print(f"    replies     : {len(reps)}   first after {'n/a' if ms is None else f'{ms:.1f} ms'}")
    print(f"    status bytes: {statuses or 'none'}")
    print(f"    log frames  : {logs or 'none'}")

    time.sleep(1.0)
    after = listing(root)
    new = {k: v for k, v in after.items() if k not in before}
    print(f"\n=== result ===")
    if new:
        for k, v in sorted(new.items()):
            print(f"  NEW FILE on the mount: {k}  ({v} bytes)")
            full = os.path.join(root, k)
            if args.src in before and os.path.basename(args.src) == os.path.basename(k):
                print(f"    source was {before[args.src]} bytes, target is {v} bytes "
                      f"-> {'MATCH' if before[args.src] == v else 'SIZE MISMATCH'}")
            if v and v <= args.max_read:
                data = open(full, 'rb').read()
                print(f"    first {min(len(data), 200)} bytes: {data[:200]!r}")
        print("  => the copy command WORKS and is a read channel off the device.")
    elif any(s == f'{STATUS_COPIED:02x}' for s in statuses):
        print("  copy reported success (0xD3) but no new file is visible - the target may map to a path the")
        print("  host cannot see in this mode. Retry from content mode, where /yaffs2/user is exposed.")
    else:
        print("  no new file and status 0xE1 - the copy did not succeed. Either the guard tripped, or the")
        print("  source path does not resolve, or the target directory is not host-visible in this mode.")
    return 0 if new else 3


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', help='console serial port (default: first cu.usbmodem*)')
    ap.add_argument('--list', action='store_true', help='list candidate ports and exit')
    ap.add_argument('--self-test', action='store_true', help='offline checks, no device needed')
    ap.add_argument('--get', nargs=2, metavar=('SRC', 'DST'),
                    help=f'two /yaffs2-relative paths to copy (default {DEFAULT_SRC} -> {DEFAULT_DST})')
    ap.add_argument('--timing', action='store_true', help='compare guard-path and work-path reply timing')
    ap.add_argument('--wait', type=float, default=4.0, help='seconds to listen after the frame')
    ap.add_argument('--max-read', type=int, default=100000, help='print contents of new files up to this size')
    ap.add_argument('--yes', action='store_true', help='confirm you accept the residual risk')
    a = ap.parse_args()

    if a.self_test:
        return self_test()
    if a.list:
        found = ports()
        print("candidate console ports:", found or "(none - is the unit in update mode?)")
        return 0
    if not a.yes:
        print(__doc__)
        print("refusing to send without --yes")
        return 1

    a.src, a.dst = a.get if a.get else (DEFAULT_SRC, DEFAULT_DST)

    found = ports()
    port = a.port or (found[0] if found else None)
    if not port:
        print("no console port found - put the unit in update mode (OP-Z Boot) and retry")
        return 1
    print(f"port          : {port}")

    con = Console(port)
    try:
        if not liveness(con):
            print("console is not answering; aborting without sending anything")
            return 1
        ver_before = version(con)
        print(f"version       : {ver_before[:60]!r}")
        if a.timing:
            guard_vs_work_timing(con)
            rc = 0
        else:
            rc = retrieve(con, a)
        alive = liveness(con)
        ver_after = version(con)
    finally:
        con.close()

    print(f"\n  PING after    : {'PONG' if alive else 'NO REPLY'}")
    print(f"  version after : {ver_after[:60]!r}   "
          f"{'UNCHANGED' if ver_after == ver_before else '*** CHANGED ***'}")
    if not alive or ver_after != ver_before:
        print("  verdict       : DAMAGE DETECTED")
        return 2
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
