#!/usr/bin/env python3
"""opzstruck.py - the "struck body" modal resonator, as fixed-point reference code.

This is the algorithm an OP-Z `.engine` would run, written so that it can be *measured* rather than
merely admired: it renders audio with the same integer arithmetic the Blackfin+ core will use, then
checks the result against theory (pitch, decay time, level) and writes a WAV to listen to.

Design (the parameters are the eight macros from doc `11`):

  a struck body is a bank of two-pole resonators. Mode m has angular frequency w_m and a decay
  radius r_m, and it is written in the *coupled* (rotation) form rather than direct form II:

      y1' =  r*cos(w)*y1 - r*sin(w)*y2
      y2' =  r*sin(w)*y1 + r*cos(w)*y2

  The direct form would need a coefficient of 2*r*cos(w), which does not fit in Q31 - it saturates at
  values just under 2.0 and the resonator then oscillates at the wrong frequency. This form's two
  coefficients, r*cos(w) and r*sin(w), are both inside +/-1 by construction, so Q31 is safe, and the
  rotation itself supplies the decay because r < 1 shrinks the state on every sample. It costs four
  fractional multiplies per mode per sample instead of two, which is the right trade: a wrong
  encoding is undebuggable, and the core has the throughput.

  Inharmonicity stretches the mode ratios from harmonic (1,2,3,4,5,6) toward the free-free bar
  ratios (1, 2.756, 5.404, 8.933, 13.34, 18.64), which is the whole marimba-to-bell-to-gong axis.

Fixed point: every coefficient and sample is Q31 (int32). Multiplication is Blackfin's fractional
(M) form - the product shifted right by 31 with saturation - which is `frac()` below. The reference
saturates explicitly so that a gain mistake shows up as a saturation count instead of as a silent
wrap-around.

Usage:
    python3 opzstruck.py selftest      # measure pitch/decay/level against theory
    python3 opzstruck.py render out.wav --freq 220 --decay 1.0
"""
import math, struct, sys, wave

FS = 48000
BLOCK = 64                     # the OS calls render() with 64 frames (doc `11` §11.9)
Q = 31
ONE = 1 << Q
BAR = (1.0, 2.756, 5.404, 8.933, 13.34, 18.64)      # free-free bar (inharmonic) ratios
HARMONIC = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)           # fully stretched-aside ratios


def sat32(v):
    return 0x7FFFFFFF if v > 0x7FFFFFFF else (-0x80000000 if v < -0x80000000 else v)


def frac(a, b):
    """Blackfin `Mult32 (T)` extraction, as the SLEIGH source defines it.

    The product is 64 bits; dx32ExtrRnd with (T) - dxM32I=0, dxM32TNS=1, dxP=0 - runs
    `rounding(rnd, acc, 4)`, which clears the low FOUR bytes before strunc4_sat truncates to
    32 bits. Four bytes is 32 bits, so the extraction is `>> 32`, not the `>> 31` a Q31
    fractional multiply wants. Compiled factory code therefore scales by half, and the rotation
    below compensates with one doubling add rather than by halving the coefficients (which would
    overflow Q31, the same trap that broke the direct form).
    """
    return sat32((a * b) >> 32)


def frac_q31(a, b):
    """Q31 multiply expressed in terms of the (T) extraction: 2 * (a*b >> 32) == (a*b) >> 31."""
    return sat32(frac(a, b) + frac(a, b))


def to_q31(x):
    return sat32(int(round(x * ONE)))


class Mode:
    __slots__ = ("c", "s", "y1", "y2", "gain")

    def __init__(self):
        self.c = self.s = self.y1 = self.y2 = 0
        self.gain = ONE


class Struck:
    """One voice of the struck-body engine."""

    def __init__(self, modes=6):
        self.modes = [Mode() for _ in range(modes)]
        self.master = to_q31(0.8)

    def coefficients(self, freq, inharmonicity=0.75, decay=1.0, brightness=0.5, t60_low=1.0):
        """Compute a1/a2 for every mode. Runs once per note-on, not per sample."""
        for m, md in enumerate(self.modes):
            ratio = HARMONIC[m] + (BAR[m] - HARMONIC[m]) * inharmonicity
            f = freq * ratio
            if f > FS * 0.45:                      # keep the mode below Nyquist
                md.c = md.s = 0
                continue
            w = 2.0 * math.pi * f / FS
            # a bigger decay macro means a longer note; higher modes die first
            t60 = max(0.02, t60_low * max(0.05, decay) / (1.0 + 0.55 * m))
            r = math.exp(-math.log(1000.0) / (t60 * FS))
            md.c = to_q31(r * math.cos(w))
            md.s = to_q31(r * math.sin(w))
            # brightness tilts the spectrum of the excitation, not the decay
            md.gain = to_q31((0.55 ** m) ** (1.0 - brightness) * (1.0 / (1.0 + 0.3 * m)))

    def strike(self, strength=1.0, position=0.3):
        """Excite the bank: an impulse whose per-mode sign is set by where the body was hit."""
        for m, md in enumerate(self.modes):
            comb = math.cos(math.pi * (m + 1) * position)
            md.y1 = sat32(int(strength * md.gain * comb * ONE * 0.5))
            md.y2 = 0

    def block(self, out):
        """Append 64 stereo frames exactly as render() must: two words per frame."""
        master = self.master
        for _ in range(BLOCK):
            acc = 0
            for md in self.modes:
                # each product is the (T) extraction (>>32), so every term is doubled back into
                # Q31 with an add - exactly what the emitted engine code does
                y1 = sat32(sat32(frac(md.c, md.y1) - frac(md.s, md.y2)) * 2)
                y2 = sat32(sat32(frac(md.s, md.y1) + frac(md.c, md.y2)) * 2)
                md.y1 = y1
                md.y2 = y2
                acc += y1
            s = frac(master, sat32(acc))
            out.append(s)
            out.append(s)                          # interleaved stereo, same value both sides


