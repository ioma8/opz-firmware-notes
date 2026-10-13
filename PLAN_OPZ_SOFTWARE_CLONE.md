# Plan: OP-Z software clone in Rust (separate repo)

Status: **approved 2026-10-13; Phase 1 started.** This document is the shared understanding reached
in the scoping interview; every decision below was chosen by the user, and the facts behind them were
measured from the artifacts named in the notes repo.

## Goal

A limited-scope, playable stand-in for the OP-Z: a terminal-programmed 6-track groovebox whose
*sound engines are ports of the real ones*, taken from the ARM64 build of the vendor application
library, and whose pattern/parameter model uses the device's own units and semantics.

Out of v1 (explicitly): step components, tape/track-11 tricks, FX tracks 9–12 chains, DMX/light
track, motion track, module track, sampling/import, song/chain mode, device file compatibility,
BLE/USB device communication, MIDI in/out, pattern banks (one pattern only), p-locks, preset slots.

In v1: 6 tracks, 16 steps per track, per-track step length, one pattern, tempo, 18 named params per
track with the device glide model, sample playback for the four drum tracks, three ported engines,
one preset per track plus "load factory preset", stereo master output.

## Where the code lives

- **Separate repository**: `~/projects/customs/opz-clone` — created 2026-10-13, branch `main`, no
  remote, scaffold commit `d809bff` (`cargo check --workspace` clean).
- This worktree (`opz-firmware-notes`, branch `work`) keeps only method notes: this file and, once
  porting starts, `PORT_METHOD.md` recording how each port was done and verified.
- Never committed anywhere: `libSnakePlugin.so`, the APK, `.engine` Blackfin blobs, device dumps,
  sample packs. The derived crate carries a provenance header per file and `publish = false`.

## Cargo workspace (three crates)

| Crate | Contents | Notes |
|---|---|---|
| `opz-dsp` | Ported DSP only: `SamplePlayerGain`, `Digital`, `AnalogA`, then `ADSR`/`DcBlocker`, `InstrumentManager`, `Synth`, `Compressor`. One module per original class. | `publish = false`; per-file header naming the source mangled symbol; frozen except for porting |
| `opz-core` | Plug/preset table (from `opz-factory-plugs.json`), pattern/sequencer model, AIFF pack reader, `Engine` (audio-thread state), command queue | no UI, no audio device — testable headless |
| `opz-tui` | Binary: ratatui/crossterm tracker grid + param strip | the only frontend in v1 |

Support: `tools/unicorn-harness/` (Python, Unicorn + capstone) and `crates/opz-dsp/tests/golden/*`
(short golden bursts, tens of KB total). Dependencies: `cpal`, `ratatui`, `crossterm`, `serde_json`,
one lock-free queue (`rtrb` or `crossbeam-queue`). No async runtime, no bevy/rodio/fundsp.

## Facts the design is built on (all measured, sources named)

1. `engines-official/*.engine` are **raw Blackfin code** — not runnable on the host, and the shared
   plugin framework they call into is only in the still-encrypted OS image. Hence: no emulation of
   device blobs (notes §43–44).
2. The APK's `lib/arm64-v8a/libSnakePlugin.so` contains ARM64 implementations of the **same 25
   engines by the same class names**, symbols intact, with the device module interface
   `initModule`/`render`/`onNoteOn`/`onNoteOff`. Sizes: `SamplePlayerGain` 5 512 B, `Digital`
   2 112 B, `AnalogA` 5 872 B; host chain `Synth` 15 852 B (`Synth::render` 11 072 B),
   `InstrumentManager` 2 372 B, `Compressor` 2 152 B, `ADSR` 816 B, `DcBlocker` 68 B.
3. Engines are largely self-contained: `AnalogA` has only 9 `bl`s (3 imports: `memset`,
   `__stack_chk_fail`, one stub). Param maths is integer Q31 (`fract32_t`), so the port should be
   **sample-for-sample reproducible**, not "close".
4. **18 parameters per track**, `u8` 0…255 → `u32` by `(v * 0x80808080) | (v >> 1)`
   (`Synth::latchParameters`, loop bound `0x12`). Order: engine param 1, engine param 2, attack,
   decay, sustain, release, FX1 send, FX2 send, filter, resonance, pan, level, portamento, LFO
   depth, LFO speed, LFO target/value, LFO shape, note style
   (`refs/op-z-sysex/docs/typed-pattern-editing.md`). Three copies per track (target / latched /
   interpolated, stride `0x48`), 12 tracks' worth (`0x360`): the glide model is
   `interpolateParameters`, the snap is `forceParametersToTarget`.
