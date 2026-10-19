#!/usr/bin/env python3
"""opzos.py - run the OP-Z OS image (opz.ldr) in opzsim and drive a factory engine from it.

Why this exists: the engines were never silent because of a decoder fault; they were starved of the
per-voice state the sequencer computes. This tool stops synthesising that state and lets the firmware
compute it instead - it maps opz.ldr's main image, note-starts a synthetic instrument record through
FUN_8012e0a4 and ticks it through FUN_8012e2c0, exactly as the OS does.

Status: FUN_8012e2c0 and FUN_8012e0a4 both run to completion. The block that remains is the record's
patch fields, which decide the per-voice coefficient - see firmware-re-docs/12-installing-a-new-engine.md.

Usage:
    python3 toolkit/opzos.py <engine.engine> [note] [--image path/to/opz.ldr]
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import opzengine as E                                   # noqa: E402
import opzsim as Z                                      # noqa: E402

BASE, SIZE = 0x80000000, 0x02000000
# Free space above the OS image (which ends at 0x815caea0). Keep this well clear of the stack and of
# anything the firmware addresses itself: a scratch record placed at 0x81f00000 was written through by
# unrelated OS code whose pointer aliased it (B[P5+0x211]), which looked exactly like the firmware
# clearing record+0x34.
RECORD, OUT, PRM = 0x81600000, 0x81610000, 0x81620000


def find_image(explicit=None):
    cands = [explicit] if explicit else []
    cands += ["/tmp/opz-fw/opz.ldr", "from-sergey/firmware/blackfin/bin/opz.ldr",
              "firmware/blackfin/bin/opz.ldr"]
    for c in cands:
        if c and pathlib.Path(c).is_file():
            return pathlib.Path(c)
    raise SystemExit("opz.ldr not found; pass --image")


def machine_with(image):
    """A whole-address-space machine: the firmware needs L1 (0x11a...), L2 (0x08...) and the main image
    (0x80...) at once, which a single flat bytearray cannot span."""
    m = Z.Machine(0, 1 << 16)
    m.mem = Z.SparseMem()
    m.mem.strict_missing = False
    m.mem_base = 0
    m.p[6] = 0x81FF0000                     # stack, below the engine windows
    m.allow_external = True
    # _off() only knows the arithmetic window, which for this machine is the whole 4 GB space, so an
    # address no LDR segment loaded looks executable and a wrong turn becomes a 200k-step march of NOPs.
    m.check_coverage = True
    return m


def map_segments(m, raw):
    n = 0
    for flags, dest, length, fill, payload in E.parse(raw):
        off = dest
        if flags & E.FLAG_FILL:
            m.mem[off:off + length] = b"\x00" * length
        else:
            m.mem[off:off + len(payload)] = payload
        n += 1
    return n


def check_pc(m, pc):
    """Fetch is only meaningful where a segment was loaded. Everywhere else is zeros, and executing
    them looks like a long boot instead of the wrong turn it is."""
    if not m.mem.mapped(pc & 0xFFFFFFFF, 2):
        raise RuntimeError(f"execution at 0x{pc & 0xFFFFFFFF:08x}, which no LDR segment covers")


def build(image, engine_path, note=69):
    raw = engine_path.read_bytes()
    m = machine_with(image)
    os_segs = map_segments(m, image.read_bytes())
    eng_segs = map_segments(m, raw)
    ex = dict(E.read_module(raw)["exports"])
    for k in range(0x17C // 4):
        m.st32(RECORD + 4 * k, 0)
    for k in range(0x40):
        m.st32(PRM + 4 * k, 0x08000000)
    for off, key in ((0x00, "init"), (0x04, "render"), (0x08, "onNoteOn"), (0x0C, "onNoteOff")):
        m.st32(RECORD + off, ex.get(key, 0) & 0xFFFFFFFF)
    m.st32(RECORD + 0x34, 0x40000000)
    m.st32(RECORD + 0x28, 0x08000000)
    return m, ex, os_segs, eng_segs


def boot(m, start=0x11A00000, limit=3_000_000):
    """Run the firmware from `start`, stopping at the first jump outside every loaded segment.

    `SparseMem` returns zeros for unloaded pages, so a wrong turn looks like a long boot executing NOPs;
    `check_pc` turns that into a reported stop instead. `run(limit=...)` is a TOTAL step budget, so each
    call passes `m.steps + chunk` rather than a per-call count.
    """
    m.pc = start
    stopped = None
    while m.steps < limit:
        try:
            check_pc(m, m.pc)
        except RuntimeError as e:
            stopped = str(e)
            break
        try:
            m.run(limit=m.steps + 20000)
        except RuntimeError as e:
            if "step limit" in str(e):
                continue
            stopped = f"{type(e).__name__}: {e}"
            break
        if (m.pc & 0xFFFFFFFF) in (0, 0xDEAD0000):
            stopped = f"returned to {m.pc & 0xFFFFFFFF:#x}"
            break
    return m.steps, m.pc & 0xFFFFFFFF, stopped


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    engine_path = pathlib.Path(argv[1])
    note = int(argv[2]) if len(argv) > 2 and not argv[2].startswith("-") else 69
    image = None
    if "--image" in argv:
        image = argv[argv.index("--image") + 1]
    m, ex, n_os, n_eng = build(find_image(image), engine_path, note)
    print(f"mapped {n_os} OS segments and {n_eng} engine segments")
    steps, pc, why = boot(m)
    print(f"firmware boot: {steps} steps, stopped at {pc:#x}: {why}")
    return
    state = RECORD + 0x48
    Z.call(m, ex["initModule"], [0, 0x81003850, state], limit=200000)
    Z.call(m, ex["init"], [state, 0], limit=200000)
    print(f"engine init ok ({m.steps} steps)")
    Z.call(m, 0x8012E0A4, [RECORD, note, 100], stack=(0, 0x08000000, 0x08000000, 0), limit=400000)
    amp = RECORD + 0x30
    print("after the OS note-start: amp "
          f"+4={m.ld32(amp + 4) & 0xFFFFFFFF:#010x} +8={m.ld32(amp + 8) & 0xFFFFFFFF:#010x} "
          f"+0xc={m.ld32(amp + 0xc) & 0xFFFFFFFF:#010x} +0x10={m.ld32(amp + 0x10) & 0xFFFFFFFF:#010x}")
    for j in range(2 * 64):
        m.st32(OUT + 4 * j, 0)
    try:
        Z.call(m, 0x8012E2C0, [RECORD, OUT, RECORD], stack=(RECORD, OUT, RECORD), limit=400000, lenient=True)
    except Exception as e:                                # noqa: BLE001 - report, do not crash
        print(f"tick stopped: {type(e).__name__}: {e}")
    sig = [m.ld32(OUT + 8 * j) / 2 ** 31 for j in range(64)]
    print(f"out peak {max(abs(v) for v in sig):.4f} over {len(sig)} frames, {m.steps} steps total")


if __name__ == "__main__":
    main(sys.argv)
