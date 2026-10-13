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

* **`renderSquare`** — its function-static `samples` (the one needing `__cxa_guard_*`) is set to
  `DAT_0017b2a0`, but only the *pointer value* matters (see the measurement below). **Settled by
  measurement — the term is not a table lookup.** Setting the bytes at
  0x17b2a0 to all-`0x11111111` and then to all-`0x99999999` and calling the original with seven
  phases gives **byte-identical results**, and a read hook over that region records zero reads. What
  the C shows as `samples[phase >> 31]` is therefore reading the two 32-bit halves of the `samples`
  variable itself (Ghidra's `PTR_x` means `&x`) — an *address-derived* term, not file data. So the
  port cannot hard-code it: the fixtures must record the two words the engine used (the harness's
  pointer halves) and the port takes them as host input, the way it takes the wavetable and octave
  table. **One measurement does not fit that story yet:** reading the `samples` symbol's two words
  after a call gives `0x60000000` and `0xa0000000` — not a pointer — so either the harness resolves a
  different address for the variable than Ghidra's `PTR_samples_002d6088`, or the term is something
  else again. Settle it by hooking *reads* of the `samples` symbol's address during one call and
  watching which offset is fetched; do that before implementing the tail rather than trusting either
  reading. (Two wrong guesses about this term have already been recorded and corrected here.) Its first half repeats `renderSaw`'s four
  quadrant blocks verbatim, so `ratio`, `sine_cubed` and `quadrant` in `analog_a.rs` apply as they
  are; the tail then combines its four terms as a chain of *saturating* add/sub:
  `((samples[phase >> 31] - v5) + v6 + v7) - v9`. Verify against the 144 `render_square` cases
  already in `tests/golden/analoga/oscillators.json` (its `renderSaw` sibling needed exactly one
  fixture-caught fix, an ordering of the two sub-branches).
* **`_RFilter_fetch`** — **its fixtures already exist** (50 calls, every row, 15 distinct outcomes,
  in `tests/golden/analoga/oscillators.json` under `r_filter_fetch`, built by
  `r_filter_fetch_cases` in the generator). It indexes each of the five banks as
  `base + row * 0x104 + {0, 4}` with
  `row = param_7 >> 0x1c`, i.e. 16 rows of 65 `fract32_t` per bank (that size was the last cause of
  silence before the host was fixed). It writes its result through the last argument.
* **`render`** — 2 044 B. Its output tail (`0x12f79c..0x12f7dc`) is
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
