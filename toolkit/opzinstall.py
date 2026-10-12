#!/usr/bin/env python3
"""Stage ONE genuine .zfw for install, eject, and report what the updater did.

Used for the pre-1.1.12 recovery shot: install an older, well-formed TE archive and
see whether the unit boots. The updater is the device's own, intended path — the
archive is TE's own signed/encrypted release, not a crafted image — and the A/B
bootloader slots plus a known-good 1.2.45 reflash make a failed attempt recoverable.

The volume is cleaned of every other *.zfw first: the bootloader installs the FIRST
firmware-named candidate in FAT order, so a leftover archive would be installed
instead of the intended one.

usage: opzinstall.py [PATH_TO_ZFW]     (default: the downloaded 1.1.9)
"""
import importlib.util, subprocess, sys, time
from pathlib import Path

H = Path.home() / '.opz-decode'
DEFAULT = Path('/Users/jakubkolcar/projects/customs/opz-firmware-notes/old-firmware/z_firmware_1_1_9.zfw')
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
SECS = int(sys.argv[2]) if len(sys.argv) > 2 else 90

_argv = sys.argv[1:]
sys.argv = sys.argv[:1]
spec = importlib.util.spec_from_file_location('F', H / 'opzfarm.py')
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)


def volume():
    for p in sorted(Path('/').glob('Volumes/OP-Z*')):
        if (p / 'systeminfo').is_dir() or p.is_dir(): return p
    return None


def port():
    c = sorted(Path('/dev').glob('cu.usbmodem*'))
    return str(c[0]) if c else None


def main():
    blob = SRC.read_bytes()
    print(f"archive: {SRC.name}  {len(blob):,} bytes")
    key = blob[0x04]
    import struct
    ln = struct.unpack_from('<I', blob, 0x80)[0]
    print(f"  zfw header: keyidx=0x{key:02x} plaintext_len={ln:,} "
          f"expected_file={0x400 + ((ln+15)//16)*16:,} (matches: {0x400 + ((ln+15)//16)*16 == len(blob)})")
    vol = volume()
    if vol is None:
        print("no OP-Z volume: put the unit in UPDATE mode first (power cycle; normal mode crashes)")
        return 2
    print(f"volume: {vol}")
    removed = 0
    for f in list(vol.iterdir()):
        if f.is_file() and (f.name.endswith('.zfw') or f.name.startswith('._')):
            f.unlink(); removed += 1
    print(f"  cleaned {removed} existing firmware file(s)/sidecar(s)")
    (vol / SRC.name).write_bytes(blob)
    for f in list(vol.iterdir()):
        if f.name.startswith('._'): f.unlink()
    left = [p.name for p in vol.iterdir() if p.is_file()]
    print(f"  staged: {left}")
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
    print(f"  ejected, capturing the updater for up to {SECS}s ...")
    buf, ser = F._read_all(ser, SECS, reopen=(lambda: None))
    if ser:
        try: ser.close()
        except Exception: pass
    raws = H / 'raws'; raws.mkdir(exist_ok=True)
    raw = raws / f"install_{SRC.stem}_{time.strftime('%Y%m%d-%H%M%S')}.bin"
    raw.write_bytes(buf)

    text = b'\n'.join(p for _, _, p in F.frames(buf))
    print(f"\ncapture {len(buf)} B -> {raw}")
    for kw in (b'detected encrypted file', b'filename found', b'decrypt', b'extract',
               b'Already installed', b'successfully upgraded', b'upgrade was unsuccessful',
               b'not compatible', b'wrong', b'error', b'failed'):
        n = text.count(kw)
        if n: print(f"   {kw.decode():28s} x{n}")
    for line in text.decode('latin1', 'replace').splitlines():
        if any(k in line for k in ('upgrad', 'extract', 'installed', 'bootloader', 'decrypt ')):
            print("   |", line.strip()[:120])
    return 0


if __name__ == '__main__':
    sys.exit(main())
