# Handoff: `AnalogA` — port complete and exact

Written at the end of the session that finished it. Everything below is verified state, not a plan.
The clone repository is `~/projects/customs/opz-clone`; `TESTED` means a command was run.

## Where the port stands

`crates/opz-dsp/src/analog_a.rs` plus `crates/opz-dsp/tests/analog_a.rs`. **All ten functions are
translated and verified**, and the engine is wired into `opz-core`'s `Engine` on track 5 (1-based),
the track the device's own slot configuration gives `analoga.engine`.

| Function | Bytes | Verified by |
|---|---|---|
| `initModule` | 32 | host-gain variant mapping |
| `init` | 92 | variant → global, scratch guard |
| `onNoteOn` | 600 | every state field × all 20 cases |
| `onNoteOff` | 8 | returns its argument |
| `renderSaw` | 628 | 144 recorded `(phase, increment)` pairs |
| `renderSquare` | 1 388 | 144 recorded `(phase, increment)` pairs |
| `setEnvelopeState` | 76 | 21 recorded calls |
| `updateFilterEnvelope` | 292 | 36 recorded calls |
| `_RFilter_fetch` | 712 | 50 recorded calls, five distinct banks |
| `render` | 2 044 | all 20 recorded voices, every block, every sample |

`render`'s test (`render_matches_the_recorded_output`, TESTED) checks per block: all 128 interleaved
stereo samples, all four scratchpad peaks, the ADSR level the engine left, the mix's first eight
samples, the filter banks against the recorded taps, and the two `_RFilter_fetch` arguments.

## The loop that works

1. If the function is pure, record fixtures by calling the original symbol directly under Unicorn —
   that is how `renderSaw`, `renderSquare`, `setEnvelopeState` and `updateFilterEnvelope` each took
   one pass. Generators: `tools/unicorn-harness/make_oscillator_fixtures.py` (oscillators, the two
   envelopes, `_RFilter_fetch`) and `make_analoga_fixtures.py` (the 20 end-to-end voices).
2. For a big function, record **stage-level** ground truth first. `render` is 2 KB of interlocking
   loops; the fixture's per-block scratchpad peaks, mix samples, ADSR level, filter taps and filter
   arguments are what localise a wrong stage to one loop.
3. Translate statement by statement from the radare2/objdump listing, not from the decompiler's C,
   and re-check every shift, clamp and narrowing. Run the test; iterate.
4. `tools/unicorn-harness/param_mutation.py` settles which parameters an engine reads (evidence in
   `crates/opz-dsp/tests/golden/param_map.json`, cross-checked by a Rust test).

## Behaviours the decompiler's C hid (each is pinned by a fixture)

* **The coefficient record is read past the end of the table.** `onNoteOn` takes
  `presets[params[0] >> 29]` and the record *after* it with no bound check, so a parameter selecting
  record 7 reads a ninth record past the eight the host fills and gets zeros. Clamping it changes the
  output (measured: `coeff_1` 52 428 799 → 209 715 199), so the port reads zeros.
* **`renderSaw`'s sub-branch order.** Within each half the first sub-branch (`phase < increment`)
  applies the cubic and the second (`phase < 2 * increment`) only the sine term.
* **`updateFilterEnvelope`'s state-machine jump.** States other than 1/2/3 jump straight to the rate
  store (`LAB_ec60`, writing only `+4`) and leave the rest of the envelope alone.
* **`render`'s gain ramps step by `>> 6`, not `>> 8`,** and the amplitude pair is the freshly
  interpolated third preset coefficient, not the record `onNoteOn` stored.
* **`render` scales each frame by the ADSR level that frame *starts* with.** The original reuses the
  register its own envelope update overwrites, so the level walks down inside the amplitude loop
  (`0x7fffffff`, `0x7ffffffe`, …). Using a block-constant level is off by 1–3 LSB and grows.
* **The lane multiplies narrow with a *logical* shift** (`lsr` / `shrn`) throughout `render`; only the
  ADSR update and `onNoteOn` use an arithmetic one. For the products that occur this usually agrees,
  but not near ±2⁶².
* **`renderSquare`'s samples table** is a two-entry literal at 0x124c320 holding `0x60000000` and
  `0xa0000000`, read as `samples[phase >> 31]`; nothing at 0x17b2a0 is ever consumed.
* **`_RFilter_fetch` reaches rows 0..7 only** — from 8 up it writes an all-zero output (a branch in
  the engine, not a short bank) — and each of the five banks contributes one output word.

## Host contract (complete; do not re-derive)

In `tools/unicorn-harness/opzso.py` → `AnalogAHost`, and explained in
`crates/opz-dsp/tests/golden/analoga/README.md`:

* five filter banks of 16×65 `fract32_t` behind `interface + 0x28`;
* a scratch buffer `init` carves into four 0x100-byte sub-buffers (saw, square, LCG noise, amplitude
  mix — watching them is the quickest way to see how far a render got);
* two **128**-entry rate tables at 0x124b370/0x124b570, a 16-entry `i16` octave table, eight
  three-`i32` coefficient records at 0x124b7b8, five gain globals;
* the ADSR must be armed in **phase 5..7** to sustain, and the filter envelope's target
  (`state + 0x3c`) has to be set on note-on or `render` holds the voice in its attack branch.

The device's own values for all of that are app data and are not in the library; the clone supplies
documented stand-ins (a Q31 sine per filter row, a quadratic rate curve, a flat/hermite octave table)
and says so where it uses them.

## What is left

Nothing for this engine. The two remaining plan items are outside it: Phase 4 (replace the interim
host with the ported `ADSR` → `InstrumentManager` → `Synth` → `Compressor` chain) and Phase 5's
`Saw013a` port.
