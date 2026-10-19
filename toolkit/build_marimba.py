#!/usr/bin/env python3
"""build_marimba.py - the marimba engine, written with toolkit/opzsdk.py (no assembly).

A struck wooden bar: six damped partials at the bar's inharmonic ratios, excited by a strike comb and
left to ring. Every choice below is the one the measurements in doc 11 justify; the DSP is unchanged
from the hand-written engine, only the way it is expressed is.

Voice contract (doc 11 section 11.9): the OS note-start path calls init then render, never onNoteOn, so
a voice comes alive from render's own arguments - pitch is argument 2 in Q16 Hz, and the amp object's
state word (argument 6, +0x10) says whether the OS still wants this voice. N voice records therefore
sound N notes. onNoteOn exists because the loader requires it and only asks for a re-strike.

Context layout, shared with the other authored engines:

    +0x00 struck flag      +0x04 note (bookkeeping)
    +0x08 reserved         +0x0c reserved
    +0x10 .. +0x3f  six (y1, y2) oscillator states
    +0x40 .. +0x6f  six (c, s) coefficients copied from the table for this block
    +0x70           the block's combined gain

Known limits, stated rather than hidden: `params[1]` is the decay knob and its unit is not settled by
any source, so both conventions are accepted (a word below 256 is a byte knob, otherwise Q31 with the
index masked to 7); the strike position and brightness are baked into the seed table because
`params[2..5]` are amp arguments on this ABI; pitch comes from render's argument 2 and the row is the
nearest semitone, so `bend` (argument 3) is ignored and a glide quantises to at most 50 cents. There is
no level control beyond the OS envelope and amp gain, and nothing here has been auditioned on hardware.
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzsdk as S
import opzmarimba as M

FS = M.FS
MODES = 6
T60_LONG = 8.0
PARAM_DECAY = 1
STRIKE_POS = 0.30
BRIGHTNESS = 0.5
RATIOS = M.MARIMBA
T60 = M.MARIMBA_T60

# ------------------------------------------------------------------------------- tables

def strike_seeds():
    """Per-mode excitation: 0.5 * (0.42**m)**(1-b) / (1+0.3m) * cos(pi(m+1)*position).

    This is what decides whether the engine sounds like wood or like a sine. A steeper tilt than this
    leaves the tuned 4x partial ~20 dB down instead of the 15 dB the reference model puts it at, and
    the engine becomes a sine with a click on top.
    """
    out = []
    for m in range(MODES):
        gain = (0.42 ** m) ** (1.0 - BRIGHTNESS) / (1.0 + 0.3 * m)
        out.append(0.5 * gain * math.cos(math.pi * (m + 1) * STRIKE_POS))
    return out


def coefficients():
    """(c, s) per note per mode, straight from opzmarimba's maths, flattened row-major."""
    rows = []
    for note in range(128):
        f0 = 440.0 * 2 ** ((note - 69) / 12.0)
        for m in range(MODES):
            f = f0 * RATIOS[m]
            if f > FS * 0.45:
                rows += [0, 0]                       # above Nyquist: this partial is muted
                continue
            w = 2.0 * math.pi * f / FS
            t60 = T60[m]
            r = 1.0 if t60 == 0.0 else math.exp(-math.log(1000.0) / (t60 * FS))
            rows += [S.q31(r * math.cos(w)), S.q31(r * math.sin(w))]
    return rows


def gain_buckets():
    """Per-block decay factors: eight target T60s, longest last so the top bucket barely damps."""
    out = []
    for t60 in (0.1, 0.2, 0.4, 0.8, 1.6, 3.0, 5.0, T60_LONG):
        g = 10 ** (-3.0 * M.BLOCK / (t60 * FS))
        out.append(int(round(g * 2 ** 31)))
    return out


e = S.Engine("marimba", slot=63)
STRIKE = e.words("STRIKE", [S.q31(x) for x in strike_seeds()])
COEF = e.words("COEF", coefficients(), stride=MODES * 8)
GAINS = e.words("GAINS", gain_buckets())
FREQ = e.words("FREQ", [S.hz_q16(n) for n in range(128)])

# ------------------------------------------------------------------------------- exports

@e.fn("initModule", ["idv", "host", "out"])
def initModule(idv, host, out):
    with S.if_(S.nz(idv)):
        S.ret(0)                                     # the OS passes 0; refuse anything else
    S.ptr(out)[0].set(0)
    S.ret(1)


@e.fn("init", ["ctx", "variant"])
def init(ctx, variant):
    c = S.pin(S.ptr(ctx))
    with S.repeat(16):                               # gate, note, reserved words, six states
        c.put(0)
    S.unpin(c)


@e.fn("onNoteOn", ["a1", "note", "ctx", "a4"])
def onNoteOn(a1, note, ctx, a4):
    v = S.ptr(ctx)
    v[0x00].set(0)                                   # ask render to re-strike
    v[0x04].set(note)


