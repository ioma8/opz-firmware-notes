#!/usr/bin/env python3
"""One ALIGNED oracle read, decoded with the corrected parser (review-2 decoder).

Stages exactly ONE crafted probe, ejects, captures the console, and decodes the leak
properly: frames split by their length field, 7D escapes undone, and the device's
128-byte log cap honoured (a capped frame's last byte is the buffer's NUL, so no byte
is invented).

This is the read that settles FIRMWARE_ANALYSIS.md 66.8 -- whether the known seed
    50 4b 03 04 14 00 c0 1e 04 00 00 00 49 fb be 94 19 5b 00
is genuine payload plaintext (a real zip local header, oddly with method 4 and a zero
DOS date) or was a console frame absorbed into the window by the old parser.

Cost: ONE firmware read.  The device reads a single candidate per boot and then aborts,
so nothing else may be staged -- and the medium does NOT return on its own afterwards
(~65 bytes per power cycle, see 66.3).

usage: opzw0.py [window_offset] [--unmasked] [--secs N] [--dry-run]
"""
import importlib.util, json, subprocess, sys, time
from pathlib import Path

H = Path.home() / '.opz-decode'
# opzfarm.py reads sys.argv[1:] at import time (it doubles as a CLI), so our own flags
# must not be visible to it.
_argv = sys.argv[1:]
sys.argv = sys.argv[:1]
spec = importlib.util.spec_from_file_location('F', H / 'opzfarm.py')
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)

idx = 0
unmasked = False
secs = 45
dry = False
delta = 1
args = list(_argv)
if '--unmasked' in args: unmasked = True; args.remove('--unmasked')
if '--dry-run' in args: dry = True; args.remove('--dry-run')
if '--delta' in args:
    _i = args.index('--delta'); delta = int(args[_i + 1]); del args[_i:_i + 2]
if '--secs' in args:
    i = args.index('--secs'); secs = int(args[i + 1]); del args[i:i + 2]
if args: idx = int(args[0])


def volume():
    for p in sorted(Path('/').glob('Volumes/OP-Z*')):
        if (p / 'systeminfo').is_dir(): return p
    return None


def port():
    c = sorted(Path('/dev').glob('cu.usbmodem*'))
    return str(c[0]) if c else None