def render(freq=220.0, decay=1.0, inharmonicity=0.75, brightness=0.5, seconds=2.0, **kw):
    v = Struck()
    v.coefficients(freq, inharmonicity, decay, brightness, **kw)
    v.strike()
    out = []
    for _ in range(int(FS * seconds / BLOCK)):
        v.block(out)
    return out


def measure_freq(buf, skip=64, lo=20.0, hi=5000.0, steps=520):
    """Pitch as the strongest spectral peak - a direct DFT scan, not autocorrelation.

    Autocorrelation was tried first and gave octave errors: an unnormalised sum is dominated by
    short lags on a decaying multi-mode signal, and it reported 56 Hz for a 220 Hz note. Scanning
    the spectrum for its maximum has no such failure mode and needs no window functions.
    """
    # block() writes interleaved stereo (two words per frame, as the ABI requires), so analysis has
    # to take one channel: reading it as mono doubles every sample and reports exactly half the pitch.
    seg = [b / 0x80000000 for b in buf[skip * 2:skip * 2 + 4096 * 2:2]]
    best_f, best_m = 0.0, -1.0
    f = lo
    ratio = (hi / lo) ** (1.0 / steps)
    for _ in range(steps):
        w = 2.0 * math.pi * f / FS
        re = im = 0.0
        # two-term recurrence keeps this cheap without importing numpy
        cw, sw = math.cos(w), math.sin(w)
        cr, sr = 1.0, 0.0
        for x in seg:
            re += x * cr
            im += x * sr
            cr, sr = cr * cw - sr * sw, sr * cw + cr * sw
        m = re * re + im * im
        if m > best_m:
            best_f, best_m = f, m
        f *= ratio
    return best_f


def measure_decay(buf):
    """Time for the RMS envelope to fall to 1/1000 of its first block."""
    def rms(lo, hi):
        lo, hi = lo * 2, hi * 2
        return math.sqrt(sum((buf[i] / 0x80000000) ** 2 for i in range(lo, hi, 2)) / max(1, (hi - lo) // 2))
    head = rms(BLOCK, BLOCK * 4)
    # buf is interleaved stereo, so it holds two words per frame; iterating len(buf)//BLOCK would
    # walk twice as many blocks as exist and run off the end on long captures
    n_blocks = (len(buf) // 2) // BLOCK
    for i in range(8, n_blocks):
        if rms(i * BLOCK, (i + 1) * BLOCK) < head / 1000.0:
            return (i * BLOCK) / FS
    return None


def write_wav(path, buf):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(b"".join(struct.pack("<h", max(-32768, min(32767, s >> 16))) for s in buf))


def selftest():
    fails = 0

    def check(name, ok, detail):
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name:28s} {detail}")

    # 1. pitch accuracy across the range
    for f0 in (110.0, 220.0, 440.0, 880.0):
        buf = render(freq=f0, seconds=0.5)
        f = measure_freq(buf)
        err = abs(f - f0) / f0
        check(f"pitch {f0:.0f} Hz", err < 0.02, f"measured {f:.1f} Hz ({100*err:.2f}% error)")

    # 2. decay tracks the decay macro (T60 halves as decay doubles)
    t = {}
    for d in (0.5, 1.0, 2.0):
        t[d] = measure_decay(render(freq=220.0, decay=d, seconds=6.0))
    check("decay grows with macro", t[0.5] < t[1.0] < t[2.0], f"T60 {t[0.5]:.2f} < {t[1.0]:.2f} < {t[2.0]:.2f} s")

    # 3. inharmonicity changes the spectrum but not the pitch
    a = render(freq=220.0, inharmonicity=0.0, seconds=0.5)
    b = render(freq=220.0, inharmonicity=1.0, seconds=0.5)
    fa, fb = measure_freq(a), measure_freq(b)
    check("inharmonicity keeps pitch", abs(fa - fb) / fa < 0.02, f"{fa:.1f} vs {fb:.1f} Hz")

    # 4. no runaway: the block must be bounded and must actually decay to silence
    buf = render(freq=220.0, seconds=3.0)
    peak = max(abs(s) for s in buf) / 0x80000000
    tail = max(abs(s) for s in buf[-BLOCK * 20:]) / 0x80000000
    check("peak stays in range", 0.02 < peak <= 1.0, f"peak {peak:.3f} full scale")
    check("decays to silence", tail < 1e-3, f"tail {tail:.2e}")

    # 5. determinism (the same note twice is bit-identical: no hidden state)
    check("deterministic", render(freq=330.0, seconds=0.2) == render(freq=330.0, seconds=0.2), "identical buffers")

    print(f"\n{'FAILED' if fails else 'all checks passed'} ({fails} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    if len(sys.argv) > 2 and sys.argv[1] == "render":
        freq = 220.0
        decay = 1.0
        args = sys.argv[3:]
        for i in range(0, len(args) - 1, 2):
            if args[i] == "--freq":
                freq = float(args[i + 1])
            elif args[i] == "--decay":
                decay = float(args[i + 1])
        write_wav(sys.argv[2], render(freq=freq, decay=decay))
        print(f"wrote {sys.argv[2]}")
        sys.exit(0)
    print(__doc__)
    sys.exit(selftest())
