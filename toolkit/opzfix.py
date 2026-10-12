#!/usr/bin/env python3
"""Write settings/plugs.json + config/dmx.json through the §24 updater primitive.

Diagnosis this implements (all from the device's own log):
  fxmanager: Couldn't find plug with id 34/36/37/39   -> g_plugs is empty. §25.2 showed that
      settings/plugs.json is its only filler in the normal boot path, and that the earlier test of
      that file ran BEFORE the engine binaries existed, so its plugs had no engine behind them.
      Empty plug table + PLAY = the null call (iid 0x0013002c / RETX 0, and the same RETX 0x8010ea4c
      as the init fault).
  dmxcontroller: Invalid dmx config json + 16x 'failed to find dmx fixture mode rgb'
      -> config/dmx.json missing; the mode is literally named "rgb" in the failure message.

Schema for plugs.json taken from the app binary itself (PlugManager::exportPlugDefinitions @ 0xd8790
and readPlugSettings @ 0xd54e0): top-level "engines" and "plugs" arrays; per plug "id", "path",
"engine", "version", "flags", "samples"; per engine "memoryslot", "version"; per preset "name",
"index", "slot", "values" (18 ints), "defaultOctave". Engine paths are written as engines/<name>.engine
to match the installed binaries.

usage: opzfix.py [--dry-run]        (stages firmware_bin_only_with_bootloader.zip on the volume)
"""
import importlib.util, json, re, subprocess, sys, time, zipfile
from pathlib import Path

H = Path.home() / '.opz-decode'
REPO = Path('/Users/jakubkolcar/projects/customs/opz-firmware-notes')
FACTORY = json.loads((REPO / 'opz-factory-plugs.json').read_text())
CATALOGUE = json.loads((REPO / 'te-dlcs.json').read_text())
ZIPNAME = 'firmware_bin_only_with_bootloader.zip'
FACTORY_DRUMS = False
ENGINES_ONLY = False  # TEST: write a plug table whose every plug maps to one loading engine (66.67)
WRITE_ENGINES = True  # the content-disk eject sync strips /yaffs2/user/engines/, so restore them
# The app installs a sample pack by creating its OWN plug (catalogue ids 150-153 = 'rdmt kicks/snares/perc/fx',
# engine sampleplayergain, samples redmountKicks/Snares/Perc/FX.aif, masks 1/2/4/8) and then pointing the drum
# track at that plug. So a working drum track is (pack plug id 150-153) + (the .aif at <root>/samplepacks/),
# not plug 13 with the catalogue's own record (which is chorus-80 and crashes an FX engine onto a drum track).
PACK_PLUGS = False  # a sampler plug whose 'samples' file cannot resolve floods the log and nulls the sample object
WRITE_PACKS = False    # the disk import owns the packs now; updater copies land in samplepacks/user/ and get GC'd
WRITE_SLOTCONFIG = True   # test: bind all 16 tracks to ONE plug whose engine is known to load
WRITE_DMX = True          # config/dmx.json is harmless and the device reads it
# Restore the healthy unit's own files from the pre-brick content-disk backup. These are the files the
# device reads but the content disk cannot deliver (its 'Syncronizing projects' exports rather than imports),
# and the preset bank MUST carry format field 1: a zero-filled file makes the boot fault with
# 'plugmanager: Wrong file format: /yaffs2/user/config/userPresets.dat (0 != 1)'.
BACKUP = Path('/Users/jakubkolcar/projects/customs/opz-firmware-notes/2026-03-19_12-22-51')
RESTORE_BACKUP = False  # payload already delivered; test the slot map on its own


