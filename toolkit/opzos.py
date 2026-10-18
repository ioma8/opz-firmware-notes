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
RECORD, OUT, PRM = 0x81F00000, 0x81F10000, 0x81F20000


def find_image(explicit=None):
    cands = [explicit] if explicit else []
    cands += ["/tmp/opz-fw/opz.ldr", "from-sergey/firmware/blackfin/bin/opz.ldr",
              "firmware/blackfin/bin/opz.ldr"]
    for c in cands:
        if c and pathlib.Path(c).is_file():
            return pathlib.Path(c)
    raise SystemExit("opz.ldr not found; pass --image")


def machine_with(image):
    m = Z.Machine(BASE, SIZE)
    m.allow_external = True
    return m


def map_segments(m, raw):
    n = 0
    for flags, dest, length, fill, payload in E.parse(raw):
        if not (BASE <= dest < BASE + SIZE):
            continue
        off = dest - BASE
        if flags & E.FLAG_FILL:
            m.mem[off:off + length] = b"\x00" * length
        else:
            m.mem[off:off + len(payload)] = payload
        n += 1
    return n


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
        Z.call(m, 0x8012E2C0, [RECORD, OUT, RECORD], stack=(RECORD, OUT, RECORD), limit=400000)
    except Exception as e:                                # noqa: BLE001 - report, do not crash
        print(f"tick stopped: {type(e).__name__}: {e}")
    sig = [m.ld32(OUT + 8 * j) / 2 ** 31 for j in range(64)]
    print(f"out peak {max(abs(v) for v in sig):.4f} over {len(sig)} frames, {m.steps} steps total")


if __name__ == "__main__":
    main(sys.argv)
