#!/usr/bin/env python3
"""opzplugs.py - the factory plug definitions, read from the OP-Z app's package.

The APK carries `assets/factory-plug-cache/<id>/metadata.json`, one per factory plug, and each lists the
engine it drives, its parameter names, and every factory preset with its values:

    {"name": "saw", "plugs": [{"engine": "saw013a.engine",
                               "parameterNames": ["offset", "space"],
                               "presets": [{"name": "stump", "values": [32, 0, ...]}]}]}

This is the patch data the firmware does not contain: `settings/plugs.json` inside the OS image holds only
engine ids and paths, with no parameter values anywhere. The same preset names appear in the OS image's
`settings/plugPresets.dat`, which is the packed form of this data.

Nothing derived here is written into the repository - the APK is read in place.

Usage:
    python3 toolkit/opzplugs.py                     # every engine and its parameter names
    python3 toolkit/opzplugs.py digital.engine      # one engine, with its presets
"""
import json, pathlib, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
APK = ROOT / "OP-Z_1.3.0_APKPure.apk"
PREFIX = "assets/factory-plug-cache/"


def plugs(apk=None):
    """{engine: {"params": [...], "presets": [{"name": ..., "values": [...]}]}}"""
    path = pathlib.Path(apk or APK)
    if not path.exists():
        return {}
    out = {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not (name.startswith(PREFIX) and name.endswith("metadata.json")):
                continue
            meta = json.loads(z.read(name))
            for plug in meta.get("plugs", []):
                engine = plug.get("engine") or ""
                if not engine:
                    continue                        # 'performance basic', 'dmx basic' drive no engine
                entry = out.setdefault(engine, {"params": plug.get("parameterNames", []), "presets": []})
                for preset in plug.get("presets", []):
                    entry["presets"].append({"name": preset["name"],
                                             "values": list(preset.get("values", []))})
    return out


def main(argv):
    table = plugs()
    if not table:
        raise SystemExit(f"no plug definitions found (looked in {APK})")
    if argv:
        for engine, entry in sorted(table.items()):
            if engine != argv[0] and pathlib.Path(engine).stem != pathlib.Path(argv[0]).stem:
                continue
            print(f"{engine}  params={entry['params']}  {len(entry['presets'])} presets")
            for preset in entry["presets"]:
                print(f"  {preset['name']:16s} {preset['values']}")
        return 0
    for engine, entry in sorted(table.items()):
        print(f"  {engine:22s} params={entry['params']}  presets={len(entry['presets'])}")
    print(f"\n{len(table)} engines, {sum(len(v['presets']) for v in table.values())} presets")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