def build_payloads():
    # Define EXACTLY the ids the device asks for: the instrument manager resolves through its default map
    # (13,14,15,17,21,25,28,31,34,36,37,39,60,70,80,100) and the fxmanager asks for 36/37, so every one of
    # those must exist with a real engine that has a published memory slot. Plug 13 (the kick) takes
    # sampleplayergain, because the catalogue's own plug 13 is chorus-80 and an FX engine on a drum track
    # is what produces the null-function crash (iid 0x0013002c, RETX 0) on track select.
    # ponytail: nine ids are given borrowed-but-placeable engines; replace them if TE ever publishes theirs.
    PAIRS = [(13, 'sampleplayergain'), (14, 'organ'), (15, 'analoga'), (17, 'ep'), (21, 'cluster'), (25, 'digital'),
             (28, 'saw013a'), (31, 'chord'), (34, 'delay'), (36, 'reverb'), (37, 'fdnreverb'), (39, 'chorus'),
             (60, 'volt'), (70, 'fm003b'), (80, 'dist'), (100, 'synthsampler')]
    assert len({e for _, e in PAIRS}) == len(PAIRS), 'engines must be distinct'
    # trackmask is a bitmask (bit N-1 = track N): the four drum tracks are 1/2/4/8 and the synth
    # group is 240, so a drum plug carrying the catalogue's 240 can never play a note.
    DRUM_MASKS = {13: 1, 14: 2, 15: 4, 17: 8}
    slots = json.loads((H / 'engines-memoryslot.json').read_text())
    engines = [{'path': f'engines/{e}.engine', 'version': 1, 'memoryslot': int(slots[f'{e}.engine'])}
               for _, e in PAIRS]
    # real plug records: the catalogue first (it covers 13/14/17 etc), then the factory file
    recs = {}
    for r in CATALOGUE if isinstance(CATALOGUE, list) else CATALOGUE.get('dlcs', []):
        for q in r.get('plugs', []) or []:
            recs[q['id']] = {'cat_engine': (q.get('engine') or ''), 'flags': q.get('flags', 0), 'trackmask': q.get('trackmask', 240),
                             'samples': q.get('samples', ''),
                             'parameterNames': q.get('parameter_names', []),
                             'presets': [{'name': pr.get('name', ''), 'index': int(pr.get('index', 0)),
                                          'slot': int(pr.get('slot', 0)),
                                          'defaultOctave': int(pr.get('default_octave', 0)),
                                          'values': [int(v) for v in (pr.get('values') or [])][:18]}
                                         for pr in (q.get('presets') or [])]}
    for q in FACTORY['plugs']:
        recs.setdefault(q['id'], {'flags': q.get('flags', 0), 'trackmask': q.get('trackmask', 240),
                                  'samples': q.get('samples', ''), 'presets': q.get('presets', [])})
    plugs = []
    for pid, eng in PAIRS:
        src = recs.get(pid, {})
        if src.get('cat_engine') and src['cat_engine'] != f'{eng}.engine':
            src = {}  # catalogue record describes a different engine: use neutral defaults
        rec = {'id': pid, 'version': 1, 'flags': src.get('flags', 0), 'samples': src.get('samples', ''),
               'trackmask': DRUM_MASKS.get(pid, src.get('trackmask', 240)), 'engine': f'engines/{eng}.engine'}
        presets = []
        for pr in src.get('presets', []) or []:
            q = {'name': pr.get('name', ''), 'index': int(pr.get('index', 0)), 'slot': int(pr.get('slot', 0)),
                 'defaultOctave': int(pr.get('defaultOctave', 0)),
                 'values': [int(v) for v in (pr.get('values') or [])][:18]}
            q['values'] += [0] * (18 - len(q['values']))
            presets.append(q)
        if presets:
            rec['presets'] = presets
        plugs.append(rec)
    # The four factory drum plugs (catalogue 121-124: te-kicks/te-snares/te-perc/te-fx) all use
    # engines/sampleplayergain.engine with a samples name that exists nowhere on the content disk
    # (TeKicks.aif, TeSnares.aif, TePercs.aif, TeFX.aif) and the drum masks 1/2/4/8. Those names can
    # therefore only resolve from firmware. Give plugs 13/14/15/17 exactly that shape: if the ROM
    # resolves them the four drum tracks work with no external pack at all; if it does not they fail
    # the way ours did (repeated AIFF_ReadOpen retries). Set FACTORY_DRUMS = False to revert.
    if FACTORY_DRUMS:
        for pid, (name, mask) in ((13, ('TeKicks.aif', 1)), (14, ('TeSnares.aif', 2)),
                                 (15, ('TePercs.aif', 4)), (17, ('TeFX.aif', 8))):
            for rec in plugs:
                if rec['id'] == pid:
                    rec['samples'], rec['trackmask'] = name, mask
                    rec['engine'] = 'engines/sampleplayergain.engine'
    plugs.append({'id': 109, 'version': 1, 'flags': 0, 'samples': '', 'trackmask': 768,
                  'engine': 'engines/crush.engine', 'presets': []})   # the fx manager asks for this id
    track_pids = [pid for pid, _ in PAIRS]
    if PACK_PLUGS:
        # The sample packs the device now really plays are the redmount set installed through the content disk.
        # Every id the device asks for must exist: 121-124 because its own '~121.engine' marker in 1-kick/01
        # makes it build a plug with that id, 150-153 because the app's catalogue numbers the redmount pack
        # that way, and 109 because the fx manager requests it. All of them name a pack that is really present,
        # since a plug whose pack cannot resolve leaves the null sample object that PLAY faults on.
        RED = {121: ('redmountKicks.aif', 1), 122: ('redmountSnares.aif', 2),
               123: ('redmountPerc.aif', 4), 124: ('redmountFX.aif', 8),
               150: ('redmountKicks.aif', 1), 151: ('redmountSnares.aif', 2),
               152: ('redmountPerc.aif', 4), 153: ('redmountFX.aif', 8)}
        for pid, (nm, mask) in RED.items():
            plugs.append({'id': pid, 'version': 1, 'flags': 0, 'samples': nm, 'trackmask': mask,
                          'engine': 'engines/sampleplayergain.engine', 'presets': []})
    plugs_json = {'engines': engines, 'plugs': plugs}
    slot_json = {'tracks': [{'index': t, 'packs': [{'id': pid, 'slot': 1}]}
                            for t, pid in enumerate(track_pids)]}
    dmx_json = {'profiles': [{'name': 'rgb', 'channels': ['red', 'green', 'blue']}],
                'config': [{'index': i, 'name': 'rgb'} for i in range(16)]}
    return plugs_json, dmx_json, slot_json


