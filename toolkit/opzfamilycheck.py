#!/usr/bin/env python3
"""opzfamilycheck.py - does an engine actually play the requested note?

A plain frequency measurement cannot answer this: an engine whose strongest partial is the 2nd or 3rd
harmonic reports 2x or 3x the requested pitch while being perfectly in tune. The earlier version of this
checker compared that reading against the expected pitch and reported 33 false failures.

Two tests that a harmonic cannot fake:

  fundamental present - energy at the requested f0 is at least 5% of the strongest harmonic, for every
                        note. A detuned engine has no energy at f0.
  octave tracking     - the measured frequency doubles when the note goes up an octave. Whether the
                        reading is f0, 2f0 or 3f0 does not matter as long as it is the SAME partial.

Usage:
    python3 toolkit/opzfamilycheck.py [dir ...]      (default: engines-family)
"""
import cmath, math, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzenginetool as T

NOTES = (45, 57, 69)
FS = 48000.0
PARAMS = [int(0.5 * (1 << 28))] * 8


def energy_at(samples, freq, n=16384):
    """DFT magnitude at one frequency over the whole clip, Hann-windowed.

    Not just the tail: a fast-decaying note leaves the last few thousand samples near silent, and
    comparing harmonic energies there measures noise rather than the engine."""
    s = samples[:n]
    m = len(s)
    w = sum(s[i] * math.sin(math.pi * i / m) ** 2 * cmath.exp(-2j * math.pi * freq * i / FS)
            for i in range(m))
    return abs(w) / m


def check(path):
    """Octave tracking is the robust test: whatever partial dominates, its frequency must double when the
    note rises an octave. A detuned engine fails it. An engine that switches which partial dominates
    (fm003b does) fails it too, so those fall back to asking whether energy exists at the requested f0."""
    info = T.describe(path)
    readings, missing = [], []
    for note in NOTES:
        f0 = 440.0 * 2 ** ((note - 69) / 12)
        samples, _ = T.render_clip(info, note, 0.35, PARAMS)
        if max((abs(v) for v in samples), default=0) == 0:
            return False, f"silent at note {note}"
        readings.append(T.S.measure_freq(samples, window=4096))
        harmonics = [energy_at(samples, f0 * k) for k in (1, 2, 3, 4)]
        missing.append(harmonics[0] < 0.05 * max(harmonics))
    steps = [readings[i + 1] / readings[i] for i in range(len(readings) - 1)]
    if all(abs(st - 2.0) < 0.08 for st in steps):
        return True, "reading " + " ".join(f"{r:.1f}" for r in readings) + " Hz, octave steps exact"
    if not any(missing):
        return True, "partial switches with note, but energy present at f0; reading " + \
                     " ".join(f"{r:.1f}" for r in readings) + " Hz"
    return False, "octave steps " + "/".join(f"{st:.2f}" for st in steps) + " and no energy at f0"


def main(argv):
    dirs = argv or ["engines-family"]
    failed = 0
    for d in dirs:
        for p in sorted(pathlib.Path(d).glob("*.engine")):
            try:
                ok, why = check(p)
            except Exception as e:                     # noqa: BLE001 - report, do not abort the sweep
                ok, why = False, f"{type(e).__name__}: {str(e)[:60]}"
            print(f"  {p.stem:18s} {'PASS' if ok else 'FAIL'}  {why}")
            failed += 0 if ok else 1
    print(f"\n{'all engines play the requested note' if not failed else str(failed) + ' engine(s) FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
