#!/usr/bin/env python3
"""opzsynth.py - declare an engine, don't write one.

This is the layer above toolkit/opzsdk.py.  An engine is a *bank of damped partials* with a gain law, and
that is what you write:

    import opzsynth as K

    K.build("marimba", slot=63,
            partials=[(1.0, 0.0), (3.93, 0.45), (9.24, 0.25), (16.0, 0.15), (24.0, 0.10), (34.0, 0.07)],
            levels=[0.294, -0.077, -0.125, 0.058, 0.0, -0.018],
            damping=K.knob(1, (0.1, 0.2, 0.4, 0.8, 1.6, 3.0, 5.0, 8.0)),
            gain="gate",
           ).write("marimba.engine")

What that buys you: no offsets, no registers, no pointer walks, no frame loop, no instruction encodings,
no module header.  The generated engine is the same object every time - a per-voice bank of two-pole
rotators whose coefficients come from a build-time table - so the one piece of DSP that has to be right
is written once, here, and every engine inherits its verification.

The sound is described by five things:

  partials    [(ratio_to_f0, t60_seconds or None), ...].  A ratio of 1.0 is the fundamental, 2.0 the
              octave; None means undamped (radius exactly 1.0) so the note sustains until the voice ends.
              A partial whose frequency passes 0.45*fs is muted automatically - it would alias.
  levels      one Q31 seed per partial: how hard the strike hits each one. A callable is called with the
              partial index. These decide the timbre more than anything else; a strike comb
              (`cos(pi*(m+1)*position)`), a 1/h harmonic tilt and a per-mode decay law are all just
              different level lists.
  gain        what scales the output: "gate" (nothing - the amp object is only an on/off gate), "envelope"
              (the OS envelope at ctx+0x118), or "envelope*velocity" (also the amp object's per-voice gain
              at amp+0x04, where a zero means unity rather than silence).
  damping     None, or K.knob(index, t60s): the preset knob at params[index] selects one of N per-block
              decay factors, so a "decay" control changes the whole tail. Both knob conventions are
              accepted, because no source settles which one the OS uses: a word below 256 is a byte knob
              (the presets store 0..255) and anything else is Q31.
  pitch       "row" snaps to the nearest semitone row; "blend" interpolates between the two bracketing
              rows, which keeps a glide continuous and costs a little more code (and needs the radius
              correction below).
  banks       split the partials into N banks detuned by +-detune_cents and, with split=True, panned: bank
              0 to the left channel, bank 1 to the right. Two detuned banks beating against each other is
              what makes an ensemble sound like an ensemble rather than like one stopped oscillator.

What the voice does on its own, because every authored engine needs it and it is easy to get wrong:

  * it comes alive from render's arguments, never from onNoteOn: the OS note-start path calls init and
    render (doc 11 section 11.9), so pitch comes from argument 2 and the amp object's state word decides
    whether the voice should sound at all. N voice records therefore sound N notes.
  * a zero or out-of-range pitch is silence, not row 0 - and it is tested before the bend is added, or the
    bend alone defeats the guard.
  * the strike seeds both state words of every partial; the rotation itself supplies the decay, because a
    per-block gain applied to the *state* would decay geometrically.
  * `[FP - n]` frame slots, 64 frames per block, the module header and its five exports: all inherited.

Escape hatch: when the sound you want is not a bank of rotators (a filter, a sample player, FM), drop one
level down to toolkit/opzsdk.py and write the statements.  This module generates exactly the same DSL, so
the two compose: see its `voice()` for the shared prologue and `bank()` for the frame loop.
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzsdk as S
import opzmarimba as M

FS = M.FS
BLOCK = M.BLOCK
NYQUIST_GATE = 0.45          # a partial above this fraction of fs is muted instead of aliasing

__all__ = ("build", "knob", "Knob", "strike_comb", "harmonic_levels", "tail_levels",
           "bank_detune", "FREE_FREE", "HARMONIC")


class Knob:
    """A preset knob that selects one of N per-block damping factors."""

    def __init__(self, index, t60s):
        if not t60s:
            raise ValueError("a damping knob needs at least one t60")
        if len(t60s) & (len(t60s) - 1):
            raise ValueError("the bucket count must be a power of two: the knob is normalised by shifts")
        self.index = index
        self.t60s = tuple(t60s)
        self.shift = int(math.log2(len(self.t60s)))

    def factors(self):
        """Per-block gain for each bucket. A bucket is a target T60 for the whole voice."""
        return [int(round(10 ** (-3.0 * BLOCK / (t * FS)) * 2 ** 31)) for t in self.t60s]


def knob(index, t60s):
    return Knob(index, t60s)


# ------------------------------------------------------------------ level shapes worth naming

FREE_FREE = (1.0, 2.756, 5.404, 8.933, 13.34, 18.64)     # a free-free bar's modes
HARMONIC = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)


def strike_comb(position, count, tilt=None):
    """Excitation levels for a struck bar: each mode is hit by where the mallet lands.

    `tilt(m)` optionally scales mode m - for a wooden bar that is `sqrt(0.42)**m / (1 + 0.3*m)` over the
    strike comb. This law is what separates "wood" from "a sine with a click": get it wrong and the tuned
    4x partial sits 20 dB down instead of 16.
    """
    out = []
    for m in range(count):
        level = math.cos(math.pi * (m + 1) * position)
        if tilt:
            level *= tilt(m)
        out.append(level)
    return out


def harmonic_levels(count, exponent=1.0):
    """1/h**exponent tilt - the additive-organ/string shape. exponent 1 is the classic sawtooth series."""
    return [1.0 / (h ** exponent) for h in range(1, count + 1)]


def tail_levels(count, t60s, longest=8.0):
    """Levels that make the fast-decaying partials quieter at the strike, for a bell-like balance."""
    return [math.sqrt(t / longest) if t else 1.0 for t in t60s[:count]]


# ------------------------------------------------------------------ table generation

def bank_detune(bank, banks=2, cents=0.0):
    """The frequency multiplier a bank is tuned to: the banks are spread symmetrically around the pitch,
    so with two banks the outermost are -cents/2 and +cents/2. A checker needs this to measure a bank."""
    if banks < 2 or not cents:
        return 1.0
    offset = (bank - (banks - 1) / 2.0) * cents / banks
    return 2.0 ** (offset / 1200.0)


def coefficients(partials, banks, detune_cents):
    """(c, s) per note per oscillator, radius = the partial's own decay, flattened row-major."""
    rows = []
    for note in range(128):
        f0 = 440.0 * 2 ** ((note - 69) / 12.0)
        for bank in range(banks):
            tuned = f0 * bank_detune(bank, banks, detune_cents)
            for ratio, t60 in partials:
                f = tuned * ratio
                if f > FS * NYQUIST_GATE:
                    rows += [0, 0]                       # muted: this partial would alias
                    continue
                w = 2.0 * math.pi * f / FS
                r = 1.0 if not t60 else math.exp(-math.log(1000.0) / (t60 * FS))
                rows += [S.q31(r * math.cos(w)), S.q31(r * math.sin(w))]
    return rows


