#!/usr/bin/env python3
"""build_marimba.py - the marimba, declared with toolkit/opzsynth.py.

A struck wooden bar is a bank of damped inharmonic partials. The three numbers that decide whether it
sounds like wood are the mode ratios (the free-free bar's 1, 3.93, 9.24, 16, 24, 34 rather than the
harmonic series), the strike comb (where the mallet lands, which kills mode 4 outright at the 0.30
position) and the tilt that keeps the tuned 4x partial about 16 dB under the fundamental, where the ear
reads "wood" rather than "sine with a click". Everything else - the gate, the strike, the pitch row, the
frame loop - is generated.

The decay knob rides params[1], whose unit no source settles, so the generated engine accepts both
conventions (see opzsynth.knob and its docstring).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzmarimba as M
import opzsynth as K

T60_LONG = 8.0
STRIKE_POS = 0.30
BRIGHTNESS = 0.5


def tail_tilt(m):
    """The reference model's excitation tilt: sqrt(0.42)**m over the model's 1/(1+0.3m) roll-off."""
    return (0.42 ** m) ** (1.0 - BRIGHTNESS) / (1.0 + 0.3 * m)


def build():
    partials = [(ratio, t60) for ratio, t60 in zip(M.MARIMBA, M.MARIMBA_T60)]
    levels = [0.5 * level for level in K.strike_comb(STRIKE_POS, len(partials), tilt=tail_tilt)]
    return K.build(
        "marimba", slot=63,
        partials=partials,
        levels=levels,
        damping=K.knob(1, (0.1, 0.2, 0.4, 0.8, 1.6, 3.0, 5.0, T60_LONG)),
        gain="gate",                     # the wood's own decay is the damping knob, not the OS envelope
        pitch="row",
    )


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "marimba.engine")
    build().write(out)