5. The 58 factory presets in `opz-factory-plugs.json` carry exactly those 18-byte vectors
   (`slot`, `index`, `defaultOctave`, `values`) — factory sounds need no reverse engineering.
6. Track layout from the content-disk slot markers: tracks 1–4 = plugs 13/14/15/17 (drum plugs →
   `SamplePlayerGain`), tracks 5–8 = plugs 21/25/28/31; catalogue maps 25 → `digital.engine`,
   31 → `chord.engine`. `trackmask` bit N-1 = track N.
7. Pattern/note model (device-proven): 16 steps × 16 tracks per pattern, 8-byte note records
   (i32 duration in 6 200 units/step, MIDI note with `FF` = unused, velocity, signed microtiming
   with raw = displayed tick × 8, age). 54-byte per-step records exist for components and p-locks —
   **not ported in v1**.
8. Pack format: AIFF `FORM`/`COMM`/`SSND` with an `APPL` chunk whose payload is `op-1` + JSON
   (`type`, `name`, `octave`, `start`/`end`/`pitch`/`playmode`/`reverse`/`volume` × 24,
   `dyna_env[8]`, `fx_*`, `lfo_*`). The offsets are not frame indices; they are proportional to
   frame position, so `frame = value × total_frames / last_end`. Genuine packs:
   `~/.opz-decode/te-assets/samples/redmount{Kicks,Snares,Perc,FX}.aif`; substitutes: 19 files in
   the main worktree. The device itself reads packs through bundled libaiff — we will not port it.
9. `Synth::render` is reached through a table, not a direct call (address stored at file offset
   `0x28e0`), and the library contains **no audio driver** — the host owns the loop.

## v1 track line-up

| Track | Engine | Port | Default pack |
|---|---|---|---|
| 1 | `sampleplayergain.engine` | `SamplePlayerGain` | `TeKicks.aif` |
| 2 | `sampleplayergain.engine` | (same port) | `TeSnares.aif` |
| 3 | `sampleplayergain.engine` | (same port) | `TePercs.aif` |
| 4 | `sampleplayergain.engine` | (same port) | `TeFX.aif` |
| 5 | `analoga.engine` | `AnalogA` | — |
| 6 | `digital.engine` | `Digital` | — |

Port queue after v1: `Saw013a` → `Volt` → `Electric` → `Fm003b` → `Organ` → `EP`.

## Realtime architecture

One `cpal` output stream at 44.1 kHz; the audio callback advances the sequencer by frames, applies
parameter glide, calls the ported `Synth::render` (with `ADSR`/`InstrumentManager`/`Compressor`),
then converts Q31 `i32` → output format once at the boundary. The two extra buffers `Synth::render`
takes stay zeroed in v1 (they are the FX-track paths, and v1 has no FX tracks). The `Engine` struct
is owned by the audio thread; the TUI only sends commands through a lock-free queue — no mutex in
the callback, and offline tests drive the same `Engine` without a sound card. A `render-to-wav`
diagnostic mode falls out of that for free.

## Verification

1. Build the Unicorn harness first (`tools/unicorn-harness/`): map the `.so` at its own vaddrs, set
   up TLS (`tpidr_el0`, seen in `AnalogA::render`), hook PLT imports (`memset`, `__stack_chk_fail`,
   unresolved stubs), call `render`/`onNoteOn`/`onNoteOff`, capture output buffers.
2. **Prove the harness before porting**: reproduce `(v * 0x80808080) | (v >> 1)` for all 256 values
   through emulation, and diff a known-packed slice boundary against its source WAV.
3. Golden vectors per port: parameter sweeps (factory preset vectors and edge values), note on/off,
   several sample counts, `fract32` and silent inputs. Rust must match **byte-for-byte**.
4. Where Unicorn cannot reach a slice (heap/constructors in `Synth`), fall back to invariants —
   silence→silence, envelope timing against `updateParametersADSR`, non-degenerate output, no
   clipping — and **say so loudly** in `PORT_METHOD.md` rather than downgrading silently.
5. Real-device audio recording is explicitly not part of this plan.

## Development phases

Rules that apply to every phase:

- A phase is **done only when its playable check passes** — the app runs, makes sound, and does the
  new thing from the keyboard. Tests alone do not end a phase.
- A phase is not started until the previous phase's playable check passes.
- Any engine port added in a phase must have its golden vectors passing *before* it is wired into
  the live `Engine`, never after.
- Anything cut from a phase moves to a named later phase or to “after v1”; it does not silently
  disappear.

