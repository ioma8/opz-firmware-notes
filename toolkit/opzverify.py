#!/usr/bin/env python3
"""opzverify.py - worst-case validation of the built engine, beyond the self-test's happy path.

opzsim's self-test proves the engine works for a handful of notes and buckets. This sweeps the space an
engine actually has to survive on a device:

  * every note in a range, measuring pitch against 440 * 2^((n-69)/12);
  * peak level per note, so nothing clips or runs away;
  * the extremes of the decay macro and a null params pointer;
  * note-on/off abuse: re-triggering inside a block, gate toggling, repeated init;
  * the instruction cost of one render call, which is what the DSP budget actually sees.

Numbers come from executing the emitted module, not from a model of it.

Usage:
    python3 opzverify.py [engine] [--every N]
"""
import pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzengine as E
import opzsim as Z
import opzstruck as S


def setup(raw, bucket=4, note=None):
    m = Z.Machine.for_module(raw)
    exports = dict(E.read_module(raw)["exports"])
    ctx = m.mem_base + Z.Machine.SCRATCH_OFF
    prm = m.mem_base + Z.Machine.PARAM_OFF
    for i in range(8):
        m.st32(prm + 4 * i, bucket << 28)
    out = m.mem_base + Z.Machine.OUT_OFF
    Z.call(m, exports["initModule"], [0, 0x81003850, ctx])
    Z.call(m, exports["init"], [ctx, 0])
    if note is not None:
        Z.call(m, exports["onNoteOn"], [0, note, ctx])
    return m, exports, ctx, prm, out


def capture(m, exports, ctx, prm, out, blocks):
    buf = []
    for _ in range(blocks):
        for j in range(2 * S.BLOCK):
            m.st32(out + 4 * j, 0)
        Z.call(m, exports["render"], [out, 440 << 16, 0], stack=(ctx, prm, 0))
        buf += [m.ld32(out + 4 * j) for j in range(2 * S.BLOCK)]
    return buf


def main(argv):
    path = pathlib.Path(argv[0]) if argv and not argv[0].startswith("-") else pathlib.Path("struck.engine")
    every = int(argv[argv.index("--every") + 1]) if "--every" in argv else 6
    raw = path.read_bytes()
    if not E.read_module(raw):
        raise SystemExit("not a valid module")

    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name:34s} {detail}")

    # ---- pitch and level across the range
    notes = list(range(24, 100, every))
    worst_err, worst_note, peak_max, peak_min = 0.0, 0, 0.0, 1.0
    for n in notes:
        want = 440.0 * 2 ** ((n - 69) / 12.0)
        # a low note needs a long analysis window, and the capture must be at least that long or the
        # slice is truncated and the estimate drifts (0.8 s of 32.7 Hz once read as 33.4 Hz)
        window = 4096 if want > 200 else 16384
        m, ex, ctx, prm, out = setup(raw, note=n)
        buf = capture(m, ex, ctx, prm, out, max(60, window // S.BLOCK + 16))
        got = S.measure_freq(buf, window=window)
        err = abs(got - want) / want
        peak = max(abs(v) for v in buf) / 2 ** 31
        if err > worst_err:
            worst_err, worst_note = err, n
        peak_max, peak_min = max(peak_max, peak), min(peak_min, peak)
        if err >= 0.02 or peak >= 1.0:
            check(f"note {n}", False, f"{got:.1f} Hz vs {want:.1f} Hz ({100*err:.1f}%), peak {peak:.3f}")
    check(f"pitch over {len(notes)} notes", worst_err < 0.02,
          f"worst {100*worst_err:.2f}% at note {worst_note}")
    check("no clipping anywhere", peak_max < 1.0, f"loudest peak {peak_max:.3f} full scale")
    check("audible everywhere", peak_min > 0.001, f"quietest peak {peak_min:.4f}")

    # ---- decay macro extremes and the null-params guard
    for bucket, want in ((0, 0.1), (7, 8.0)):
        m, ex, ctx, prm, out = setup(raw, bucket=bucket, note=69)
        blocks = int(S.FS * want * 1.6 / S.BLOCK)
        t60 = S.measure_decay(capture(m, ex, ctx, prm, out, blocks))
        ok = t60 is not None and abs(t60 - want) / want < 0.2
        check(f"decay bucket {bucket}", ok, f"T60 {t60:.2f} s vs {want} s" if t60 else "not reached")

    m, ex, ctx, prm, out = setup(raw, note=69)
    for j in range(2 * S.BLOCK):
        m.st32(out + 4 * j, 0)
    Z.call(m, ex["render"], [out, 440 << 16, 0], stack=(ctx, 0, 0))   # null params
    buf = [m.ld32(out + 4 * j) for j in range(2 * S.BLOCK)]
    check("null params survives", any(v != 0 for v in buf), "renders with gain 1.0")

    # ---- abuse: gate toggling and re-triggering inside a block
    m, ex, ctx, prm, out = setup(raw, note=69)
    capture(m, ex, ctx, prm, out, 2)
    for _ in range(8):
        Z.call(m, ex["onNoteOff"], [0, ctx])
        Z.call(m, ex["onNoteOn"], [0, 69, ctx])
        capture(m, ex, ctx, prm, out, 1)
    buf = capture(m, ex, ctx, prm, out, 4)
    check("survives 8 re-triggers", max(abs(v) for v in buf) > 0, "still sounding")
    check("re-trigger keeps pitch", abs(S.measure_freq(buf) - 440) / 440 < 0.03,
          f"{S.measure_freq(buf):.1f} Hz")

    # ---- repeated init must not leak state between notes
    m, ex, ctx, prm, out = setup(raw, note=69)
    capture(m, ex, ctx, prm, out, 4)
    Z.call(m, ex["init"], [ctx, 0])
    buf = capture(m, ex, ctx, prm, out, 1)
    check("init silences the voice", all(v == 0 for v in buf), "gate cleared by init")

    # ---- cost: instructions per render call, and the resulting DSP load
    m, ex, ctx, prm, out = setup(raw, note=69)
    before = m.steps
    capture(m, ex, ctx, prm, out, 1)
    per_call = m.steps - before
    per_second = per_call * (S.FS / S.BLOCK)
    check("render cost", per_call < 20000, f"{per_call:,} instructions/call = {per_second/1e6:.2f} M inst/s per voice")

    print(f"\n{'FAILED' if fails else 'all checks passed'} ({fails} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
