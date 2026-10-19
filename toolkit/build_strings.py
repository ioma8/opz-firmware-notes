#!/usr/bin/env python3
"""build_strings.py - an ambient string-ensemble engine, written with toolkit/opzsdk.py.

Four harmonics with a 1/h tilt, in two banks detuned by a few cents, with bank A on the left channel and
bank B on the right. The detuning is what makes it sound like an ensemble rather than a synth: the two
banks beat against each other, and because they are also panned apart the beat is what makes the note move
across the stereo field. Vibrato is deliberately absent - the beating stands in for it and costs nothing.

Everything else is the verified voice contract the other authored engines use: pitch from render's
argument 2 (Q16 Hz), the strike seeded when the amp object's state word goes from idle to active, and
loudness from the OS envelope (`ctx+0x118`) times the amp object's voice gain (`amp+0x04`, zero meaning
unity). The engine sustains as long as the gate is open, so the note's shape is the OS envelope's and the
OP-Z's reverb on the track is the space around it.

Not implemented: `params[]` (the eighteen preset words; on this ABI `params[2..5]` are amp arguments, and
guessing which of the rest is a level would risk silencing the engine) and any engine-side release - the
OS amp envelope already does that. Nothing here has been auditioned on hardware.
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzsdk as S
import opzmarimba as M

FS = M.FS
HARMONICS = 4
BANKS = 2
OSCILLATORS = HARMONICS * BANKS
DETUNE_CENTS = 6.0            # +-6 cents between the banks: audible beating, no obvious chorus
LEVEL = 0.13                  # per-oscillator seed, so four harmonics sum well clear of clipping

# ------------------------------------------------------------------------------- tables

def detune(bank):
    return 2.0 ** ((1 if bank else -1) * DETUNE_CENTS / 1200.0)


def coefficients():
    """(c, s) per note per oscillator: oscillator = bank * HARMONICS + harmonic, radius 1.0."""
    rows = []
    for note in range(128):
        f0 = 440.0 * 2 ** ((note - 69) / 12.0)
        for bank in range(BANKS):
            for h in range(1, HARMONICS + 1):
                f = f0 * h * detune(bank)
                if f > FS * 0.45:
                    rows += [0, 0]
                    continue
                w = 2.0 * math.pi * f / FS
                rows += [S.q31(math.cos(w)), S.q31(math.sin(w))]
    return rows


def seeds():
    """1/h tilt per harmonic, the same level in both banks."""
    out = []
    for bank in range(BANKS):
        for h in range(1, HARMONICS + 1):
            out.append(LEVEL / h)
    return out


e = S.Engine("strings", slot=71)
SEEDS = e.words("SEEDS", [S.q31(x) for x in seeds()])
COEF = e.words("COEF", coefficients(), stride=OSCILLATORS * 8)
FREQ = e.words("FREQ", [S.hz_q16(n) for n in range(128)])

# ------------------------------------------------------------------------------- exports

@e.fn("initModule", ["idv", "host", "out"])
def initModule(idv, host, out):
    with S.if_(S.nz(idv)):
        S.ret(0)
    S.ptr(out)[0].set(0)
    S.ret(1)


@e.fn("init", ["ctx", "variant"])
def init(ctx, variant):
    c = S.pin(S.ptr(ctx))
    with S.repeat(16):
        c.put(0)
    with S.repeat(40):                    # the oscillator states, past the words render keeps
        c.put(0)
    S.unpin(c)


@e.fn("onNoteOn", ["a1", "note", "ctx", "a4"])
def onNoteOn(a1, note, ctx, a4):
    v = S.ptr(ctx)
    v[0x00].set(0)
    v[0x04].set(note)


@e.fn("onNoteOff", ["a1", "ctx"])
def onNoteOff(a1, ctx):
    # the context register here is not documented; range-check it so a wrong guess writes nothing
    with S.if_(ctx < 0x10000000):
        S.ret()
    c = S.pin(S.ptr(ctx))
    c.put(1)
    with S.repeat(55):                    # every state word this engine uses
        c.put(0)
    S.unpin(c)


@e.fn("render", ["out", "pitch", "bend", "ctx", "params", "amp"])
def render(out, pitch, bend, ctx, params, amp):
    o = S.pin(S.ptr(out))
    c = S.pin(S.ptr(ctx))
    k = S.pin(S.ptr(ctx).at(0x60))         # this block's coefficients
    acc = S.var("acc", hot=True)
    vel = S.var("vel")
    gain = S.var("gain")
    row = S.var("row")
    y1 = S.var("y1")
    y2 = S.var("y2")
    left = S.var("left")

    # ---- amp object: gate, then the per-voice gain (zero means unity, not silence)
    vel.set(0x7FFFFFFF)
    with S.if_(S.nz(amp)):
        with S.if_(S.zero(S.ptr(amp)[0x10])):
            c[0x00].set(0)
            S.ret()
        vel.set(S.ptr(amp)[0x04])
        with S.if_(S.zero(vel)):
            vel.set(0x7FFFFFFF)

    # ---- no pitch means no note: tested before anything derives from it, and unsigned so a negative
    # argument (which the search would read as enormous and clamp to the top row) is rejected too
    with S.if_(S.zero(pitch)):
        c[0x00].set(0)
        S.ret()
    with S.if_(pitch < 0x40000000):
        pass
    with S.else_():
        c[0x00].set(0)
        S.ret()

    # ---- strike: all ten oscillators start at their harmonic's level, at rest
    with S.if_(S.zero(c[0x00])):
        c[0x00].set(1)
        for i in range(OSCILLATORS):
            c[0x10 + 8 * i].set(SEEDS[i])
            c[0x14 + 8 * i].set(0)

    # ---- the block's coefficients, then the output gain
    row.set(S.find_row(pitch, FREQ))
    for i in range(OSCILLATORS):
        k[8 * i].set(COEF.row(row)[8 * i])
        k[8 * i + 4].set(COEF.row(row)[8 * i + 4])
    gain.set(S.qmul(c[0x118], vel))

    # ---- 64 frames. Both new states come from the OLD pair; a bank's sum is its channel.
    with S.repeat(64):
        left.set(0)
        acc.set(0)
        for i in range(OSCILLATORS):
            y1.set(c[0x10 + 8 * i])
            y2.set(c[0x14 + 8 * i])
            c[0x10 + 8 * i].set(S.qmul(k[8 * i], y1) - S.qmul(k[8 * i + 4], y2))
            c[0x14 + 8 * i].set(S.qmul(k[8 * i + 4], y1) + S.qmul(k[8 * i], y2))
            if i < HARMONICS:
                left.set(left + c[0x10 + 8 * i])
            else:
                acc.set(acc + c[0x10 + 8 * i])
        left.set(S.qmul(left, gain))
        acc.set(S.qmul(acc, gain))
        o.put(left)                        # bank A -> left
        o.put(acc)                         # bank B -> right


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "strings.engine")
    e.write(out)