### Phase 1 — Drum machine (foundation, harness, first engine)

Status 2026-10-13: **the drum machine plays.** `cargo test --workspace` is green (41 tests) with the
port, the harness and the fixtures in place. What is *not* finished is engine fidelity: four fixture
cases still differ structurally and the interpolator rounds differently — the measured list is in
[PORT_METHOD.md](PORT_METHOD.md) → "Open items", and the port's own test encodes each budget with its
reason.

Goal: a working 4-track drum groovebox built on a ported OP-Z engine.

- [x] Workspace + crates + `.gitignore` + `opz-dsp` provenance README (scaffold commit `d809bff`).
- [x] `tools/unicorn-harness/`: loader (ELF segments, relocations, stub page, TLS, write-prot
      promotion), `selftest.py`, `spg.py` (host scaffolding + field documentation),
      `probe_callbacks.py`, `make_fixtures.py`.
- [x] Harness self-test passes: the original `Synth::latchParameters` converts all 256 byte values as
      `(v * 0x00808080) | (v >> 1)` — which also fixed `params.rs` (the constant was wrong).
- [x] Host interface established by measurement: `interface+0x48` returns a **40-byte sample record**
      (`+0x00` data, `+0x08` frames, `+0x0c` pitch, `+0x10` rate), `+0x08` readiness, `+0x40` the
      envelope hook; host globals `0x124a5cc` and `0x124a7b0`; `render` bails unless `ADSR+0x10` is
      non-zero; the engine never selects slices itself.
- [x] Golden fixtures generated from the original engine (10 cases, 8 non-silent, reproducible).
- [x] Port of `SamplePlayerGain` in Rust (≈1 500 lines, no `todo!()`); host-side constants, descriptor
      contract and envelope defaults aligned with the fixtures. `note_on`'s output is verified **exactly**
      against the original, field for field (`note_on_state_matches_the_original`).
- [x] `opz-core`: AIFF pack reader, plug/preset tables with generator (`tools/gen-plugs.py`),
      pattern/note model in device units, transport, interim host `Engine`, command mirroring.
- [x] `opz-tui`: ratatui grid, cpal output, key map (`docs/KEYS.md`), pack loading from
      `samplepacks/` (`tools/setup-packs.sh`).
- [x] **Audio verified end to end offline**: `render_audio_integration` drives an AIFF pack through the
      `Engine` and the ported engine and produces Q31 audio; the empty-pattern, short-note, loop-length
      and truncation properties hold.
- [ ] **Open:** engine fidelity, in the order listed in [PORT_METHOD.md](PORT_METHOD.md): the original's
      read loop (two position accumulators), the release path, non-zero slices, retrigger. Budgets are
      in the port's golden test with the measured deviation for each case.
- [ ] **Unverified by a human:** nobody has listened to `cargo run -p opz-tui` yet. Everything above is
      offline evidence; the interactive check is still owed.

**Playable check:** `cargo run -p opz-tui`, programme a beat on tracks 1–4 (each with its own pack),
press play, hear four distinct drum sounds in time; tempo changes take effect live.
*Offline half verified (audio reaches the output buffer); the listening half needs a person at a
terminal.*

**Not in this phase:** synth notes, the 18-param UI, the ported host chain, glide.

### Phase 2 — First synth voice, and the parameter UI

Goal: the same app plus one real synth engine you can play from the terminal keyboard.

- [ ] Port `Digital` (2 112 B), golden vectors passing, and extract its param-index map from the
      disassembly.
- [ ] Track 5 (`digital.engine`) wired in; notes playable from the TUI keyboard, lengths/velocities
      from the pattern rather than key-hold.
- [ ] The 18 named params per track, with the device's `u8 → Q31` conversion, and parameter glide in
      the interim host (target → current interpolation, same shape as the ported version).
- [ ] Preset loading: factory `values` vectors from `opz-factory-plugs.json` per track.
- [ ] Note entry in the TUI: enter/record a step’s note, duration (6 200/step units), microtiming
      (tick × 8), per-track step length 1–16.

**Playable check:** programme a drum beat and a synth line, play both together, and sweep the
synth’s params live while it runs.

### Phase 3 — Second synth, per-engine parameter knowledge

Goal: two synths, and param UI that only shows what each engine actually reads.

- [ ] Port `AnalogA` (5 872 B), golden vectors passing, param-index map extracted.
- [ ] Track 6 (`analoga.engine`) wired in; both synth engines get their own named param pages and
      ranges, `p1…p18` fallback elsewhere.
