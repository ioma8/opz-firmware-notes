#!/usr/bin/env python3
"""opzhost.py - the OS memory an engine reads that is not in its own .engine file.

A factory engine is not self-contained. `initModule` receives a pointer to the OS's host-services table, and
the engines store that pointer in their own data and then read through it while rendering - `chord`, for
example, keeps it at `0x81be2d58` and reads `[table + 0xc]`, which is `0x0800bb44` in L2 SRAM: a 2048-entry
Q31 sine table the OS keeps there for exactly this purpose.

A harness that returns zero for that address gets silence, which is precisely what happened before this file
existed. So this module extracts the two regions an engine actually needs from the OS image and caches them:

    region                what it is
    0x0800b000..+0x3000   L2 SRAM, including the shared sine table at 0x0800bb44
    0x81003850..+0x40     the 13-entry host-services table itself

The regions are cached as JSON under ~/.cache/opzenginetool/hostmem.json so nothing derived from the firmware
lands in the repository. Regenerate with:

    python3 toolkit/opzhost.py extract

which drives headless Ghidra over from-sergey/firmware/blackfin/bin/opz.ldr (the OS image) and reads the two
ranges. Without the cache the tool still runs; engines that need host memory are just silent.
"""
import json, pathlib, subprocess, sys

CACHE = pathlib.Path.home() / ".cache" / "opzenginetool" / "hostmem.json"
TABLE_ADDR = 0x81003850          # what the OS passes as initModule's second argument
TABLE_WORDS = 13
REGIONS = [(0x0800B000, 0x3000), (TABLE_ADDR, 0x40)]


def image_path(image=None):
    for cand in (image, "from-sergey/firmware/blackfin/bin/opz.ldr", "/tmp/opz-fw/opz.ldr"):
        if cand and pathlib.Path(cand).exists():
            return pathlib.Path(cand)
    return None


def regions_from_image(image=None):
    """The two host regions built straight from the OS image.

    The image is a dlm container whose segments carry their own load addresses, so the bytes can be read
    directly with opzengine.parse - no Ghidra project and no cache are needed, and nothing derived from
    the firmware is written into the repository.
    """
    path = image_path(image)
    if path is None:
        return []
    import opzengine as E
    segs = E.parse(path.read_bytes())
    regions = []
    for base, size in REGIONS:
        buf = bytearray(size)
        for flags, dest, length, fill, payload in segs:
            end = dest + (len(payload) if payload else length)
            lo, hi = max(base, dest), min(base + size, end)
            if lo >= hi or not payload:
                continue
            for addr in range(lo, hi):
                off = addr - dest
                if off < len(payload):
                    buf[addr - base] = payload[off]
        regions.append((base, bytes(buf)))
    return regions


def load():
    """[(base, bytes)]: the cache when it exists, else the regions rebuilt from the OS image."""
    if CACHE.exists():
        try:
            cached = [(r["base"], bytes.fromhex(r["hex"])) for r in json.loads(CACHE.read_text())]
            if cached:
                return cached
        except Exception:
            pass
    return regions_from_image()


def host_table():
    """The 13 dwords of the host-services table, or the values documented in doc 11 as a fallback."""
    for base, blob in load():
        if base == TABLE_ADDR and len(blob) >= TABLE_WORDS * 4:
            return [int.from_bytes(blob[4 * i:4 * i + 4], "little") for i in range(TABLE_WORDS)]
    return [0x801098CE, 0x80109978, 0x81128264, 0x0800BB44, 0x11B019E8, 0x815C8070, 0x815C7E70,
            0x800314C0, 0x80031688, 0x80100E64, 0x800FBC78, 0x8012CC80, 0x8012CD48]


def apply_to_interpreter(machine, table_slot=None):
    """Preload the interpreter's external memory. Returns the address to pass as initModule's R1."""
    for base, blob in load():
        for i in range(0, len(blob) - 3, 4):
            machine.external[base + i] = int.from_bytes(blob[i:i + 4], "little")
    slot = table_slot if table_slot is not None else TABLE_ADDR
    if table_slot is not None:                      # relocated inside the module window
        for i, v in enumerate(host_table()):
            machine.st32(slot + 4 * i, v)
        return slot
    return TABLE_ADDR


def extract(image=None):
    """Drive Ghidra to pull the two ranges out of the OS image and cache them."""
    image = pathlib.Path(image or "from-sergey/firmware/blackfin/bin/opz.ldr")
    if not image.exists():
        raise SystemExit(f"OS image not found: {image}")
    ghidra = None
    for cand in pathlib.Path.home().glob("Applications/Ghidra_*/support/analyzeHeadless"):
        ghidra = cand
        break
    if ghidra is None:
        raise SystemExit("analyzeHeadless not found under ~/Applications/Ghidra_*")
    project = pathlib.Path("/tmp/opz-fw/ghidra")
    if not project.exists():
        raise SystemExit(f"Ghidra project not found: {project} (import opz.ldr first)")
    regions = []
    for base, size in REGIONS:
        out = pathlib.Path(f"/tmp/opzhost-{base:08x}.txt")
        cmd = [str(ghidra), str(project), "OPZ", "-process", "opz.ldr", "-noanalysis",
               "-scriptPath", "ghidra-scripts", "-postScript", "HexRange.java", str(out),
               f"0x{base:08x}", str(size)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if not out.exists():
            raise SystemExit(f"dump failed for 0x{base:08x}:\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
        words = {}
        for line in out.read_text().splitlines():
            parts = line.split()
            if not parts:
                continue
            a = int(parts[0], 16)
            for i, tok in enumerate(parts[1:17]):
                words[a + i] = int(tok, 16)
        lo = min(words)
        blob = bytes(words.get(a, 0) for a in range(lo, lo + size))
        regions.append({"base": lo, "size": len(blob), "hex": blob.hex()})
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(regions))
    print(f"cached {len(regions)} regions -> {CACHE}")
    for r in regions:
        print(f"  0x{r['base']:08x}  {r['size']} bytes")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "extract":
        extract(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        regs = load()
        print(f"{len(regs)} regions cached" if regs else "no host memory cached; run: opzhost.py extract")
        for base, blob in regs:
            print(f"  0x{base:08x}  {len(blob)} bytes")
        print("host table:", " ".join(f"{v:08x}" for v in host_table()))
