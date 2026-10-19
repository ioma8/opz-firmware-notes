#!/usr/bin/env python3
"""opzfxcheck.py - do the factory effect engines process audio?

Runs each of the eight factory effects from the vendor's own ARM64 library
(`~/.opz-decode/opzso/libSnakePlugin.so`, symbols in `syms.json`) under Unicorn and measures how many output
samples are non-zero. Nothing here is a reimplementation: it is the vendor's code, called with the arguments its
mangled symbol names declare.

Three things had to be right before any effect worked, and each cost a round of this investigation:

  signature   `renderFX(unsigned const* params, int frames, void* state, fract32_t* in, fract32_t* out, ...)` -
              params and frame count FIRST, buffers third and fourth
  scratch     some effects need a buffer of their own as the sixth argument; handing them the output buffer
              silences `Chorus2`
  in place    `Chorus` writes into the INPUT buffer and never into the output one - an insert effect
  latency     `Delay` emits nothing for the first ~58 ms (block 44) and `FdnReverb` until block 27, so short runs
              read as silence

The loader comes from the sibling porting repository (`~/projects/customs/opz-clone/tools/unicorn-harness`);
this script only drives it, so the clone must be present.

Usage:
    python3 toolkit/opzfxcheck.py [--blocks N]
"""
import argparse, json, math, pathlib, struct, sys

CLONE_HARNESS = pathlib.Path.home() / "projects/customs/opz-clone/tools/unicorn-harness"
SYMS = pathlib.Path.home() / ".opz-decode/opzso/syms.json"

EFFECTS = ("Chorus", "Chorus2", "Crush", "Delay", "Dist", "FdnReverb", "Reverb", "TapeTwo")


def symbols():
    return {s["name"]: s["vaddr"] for s in json.loads(SYMS.read_text())["symbols"]}


def mangled(syms, cls, suffix):
    for name in syms:
        if name.startswith(f"_ZN{len(cls)}{cls}") and suffix in name:
            return name
    return None


def run_one(cls, syms, blocks, OpzSo, UC_PROT_ALL, X0):
    init_module = mangled(syms, cls, "initModule")
    init = mangled(syms, cls, "4init")
    render = mangled(syms, cls, "renderFX")
    if not render:
        return None, "no renderFX symbol"

    so = OpzSo()
    for base, size in ((0x1E0000, 0x200000 - 0x1E0000), (0x200000, 0x1800000)):
        try:
            so.uc.mem_map(base, size, UC_PROT_ALL)      # the library declares a 24 MB BSS
        except Exception:
            pass
    so.stub("noop", lambda s, n: None)
    so.stub("clock", lambda s, n: s.reg_write(X0, 1000000))
    stub = so.stub_address("noop")

    iface = so.alloc(0x80)
    for off in range(0, 0x80, 8):
        so.write(iface + off, struct.pack("<Q", stub))
    flags = so.alloc(8)
    state = so.alloc(0x1000)
    lines = so.alloc(0x200000)                          # init's 4th argument: >= 1 MB
    temp = so.alloc(0x40000)
    scratch = so.alloc(0x40000)                         # sixth argument for the effects that need one
    params = so.alloc(0x100)
    buf = so.alloc(64 * 2 * 4)                          # Chorus works in place on its input
    out = so.alloc(64 * 2 * 4)
    so.write_u32_array(params, [0x40404040] * 18)

    if init_module:
        so.call(syms[init_module], [0, iface, flags])
    if init:
        so.call(syms[init], [state, 0, 0, lines, temp])

    changed_in = nonzero_out = 0
    for block in range(blocks):
        for i in range(128):
            value = int(0.5 * math.sin(2 * math.pi * 440 * (block * 64 + i / 2) / 48000) * 0x7FFFFFFF)
            so.write_u32(buf + 4 * i, value & 0xFFFFFFFF)
            so.write_u32(out + 4 * i, 0)
        so.call(syms[render], [params, 64, state, buf, out, scratch])
        nonzero_out += sum(1 for i in range(128) if struct.unpack("<i", so.read(out + 4 * i, 4))[0])
        changed_in += sum(1 for i in range(128)
                          if struct.unpack("<i", so.read(buf + 4 * i, 4))[0]
                          != int(0.5 * math.sin(2 * math.pi * 440 * (block * 64 + i / 2) / 48000) * 0x7FFFFFFF))
    total = blocks * 128
    return (changed_in, nonzero_out, total), None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=200)
    a = ap.parse_args(argv)
    if not CLONE_HARNESS.is_dir() or not SYMS.exists():
        raise SystemExit(f"needs the vendor library ({SYMS}) and the loader ({CLONE_HARNESS})")
    sys.path.insert(0, str(CLONE_HARNESS))
    from opzso import OpzSo
    from unicorn import UC_PROT_ALL
    from unicorn.arm64_const import UC_ARM64_REG_X0

    syms = symbols()
    working = []
    for cls in EFFECTS:
        meas, err = run_one(cls, syms, a.blocks, OpzSo, UC_PROT_ALL, UC_ARM64_REG_X0)
        if err:
            print(f"  {cls:10s} {err}")
            continue
        changed_in, nonzero_out, total = meas
        works = nonzero_out or changed_in
        print(f"  {cls:10s} {'PROCESSES' if works else 'silent   '}  "
              f"out {nonzero_out:5d}/{total} nonzero, input changed {changed_in:5d}/{total}")
        if works:
            working.append(cls)
    print(f"\n  {len(working)} of {len(EFFECTS)} factory effects process audio: {', '.join(working) or 'none'}")
    missing = [c for c in EFFECTS if c not in working]
    if missing:
        print("  not processing: " + ", ".join(missing))
        if "TapeTwo" in missing:
            # Measured, not assumed (see firmware-re-docs/13-factory-engine-status.md and
            # HYPOTHESES.csv): renderFX stores 128 zero samples into tapeBuffer_z_l/z_r, the very
            # buffers its mix loop then reads, so its output is zero for every host input.
            print("  TapeTwo is silent by construction: its renderFX zeroes the buffers it then")
            print("  reads, and FxManager::render only forwards to it. 7 of 8 is this library's ceiling.")
    return 0 if len(working) == len(EFFECTS) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