- [ ] Mute per track; master level; per-track octave from presets.
- [ ] Per-engine parameter mutation tests (change one byte, diff output against the emulator) to
      confirm the extracted maps.

**Playable check:** a six-track groove — four drum tracks plus two distinct synths — programmed and
played entirely from the TUI, with per-engine param pages behaving differently where the engines
differ.

### Phase 4 — Replace the interim host with the ported chain

Goal: the app sounds and behaves like the device’s own voice path, not our approximation.

- [ ] Port `ADSR` + `updateParametersADSR`/`AHD` + `DcBlocker`, golden vectors passing.
- [ ] Port `InstrumentManager` — voice start/end indices, overload handling, vibrato/pitch bend.
- [ ] Port `Synth` (`Synth::render` 11 072 B and the latch/target/interpolate/LFO paths); the two
      extra output buffers stay zeroed (no FX tracks in v1).
- [ ] Port `Compressor` + `masterCompressor` for the master bus.
- [ ] Delete the interim host; the `Engine` now calls the ported chain. Where Unicorn cannot reach a
      slice, invariants stand in and are recorded in `PORT_METHOD.md`.
- [ ] Check realtime safety (no `malloc`/`new` in the callback) from the Unicorn traces; pre-warm if
      anything allocates.

**Playable check:** the six-track groove from Phase 3 plays through the ported chain, audibly
better-behaved at the edges (param glide, voice stealing on rapid re-triggering, master compression),
with the offline render byte-identical to the Phase 3 output for the same preset vectors and events.

### Phase 5 — Fidelity pass, method notes, and the repeatable pipeline

Goal: v1 closed out against the acceptance criteria, with the port process documented and proven
repeatable on a fresh engine.

- [ ] `render-to-wav` diagnostic mode (same `Engine`, no sound card) and a short A/B script.
- [ ] Port `Saw013a` as the first post-v1 engine to prove the pipeline is mechanical, not bespoke.
- [ ] `PORT_METHOD.md` in this worktree: per-port source symbols, harness results, every
      invariant-instead-of-golden case, and the open unknowns that remain.
- [ ] `README.md` in the clone repo: setup, keys, what v1 is and is not.
- [ ] Walk the acceptance criteria below one by one and record the result; only then plan the next
      engine batch (`Volt`, `Electric`, `Fm003b`, `Organ`, `EP`) or a v2 feature (p-locks, step
      components, FX tracks, pattern banks, chain mode).

**Playable check:** a fresh clone of the repo, setup command, `cargo run -p opz-tui`, six tracks,
`Saw013a` available on a track, and the whole thing still playing after the host swap.

## Acceptance criteria

- `cargo test` passes with no Unicorn dependency at test time (golden fixtures are committed files).
- Cloning the repo, running the setup command, and `cargo run -p opz-tui` produces sound on four
  drum tracks and two synth tracks from keyboard input alone.
- The four drum tracks load the named packs and their slices map the way the ported
  `SamplePlayerGain` says they do, not the way we guessed.
- Every ported function is either golden-verified or has an explicit, recorded reason why not.
- No device interaction of any kind: no console commands, no USB/BLE, no firmware, no cubes.

## Boundaries

- No touching, flashing, resetting or otherwise instructing the OP-Z. `0x15` (NAND format) remains
  forbidden in every context, including toy scripts.
- No committing firmware, APK, `.so`, `.engine` blobs, raw device captures, or sample packs.
- `opz-dsp` is never published, and the extraction inputs stay outside git.
- If the relay/oracle work in the main worktree is resumed, it is a different task with its own
  plan (`PLAN_OPZ_BOOTLOADER_ORACLE_AUTOCYCLE.md`).

## Open unknowns (to be resolved during the port, not by guessing)

| Unknown | How it gets resolved |
|---|---|
| What the four `Synth::render` buffers are exactly | Harness call with distinguishable inputs |
| Which of the 18 params each engine reads | Disassembly of the ported `render`, then one-byte mutation diffs |
| Where the per-track filter lives (`TrackFilter` has no own symbols) | Locate `trackFilterProcess` callers during the `Synth` port |
| Whether `Synth`/`InstrumentManager` are realtime-safe (allocation) | Unicorn trace for `malloc`/`new` hits |
| Whether `dyna_env`/`playmode`/`reverse`/`volume` are consumed by the engine | Disassembly + mutation |
| The true time unit of the `APPL` slice offsets | Not needed for v1; normalisation by `last_end` is used and marked `shortcut:` |
| Device-default note/slice mapping for drum tracks | `SamplePlayerGain` disassembly + preset `octave` |
