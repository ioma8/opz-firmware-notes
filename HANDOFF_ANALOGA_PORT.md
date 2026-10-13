# Handoff: finishing the `AnalogA` port

Written at the end of a session that ran out of context mid-port. Everything below is verified
state, not a plan. The clone repository is `~/projects/customs/opz-clone`; `TESTED` means a command
was run.

## Where the port stands

`crates/opz-dsp/src/analog_a.rs` (522 lines) plus `crates/opz-dsp/tests/analog_a.rs` (276 lines).
`cargo test --workspace` → **63 tests passing** (`TESTED`), tree clean, `phase-1` and `phase-2`
tagged, Phase 3 deliberately untagged.

| Function | Bytes | Status | Verified by |
|---|---|---|---|
| `initModule` | 32 | ported | host-gain variant mapping |
| `init` | 92 | ported | variant → global, scratch guard |
| `onNoteOn` | 600 | ported | every state field × all 20 cases |
| `onNoteOff` | 8 | ported | returns its argument |
| `renderSaw` | 628 | ported | 144 recorded `(phase, increment)` pairs |
| `setEnvelopeState` | 76 | ported | 21 recorded calls |
| `updateFilterEnvelope` | 292 | ported | 36 recorded calls |
| `renderSquare` | 1 388 | **not ported** | 144 cases already recorded |
| `_RFilter_fetch` | 712 | **not ported** | needs fixtures (make them first) |
| `render` | 2 044 | **not ported** | 20 recorded outputs |

## The loop that works

1. If the function is pure, record fixtures by calling the original symbol directly — that is how
   `renderSaw`, `setEnvelopeState` and `updateFilterEnvelope` each took one pass. The generator is
   `tools/unicorn-harness/make_oscillator_fixtures.py`; add a function to its `SYMBOLS`/case builders
   and re-run it. For `_RFilter_fetch`, do this first: five buffer pointers, two ints, one out
   pointer.
2. Translate statement by statement from `/tmp/opz-decomp-analoga.txt` (49 KB, regenerable with
   `tools/ghidra-scripts/DecompileTo.java`, see `PORT_METHOD.md`) — but **check every shift and
   clamp against the radare2 listing**, because the decompiler's C hid three real behaviours already:
   the record read past the table end, the sub-branch ordering in `renderSaw`, and the state-machine
   jump in `updateFilterEnvelope`.
3. Run the test; the four defects found so far were all caught within one or two runs.

## What is already known about the remaining three

* **`renderSquare`** — **ported and exact on all 144 recorded cases.** Four copies of the same
  quadrant block (the phase, `!phase`, `phase ^ 0x80000000`, `phase ^ 0x7fffffff`) combined by a
  saturating chain against a two-entry sample table selected by the phase's sign bit:
  `((samples[phase >> 31] - b0) + b1 + b2) - b3`, with `samples = [0x60000000, 0xa0000000]` taken
  from the variable at 0x124c320 (the same +/-0.75 constants `renderSaw` uses as its bias; nothing at
  0x17b2a0 is read).

* **`_RFilter_fetch`** — **ported and exact on all 50 recorded cases.** It is a two-dimensional
  interpolated fetch: `param_7`'s top nibble selects the row and carries a row fraction, `param_6`
  selects and interpolates inside a 65-entry row, and each of the five banks contributes one output
  word. Two measured facts: **rows 0..=7 only** (from 8 up the engine writes an all-zero output - a
  real branch, found by filling a 32-row bank with its own word indices), and the five outputs are one
  per bank (the fixtures now fill five *distinct* banks and record all five words). Multiplies are
  plain `(a*b) >> 31` with saturating adds, no sentinel check.

* **`_RFilter_fetch` older note** — **its fixtures already exist** (50 calls, every row, 15 distinct outcomes,
  in `tests/golden/analoga/oscillators.json` under `r_filter_fetch`, built by
  `r_filter_fetch_cases` in the generator). It indexes each of the five banks as
  `base + row * 0x104 + {0, 4}` with
  `row = param_7 >> 0x1c`, i.e. 16 rows of 65 `fract32_t` per bank (that size was the last cause of
  silence before the host was fixed). It writes its result through the last argument.
