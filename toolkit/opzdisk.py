#!/usr/bin/env python3
"""Place the kick sample pack on a MOUNTED OP-Z content disk (content mode).

Why the disk and not the updater: the eject sync registers packs and garbage-collects
samplepacks/user/ entries no plug references (§66.41). Raw updater writes never register.
The marker samplepacks/1-kick/01/~13.engine binds slot 01 of 1-kick to plug 13, so the kick
pack reaches track 1 through the disk's own layout with no plugs.json edit (§66.42).
"""
import json, shutil, subprocess, sys
from pathlib import Path

H = Path.home() / '.opz-decode'
VOLUME = Path('/Volumes/OP-Z')
# Each drum track's slot 01 marker names its plug, and the redmount DLC ships one pack per drum
# family, so the disk's own layout maps them one-to-one onto the four drum tracks:
#   1-kick/01/~13.engine -> plug 13  <- redmountKicks.aif
#   2-snare/01/~14.engine -> plug 14 <- redmountSnares.aif
#   3-perc/01/~15.engine  -> plug 15 <- redmountPerc.aif
#   4-fx/01/~17.engine    -> plug 17 <- redmountFX.aif
# samplepacks/user/ is the area the eject sync actually manages (it named the pack there
# "unused sample pack" and deleted it when no plug referenced it). Slot directories only ever
# hold the ~<plugid>.engine markers - a pack there survives but counts as 0 kB of samples.
MAPPING = (
    ('samplepacks/user', 'redmountKicks.aif', 13, 1),
    ('samplepacks/user', 'redmountSnares.aif', 14, 2),
    ('samplepacks/user', 'redmountPerc.aif', 15, 4),
    ('samplepacks/user', 'redmountFX.aif', 17, 8),
)
# the four drum plugs and the mask bits that name tracks 1-4 (bit N-1 = track N, per the catalogue)
DRUM_PLUGS = {pid: (name, mask) for _, name, pid, mask in MAPPING}


def main():
    if not (VOLUME / 'samplepacks').is_dir():
        print(f"not a mounted content disk: {VOLUME}/samplepacks missing "
              "(update mode shows only systeminfo/)")
        return 2
    missing = [f for _, f, _, _ in MAPPING if not (H / 'samples' / f).is_file()]
    if missing:
        print(f"missing packs in {(H / 'samples')}: {missing}")
        return 2
    # AppleDouble files would be scanned as content by the device
    for junk in VOLUME.rglob('._*'):
        junk.unlink()
    for rel, name, _pid, _mask in MAPPING:
        src = H / 'samples' / name
        dest = VOLUME / rel
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest / name)
        print(f"  {src.stat().st_size:>9,} B -> {rel}/{name}")
    # the slot-dir copies the previous attempt made are markers-only territory: drop them
    for slot in ('samplepacks/1-kick/01', 'samplepacks/2-snare/01',
                 'samplepacks/3-perc/01', 'samplepacks/4-fx/01'):
        for stale in (VOLUME / slot).glob('redmount*.aif'):
            stale.unlink(); print(f"  removed {slot}/{stale.name} (slot dirs hold markers, not audio)")
    # plugs.json has to travel WITH the pack: the eject sync keeps only packs some plug references,
    # and the updater cannot set the reference without crashing content mode's FAT export.
    plugs = json.loads((H / 'ablation/plugs.json.new').read_text())
    for rec in plugs['plugs']:
        if rec['id'] in DRUM_PLUGS:
            name, mask = DRUM_PLUGS[rec['id']]
            rec['samples'] = name
            rec['trackmask'] = mask
            print(f"  plug {rec['id']:>3} -> samples={name!r} trackmask={mask}")
    settings = VOLUME / 'settings'; settings.mkdir(exist_ok=True)
    (settings / 'plugs.json').write_bytes(json.dumps(plugs, indent=1).encode())
    print(f"  {(settings / 'plugs.json').stat().st_size:>9,} B -> settings/plugs.json")
    slt = VOLUME / 'settings' / 'slotConfiguration.json'
    if (H / 'ablation/slotConfiguration.json.new').is_file():
        shutil.copyfile(H / 'ablation/slotConfiguration.json.new', slt)
    for junk in VOLUME.rglob('._*'):
        junk.unlink()
    subprocess.run(['sync'])
    print("staged. Eject the disk to make the unit import and register the pack, "
          "then power-cycle and press track 1.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
