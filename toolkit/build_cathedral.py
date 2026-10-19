#!/usr/bin/env python3
"""build_cathedral.py - the cathedral organ, declared with toolkit/opzsynth.py.

Six pipe ranks (16', 8', 4', 2 2/3', 2' and 1 1/3') as undamped partials, so a note holds for as long as
the voice lives. Pitch is blended between the two bracketing semitone rows rather than snapped to one, so
a glide is continuous; the generated engine rescales the blended pair back onto the unit circle, because
two blended unit vectors are shorter than one and the note would fade between rows. Loudness is the OS
envelope times the amp object's per-voice gain, which is what gives the ranks velocity.

The space is the OP-Z's own reverb on the track: this engine is a dry source.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzsynth as K

RANKS = ((0.5, None), (1.0, None), (2.0, None), (3.0, None), (4.0, None), (6.0, None))
LEVELS = (0.085, 0.145, 0.105, 0.070, 0.050, 0.035)     # the 16' and 8' ranks carry the body


def build():
    return K.build(
        "cathedral", slot=74,
        partials=RANKS,
        levels=LEVELS,
        gain="envelope*velocity",
        pitch="blend",
    )


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "cathedral.engine")
    build().write(out)
