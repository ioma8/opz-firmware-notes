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

* **`renderSquare`** — **settled by measurement, and it is simplest of all.** A read hook shows the
  function fetching 4 bytes at `0x124c320` (at `0x12fb3c`), whose contents are **`0x60000000` and
  `0xa0000000`**: a *two-entry* table selected by the phase's sign bit (`samples[phase >> 31]`). That
  is why changing the bytes at `0x17b2a0` changed nothing — the `0x17b2a0` address is what the GOT slot
  is pointed at during the lazy init, but the function never reads it. So the port needs a two-entry
  `[0x60000000, 0xa0000000]` table (the same ±0.75 constants `renderSaw` uses as its bias) and no
  host input at all. The tail combines it as
  `((samples[phase >> 31] − v5) + v6 + v7) − v9`, saturating. Its first half repeats `renderSaw`'s four
  quadrant blocks verbatim, so `ratio`, `sine_cubed` and `quadrant` in `analog_a.rs` apply as they are.
  Verify against the 144 `render_square` cases
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
