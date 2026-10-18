#!/usr/bin/env python3
"""build_family.py - emit a family of instrument engines from build_struck.py's verified builder.

This is the route to "every engine audible and correctly pitched in the app" that does not depend on
the factory binaries: the same verified code, with different modal ratios, damping and strike position
per instrument. These are OUR engines. They are not the OP-Z factory engines and must never be
presented as such - the factory ones still need state the sequencer computes (see
firmware-re-docs/12-installing-a-new-engine.md).

The builder reads `opzstruck.MARIMBA`, `opzstruck.MARIMBA_T60` and `build_struck.STRIKE_POS` when it
runs, so a family is a driver rather than a rewrite.

Usage:
    python3 toolkit/build_family.py [outdir]
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_struck as B                              # noqa: E402
import opzstruck as S                                 # noqa: E402

# name -> (mode ratios, per-mode T60 seconds, strike position)
PRESETS = {
    "bar":   ((1.0, 3.93, 9.24, 16.0, 24.0, 34.0), (0.0, 0.45, 0.25, 0.15, 0.10, 0.07), 0.22),
    "bell":  ((1.0, 2.0, 2.9, 4.1, 5.4, 6.8),      (0.0, 2.20, 1.70, 1.20, 0.90, 0.60), 0.50),
    "pluck": ((1.0, 2.0, 3.0, 4.0, 5.0, 6.0),      (0.0, 0.30, 0.20, 0.14, 0.10, 0.07), 0.12),
    "glass": ((1.0, 2.76, 5.40, 8.93, 13.3, 18.6), (0.0, 1.60, 1.10, 0.80, 0.55, 0.40), 0.35),
    "organ": ((1.0, 2.0, 3.0, 4.0, 5.0, 6.0),      (0.0, 6.00, 4.00, 3.00, 2.20, 1.60), 0.50),
}


# One preset per factory *instrument* slot, so the app has a working engine wherever a factory one is
# named. These are our modal-synth voices, not the factory binaries: the ratios/damping/strike below
# give each name a deliberately different character (harmonic vs inharmonic, long vs plucked).
FACTORY_SLOTS = {
    "analoga":   ((1.0, 2.0, 3.0, 4.0, 5.0, 6.0),      (0.0, 3.00, 2.00, 1.50, 1.10, 0.80), 0.50),
    "chord":     ((1.0, 1.5, 2.0, 2.5, 3.0, 4.0),      (0.0, 4.00, 3.00, 2.20, 1.60, 1.20), 0.45),
    "cluster":   ((1.0, 1.06, 2.0, 2.12, 3.0, 3.18),    (0.0, 3.50, 2.60, 1.90, 1.40, 1.00), 0.50),
    "digital":   ((1.0, 2.0, 4.0, 8.0, 16.0, 22.0),     (0.0, 2.00, 1.20, 0.70, 0.40, 0.25), 0.50),
    "electric":  ((1.0, 2.0, 3.0, 4.0, 6.0, 8.0),       (0.0, 3.20, 2.40, 1.80, 1.20, 0.90), 0.30),
    "ep":        ((1.0, 2.0, 3.0, 5.0, 7.0, 9.0),       (0.0, 2.60, 1.90, 1.20, 0.80, 0.55), 0.25),
    "fm003b":    ((1.0, 3.0, 5.0, 7.0, 11.0, 13.0),     (0.0, 1.80, 1.20, 0.85, 0.55, 0.35), 0.40),
    "ministringshort": ((1.0, 2.0, 3.0, 4.0, 5.0, 7.0), (0.0, 1.40, 1.00, 0.75, 0.55, 0.40), 0.18),
    "organ":     ((1.0, 2.0, 4.0, 8.0, 3.0, 6.0),       (0.0, 8.00, 6.00, 5.00, 4.00, 3.50), 0.50),
    "sampleplayergain": ((1.0, 2.0, 3.0, 4.0, 5.0, 6.0), (0.0, 1.00, 0.70, 0.50, 0.35, 0.25), 0.10),
    "saw013a":   ((1.0, 2.0, 3.0, 4.0, 5.0, 7.0),       (0.0, 5.00, 4.00, 3.00, 2.20, 1.60), 0.50),
    "synthsampler": ((1.0, 2.0, 3.0, 4.0, 5.0, 7.0),    (0.0, 1.20, 0.85, 0.60, 0.45, 0.30), 0.15),
    "volt":      ((1.0, 2.0, 3.0, 4.0, 5.0, 6.0),       (0.0, 4.50, 3.40, 2.60, 1.90, 1.40), 0.50),
}
PRESETS.update(FACTORY_SLOTS)


def build_one(ratios, t60s, strike):
    S.MARIMBA, S.MARIMBA_T60, B.STRIKE_POS = ratios, t60s, strike
    return B.build()[0]


def main(argv):
    outdir = pathlib.Path(argv[1] if len(argv) > 1 else "engines-family")
    outdir.mkdir(parents=True, exist_ok=True)
    for name, (ratios, t60s, strike) in PRESETS.items():
        raw = build_one(ratios, t60s, strike)
        p = outdir / f"{name}.engine"
        p.write_bytes(raw)
        print(f"  wrote {p} ({len(raw)} B)")


if __name__ == "__main__":
    main(sys.argv)
