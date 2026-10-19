#!/usr/bin/env python3
"""build_strings.py - an ambient string ensemble, declared with toolkit/opzsynth.py.

Four harmonics with a 1/h tilt, in two banks detuned by six cents and panned apart: the two banks beat
against each other and the beat moves across the stereo field, which is what makes it sound like an
ensemble rather than one stopped oscillator. The partials are undamped, so a note holds while the OS
envelope is open; the envelope times the amp gain is the loudness, and the OP-Z's reverb on the track is
the space.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzsynth as K

HARMONICS = 4
DETUNE_CENTS = 6.0
LEVEL_PER_HARMONIC = 0.13


def build():
    return K.build(
        "strings", slot=71,
        partials=[(float(h), None) for h in range(1, HARMONICS + 1)],
        levels=[LEVEL_PER_HARMONIC / h for h in range(1, HARMONICS + 1)],
        banks=2,
        detune_cents=DETUNE_CENTS,
        split=True,                       # bank 0 left, bank 1 right
        gain="envelope*velocity",
        pitch="row",
    )


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "strings.engine")
    build().write(out)
