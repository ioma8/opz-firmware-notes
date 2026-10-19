#!/usr/bin/env python3
"""install_marimba.py - package the marimba-body engine for installation on an OP-Z.

Builds the engine, registers it as a plug in the OS's own `plugs_patch.json` auto_import list, and writes
a ZIP_STORED payload whose entry paths escape to the device's real locations. Staging is then the ordinary
update-medium procedure: copy the archive to the mounted volume as `firmware_bin_only_with_bootloader.zip`,
eject, and watch the console.

Placement is derived rather than guessed: the factory engines obey `base = 0x81be4c00 + (slot-61)*0x1400`
for every engine in slots 59..89 (fourteen of fourteen), the arena is a 0x1400-byte grid, and slot 63's
three slots end exactly where reverb (slot 66) begins. The engine is built for that slot and registered
with the same `memoryslot`.

What is still an assumption, stated plainly:
  * `memoryslot` -> address is verified by that regression but not by documentation, so a unit that
    disagrees would fail the loader's range check (`Bad address`, `dlm.cpp:0x57`) rather than misbehave;
  * the plug id 160 is above the factory cluster (10..153) and below the single large user id, i.e. a
    free number rather than a reserved one.

Usage:
    python3 toolkit/install_marimba.py --dry-run         # show the payload without writing it
    python3 toolkit/install_marimba.py -o payload.zip
"""
import json, pathlib, sys, zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import build_marimba

REPO = pathlib.Path(__file__).resolve().parent.parent
ENGINE_NAME = "marimba"
PLUG_ID = 160
MEMORYSLOT = 63                     # the slot the module is linked for: base 0x81be7400
TARGET_TRACKS = [4, 5, 6, 7]        # the synth tracks a plug can occupy


def patch_plugs(patch_path, dry_run=False):
    """Append our record to auto_import, preserving every existing entry."""
    if patch_path.exists():
        data = json.loads(patch_path.read_text())
    else:
        data = {"auto_import": []}
    entries = data.setdefault("auto_import", [])
    entries[:] = [e for e in entries if e.get("engine", {}).get("path") != f"engines/{ENGINE_NAME}.engine"]
    entries.append({
        "engine": {"memoryslot": MEMORYSLOT, "path": f"engines/{ENGINE_NAME}.engine", "version": 1},
        "plug": {
            "engine": f"engines/{ENGINE_NAME}.engine",
            "flags": 0,
            "id": PLUG_ID,
            "memoryslot": MEMORYSLOT,
            "name": ENGINE_NAME,
            "samples": "",
            "version": 1,
        },
        "tracks": TARGET_TRACKS,
    })
    return data


def build_payload(engine_bytes, plugs_json):
    """ZIP_STORED with entry paths that land on the device's real files."""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr(f"../user/engines/{ENGINE_NAME}.engine", engine_bytes)
        z.writestr(f"../system/content/engines/{ENGINE_NAME}.engine", engine_bytes)
        z.writestr("../system/content/settings/plugs_patch.json",
                   json.dumps(plugs_json, indent=1))
    return buf.getvalue()


def build_full_payload(tree, engine_bytes, plugs_json):
    """A payload the bootloader accepts: the genuine firmware tree plus our files.

    A three-entry zip is refused before extraction - the installer looks for the BLE component
    (`failed to find ble firmware file`) and logs `upgrade not compatible with this device`. It
    extracts a whole `firmware/` tree and installs `firmware/blackfin/system/content/` from it, so
    the engine and the patched registry ride along inside that tree.
    """
    import io
    buf = io.BytesIO()
    eng = f"firmware/blackfin/system/content/engines/{ENGINE_NAME}.engine"
    reg = "firmware/blackfin/system/content/settings/plugs_patch.json"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for f in sorted(tree.rglob("*")):
            if not f.is_file() or f.name.startswith("._") or f.name == ".DS_Store":
                continue
            rel = f"firmware/{f.relative_to(tree).as_posix()}"
            if rel == eng or rel == reg:
                continue                      # ours replaces the factory copy
            z.writestr(rel, f.read_bytes())
        z.writestr(eng, engine_bytes)
        z.writestr(reg, json.dumps(plugs_json, indent=1))
    return buf.getvalue()


def main(argv):
    dry = "--dry-run" in argv
    out = pathlib.Path(argv[argv.index("-o") + 1]) if "-o" in argv else pathlib.Path("marimba_payload.zip")

    engine, code, hl, cl, dl = build_marimba.build()
    print(f"engine   {len(engine)} B   header 0x{build_marimba.MOD_BASE:08x} "
          f"code {cl} B @0x{build_marimba.CODE_BASE:08x} data {dl} B @0x{build_marimba.DATA_BASE:08x}")
    print(f"         memoryslot {MEMORYSLOT}, span 0x{build_marimba.MOD_BASE:08x}"
          f"..0x{build_marimba.MOD_BASE + hl + cl + dl:08x}")

    firmware_patch = REPO / "from-sergey/firmware/blackfin/system/content/settings/plugs_patch.json"
    plugs = patch_plugs(firmware_patch, dry)
    auto = plugs["auto_import"]
    print(f"plugs    auto_import now holds {len(auto)} entr{'y' if len(auto) == 1 else 'ies'}; "
          f"ours is id {PLUG_ID} on tracks {TARGET_TRACKS}")

    tree = REPO / "from-sergey" / "firmware"
    full = "--full" in argv
    payload = build_full_payload(tree, engine, plugs) if full else build_payload(engine, plugs)
    print(f"payload  {len(payload)} B (ZIP_STORED, {'full firmware tree' if full else 'engine files only'})")
    with zipfile.ZipFile(__import__("io").BytesIO(payload)) as z:
        for info in z.infolist():
            print(f"         {info.filename:52s} {info.file_size:7d} B")
        assert z.testzip() is None

    if dry:
        print("\n--dry-run: nothing written")
        return 0
    out.write_bytes(payload)
    print(f"\nwrote {out}")
    print(f"""
Next, on the device (this is the step that needs hands, not code):
  1. put the OP-Z in upgrade mode and mount its volume;
  2. delete stray .zip/.zfw/._ files from the volume, then copy this archive there as
     firmware_bin_only_with_bootloader.zip;
  3. eject, and watch the console while the updater runs;
  4. play a note on a synth track and select plug id {PLUG_ID} ("{ENGINE_NAME}").

What to look for:
  * "Can't load engine {PLUG_ID}" means the plug registered but the module was rejected -- compare the
    log line against dlm's messages (Bad header / Bad address / Data outside buffer);
  * silence from the plug with no engine error means it loaded and the note/gate path is wrong;
  * a pitched strike means it works: measure A4 at 440 Hz and confirm the tail shortens as the decay
    macro is turned down.""")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