def main():
    win = F.align16(idx)
    F.MASK_DELTA[0] = delta
    if win != idx:
        print(f"NOTE: {idx} is not 16-byte aligned -> readable window is {win} (66.1)")
    probe = F.craft(win, mask_first=not unmasked)
    src = F.SRC.read_bytes()
    print(f"probe for payload window {win}: {len(probe)} B, "
          f"mask={'OFF (unmasked)' if unmasked else f'delta 0x{delta:02x}'}, "
          f"name block0 == file[0x{0x400+win:X}:0x{0x400+win+16:X}]")
    # near the payload end craft() clips the window and zero-pads it, so compare the
    # bytes that exist and require the remainder to be the documented padding
    avail = src[0x400 + win:0x400 + win + 256]
    assert probe[0x300:0x300 + len(avail)] == avail, 'window mismatch'
    assert probe[0x300 + len(avail):0x400] == bytes(256 - len(avail)), 'window tail must be zero-padded'
    assert probe[0x70:0x80] == (src[0x400 + win - 16:0x400 + win] if unmasked
                                else bytes(b ^ delta for b in src[0x400 + win - 16:0x400 + win])), 'IV mismatch'
    if dry:
        print("dry run: probe verified, nothing staged, nothing touched")
        print(f"  IV      : {' '.join(f'{b:02x}' for b in probe[0x70:0x80])}")
        print(f"  name[0:16]: {' '.join(f'{b:02x}' for b in probe[0x300:0x310])}")
        print(f"  file[0x{0x400+win:X}:0x{0x400+win+16:X}]: {' '.join(f'{b:02x}' for b in src[0x400+win:0x400+win+16])}")
        assert probe[0x300:0x310] == src[0x400+win:0x400+win+16], 'name block 0 must equal the window ciphertext'
        return 0

    vol = volume()
    if vol is None:
        print("no OP-Z volume mounted -> power-cycle the unit (hold POWER ~2 s, then PLAY) and rerun")
        return 2
    print(f"volume: {vol}")
    for f in vol.iterdir():
        if f.is_file() and (f.name.endswith('.zfw') or f.name.startswith('._')):
            f.unlink()
    (vol / 'z_firmware_probe_000.zfw').write_bytes(probe)
    for f in list(vol.iterdir()):
        if f.name.startswith('._'): f.unlink()
    left = [p.name for p in vol.iterdir() if p.is_file()]
    print(f"staged: {left}  (must be exactly one probe: the device reads one per boot)")
    subprocess.run(['sync'])

    p = port()
    ser = None
    if p:
        import serial
        ser = serial.Serial(p, 115200, timeout=1)
        ser.reset_input_buffer()
    for _ in range(4):
        ej = subprocess.run(['diskutil', 'eject', str(vol)], capture_output=True, text=True)
        if 'ejected' in (ej.stdout + ej.stderr) or not vol.is_dir(): break
        time.sleep(1.5)
    print(f"ejected, capturing {secs}s ...")
    buf, ser = F._read_all(ser, secs, reopen=(lambda: _reopen(p)))
    if ser:
        try: ser.close()
        except Exception: pass

    raws = H / 'raws'; raws.mkdir(exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    raw = raws / f'w{win}_{"unmasked" if unmasked else f"d{delta}"}_{stamp}.bin'
    raw.write_bytes(buf)

    frames = F.frames(buf)
    leaks = [(len(p), p) for _, _, p in frames if F.LEAK_PREFIX in p]
    print(f"\ncapture {len(buf)} B -> {raw}")
    print(f"frames: {len(frames)}   leak frames: {len(leaks)}   "
          f"reads detected: {sum(1 for _, _, p in frames if b'detected encrypted file' in p)}")
    if not leaks:
        print("NO LEAK: the device did not read the probe this boot (already used its one "
              "read, or it is wedged).  Power-cycle and rerun.")
        return 3
    plen, payload = leaks[0]
    capped = plen >= F.FRAME_MAX
    nb, produced, got = F.parse_cycle(buf, [[win, win + F.WIN]])
    out = bytes(nb[str(win + i)] for i in range(got))
    print(f"\nleak: payload {plen} B, capped={capped} (device log buffer = {F.FRAME_MAX}), "
          f"decoded {got} B at payload {win}..{win + got}")
    if capped:
        print(f"  ('..' truncation marker stripped: {F.LAST['marker']} frame(s) -> a capped read "
              f"yields {F.FRAME_MAX - 4 - 58 - 2 - 1} real bytes, and the 2 bytes it overwrote "
              f"must be re-read from an overlapping window)")
    print(f"  hex   : {' '.join(f'{b:02x}' for b in out)}")
    print(f"  ascii : {''.join(chr(b) if 32 <= b < 127 else '.' for b in out)}")

    if got >= 6:
        ver = int.from_bytes(out[4:6], 'little') if got >= 6 else None
        flg = int.from_bytes(out[6:8], 'little') if got >= 8 else None
        mth = int.from_bytes(out[8:10], 'little') if got >= 10 else None
        print(f"\n  as a zip local header: signature={out[:4]!r} version={ver} "
              f"flags={('0x%04x' % flg) if flg is not None else '?'} "
              f"method={mth}  (method 8 = Deflate, 4 = Reduced - see 66.7)")

    known = {int(k): v for k, v in F.GROUND_TRUTH.items()}
    diff = [(o, v, known[o]) for o, v in enumerate(out) if o in known and v != known[o]]
    hit = [o for o in range(len(out)) if o in known]
    if diff:
        print(f"\n  *** SEED DIFFERS at {len(diff)} byte(s): " +
              ', '.join(f'@{o}: got 0x{g:02x} want 0x{w:02x}' for o, g, w in diff[:8]))
        print("  -> the old seed was NOT the plaintext at this window: re-derive everything from scratch")
    elif len(hit) >= 19:
        print(f"\n  SEED CONFIRMED on all {len(hit)} known bytes -> the payload really does start "
              f"'PK\\x03\\x04 14 00 c0 1e 04 00 ...' and the frame-splice theory (66.8) is disproved")
    else:
        print(f"  (only {len(hit)} known byte(s) recovered)")
    print(f"  capped={capped} means " + ("the window did NOT end on a NUL - the log buffer cut it"
                                        if capped else "the leak ended on a real NUL in the window"))
    return 0


def _reopen(p):
    import serial
    try: return serial.Serial(p, 115200, timeout=1)
    except Exception: return None


if __name__ == '__main__':
    sys.exit(main())
