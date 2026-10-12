#!/usr/bin/env python3
"""The §24 write primitive: a plain zip that the OP-Z updater extracts into /yaffs2/.

The updater builds every destination as '/yaffs2/upgrade/' + <entry name>, resolves '..'
without sanitising it, creates missing parent directories, and runs this extraction before
the `ble` gate that stops a real upgrade.  So a plain (unencrypted) zip named
firmware_bin_only_with_bootloader.zip in the volume root is a host write primitive into the
device's internal filesystem.  No key, no crafted .zfw, no encryption needed.

Two edits the notes flag as never having been applied through this channel:
  1. ../user/config/general.json      - the device's own 10-key set, with disable_start_sound
                                        true.  The crash sits immediately after
                                        'snakesystem: load general config'; the earlier attempt
                                        went through the content disk and was void (the device
                                        writes its config out at boot and clobbers the disk copy).
  2. ../user/samplepacks/user/<id>.engine - the 21 real engine binaries.  The device's own slot
                                        ghosts are 0-byte ~<id>.engine markers and sample memory
                                        reports 0 kB; the samplepacks/user/ path has only ever
                                        been attempted through the content disk, where the content
                                        sync deletes it.

Config is written first so an early abort cannot skip it.  Entries are STORED, matching the
ablation archive the notes built for this purpose.

usage: opzablate.py [--dry-run]
"""
import io, json, shutil, subprocess, sys, time, zipfile
from pathlib import Path

H = Path.home() / '.opz-decode'
REPO = Path('/Users/jakubkolcar/projects/customs/opz-firmware-notes')
ENGINES = REPO / 'engines'
CONFIG_SRC = H / 'contentdisk-baseline/general.json.orig'
ZIPNAME = 'firmware_bin_only_with_bootloader.zip'
DRY = '--dry-run' in sys.argv

# plug id -> engine file, from the factory catalogue (same mapping the notes' ablation used)
PLUG_ENGINE = {10: 'analoga', 13: 'chorus2', 14: 'organ', 17: 'ep', 43: 'fdnreverb', 25: 'leaddigital',
               31: 'chord', 11: 'cluster', 26: 'saw013a', 34: 'delay', 35: 'reverb', 38: 'tapetwo',
               39: 'chorus', 65: 'volt', 71: 'sampleplayergain', 109: 'crush', 112: 'dist',
               129: 'fm003b', 138: 'synthsampler', 98: 'electric', 99: 'ministringshort'}


SRC_ZIP = H / 'ablation/firmware_bin_only_with_bootloader.zip'  # the notes' own ablation archive


def build(path):
    """The notes' ablation archive verbatim (its plug->engine mapping is the checked one),
    with the config entry prepended so an early abort can never skip it."""
    cfg = json.loads(CONFIG_SRC.read_text())
    cfg['disable_start_sound'] = True
    body = json.dumps(cfg, indent=1, sort_keys=True).encode()
    z = zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED)
    z.writestr('../user/config/general.json', body)
    n = 1
    with zipfile.ZipFile(SRC_ZIP) as src:
        for i in src.infolist():
            if i.filename == 'P0.txt':
                continue  # re-added last
            z.writestr(i.filename, src.read(i.filename))
            n += 1
    z.writestr('P0.txt', b'ablation marker\n')
    z.close()
    return n, len(body), [i.filename for i in zipfile.ZipFile(path).infolist()]


def volume():
    for p in sorted(Path('/').glob('Volumes/OP-Z*')):
        if p.is_dir(): return p
    return None


def main():
    out = H / 'ablation' / ZIPNAME
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / (ZIPNAME + '.new')  # never read and write the source archive at once
    n, clen, names = build(tmp)
    tmp.replace(out)
    print(f"built {out}  ({out.stat().st_size:,} B, {n} entries)")
    print(f"  ../user/config/general.json = {clen} B, the device's own 10 keys, disable_start_sound=true")
    print(f"  ../user/samplepacks/user/*.engine = {n-2} real engine binaries")
    for x in names[:4]: print("    ", x)
    print(f"     ... ({len(names)} total)")
    if DRY:
        print("dry run: nothing staged"); return 0
    vol = volume()
    if vol is None:
        print("no OP-Z volume: put the unit in update mode first"); return 2
    removed = []
    for f in list(vol.iterdir()):
        if f.is_file() and (f.name.endswith(('.zfw', '.zip')) or f.name.startswith('._')):
            f.unlink(); removed.append(f.name)
    print(f"volume {vol}: removed {removed or 'nothing'}")
    shutil.copyfile(out, vol / ZIPNAME)
    for f in list(vol.iterdir()):
        if f.name.startswith('._'): f.unlink()
    subprocess.run(['sync'])
    print(f"staged {ZIPNAME}; volume now: {[p.name for p in vol.iterdir()][:6]}")
    ser = None
    ports = sorted(Path('/dev').glob('cu.usbmodem*'))
    if ports:
        import serial
        ser = serial.Serial(str(ports[0]), 115200, timeout=1); ser.reset_input_buffer()
    for _ in range(4):
        ej = subprocess.run(['diskutil', 'eject', str(vol)], capture_output=True, text=True)
        if 'ejected' in (ej.stdout + ej.stderr) or not vol.is_dir(): break
        time.sleep(1.5)
    print("ejected; capturing the updater for up to 75 s ...")
    import importlib.util
    sys.argv = ['x', '1', '1']  # opzfarm.py parses argv at import time
    spec = importlib.util.spec_from_file_location('F', H / 'opzfarm.py')
    F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
    buf, ser = F._read_all(ser, 75, reopen=(lambda: None))
    if ser:
        try: ser.close()
        except Exception: pass
    raw = H / 'raws' / f"ablate_{time.strftime('%Y%m%d-%H%M%S')}.bin"
    raw.write_bytes(buf)
    text = b'\n'.join(p for _, _, p in F.frames(buf))
    print(f"\ncapture {len(buf)} B -> {raw}")
    for kw in (b'comparing', b'[extract] progress', b'Failed to extract', b'content: OK',
               b'upgrade was unsuccessful', b'disk_io', b'ENOENT', b'opendir failed'):
        n2 = text.count(kw)
        if n2: print(f"   {kw.decode():24s} x{n2}")
    for line in text.decode('latin1', 'replace').splitlines():
        if 'extract' in line or 'disk_io' in line or 'unsuccessful' in line or 'content:' in line:
            print("   |", line.strip()[:118])
    # the volume normally comes back within ~10 s; delete the archive so the next boot is clean
    print("\nwaiting for the volume to return so the archive can be removed (60 s) ...")
    dl = time.time() + 60
    while time.time() < dl:
        v = volume()
        if v is not None:
            print(f"   volume back: {v}")
            try:
                (v / ZIPNAME).unlink(); print(f"   deleted {ZIPNAME} - next boot is clean")
            except Exception as e:
                print(f"   could not delete: {e}")
            return 0
        time.sleep(2)
    print("   volume did not return within 60 s (a power cycle brings it back; I will clean it then)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
