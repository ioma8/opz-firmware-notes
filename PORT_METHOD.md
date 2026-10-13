# Port method — how the OP-Z engines are translated and verified

Companion to `PLAN_OPZ_SOFTWARE_CLONE.md`. The code lives in a separate repository
(`~/projects/customs/opz-clone`); this file is the method record: what was done, how it is verified,
and what is still open. It is updated as ports land.

## Principle

The port is a **translation of the original code, checked against the original code**. Two things make
that possible and both are used together:

1. **Disassembly and decompilation.** `libSnakePlugin.so` (ARM64, from the companion APK, symbols
   intact) is read with radare2 and with Ghidra headless:
   `tools/ghidra-scripts/DecompileTo.java` decompiles by symbol name —
   `analyzeHeadless /tmp/ghidra-proj opzso -import <so> -scriptPath tools/ghidra-scripts -postScript DecompileTo.java "SamplePlayerGain" out.txt`.
   The decompiled C is the *reading* copy; the disassembly is the authority when they disagree.
2. **Execution of the original under Unicorn** (`tools/unicorn-harness/`). The library is mapped at its
   own virtual addresses, relocations applied, imports and PLT stubs hooked, TLS set up; host-side
   pieces are supplied in Python. Golden fixtures generated this way are committed as small binary/JSON
   pairs, so `cargo test` needs no emulator.

Nothing is "close enough": where the port and the original differ, the difference is either fixed or
written down with its measured size.

## Facts the harness established (do not re-derive)

- Engine modules are **static functions** with an opaque host state:
  `initModule(id, const ModuleCallbackInterface*, u32* out)`, `init(state, a, b, tempBuffer, d)`,
  `render(fract32_t* out, u32 frames, int track, void* state, const u32* params, ADSR*)`,
  `onNoteOn(note, velocity, state, params)`, `onNoteOff(note, state)`. `out` is **interleaved stereo**
  Q31 and `frames` is the frame count (2 samples each).
- `initModule(0, iface, out)` stores `iface` in the engine's own global; `init` stores its 5th argument
  in the global `tempBuffer` and its 3rd in `state+0x20`.
- `SamplePlayerGain` does **not** pick slices. `onNoteOn` calls `iface+0x48(id, note)` for a pointer to
  a **40-byte sample record** (`+0x00` data, `+0x08` readable frames, `+0x0c` pitch, `+0x10` rate) and
  `iface+0x08(8)` for readiness; a null result logs *"Sample should be available here."* A record length
  ≥ `0x200000` logs *"Sample too long"*. The record's frame count is the usable length of the buffer the
  slice points into — a too-small value makes the engine render silence.
- `iface+0x40` is a **host envelope hook** (`updateParametersAHD`-shaped). The harness registers a no-op
  and freezes the `ADSR` instead (`level`, `mul`, `add`, `state`), because the real implementation lives
  in the app, not the library. The port therefore treats the envelope as host input
  (`DrumEngine::set_adsr_words`).
- `render` returns immediately when `ADSR+0x10` (phase) is zero.
- Host-supplied globals with no initialiser in the library: `0x124a5c4` (release scale — **zero** in the
  fixtures, because nothing initialises it), `0x124a5cc` (mix gain, `0x7fffffff`), `0x124a7b0` (16-entry
  per-octave i16 table, `0x7fff` each).
- The device's `u8 → Q31` conversion is `(v * 0x00808080) | (v >> 1)` (constant built by
  `mov`+`movk`), verified by executing `Synth::latchParameters` for all 256 values. 255 maps to
  `0x7fffffff`.

## Verification in the clone repository