* **`render`** — 2 044 B, the last function. **Reading state** (decompilation at
  `/tmp/opz-decomp-analoga.txt`, regenerate per `PORT_METHOD.md`): read 320–400 (the gates, the
  velocity/level/host-gain chain), 505–660 (the `_RFilter_fetch` call, the oscillator loops, the
  amplitude loop and the engine's own envelope update) and 660–828 was **not** read; 400–505 is a
  fragment seen. Sections still to read: **400–505** and **660–828** (the tail: the filter calls and
  the output mix). What is already known:
  * it gates on `adsr.phase` (0 → return) and on `state + 0x29` (the kill countdown);
  * it calls `updateFilterEnvelope(state + 0x30, params[2..6])` and fetches a coefficient record from
    `presets[params[0] >> 29]` (and the record after it) at `+8`, like `onNoteOn` does;
  * the oscillator loops call `renderSaw(state+0x00, param_2)` into `g_scratchpads[0]` and
    `renderSquare(state+0x04, param_2 >> 1)` into `[1]`, with an LCG (`* 0xbb38435 + 0x3619636b`,
    seed at the `randSeed` global) into `[2]`;
  * the amplitude loop writes `g_scratchpads[3]` and updates `adsr.level` every frame
    (`level = sat(mul31(mul*level) + ((0x7fffffff - cube) * add >> 31))`);
  * after the amplitude loop it fills an output struct and calls
    `_RFilter_fetch(bank0..bank4, cutoff & mask, mode, out5)` (the cutoff comes from the same
    velocity/level/state chain, the `mode` word from `params[9]`), then mixes in a 64-sample loop:
    `pad3[i]` (the amplitude mix) is scaled by the filter output and saturating-added into `out`;
  * the tail is `out[i] += sat((gain_pair × scratchpad[3][i]) >> 31)`;
  * **the ADSR phase must be 5..7** for the voice to sustain (0 is silent, 1..4 run out after a
    block) and the host sets the filter envelope target at `state + 0x3c`.
  Checked against the 20 recorded outputs in `tests/golden/analoga/cases.json`, each of which also
  records `state_after_note_on` **and, per render call, `stages`**: the four scratchpads' peaks
  (saw, square, LCG noise, amplitude mix), the mix's first eight samples, the ADSR level the engine
  left, and the first filter taps. Verify stage by stage against those rather than only the final
  mix - that is what makes a wrong stage cheap to find. Example (`four_blocks`): pad peaks
  `[1591502648, 1610612736, 2022170538, 372018194]` then `[999089904, ...]`, ADSR level
  `0x7fffffbf -> 0x7fffff7f -> 0x7fffff3f -> 0x7ffffeff` (a slow decay toward the sustain). Its output tail (`0x12f79c..0x12f7dc`) is
  `out[i] += sat((gain_pair × scratchpad[3][i]) >> 31)`, so scratchpad[3] carries the signal. The
  ADSR phase must be 5..7 for the voice to sustain, and `render` writes `adsr.level` every frame. It
  is checked against the 20 recorded outputs in `tests/golden/analoga/cases.json`, each of which
  also records `state_after_note_on`.

## Host contract (complete; do not re-derive)

In `tools/unicorn-harness/opzso.py` → `AnalogAHost`, and explained in
`crates/opz-dsp/tests/golden/analoga/README.md`: five filter banks of 16×65 behind
`interface + 0x28`; a scratch buffer `init` carves into four 0x100-byte sub-buffers (saw, square, LCG
noise, amplitude mix — the quickest way to see how far a render got); two **128**-entry rate tables at
0x124b370/0x124b570 (the `.bss` layout fixes that size); a 16-entry `i16` octave table; coefficient
records at 0x124b7b8; five gain globals; ADSR phase 5..7; and the filter envelope target at
`state + 0x3c`, which the host must set for `render` to open the filter.

## After the port

Wire the second synth track (index 4, `analoga.engine` — the device's own default map puts a
device-only plug there, so this is a documented substitution) which completes the one unmet
acceptance criterion, then Phase 4's host chain and Phase 5's `Saw013a`.
