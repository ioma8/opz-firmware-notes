#!/usr/bin/env python3
"""Execution check for strings.engine: pitch, harmonic tilt, sustain, stereo width, dynamics, polyphony.

Numbers come from running the module in the interpreter, not from a model of it: a Goertzel level at a
chosen frequency over a whole note, on the channel the bank the check is about lives on.

Usage: python3 opzstringscheck.py [strings.engine]
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzengine as E
import opzsim as Z
import build_strings as B

HARMONICS = B.HARMONICS


def render(raw, exports, note, vel=0x7FFFFFFF, env=0x7FFFFFFF, blocks=96, voices=1, amp_on=True):
    """Render `blocks` blocks round-robin over `voices` contexts; return the interleaved samples."""
    m = Z.Machine.for_module(raw)
    params = m.mem_base + Z.Machine.PARAM_OFF
    amp = params + 0x40
    out = m.mem_base + Z.Machine.OUT_OFF
    notes = note if isinstance(note, (list, tuple)) else [note] * voices
    ctxs = [m.mem_base + Z.Machine.SCRATCH_OFF + i * 0x400 for i in range(len(notes))]
    for ctx in ctxs:
        m.st32(ctx + 0x118, env)
        Z.call(m, exports["init"], [ctx, 0])
    m.st32(amp + 0x04, vel)
    m.st32(amp + 0x10, 2 if amp_on else 0)
    samples = []
    for _ in range(blocks):
        for i, ctx in enumerate(ctxs):
            Z.call(m, exports["render"], [out, Z.hz_to_q16(notes[i]), 0], stack=(ctx, params, amp))
            samples.append([m.ld32(out + 4 * j) for j in range(2 * Z.S.BLOCK)])
    return samples, m, ctxs


def channel(blocks, which):
    """Flatten one interleaved channel of a per-block sample list."""
    return [v for b in blocks for v in b[which::2]]


def level(samples, hz):
    """Goertzel magnitude at hz, normalised so a full-scale sine reads about 1.0."""
    if not samples:
        return 0.0
    ang = 2 * math.pi * hz / Z.S.FS
    c, s = math.cos(ang), math.sin(ang)
    x, y = 1.0, 0.0
    re = im = 0.0
    for value in samples:
        re += value * x
        im -= value * y
        x, y = x * c - y * s, x * s + y * c
    return 2 * math.hypot(re, im) / (len(samples) * 2**31)


def energy(samples):
    return math.sqrt(sum(v * v for v in samples) / max(1, len(samples)))


def main(path="strings.engine"):
    raw = pathlib.Path(path).read_bytes()
    exports = dict(E.read_module(raw)["exports"])
    failures = []

    def check(name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {name:44s} {detail}")
        if not ok:
            failures.append(name)

    # ---- pitch. Two traps here: bank A is detuned several cents down, and a Goertzel probe at the
    # wrong frequency loses magnitude over a long window (the error in Hz grows with the harmonic), so
    # measure at the bank's own frequency and confirm it is the peak of a small sweep.
    for note in (45, 57, 69, 81):
        blocks, _, _ = render(raw, exports, note)
        left = channel(blocks, 0)
        want = 440.0 * 2 ** ((note - 69) / 12.0) * B.detune(0)
        sweep = [(want * (1 + d / 1000.0), level(left, want * (1 + d / 1000.0)))
                 for d in range(-5, 6)]
        best_hz, best = max(sweep, key=lambda kv: kv[1])
        check(f"pitch note {note}", abs(best_hz / want - 1) < 0.0015 and level(left, want) > 0.9 * best,
              f"{best_hz:.1f} Hz (bank A detuned 6 cents: {want:.1f})")

    # ---- levels, sustain, clipping on one note
    blocks, _, _ = render(raw, exports, 69)
    left, right = channel(blocks, 0), channel(blocks, 1)
    peak = max(max(map(abs, left)), max(map(abs, right))) / 2**31
    check("no clipping", peak < 0.99, f"peak {peak:.3f} full scale")
    check("audible", peak > 0.05, f"peak {peak:.3f}")
    head, tail = energy(left[: len(left) // 4]), energy(left[-len(left) // 4:])
    check("sustains rather than decaying", 0.7 < tail / max(head, 1e-9) < 1.4,
          f"tail/head {tail / max(head, 1e-9):.2f}")

    # ---- the 1/h harmonic tilt, measured on one bank
    f0 = 440.0 * B.detune(0)                      # the bank's own frequency, not the equal-tempered one
    fund = level(left, f0)
    for h in range(2, HARMONICS + 1):
        rel = level(left, f0 * h) / max(fund, 1e-12)
        want = 1.0 / h
        db = 20 * math.log10(max(rel, 1e-12) / want)
        check(f"harmonic {h} at 1/{h}", abs(db) < 2.0, f"{20 * math.log10(max(rel, 1e-12)):.1f} dB, "
                                                     f"{db:+.1f} dB off 1/{h}")
    check("no fifth harmonic above the Nyquist gate", level(left, f0 * 5) / max(fund, 1e-12) < 0.02,
          "engine has four harmonics")

    # ---- the two banks are detuned and panned: identical channels would mean no ensemble
    diff = sum(abs(a - b) for a, b in zip(left, right)) / max(1, len(left))
    check("banks are panned apart", diff > 1e6, f"mean |L-R| = {diff / 2**31:.3f} full scale")

    # ---- the voice gain scales the output, and an idle amp object writes nothing
    quiet, _, _ = render(raw, exports, 69, vel=0x40000000)
    qpk = max(max(map(abs, b)) for b in quiet) / 2**31
    check("velocity gain halves the peak", abs(qpk / peak - 0.5) < 0.05, f"{qpk:.3f} vs {peak:.3f}")
    idle, _, _ = render(raw, exports, 69, amp_on=False)
    check("amp idle -> silence", max(max(map(abs, b)) for b in idle) == 0, "")

    # ---- polyphony: two contexts rendered alternately hold two pitches
    pair, _, _ = render(raw, exports, [57, 81], voices=2)
    va = [v for b in pair[::2] for v in b[::2]]
    vb = [v for b in pair[1::2] for v in b[::2]]
    a, b_ = level(va, 220.0), level(vb, 880.0)
    check("two voices, two pitches", a > 3 * level(va, 880.0) and b_ > 3 * level(vb, 220.0),
          f"voice A sings 220 ({a:.3f} vs {level(va, 880.0):.3f} at 880), "
          f"voice B sings 880 ({b_:.3f} vs {level(vb, 220.0):.3f} at 220)")

    # ---- onNoteOff silences the voice
    blocks, m, ctxs = render(raw, exports, 69, blocks=4)
    Z.call(m, exports["onNoteOff"], [0, ctxs[0]])
    out = m.mem_base + Z.Machine.OUT_OFF
    for j in range(2 * Z.S.BLOCK):
        m.st32(out + 4 * j, 0)
    Z.call(m, exports["render"], [out, Z.hz_to_q16(69), 0],
           stack=(ctxs[0], m.mem_base + Z.Machine.PARAM_OFF, m.mem_base + Z.Machine.PARAM_OFF + 0x40))
    check("onNoteOff -> silence", max(abs(m.ld32(out + 4 * j)) for j in range(2 * Z.S.BLOCK)) == 0, "")

    if failures:
        print(f"\n{len(failures)} check(s) failed: " + ", ".join(failures))
        return 1
    print(f"\nPASS strings.engine: pitch, {HARMONICS}-harmonic tilt, sustain, stereo width, dynamics, "
          f"polyphony, release")
    return 0


if __name__ == "__main__":
    import opztime
    opztime.watch("strings verifier")
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "strings.engine"))
