#!/usr/bin/env python3
"""opzfactoryaudible.py - does the factory module produce any audio at all?

`opzfactorycheck.py` asks the hard question (does it reach the requested note, 2 of 13 pass). This asks the
easy one: does the render write a single nonzero sample. The distinction matters because most of the
remaining engines execute their whole DSP body and write zeros, which is a different failure from not
running at all.

Some engines only reach their DSP once a prerequisite the OS would supply is in place. Each one below is
documented with its evidence in firmware-re-docs/13-factory-engine-status.md, and a forced register is
labelled in the output so an opened gate is never mistaken for a playing engine.

Usage:
    python3 toolkit/opzfactoryaudible.py
"""
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzenginetool as T

# ("poke", address, register, value) or ("fill", start, end, word)
PREREQ = {
    "cluster.engine": ("gate R3 -> 1 at 0x81c0064c", [(0x81C0064C, 3, 1)], []),
    "electric.engine": ("table 0x81c39e00-0x81c3a000 = 0x40000000", [], [(0x81C39E00, 0x81C3A000, 0x40000000)]),
    "organ.engine": ("gate R2 -> 1 at 0x81b7d1c4", [(0x81B7D1C4, 2, 1)], []),
}


def main():
    params = [0] * 8
    rows, audible = [], 0
    for path in sorted(T.find_engines()):
        p = pathlib.Path(path)
        if "engines-official" not in str(p):
            continue
        info = T.describe(p)
        if info["kind"] not in ("instrument", "effect"):
            continue
        why, pokes, fills = PREREQ.get(p.name, ("-", [], []))
        try:
            samples, meta = T.render_clip(info, 69, 0.02, params, pokes=pokes, fills=fills)
        except Exception as e:
            rows.append((p.name, info["kind"], "ERROR", f"{type(e).__name__}: {str(e)[:40]}", "-", why))
            continue
        nz = sum(1 for v in samples if v)
        # "writes any audio" needs a floor, or a single stray integer counts as playing. 1% of samples
        # nonzero and a peak of at least 1e-4 of full scale (-80 dB) reproduces the tally recorded in
        # firmware-re-docs/13-factory-engine-status.md; organ's transient is 27 samples at 1/2^31 and fails
        # both, which is the honest verdict for an engine that does not sustain a note.
        ok = nz * 100 >= len(samples) and meta["peak"] >= 1e-4
        audible += ok
        rows.append((p.name, info["kind"], "AUDIBLE" if ok else "silent",
                     f"{nz}/{len(samples)}", meta["peak"], why))
    for name, kind, verdict, nz, peak, why in rows:
        print(f"  {name:20s} {kind:10s} {verdict:8s} nz {nz:12s} peak {peak:<10} {why}")
    ins = [r for r in rows if r[1] == "instrument"]
    fx = [r for r in rows if r[1] == "effect"]
    print(f"\ninstruments: {sum(1 for r in ins if r[2] == 'AUDIBLE')} of {len(ins)} write any audio")
    print(f"effects:     {sum(1 for r in fx if r[2] == 'AUDIBLE')} of {len(fx)} write any audio")
    print("rows marked with a prerequisite are judged with that prerequisite in place; "
          "an effect is judged on its own output, not on its input")
    return 0


if __name__ == "__main__":
    sys.exit(main())
