#!/usr/bin/env python3
"""OP-Z console frame codec + oracle alignment helpers.

Two defects in ~/.opz-decode/opzfarm.py, confirmed 2026-10-10:

  parse_cycle() copies raw stream bytes, never undoes the 7D escape, and stops
  only on the RARE 'C0 2E 04' routing.  Routing 0x1E is the common log routing
  (151 of 170 frames in the genuine capture), so a following frame header can be
  absorbed into a leak window and every later offset shifts.

  craft() takes ciphertext from 0x400+idx with no 16-byte alignment.  Any idx
  not a multiple of 16 splices cipher mid-block, and the "decrypted window" is
  pseudorandom, NOT the payload at that offset.  Re-reading the same misaligned
  probe reproduces the same garbage, so repeatability looked like verification.

Also: the device's log message buffer caps a frame at 128 bytes (max over 1253
frames in opzraw3.bin, and the leak frame lands exactly on it), which limits any
leaked window to 128-4-58-1 = 65 bytes regardless of IV masking.

Self-test against real captures:  python3 opzframe.py [capture ...]
"""
import sys
from pathlib import Path

ESCAPE, ESCAPE_XOR = 0x7D, 0x20
FRAME_MAX = 128          # device log-message ceiling, measured
BASE = 0x400             # ciphertext payload base in a .zfw


def frames(buf):
    """Split a console stream into (offset, routing, type, payload) frames.
    Length is a big-endian u32 and 0x7D escapes the next byte as byte^0x20."""
    i, out = 0, []
    while i < len(buf):
        if buf[i] != 0xC0:
            i += 1
            continue
        if i + 7 > len(buf):
            break
        ln = int.from_bytes(buf[i + 3:i + 7], 'big')
        if ln > len(buf) - i - 7 or ln == 0:
            i += 1
            continue
        j, raw = i + 7, bytearray()
        while len(raw) < ln and j < len(buf):
            b = buf[j]; j += 1
            if b == ESCAPE and j < len(buf):
                raw.append(buf[j] ^ ESCAPE_XOR); j += 1
            else:
                raw.append(b)
        out.append((i, buf[i + 1], buf[i + 2], bytes(raw)))
        i = j
    return out


def messages(buf):
    """Human-readable log lines: drop the 4-byte tick, keep the text."""
    return [p[4:].split(b'\x00', 1)[0] for *_, p in frames(buf)]


def leaks(buf):
    """Bytes after 'failed to find .zip file in ', per frame, escape-decoded.
    Returns [(frame_len, leaked_bytes, truncated?)]."""
    marker = b'failed to find .zip file in '
    out = []
    for r, t, ln, p in [(f[1], f[2], 7 + len(f[3]), f[3]) for f in frames(buf)]:
        k = p.find(marker)
        if k < 0:
            continue
        s = p[k + len(marker):]
        nul = s.find(b'\x00')
        s = s if nul < 0 else s[:nul]
        out.append((ln, s, len(p) >= FRAME_MAX))
    return out


def align16(idx):
    """Largest block boundary <= idx (the offset actually readable)."""
    return idx - (idx % 16)


def craft(src, idx, mask=True, win=256):
    """Build one oracle probe for payload offset idx.  Returns (probe, actual_idx).
    actual_idx may be below idx: the readable window always starts on a boundary."""
    idx = align16(idx)
    d = src.read_bytes()
    s = BASE + idx
    if s + 16 > len(d):
        raise ValueError(f'idx {idx} past payload end')
    win_b = d[s:s + win]
    win_b += bytes(win - len(win_b))
    out = bytearray(d[:BASE])
    iv = bytearray(d[s - 16:s])
    if mask:
        for i in range(16):
            iv[i] ^= 0x01
    out[0x70:0x80] = iv
    out[0x300:0x400] = win_b
    out += d[BASE:BASE + 32]
    return bytes(out), idx


def unmask(leaked, already_masked=True):
    """Undo the IV ^1 mask on the first block, and drop the '..' truncation tail."""
    b = bytearray(leaked)
    if already_masked:
        for i in range(min(16, len(b))):
            b[i] ^= 0x01
    return bytes(b)


def _selftest(paths):
    ok = True
    for p in paths:
        raw = Path(p).read_bytes()
        F = frames(raw)
        consumed = sum(7 + len(f[3]) for f in F)
        frac = consumed / len(raw)
        mx = max(len(f[3]) for f in F)
        print(f'{Path(p).name}: {len(F)} frames, max={mx}, consumed {consumed}/{len(raw)} ({frac:.1%})')
        assert frac > 0.90, f'frame walk lost data in {p}'
        assert mx <= FRAME_MAX, f'frame longer than the 128-byte ceiling in {p}'
        if mx > FRAME_MAX:
            ok = False
    # the genuine capture must decode its own log lines
    g = Path('/Users/jakubkolcar/projects/customs/opz-firmware-notes/console_upgrade_1_2_45.bin')
    if g.exists():
        txt = b'\n'.join(messages(g.read_bytes()))
        assert b'bootdisk: filename found: firmware_bin_only_with_bootloader.zip' in txt
        print('genuine capture decodes its own filename-found line: OK')
    # leaks: measured cap present, trailing '..' visible
    r = Path('/tmp/opzraw3.bin')
    if r.exists():
        L = leaks(r.read_bytes())
        for ln, s, trunc in L:
            print(f'  leak: frame={ln} bytes={len(s)} truncated={trunc} tail={s[-4:].hex()}')
            assert trunc and len(s) == 65, 'expected a 65-byte leak capped at 128'
    # alignment: the readable window must always start on a 16-byte boundary
    z = Path('/Users/jakubkolcar/projects/customs/opz-firmware-notes/z_firmware_1_2_45.zfw')
    if z.exists():
        p, a = craft(z, 1490319)
        assert a == 1490304, a
        assert p[0x300:0x310] == z.read_bytes()[BASE + 1490304:BASE + 1490320]
        print(f'craft(1490319) -> readable window {a} (block-aligned), name block 0 sourced from 0x{BASE+1490304:X}')
    assert align16(0) == 0 and align16(30) == 16 and align16(1490319) == 1490304 and align16(1490320) == 1490320
    print('SELFTEST PASSED' if ok else 'SELFTEST FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    args = sys.argv[1:] or ['/tmp/opzraw3.bin', '/tmp/opzautocycle.raw',
                            '/Users/jakubkolcar/projects/customs/opz-firmware-notes/console_upgrade_1_2_45.bin']
    sys.exit(_selftest([a for a in args if Path(a).exists()]))
