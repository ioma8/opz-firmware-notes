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
| `tools/unicorn-harness/make_saw013a_fixtures.py` | regenerates `crates/opz-dsp/tests/golden/saw013a/cases.json` (19 cases) deterministically, twice per case, and refuses an all-silent fixture |
| `saw013a_note_on_matches_the_original` (`opz-dsp/tests/host.rs`) | **exact**: the whole 26-word state block after `onNoteOn`, all 19 cases |
| `render_matches_every_golden_case` (`opz-dsp`) | **exact**: every one of the 128 samples of every block of all 19 cases, plus the ADSR level each call leaves |
| `render_matches_the_device` (`opz-dsp`) | one traced block's output, its two `+0x38` host calls and its exit state, against the device's register file |
| `a_saw_track_plays_through_the_ported_chain` (`opz-core`) | a track assigned `saw013a.engine` sounds through the ported mixer |

## Engines ported so far

| Engine | Code | Verified by |
|---|---|---|
| `SamplePlayerGain` | `crates/opz-dsp/src/sample_player_gain.rs` | 10 fixtures byte-exact + exact `onNoteOn` state |
| `Digital` | `crates/opz-dsp/src/digital.rs` | 35 fixtures byte-exact |
| `AnalogA` | `crates/opz-dsp/src/analog_a.rs` | 20 end-to-end voices sample for sample, plus 50 `_RFilter_fetch` calls, 144 `(phase, increment)` pairs per oscillator, 21 `setEnvelopeState` and 36 `updateFilterEnvelope` calls |
| `Saw013a` | `crates/opz-dsp/src/saw013a.rs` | 19 cases byte-exact through `render`, the exact `onNoteOn` state block, and a traced block's host calls and exit state |

All three were translated from the disassembly with the decompiler's C as a guide, and all three
needed the *assembly* to settle questions the C obscured: for the sample player the read loop's two
position accumulators; for `Digital` the pan matrix, `onNoteOn`'s four gain stores and the envelope
fold (Ghidra reuses variable names across reused registers); for `AnalogA` the gain-ramp shift
(`>> 6`, not the `>> 8` the C suggested), the per-frame ADSR level and the logical narrowing of the
lane multiplies. `HANDOFF_ANALOGA_PORT.md` lists all eight of those `AnalogA` behaviours.

`Saw013a` added a third: **a fixture that agrees on one case is not a fixture that agrees.** Its
prologue trace verified the lane machinery on `note_60`, where the fixture's parameters make it inert
(`v8 = v9 = ramp = 0`). Rendering every case block by block found four transcription bugs at once — a
32-bit add whose sum fed a 64-bit `mul`, a phase multiplier that needs `sxtw`, a `dup`'d blend scalar
that must be sign-extended into `smull`, and the wrap handler's clamp being on a 64-bit `lsl`. The
working loop was: render all cases, bisect to the first differing *frame*, then dump the device's
register file at the PCs that produce that frame. And two of the fixtures' own bugs surfaced the same
way (the gain table read at a 2-byte stride, and `render` being handed one buffer for every block, so
every block after the first was cumulative).

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

## Open items

None at the engine level. Every ported engine is byte-exact against its fixtures:

| Engine | Fixtures | State |
|---|---|---|
| `SamplePlayerGain` | 10 cases | byte-exact, no tolerance (the read loop, the release path, non-zero slices and retrigger were the last four; the per-case budgets are gone) |
| `Digital` | 35 cases | byte-exact |
| `AnalogA` | 20 voices + the 50/144/21/36 call replays | byte-exact |
| `Saw013a` | 19 cases | byte-exact, plus the exact `onNoteOn` state block and one traced block's host calls |
| the host chain (`Synth`, `InstrumentManager`, `ADSR`, `Compressor`, track filters, master bus) | 14 whole-mixer cases | byte-exact, including the master's DC-blocked mix |

The history of that sample-player work is worth keeping: the four cases that used to differ structurally
all lived in the read loop, and translating it (two position accumulators, one software-pipelined
iteration, a separate Q15 fraction accumulator) turned them exact rather than merely closer - which is
what the per-case budgets had been hiding.

## The host's mute is a `LoopHost` flag, not port behaviour

`Synth::render` has no per-track mute. The device's `+0x6d1c` byte gates only the *track filter*, and the
macro's `+0x6848` mask reaches the *pan lane*; a track that is neither nor still runs its mix-down and its
FX sends, and the app silences it by not triggering it. Measured on a muted track with a drum: the group
sums stay in the millions and only drain through the filter, the DC blocker and the compressor.

The host needs a mute that takes effect while a voice is *running* (the app's `SetMute` deliberately keeps
the note), so `LoopHost` carries `muted: [bool; MIXED_TRACKS]` and `render_tracks` drops a muted track's
mix before the DC block. The voice keeps rendering, so unmuting picks it up mid-note.

This is an extension, and it is kept out of the port's own behaviour on purpose: the whole-mixer fixture
leaves the flag all-false, so `Synth::render` compares word for word against the device as before. Putting
the same clear in the not-enabled branch made the comparison fail - which is the evidence that the device
does not do it.