| Check | What it proves |
|---|---|
| `tools/unicorn-harness/selftest.py` | the harness runs the original correctly (256-value conversion proof + engine smoke call) |
| `tools/unicorn-harness/make_fixtures.py` | regenerates `crates/opz-dsp/tests/golden/sample_player_gain/{pack.bin,cases.json}` deterministically; exits non-zero if everything is silent |
| `note_on_state_matches_the_original` | **exact**: every state field `noteOn` computes (gains, window bounds, increment, counters) equals the original's, field for field |
| `golden_cases_match` (sample player) | **byte-exact** on all ten cases, no tolerance |
| `golden/digital/cases.json` + `tests/digital.rs` | **byte-exact** on all 35 `Digital` cases, no tolerance, with anti-vacuity assertions |
| `golden/analoga/cases.json` + `tests/analog_a.rs` | **byte-exact** on all 20 `AnalogA` voices, every block: all 128 stereo samples and each block's four scratchpad peaks, ADSR level, mix samples, filter taps and `_RFilter_fetch` arguments |
| `render_audio_integration` (`opz-core`) | the whole chain — AIFF pack → `Engine` → ported DSP → Q31 audio — produces sound |

## Engines ported so far

| Engine | Code | Verified by |
|---|---|---|
| `SamplePlayerGain` | `crates/opz-dsp/src/sample_player_gain.rs` | 10 fixtures byte-exact + exact `onNoteOn` state |
| `Digital` | `crates/opz-dsp/src/digital.rs` | 35 fixtures byte-exact |
| `AnalogA` | `crates/opz-dsp/src/analog_a.rs` | 20 end-to-end voices sample for sample, plus 50 `_RFilter_fetch` calls, 144 `(phase, increment)` pairs per oscillator, 21 `setEnvelopeState` and 36 `updateFilterEnvelope` calls |

All three were translated from the disassembly with the decompiler's C as a guide, and all three
needed the *assembly* to settle questions the C obscured: for the sample player the read loop's two
position accumulators; for `Digital` the pan matrix, `onNoteOn`'s four gain stores and the envelope
fold (Ghidra reuses variable names across reused registers); for `AnalogA` the gain-ramp shift
(`>> 6`, not the `>> 8` the C suggested), the per-frame ADSR level and the logical narrowing of the
lane multiplies. `HANDOFF_ANALOGA_PORT.md` lists all eight of those `AnalogA` behaviours.

## A method note worth keeping

Two things repeatedly cost time and are worth doing first next round:

1. **The decompiler's C is for shape, the assembly is the authority.** In `Digital`, Ghidra reused
   variable names across registers and got the loop's two gain vectors, the pan matrix and
   `onNoteOn`'s four stores wrong (or unreadable); the pan/target structure only became clear from the
   disassembly. Port from the C, then check every arithmetic step against the listing.
2. **A flat host table hides whole code paths.** The first `Digital` fixtures used a flat octave
   table, which makes every octave slope zero — the entire octave search and its clamps were
   untested and the port passed anyway. Give host tables *varying* values (and the gain globals
   distinct ones, so a case proves *which* global was read), then regenerate the fixtures.

## Open items (measured, in priority order)

1. **The read loop.** The original advances *two* position accumulators (forward and reverse) in one
   software-pipelined iteration and derives the interpolation fraction from a separate Q15 accumulator;
   the port advances one direction and recomputes the fraction from the position. Effect: 29–104 LSB of
   rounding on ordinary amplitudes (`mid_preset`, `note_started_mid_buffer`, `level_1_velocity_1`,
   `pan_right`), amplified to 2.5e7 when every parameter is at maximum because the output sits on the
   clamp.
2. **Release path after `noteOff`.** `note_off_midway` and `release_tail_4_blocks` still differ
   structurally (≈2.4e9–2.8e9 LSB); the port's phase handling for the released voice is not the
   original's.
3. **Non-zero slices.** `slice_7_note_43_pan_left` differs structurally: the port reads `state[0x18]`
   semantics as pack-relative, and adding the slice base alone does not fix it, so the window/position
   arithmetic for slices past the first needs the same read loop translated.
4. **Retrigger.** `retrigger_same_buffer` (two `noteOn` events in one buffer) differs structurally.
5. **Phase-4 host chain.** `Synth`, `InstrumentManager`, `Compressor`, and the real `ADSR` derivation
   (`updateParametersADSR` / `updateParametersAHD`) are not ported yet; the interim host in `opz-core`
   stands in for them, and the envelope is host input rather than derived.

Item 1 is what turns items 2–4 from "structurally different" into "exact": all of them live in the same
loop, which is why they are listed together as the next, and last, piece of engine fidelity.