def volume():
    for p in sorted(Path('/').glob('Volumes/OP-Z*')):
        if p.is_dir():
            return p
    return None


def main():
    plugs_json, dmx_json, slot_json = build_payloads()
    pb = json.dumps(plugs_json, indent=1).encode()
    db = json.dumps(dmx_json, indent=1).encode()
    sb = json.dumps(slot_json, indent=1).encode()
    print(f"plugs.json            : {len(pb):,} B  {len(plugs_json['engines'])} engines, {len(plugs_json['plugs'])} plugs")
    print(f"slotConfiguration.json: {len(sb):,} B  {len(slot_json['tracks'])} tracks -> plug "
          f"{slot_json['tracks'][0]['packs'][0]['id']}")
    print(f"dmx.json              : {len(db):,} B  1 profile + {len(dmx_json['config'])} fixtures")
    ids = sorted(r['id'] for r in plugs_json['plugs'])
    print(f"  plug ids: {ids}")
    print(f"  engine paths referenced: {len(plugs_json['engines'])}")
    if '--dry-run' in sys.argv:
        (H / 'ablation').mkdir(exist_ok=True)
        (H / 'ablation/plugs.json.new').write_bytes(pb)
        (H / 'ablation/dmx.json.new').write_bytes(db)
        (H / 'ablation/slotConfiguration.json.new').write_bytes(sb)
        print("dry run: written to ~/.opz-decode/ablation/*.new")
        return 0
    vol = volume()
    if vol is None:
        print("no OP-Z volume: the unit must be in UPDATE mode")
        return 2
    out = H / 'ablation' / ZIPNAME
    eng_files = sorted((H / 'engines-official').glob('*.engine'))
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as z:
        # THE fix: the dlm loader opens /yaffs2/user/engines/<name>.engine, which is where the log shows
        # every engine load failing. The first ablation put these in samplepacks/user/ - wrong path.
        smp = []   # the disk owns the packs now; blanking leftovers only plants 0-byte packs
        if smp:
            # FileManager::getAbsolutePath(rel) is literally root + rel, and a pack under
            # /yaffs2/user/samplepacks/** is provably never opened by the playback loader. If the root is
            # /yaffs2/ then the app's own "user/..." relatives explain every absolute path in its logs, and
            # the pack belongs at /yaffs2/<name>. One '..' from the updater's /yaffs2/upgrade/ base reaches
            # /yaffs2/ exactly (two reach past the yaffsfs root and fail), so '../../' is not usable but
            # '../' is - giving a location completely outside the content tree.
            z.writestr(f'../{smp[0].name}', b'')
            # Blank every copy ever planted inside /yaffs2/user/. Content mode builds its FAT export by
            # walking that tree and faults on unexpected entries in samplepacks/ (mass_storage: create and
            # mount FAT, FA 0x1, RETX 0x80033fd6), which is what makes content mode unreachable. The
            # updater can only write, never delete, so the files are truncated to 0 bytes to reclaim space.
            for rel in ('samplepacks', 'samplepacks/user', 'samplepacks/1-kick', 'samplepacks/1-kick/01'):
                if PACK_PLUGS and rel in ('samplepacks', 'samplepacks/user'):
                    continue  # these two now carry the real kick pack, so do not blank them
                z.writestr(f'../user/{rel}/{smp[0].name}', b'')
        if WRITE_ENGINES:
            # The app's sync emptied these files: its client state says "same crc", so it never re-sends
            # the data, and finalize then finds a 0-byte file (crc 0 != expected) - which is why the unit
            # logs 'instrumentmanag: Can't load engine 17' and crashes when that track is selected. All 21
            # official binaries match the CRCs the device expects (verified 13/13 where the log named
            # them), so writing them back makes the app's verification pass and lets the sample packs it
            # already downloaded apply.
            for f in eng_files:
                z.writestr(f'../user/engines/{f.name}', f.read_bytes())
        if PACK_PLUGS and WRITE_PACKS:
            # The app's own pairing: the .aif in the samplepacks tree it asks the device to write. 'samplepacks/'
            # is the first prefix the loader tries, and 'samplepacks/user/' is the fallback, so seed both.
            for nm in ('redmountKicks.aif', 'redmountSnares.aif', 'redmountPerc.aif', 'redmountFX.aif'):
                f = H / 'samples' / nm
                if f.is_file():
                    b = f.read_bytes()
                    z.writestr(f'../user/samplepacks/{nm}', b)
                    z.writestr(f'../user/samplepacks/user/{nm}', b)
        if RESTORE_BACKUP and BACKUP.is_dir():
            for proj in sorted((BACKUP / 'projects').glob('*.opz')):
                z.writestr(f'../user/projects/{proj.name}', proj.read_bytes())
            for nm in ('userPresets.dat', 'dmx.json', 'general.json', 'midi.json'):
                f = BACKUP / 'config' / nm
                if f.is_file():
                    z.writestr(f'../user/config/{nm}', f.read_bytes())
        if WRITE_DMX:
            z.writestr('../user/config/dmx.json', db)
        if not ENGINES_ONLY:
            # Only ever reached intentionally: this file is the device's own rebuilt plug table, and
            # overwriting it costs the pack plugs and the drum sound (see section 66.51).
            z.writestr('../user/settings/plugs.json', pb)
            if WRITE_SLOTCONFIG:
                z.writestr('../user/settings/slotConfiguration.json', sb)
        z.writestr('P0.txt', b'engine+plug fix\n')
    print(f"built {out} ({out.stat().st_size:,} B, 7 entries "
          f"= pack at /yaffs2/ + 4 blanks + 3 json + marker)")
    removed = []
    for f in list(vol.iterdir()):
        if f.is_file() and (f.name.endswith(('.zfw', '.zip')) or f.name.startswith('._')):
            f.unlink(); removed.append(f.name)
    print(f"volume {vol}: removed {removed or 'nothing'}")
    (vol / ZIPNAME).write_bytes(out.read_bytes())
    for f in list(vol.iterdir()):
        if f.name.startswith('._'): f.unlink()
    subprocess.run(['sync'])
    print(f"staged. volume now: {[p.name for p in vol.iterdir()][:6]}")
    ser = None
    ports = sorted(Path('/dev').glob('cu.usbmodem*'))
    if ports:
        import serial
        ser = serial.Serial(str(ports[0]), 115200, timeout=1); ser.reset_input_buffer()
    for _ in range(4):
        ej = subprocess.run(['diskutil', 'eject', str(vol)], capture_output=True, text=True)
        if 'ejected' in (ej.stdout + ej.stderr) or not vol.is_dir(): break
        time.sleep(1.5)
    print("ejected; capturing the updater until the extract settles (max 480 s) ...")
    sys.argv = ['x', '1', '1']
    spec = importlib.util.spec_from_file_location('F', H / 'opzfarm.py')
    F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
    buf = b''; seen = -1; idle = 0
    while idle < 3 and len(buf) < 40_000_000:
        chunk, ser = F._read_all(ser, 20, reopen=(lambda: None))
        if not chunk:
            break
        buf += chunk
        tt = b'\n'.join(p for _, _, p in F.frames(buf))
        pr = re.findall(rb'\[extract\] progress (\d+)/(\d+)', tt)
        cur, tot = (int(pr[-1][0]), int(pr[-1][1])) if pr else (-1, -1)
        if cur == seen: idle += 1
        else: idle = 0
        seen = cur
        if tot > 0 and cur >= tot: break
        if tt.count(b'unsuccessful') > 3 and cur < 0: break
    if ser:
        try: ser.close()
        except Exception: pass
    (H / 'raws' / f"plugfix_{time.strftime('%Y%m%d-%H%M%S')}.bin").write_bytes(buf)
    text = b'\n'.join(p for _, _, p in F.frames(buf))
    for kw in (b'comparing', b'[extract] progress', b'Failed to extract', b'unsuccessful'):
        n = text.count(kw)
        if n: print(f"   {kw.decode():22s} x{n}")
    pr = re.findall(rb'\[extract\] progress (\d+)/(\d+)', text)
    if pr:
        cur, tot = int(pr[-1][0]), int(pr[-1][1])
        print(f"   extract: last {cur}/{tot} -> {'COMPLETE' if cur >= tot else 'INCOMPLETE'}")
    for line in text.decode('latin1', 'replace').splitlines():
        if '[extract]' in line or 'comparing' in line:
            print("   |", line.strip()[:110])
        if 'redmount' in line.lower() or 'samplepacks/user' in line:
            print("   *", line.strip()[:110])
    print("\nNEXT: power-cycle. The write lands on the following boot; then a further power-on is the test.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
