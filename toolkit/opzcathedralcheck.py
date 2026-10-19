#!/usr/bin/env python3
"""Execution check for cathedral.engine: pitch, ranks, sustain, dynamics, bend, polyphony, headroom."""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzengine as E
import opzsim as Z

RANKS = (0.5, 1, 2, 3, 4, 6)


def render(raw, exports, note, vel=0x7FFFFFFF, env=0x7FFFFFFF, bend=0, blocks=96, voices=1):
    """Render `blocks` blocks, round-robin over `voices` contexts; return one sample list per voice."""
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
    m.st32(amp + 0x10, 2)
    left = [[] for _ in ctxs]
    for _ in range(blocks):
        for i, ctx in enumerate(ctxs):
            Z.call(m, exports["render"], [out, Z.hz_to_q16(notes[i]), bend], stack=(ctx, params, amp))
            left[i].extend(m.ld32(out + 4 * j) for j in range(2 * Z.S.BLOCK))
    return left[0] if len(left) == 1 else left


def level(stereo, hz):
    samples = stereo[::2]
    ang = 2 * math.pi * hz / Z.S.FS
    c, s = math.cos(ang), math.sin(ang)
    x, y = 1.0, 0.0
    re = im = 0.0
    for value in samples:
        re += value * x
        im -= value * y
        x, y = x * c - y * s, x * s + y * c
    return 2 * math.hypot(re, im) / (len(samples) * 2**31)


def peak(samples):
    return max(map(abs, samples)) / 2**31


def main(path="cathedral.engine"):
    raw = pathlib.Path(path).read_bytes()
    exports = dict(E.read_module(raw)["exports"])

    clips, energy = {}, {}
    for note, target in ((60, 261.6256), (72, 523.2511)):
        s = render(raw, exports, note)
        clips[note], energy[note] = s, sum(v * v for v in s)
        got = Z.S.measure_freq(s)
        assert abs(got / target - 1) < 0.01, f"note {note}: {got:.2f} Hz vs {target:.2f} Hz"
    top = render(raw, exports, 127, blocks=48)
    f127 = 440.0 * 2 ** ((127 - 69) / 12)
    assert level(top, f127) > 0.1, f"MIDI 127 renders {level(top, f127):.4f} at its own pitch"
    assert level(top, f127 * 2 ** (-1 / 12)) < 0.01, "MIDI 127 falls back to the previous semitone"

    levels = [level(clips[60], 261.6256 * r) for r in RANKS]
    assert min(levels) > 0.01, f"missing organ ranks: {levels}"

    # Sustain: the last quarter of the note is as loud as the first quarter.
    q = len(clips[60]) // 4
    head, tail = sum(v * v for v in clips[60][:q]), sum(v * v for v in clips[60][-q:])
    assert 0.75 < tail / head < 1.25, f"note 60 is not sustained ({head:.3e} -> {tail:.3e})"

    # A pitch held BETWEEN two table rows must sustain too. Interpolating two unit vectors shortens the
    # radius, and this oscillator has no damping of its own, so a shorter radius is a fade: half a semitone
    # off row 100 used to lose 83% in 0.8 s. This is the check that catches that class of bug.
    between = render(raw, exports, 100.5, blocks=480)
    q = len(between) // 4
    head, tail = sum(v * v for v in between[:q]), sum(v * v for v in between[-q:])
    assert 0.85 < tail / head < 1.15, f"a pitch held between rows fades ({head:.3e} -> {tail:.3e})"

    # Dynamics: velocity (amp+0x08) and the OS envelope (record+0x160 == ctx+0x118) both scale the output.
    loud = peak(clips[60])
    for factor in (0.5, 0.25):
        got = peak(render(raw, exports, 60, vel=int(0x7FFFFFFF * factor), blocks=48))
        assert abs(got / loud - factor) < 0.05 * factor, f"velocity {factor}: {got / loud:.3f} of full"
        got = peak(render(raw, exports, 60, env=int(0x7FFFFFFF * factor), blocks=48))
        assert abs(got / loud - factor) < 0.05 * factor, f"envelope {factor}: {got / loud:.3f} of full"

    # Bend: render argument 3 is (target - current) >> 6 Q16 Hz, so half of it lands on the block's
    # midpoint. The shift must be continuous, i.e. far below a semitone, not snapped to one.
    for bend in (2000, -2000):
        got = Z.S.measure_freq(render(raw, exports, 69, bend=bend, blocks=96))
        want = 440.0 + bend / 2048.0
        assert abs(got - want) < 1.0, f"bend {bend}: {got:.2f} Hz vs {want:.2f} Hz"
    assert abs(Z.S.measure_freq(render(raw, exports, 69, blocks=96)) - 440.0) < 0.5, "unbent pitch drifted"

    # Polyphony: two voices at once, each holding its own pitch.
    a, b = render(raw, exports, [57, 81], blocks=96)
    assert abs(Z.S.measure_freq(a) / 220.0 - 1) < 0.01, f"voice A: {Z.S.measure_freq(a):.2f} Hz"
    assert abs(Z.S.measure_freq(b) / 880.0 - 1) < 0.01, f"voice B: {Z.S.measure_freq(b):.2f} Hz"

    assert peak(clips[60]) < 0.99, f"clipping: {peak(clips[60]):.3f} full scale"
    print(f"PASS pitch 60/72/127; ranks {', '.join(f'{x:.2f}' for x in levels)}; sustain; "
          f"velocity+envelope dynamics; continuous bend; polyphony; peak {peak(clips[60]):.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "cathedral.engine")
