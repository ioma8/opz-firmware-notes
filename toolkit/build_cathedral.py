#!/usr/bin/env python3
"""build_cathedral.py - the cathedral-organ engine, written with toolkit/opzsdk.py (no assembly).

Six phase-coherent pipe ranks (16', 8', 4', 2 2/3', 2' and 1 1/3') per voice, plus the OP-Z's own reverb
on the track for the tail. This engine is a dry, sustained organ source.

Everything a voice needs comes from render's own arguments, because the OS note-start path calls init and
render and never onNoteOn: pitch is argument 2 in Q16 Hz, argument 3 is the glide delta
`(target - current) >> 6` and lands half of itself on the block's midpoint, and the note is struck when
the amp object's state word (argument 6, +0x10) goes from idle to active. Loudness is the OS envelope
(`ctx+0x118`, the voice record's +0x160) times the amp object's voice gain (`amp+0x04`, the field chord
loads at 0x81be278c); a zero there means unity, so a wrong guess about that field costs a dead velocity
knob instead of a silent engine.

Pitch is *interpolated* between the two bracketing semitone rows rather than snapped to the nearer one, so
a glide is continuous. Two things go wrong naively and are handled here:

  * interpolating between two unit vectors shortens the radius to cos(dw/2), and these oscillators have no
    damping of their own, so a note held between rows would fade instead of sustaining. The pair is
    rescaled by 1 + eps + 1.5 eps^2 with eps = 0.5 - r^2/2, skipped where the pair is not a rotation at
    all (a rank past Nyquist has a zero row whose length *is* its level).
  * a zero or negative pitch must be rejected *before* the bend is added, and the search must be able to
    select the last row, or note 127 renders a semitone low.

Not implemented, deliberately: `params[]` is unread (guessing which of the eighteen words is the drawbar
risks silencing the engine, and `params[2..5]` are amp arguments on this ABI), the output is mono, and
there is no engine-generated reverb. Nothing here has been auditioned on hardware.
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzsdk as S
import opzmarimba as M

FS = M.FS
RANKS = 6
RATIOS = (0.5, 1.0, 2.0, 3.0, 4.0, 6.0)
LEVELS = (0.085, 0.145, 0.105, 0.070, 0.050, 0.035)   # drawbar-like: 16' and 8' carry the body

# ------------------------------------------------------------------------------- tables

def coefficients():
    """(c, s) per note per rank, radius 1.0: the voice sustains until the amp gate closes."""
    rows = []
    for note in range(128):
        f0 = 440.0 * 2 ** ((note - 69) / 12.0)
        for ratio in RATIOS:
            f = f0 * ratio
            if f > FS * 0.45:
                rows += [0, 0]                            # above Nyquist: rank muted
                continue
            w = 2.0 * math.pi * f / FS
            rows += [S.q31(math.cos(w)), S.q31(math.sin(w))]
    return rows


e = S.Engine("cathedral", slot=74)
STRIKE = e.words("STRIKE", [S.q31(x) for x in LEVELS])
COEF = e.words("COEF", coefficients(), stride=RANKS * 8)
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
    S.unpin(c)


@e.fn("onNoteOn", ["a1", "note", "ctx", "a4"])
def onNoteOn(a1, note, ctx, a4):
    v = S.ptr(ctx)
    v[0x00].set(0)
    v[0x04].set(note)


@e.fn("onNoteOff", ["a1", "ctx"])
def onNoteOff(a1, ctx):
    # doc 11 documents the state map and the note-on path, not this export's arguments, so the context
    # candidate is range-checked first: a wrong register then writes nothing instead of 64 bytes.
    with S.if_(ctx < 0x10000000):
        S.ret()
    c = S.pin(S.ptr(ctx))
    c.put(1)
    with S.repeat(15):
        c.put(0)
    S.unpin(c)


@e.fn("render", ["out", "pitch", "bend", "ctx", "params", "amp"])
def render(out, pitch, bend, ctx, params, amp):
    o = S.pin(S.ptr(out))
    c = S.pin(S.ptr(ctx))
    k = S.pin(S.ptr(ctx).at(0x40))                    # this block's interpolated (c, s)
    acc = S.var("acc", hot=True)
    vel = S.var("vel")
    gain = S.var("gain")
    row = S.var("row")
    hirow = S.var("hirow")
    frac = S.var("frac")
    lo_c = S.var("lo_c")
    lo_s = S.var("lo_s")
    hi_c = S.var("hi_c")
    hi_s = S.var("hi_s")
    tmp = S.var("tmp")
    eps = S.var("eps")
    epss = S.var("epss")
    y1 = S.var("y1")
    y2 = S.var("y2")

    # ---- the amp object: gate first, then the voice gain. A null pointer means "render anyway".
    vel.set(0x7FFFFFFF)
    with S.if_(S.nz(amp)):
        with S.if_(S.zero(S.ptr(amp)[0x10])):
            c[0x00].set(0)
            S.ret()
        vel.set(S.ptr(amp)[0x04])
        with S.if_(S.zero(vel)):
            vel.set(0x7FFFFFFF)                       # unfilled field: unity, not silence

    # ---- a zero pitch is "not set yet", and it is tested BEFORE the bend is added: after it, the bend
    # alone defeated this guard and produced an 8 Hz thump at full amplitude. Anything past the table -
    # including a negative value, which an unsigned compare reads as enormous - is no pitch at all.
    with S.if_(S.zero(pitch)):
        c[0x00].set(0)
        S.ret()
    pitch = pitch + (bend << 5)                       # half the glide delta: the block midpoint
    with S.if_(pitch < 0x40000000):                   # 16384 Hz in Q16, above the top row's 12544
        pass
    with S.else_():
        c[0x00].set(0)
        S.ret()

    # ---- strike: the six ranks start phase-coherent at their own levels
    with S.if_(S.zero(c[0x00])):
        c[0x00].set(1)
        for m in range(RANKS):
            c[0x10 + 8 * m].set(STRIKE[m])
            c[0x14 + 8 * m].set(0)

    # ---- bracketing rows and the Q16 fraction between them
    row.set(S.find_row(pitch, FREQ))
    hirow.set(row + 1)
    frac.set(0)
    with S.if_(row < 127):
        frac.set(S.udiv(pitch - FREQ[row], FREQ[row + 1] - FREQ[row]))
    with S.else_():
        hirow.set(127)                                # clamped at the top: no row above to blend to

    # ---- interpolate, then rescale to the unit circle so the voice keeps its level between rows
    for m in range(RANKS):
        lo_c.set(COEF.row(row)[8 * m])
        lo_s.set(COEF.row(row)[8 * m + 4])
        hi_c.set(COEF.row(hirow)[8 * m])
        hi_s.set(COEF.row(hirow)[8 * m + 4])
        lo_c.set(lo_c + S.qmul(hi_c - lo_c, frac << 15))   # Q16 fraction -> Q31
        lo_s.set(lo_s + S.qmul(hi_s - lo_s, frac << 15))
        # r^2/2 is about 0.5 for a unit pair. Below 0.25 the pair is not a rotation at all (a rank past
        # Nyquist has a zero row, and a zero pair's length *is* its level), so leave it alone there.
        tmp.set(S.mul32(lo_c, lo_c) + S.mul32(lo_s, lo_s))
        with S.if_(tmp >= 0x20000000):
            eps.set(0x40000000 - tmp)                      # eps = 0.5 - r^2/2
            epss.set(S.mul32(eps, eps))                    # eps^2 / 2
            tmp.set(eps + epss + epss + epss)              # eps + 1.5 eps^2
            lo_c.set(lo_c + S.qmul(lo_c, tmp))
            lo_s.set(lo_s + S.qmul(lo_s, tmp))
        k[8 * m].set(lo_c)
        k[8 * m + 4].set(lo_s)

    # ---- the block's output gain: the OS envelope (record+0x160 == ctx+0x118) times the voice gain
    gain.set(S.qmul(c[0x118], vel))

    # ---- 64 frames. Both new states come from the OLD pair; storing y1 first would make the rotation grow.
    with S.repeat(64):
        acc.set(0)
        for m in range(RANKS):
            y1.set(c[0x10 + 8 * m])
            y2.set(c[0x14 + 8 * m])
            c[0x10 + 8 * m].set(S.qmul(k[8 * m], y1) - S.qmul(k[8 * m + 4], y2))
            c[0x14 + 8 * m].set(S.qmul(k[8 * m + 4], y1) + S.qmul(k[8 * m], y2))
            acc.set(acc + c[0x10 + 8 * m])
        y1.set(S.qmul(acc, gain))
        o.put(y1)
        o.put(y1)


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "cathedral.engine")
    e.write(out)