@e.fn("onNoteOff", ["a1", "ctx"])
def onNoteOff(a1, ctx):
    # Which register carries ctx here is NOT established: doc 11 documents the state map and the
    # note-on path and says nothing about this export, so the pointer is range-checked first. A wrong
    # guess then writes nothing instead of 64 bytes at whatever integer arrived, and a no-op is
    # harmless because render's amp gate still ends the voice.
    with S.if_(ctx < 0x10000000):                     # unsigned: every real pointer is above this
        S.ret()
    c = S.pin(S.ptr(ctx))
    c.put(1)                                         # +0x00 = 1: struck, so render will not restart
    with S.repeat(15):                               # +0x04 .. +0x3f: silence the voice
        c.put(0)
    S.unpin(c)


@e.fn("render", ["out", "pitch", "bend", "ctx", "params", "amp"])
def render(out, pitch, bend, ctx, params, amp):
    o = S.pin(S.ptr(out))                            # 64 interleaved stereo frames
    c = S.pin(S.ptr(ctx))
    k = S.pin(S.ptr(ctx).at(0x40))                   # the block's coefficients, at static offsets
    gain = S.var("gain")
    acc = S.var("acc", hot=True)
    y1 = S.var("y1")
    y2 = S.var("y2")
    cc = S.var("cc")
    ss = S.var("ss")
    row = S.var("row")

    # ---- the amp object (argument 6). Every factory instrument tests amp+0x10 first and returns when it
    # is zero: the OS owns the voice, so a released one must cost nothing and write nothing. A null
    # pointer still renders, so a caller that passes only the three register words behaves as before.
    with S.if_(S.nz(amp)):
        with S.if_(S.zero(S.ptr(amp)[0x10])):
            c[0x00].set(0)                           # idle: the next active tick re-strikes
            S.ret()

    # ---- a pitch outside the table is not a note: row 0 is 8 Hz, which would be a sub-audio thump at
    # full amplitude. The test runs before anything derives from the pitch. Unsigned, so a negative
    # pitch - which the search would read as an enormous positive and clamp to the top row - is caught.
    with S.if_(S.zero(pitch)):
        c[0x00].set(0)
        S.ret()
    with S.if_(pitch < 0x40000000):                   # 16384 Hz in Q16, above the top row's 12544
        pass
    with S.else_():
        c[0x00].set(0)
        S.ret()

    # ---- strike: seed the six modes from the table, at rest
    with S.if_(S.zero(c[0x00])):
        c[0x00].set(1)
        for m in range(MODES):
            c[0x10 + 8 * m].set(STRIKE[m])
            c[0x14 + 8 * m].set(0)

    # ---- the row for this note, then its twelve coefficients, copied into the voice's own scratch so
    # the frame loop addresses them with static offsets and never rewinds a pointer.
    row.set(S.find_row(pitch, FREQ))
    for m in range(MODES):
        k[8 * m].set(COEF.row(row)[8 * m])
        k[8 * m + 4].set(COEF.row(row)[8 * m + 4])

    # ---- the decay macro: params[PARAM_DECAY] picks one of eight per-block factors. A word below 256 is
    # a byte knob (the presets store 0..255), anything else is Q31 and masked to three bits so a negative
    # word cannot index past the table; a null pointer applies no extra damping.
    gain.set(0x7FFFFFFF)
    with S.if_(S.nz(params)):
        with S.if_(S.ptr(params)[4 * PARAM_DECAY] < 256):
            row.set(S.ptr(params)[4 * PARAM_DECAY] >> 5)
        with S.else_():
            row.set((S.ptr(params)[4 * PARAM_DECAY] >> 28) & 7)
        gain.set(GAINS[row])

    # ---- 64 frames: each mode is a norm-preserving rotation, so only the block gain damps the voice.
    # Both new states are computed from the OLD pair: storing y1 first and then reading it back for y2
    # turns the rotation into something that grows, which is how this engine first came out at twice the
    # intended level.
    with S.repeat(64):
        acc.set(0)
        for m in range(MODES):
            y1.set(c[0x10 + 8 * m])
            y2.set(c[0x14 + 8 * m])
            cc.set(k[8 * m])
            ss.set(k[8 * m + 4])
            c[0x10 + 8 * m].set(S.qmul(cc, y1) - S.qmul(ss, y2))
            c[0x14 + 8 * m].set(S.qmul(ss, y1) + S.qmul(cc, y2))
            acc.set(acc + c[0x10 + 8 * m])
        y1.set(S.qmul(acc, gain))
        o.put(y1)
        o.put(y1)

    # ---- the decay factor belongs to a BLOCK, not a sample: applying it inside the 64-frame loop made it
    # act 64 times per block (0.99885^64 = 0.929, a 7% collapse - measured, doc 11 section 11.14).
    for w in range(2 * MODES):
        c[0x10 + 4 * w].set(S.qmul(c[0x10 + 4 * w], gain))


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "marimba.engine")
    e.write(out)