def seeds(levels, count, banks):
    """One seed per oscillator: the partial's level, the same in every bank."""
    if callable(levels):
        levels = [levels(i) for i in range(count)]
    levels = list(levels)
    if len(levels) != count:
        raise ValueError(f"{len(levels)} levels for {count} partials")
    return [S.q31(x) for x in levels] * banks


# ------------------------------------------------------------------ the generated engine

def build(name, slot, partials, levels, *, gain="gate", damping=None, pitch="row", banks=1,
          detune_cents=0.0, split=None, span_slots=3):
    """Generate and return the engine. `partials` is [(ratio, t60), ...]; see the module docstring."""
    count = len(partials)
    osc = count * banks
    level_list = [levels(i) for i in range(count)] if callable(levels) else list(levels)
    if len(level_list) != count:
        raise ValueError(f"{len(level_list)} levels for {count} partials")
    # the engine's output is the plain sum of its oscillators, so the seeds ARE the peak in the worst case
    if sum(abs(x) for x in level_list) > 1.0:
        raise ValueError(f"the seeds sum to {sum(abs(x) for x in level_list):.2f}, which can clip: "
                         f"scale them, or split them across banks")
    if not any(440.0 * ratio <= FS * NYQUIST_GATE for ratio, _ in partials):
        raise ValueError("every partial is above the Nyquist gate at note 69: this engine would be silent")
    if pitch not in ("row", "blend"):
        raise ValueError("pitch must be 'row' or 'blend'")
    if gain not in ("gate", "envelope", "envelope*velocity"):
        raise ValueError("gain must be 'gate', 'envelope' or 'envelope*velocity'")
    if split is None:
        split = banks == 2                            # two banks are panned apart by default
    if split and banks != 2:
        raise ValueError("split output needs exactly two banks")
    if 0x10 + 16 * osc > 0x118:                      # the coefficients must stay clear of the OS envelope
        raise ValueError(f"{osc} oscillators would overwrite the OS envelope at ctx+0x118")
    if count == 0:
        raise ValueError("an engine needs at least one partial")
    mode = pitch                                      # `pitch` and `gain` are also render's own names
    gain_mode = gain

    e = S.Engine(name, slot, span_slots=span_slots)
    SEEDS = e.words("SEEDS", seeds(levels, count, banks))
    COEF = e.words("COEF", coefficients(partials, banks, detune_cents), stride=osc * 8)
    FREQ = e.words("FREQ", [S.hz_q16(n) for n in range(128)])
    GAINS = e.words("GAINS", damping.factors()) if damping else None
    STATE = 0x10                                      # 2 words per oscillator
    COEF_AT = 0x10 + 8 * osc                          # this block's coefficients
    LAYOUT_WORDS = 4 + 2 * osc                        # the header words plus every state word

    # ---------------------------------------------------------------- initModule / init / note events
    @e.fn("initModule", ["idv", "host", "out"])
    def initModule(idv, host, out):
        with S.if_(S.nz(idv)):
            S.ret(0)                                  # the OS passes 0; refuse anything else
        S.ptr(out)[0].set(0)
        S.ret(1)

    @e.fn("init", ["ctx", "variant"])
    def init(ctx, variant):
        c = S.pin(S.ptr(ctx))
        with S.repeat(LAYOUT_WORDS):
            c.put(0)
        S.unpin(c)

    @e.fn("onNoteOn", ["a1", "note", "ctx", "a4"])
    def onNoteOn(a1, note, ctx, a4):
        # this export is not what starts a note on the device, so it only asks render to re-strike
        v = S.ptr(ctx)
        v[0x00].set(0)
        v[0x04].set(note)

    @e.fn("onNoteOff", ["a1", "ctx"])
    def onNoteOff(a1, ctx):
        # which register carries the context here is not documented: range-check it so a wrong guess
        # writes nothing instead of 64 bytes at an arbitrary address (render's amp gate still ends the
        # voice, so a no-op is harmless)
        with S.if_(ctx < 0x10000000):
            S.ret()
        c = S.pin(S.ptr(ctx))
        c.put(1)                                      # struck, so render will not restart the note
        with S.repeat(LAYOUT_WORDS - 1):
            c.put(0)
        S.unpin(c)

    # ---------------------------------------------------------------- render
    @e.fn("render", ["out", "pitch", "bend", "ctx", "params", "amp"])
    def render(out, pitch, bend, ctx, params, amp):
        o = S.pin(S.ptr(out))
        c = S.pin(S.ptr(ctx))
        k = S.pin(S.ptr(ctx).at(COEF_AT))
        acc = S.var("acc", hot=True)
        right = S.var("right") if split else None
        gain = S.var("gain")
        vel = S.var("vel")
        row = S.var("row")
        hirow = S.var("hirow") if mode == "blend" else None
        frac = S.var("frac") if mode == "blend" else None
        y1 = S.var("y1")
        y2 = S.var("y2")
        lo_c = S.var("lo_c")
        lo_s = S.var("lo_s")
        hi_c = S.var("hi_c") if mode == "blend" else None
        hi_s = S.var("hi_s") if mode == "blend" else None
        tmp = S.var("tmp")
        damp = S.var("damp") if damping else None
        eps = S.var("eps") if mode == "blend" else None
        epss = S.var("epss") if mode == "blend" else None

        # ---- the amp object: gate, then the per-voice gain. A zero gain means unity, not silence, so a
        # field the OS does not fill costs a velocity knob instead of the whole engine.
        vel.set(0x7FFFFFFF)
        with S.if_(S.nz(amp)):
            with S.if_(S.zero(S.ptr(amp)[0x10])):
                c[0x00].set(0)                        # idle: the next active tick re-strikes
                S.ret()
            if gain_mode == "envelope*velocity":
                vel.set(S.ptr(amp)[0x04])
                with S.if_(S.zero(vel)):
                    vel.set(0x7FFFFFFF)

        # ---- no pitch is no note. Tested before the bend is added (after it, the bend alone made this
        # guard miss) and unsigned, so a negative argument - which a table search reads as enormous - is
        # rejected instead of clamping to the top row.
        with S.if_(S.zero(pitch)):
            c[0x00].set(0)
            S.ret()
        if mode == "blend":
            pitch = pitch + (bend << 5)               # half the glide delta: the block's midpoint
        with S.if_(pitch < 0x40000000):               # 16384 Hz in Q16, above the top row
            pass
        with S.else_():
            c[0x00].set(0)
            S.ret()

        # ---- the strike: every oscillator starts at its level, at rest
        with S.if_(S.zero(c[0x00])):
            c[0x00].set(1)
            for i in range(osc):
                c[STATE + 8 * i].set(SEEDS[i])
                c[STATE + 8 * i + 4].set(0)

        # ---- the coefficient row(s) for this note
        row.set(S.find_row(pitch, FREQ))
        if mode == "row":
            for i in range(osc):
                k[8 * i].set(COEF.row(row)[8 * i])
                k[8 * i + 4].set(COEF.row(row)[8 * i + 4])
        else:
            hirow.set(row + 1)
            frac.set(0)
            with S.if_(row < 127):
                frac.set(S.udiv(pitch - FREQ[row], FREQ[row + 1] - FREQ[row]))
            with S.else_():
                hirow.set(127)                        # clamped at the top: no row above to blend to
            for i in range(osc):
                lo_c.set(COEF.row(row)[8 * i])
                lo_s.set(COEF.row(row)[8 * i + 4])
                hi_c.set(COEF.row(hirow)[8 * i])
                hi_s.set(COEF.row(hirow)[8 * i + 4])
                lo_c.set(lo_c + S.qmul(hi_c - lo_c, frac << 15))     # Q16 fraction -> Q31
                lo_s.set(lo_s + S.qmul(hi_s - lo_s, frac << 15))
                # Two unit vectors blended shorten to cos(dw/2), and these rotators have no damping of
                # their own, so a pitch held between rows would fade instead of sustaining. Rescale by
                # 1 + eps + 1.5 eps^2 with eps = 0.5 - r^2/2. Below r^2/2 = 0.25 the pair is not a
                # rotation at all (a muted partial's zero row has length zero, and its length IS its
                # level), so that case is left alone.
                tmp.set(S.mul32(lo_c, lo_c) + S.mul32(lo_s, lo_s))
                with S.if_(tmp >= 0x20000000):
                    eps.set(0x40000000 - tmp)
                    epss.set(S.mul32(eps, eps))       # eps^2 / 2
                    tmp.set(eps + epss + epss + epss) # eps + 1.5 eps^2
                    lo_c.set(lo_c + S.qmul(lo_c, tmp))
                    lo_s.set(lo_s + S.qmul(lo_s, tmp))
                k[8 * i].set(lo_c)
                k[8 * i + 4].set(lo_s)

        # ---- the block's output gain
        if gain_mode == "envelope":
            gain.set(c[0x118])                        # the OS envelope, record+0x160
        elif gain_mode == "envelope*velocity":
            gain.set(S.qmul(c[0x118], vel))
        else:
            gain.set(0x7FFFFFFF)

        # ---- the per-block damping: one of N bucket factors selected by a preset knob. The knob's unit
        # is not settled by any source (the presets store eighteen 0..255 values, the sibling port's
        # parameter map records a byte baseline of 128, and its fixtures pass Q31 words), so a word below
        # 256 is treated as a byte knob and normalised, and anything else takes the Q31 path with the
        # index masked to the bucket count - a bare shift would pin a byte knob at bucket 0 forever and
        # let a negative word index past the table.
        if damping:
            row.set(0)
            with S.if_(S.nz(params)):
                with S.if_(S.ptr(params)[4 * damping.index] < 256):
                    row.set(S.ptr(params)[4 * damping.index] >> (8 - damping.shift))
                with S.else_():
                    row.set((S.ptr(params)[4 * damping.index] >> 28) & (len(damping.t60s) - 1))
            damp.set(GAINS[row])
            for w in range(2 * osc):
                c[STATE + 4 * w].set(S.qmul(c[STATE + 4 * w], damp))

        # ---- 64 frames. Both new state words come from the OLD pair: storing y1 first and then reading
        # it back for y2 turns the rotation into something that grows.
        with S.repeat(BLOCK):
            acc.set(0)
            if split:
                right.set(0)
            for i in range(osc):
                y1.set(c[STATE + 8 * i])
                y2.set(c[STATE + 8 * i + 4])
                c[STATE + 8 * i].set(S.qmul(k[8 * i], y1) - S.qmul(k[8 * i + 4], y2))
                c[STATE + 8 * i + 4].set(S.qmul(k[8 * i + 4], y1) + S.qmul(k[8 * i], y2))
                if split and i >= count:
                    right.set(right + c[STATE + 8 * i])
                else:
                    acc.set(acc + c[STATE + 8 * i])
            if gain_mode == "gate":
                out_l, out_r = acc, (right if split else acc)
            else:
                acc.set(S.qmul(acc, gain))
                out_l = acc
                out_r = acc
                if split:
                    right.set(S.qmul(right, gain))
                    out_r = right
            o.put(out_l)
            o.put(out_r)

    return e


if __name__ == "__main__":
    print(__doc__)
