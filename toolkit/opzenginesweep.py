#!/usr/bin/env python3
"""Sweep every factory engine and report whether it actually makes *sound*.

    python3 toolkit/opzenginesweep.py            # all 21 engines in engines-official/
    python3 toolkit/opzenginesweep.py volt       # one engine, verbose

The point of this tool is the criterion, not the loop. A single loud sample is not audio: two factory
engines already produced a start-up spike (peak 0.986) and a full-scale DC offset (peak 1.000), and both
looked like success to a peak-only check. So an engine is only called audible here when all three hold:

  1. tail RMS      - energy left after the first block, so a one-shot transient cannot pass
  2. dynamic range - more than a handful of distinct sample values, so DC cannot pass
  3. pitch         - zero crossings within 8% of the note it was asked to play

Anything that fails is reported with the reason, so a sweep result is a measurement rather than a mood.
"""

import math
import pathlib
import sys

import opzengine as E
import opzhost as H
import opzsim as Z
import opzmarimba as S
import opztime

NOTE, FREQ = 69, 440.0
BLOCKS = 8


def play(mod_path, note=NOTE, freq=FREQ, blocks=BLOCKS):
    """Render one note and return the left channel of the tail, plus the whole signal."""
    raw = pathlib.Path(mod_path).read_bytes()
    ex = dict(E.read_module(raw)["exports"])
    kind = "render" if "render" in ex else "renderFX"
    m = Z.Machine.for_module(raw)
    m.allow_external = True
    table = H.apply_to_interpreter(m, table_slot=m.mem_base + Z.Machine.SCRATCH_OFF - 0x200)
    ctx = m.mem_base + Z.Machine.SCRATCH_OFF
    prm = m.mem_base + Z.Machine.PARAM_OFF
    out = m.mem_base + Z.Machine.OUT_OFF
    amp = ctx + 0x1000
    fx_in, fx_state = prm + 0x8000, prm + 0x9000
    for i in range(8):
        m.st32(prm + 4 * i, int(0.5 * (1 << 28)))
    # the amp object's fields are filled by the OS before every tick, not by the engine: FUN_8012e0a4
    # writes record+0x40 (amp+0x10) = 5, record+0x38 (amp+0x08) = 0x7f000000 and record+0x3c
    # (amp+0x0c) = -(record[0x34] * [0x815c8088]), a negative scaling. amp+0x04 is the per-voice gain
    # chord loads at 0x81be278c. Leaving them zero is why engines read as silent here.
    m.st32(amp + 0x10, 2)
    m.st32(amp + 0x04, 0x7fffffff)
    m.st32(amp + 0x08, 0x7f000000)
    m.st32(amp + 0x0c, -0x40000000 & 0xFFFFFFFF)
    Z.call(m, ex["initModule"], [0, table, ctx], limit=60000)
    Z.call(m, ex["init"], [ctx, 0], limit=60000)
    if "onNoteOn" in ex:
        # the convention that actually plays an engine (the same one opzenginetool uses for marimba):
        # note and context, with the first word unused
        Z.call(m, ex["onNoteOn"], [0, note, ctx], limit=60000)
    left, first_block = [], None
    for blk in range(blocks):
        for j in range(2 * S.BLOCK):
            m.st32(out + 4 * j, 0)
        if kind == "render":
            # The Blackfin ABI passes every argument on the stack as well as in R0-R2, and factory
            # engines read them from the stack: chord takes its context at [FP+0x14], its parameters at
            # [FP+0x18] and its amp at [FP+0x1c], which only line up when all six words are pushed
            # (LINK puts FP eight bytes above the first stack word). Pushing three leaves those slots
            # zero, which is why the engines looked blind to their own state for so long.
            freq_q16 = int(freq) << 16
            Z.call(m, ex["render"], [out, freq_q16, 0],
                   stack=(out, freq_q16, 0, ctx, prm, amp), limit=200000)
        else:
            for j in range(S.BLOCK):
                v = 0.5 * math.sin(2 * math.pi * freq * (blk * S.BLOCK + j) / 48000)
                m.st32(fx_in + 4 * j, int(v * (1 << 31)) & 0xFFFFFFFF)
            # same convention for effects: all five arguments on the stack, first three also in registers
            freq_q16 = int(freq) << 16
            Z.call(m, ex["renderFX"], [ctx, freq_q16, fx_state, fx_in, out],
                   stack=(ctx, freq_q16, fx_state, fx_in, out), limit=200000)
        blk_samples = [m.ld32(out + 8 * j) / 2**31 for j in range(S.BLOCK)]
        if blk == 0:
            first_block = blk_samples
        else:
            left += blk_samples
    return left, first_block


def measure(engine, blocks=BLOCKS):
    """Return (verdict, detail) for one engine."""
    try:
        tail, first = play(engine, blocks=blocks)
    except TimeoutError:
        return "timeout", "exceeded the watchdog"
    except Exception as e:                                   # an engine-specific failure is a result too
        msg = str(e)
        if "null function pointer" in msg:
            return "needs-state", "calls an OS-installed callback the harness cannot supply"
        if "keeps calling outside" in msg:
            return "needs-state", "jumps out of its module and never returns"
        if "did not return" in msg:
            return "loops", "never returns within the step budget"
        return "error", f"{type(e).__name__}: {msg[:60]}"
    if not tail:
        return "error", "no samples"
    rms = math.sqrt(sum(v * v for v in tail) / len(tail))
    distinct = len({round(v, 3) for v in tail})
    zc = [i for i in range(1, len(tail)) if tail[i - 1] < 0 <= tail[i]]
    pitch = (len(zc) - 1) / ((zc[-1] - zc[0]) / 48000) if len(zc) > 2 else 0.0
    peak = max(abs(v) for v in [*first, *tail])
    detail = f"peak {peak:.3f}  tail-rms {rms:.4f}  distinct {distinct:4d}  {pitch:6.1f} Hz"
    if rms < 0.002:
        return "silent", detail
    if distinct < 12:
        return "flat", detail + "  (DC or one-shot)"
    if pitch == 0 or abs(pitch - FREQ) > 0.08 * FREQ:
        return "detuned", detail + f"  (expected {FREQ:.0f})"
    return "AUDIO", detail


def main(argv):
    opztime.watch("engine sweep", 115)
    names = argv or sorted(p.stem for p in pathlib.Path("engines-official").glob("*.engine"))
    counts = {}
    for name in names:
        engine = name if name.endswith(".engine") else f"engines-official/{name}.engine"
        verdict, detail = measure(engine)
        counts[verdict] = counts.get(verdict, 0) + 1
        print(f"  {pathlib.Path(engine).stem:16s} {verdict:8s} {detail}", flush=True)
    print()
    print("  " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    return 0 if counts.get("AUDIO") == len(names) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
