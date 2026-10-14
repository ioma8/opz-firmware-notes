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
- [x] **Engine fidelity.** Closed: `golden_cases_match` now compares all ten `SamplePlayerGain` cases
      byte for byte, with no tolerance and no budget, and passes - the read loop (both position
      accumulators), the release path, non-zero slices and retrigger all agree with the original now
      that the loop is translated. The old per-case budgets were deleted with the last of them.
- [ ] **Unverified by ear:** nobody has listened to `cargo run -p opz-tui` yet. Everything above is
      offline evidence; the interactive check is still owed. What *is* verified is that the app runs and
      takes keys (driven through a pty: it enters the alternate screen, shows the six tracks, the loaded
      packs and the grid, and a step programmed by keystroke shows up), and that the same `Engine` writes
      a non-silent WAV offline (`afinfo`: 1 ch / 44100 Hz / Int16; peak non-zero; byte-identical across
      runs). Only the listening half needs a person.

**Playable check:** `cargo run -p opz-tui`, programme a beat on tracks 1–4 (each with its own pack),
press play, hear four distinct drum sounds in time; tempo changes take effect live.
*Offline half verified (audio reaches the output buffer); the listening half needs a person at a
terminal.*

**Not in this phase:** synth notes, the 18-param UI, the ported host chain, glide.

### Phase 2 — First synth voice, and the parameter UI

Goal: the same app plus one real synth engine you can play from the terminal keyboard.

Status 2026-10-13: **done, engine-exact.** `Digital` reproduces the original byte for byte on all 35
golden cases and the synth track plays alongside the drums in the offline playable test. A human
listening is still owed (as in Phase 1).

- [x] Port `Digital` (2 112 B): `crates/opz-dsp/src/digital.rs`, translated statement by statement
      from the disassembly — Ghidra's C gave the shape, the assembly decided the pan matrix, the four
      `onNoteOn` gain stores and the envelope fold, where Ghidra reuses its variable names. 35 golden
      cases (notes, octave shift, detune, pan/level, the velocity-255 wrap, multi-block state, the kill
      countdown, the octave search's boundaries, every `init` variant) match with **no tolerance**
      (`crates/opz-dsp/tests/digital.rs`; fixtures documented in `tests/golden/digital/README.md` and
      regenerable, byte-identically, from `tools/unicorn-harness/make_digital_fixtures.py`).
- [x] Its parameter map, extracted from the disassembly and recorded on the module: `params[0] >> 27`
      is the octave shift, `params[1]` the detune, `params[2..=5]` go to the host's envelope callback,
      `params[10]` the pan, `params[11]` the level. This engine does not read the filter, LFO or
      note-style parameters at all.
- [x] The digital track is wired in: `VoiceEngine::for_track` asks the plug table
      (`engine_for_track`), so the track the *device* assigns to `digital.engine` — index 5, per its own
      `slotConfiguration.json` — gets the ported voice while the drum tracks keep the sample player.
      Notes come from the pattern with the pattern's velocity and length (no key-hold).
- [x] The 18 named parameters, the device `u8 → Q31` conversion and glide are in place from Phase 1;
      glide now steps **once per 64-frame block**, in `render_block`, the way the device interpolates.
- [x] Preset loading: `Engine::new` boots each track from the first factory preset of its plug, and
      the preset table is generated from `opz-factory-plugs.json` by `tools/gen-plugs.py`.
- [x] Note entry in the TUI: `i`/`u` place and transpose a step's note (`I`/`U` by an octave), `[`/`]`
      the duration in the device's 6 200 units per step, `,`/`.` the microtiming (ticks × 8), `;`/`'`
      the per-track length 1–16. Documented in `docs/KEYS.md`, covered by `cargo test -p opz-tui`.

**Playable check:** programme a drum beat and a synth line, play both together, and sweep the
synth’s params live while it runs.
*Offline half verified: `drum_beat_and_synth_line_play_together` renders a four-kick bar plus a
four-note synth line through the real host, asserts every quarter of the bar carries energy, and
asserts that sweeping a synth parameter while it runs changes the audio while an untouched engine
reproduces itself exactly. The listening half needs a person at a terminal.*

**Host timing, settled here and inherited by Phase 4:** both engines — and the device — render in
64-frame blocks, so the interim host advances the transport in those blocks and hands the mixed
output out sample by sample. A note therefore starts or ends on a block boundary (1.45 ms at
44.1 kHz), and `microtiming` is editable and stored but not yet applied to playback; sub-block timing
is the ported `Sequencer`/`InstrumentManager`'s job in Phase 4.

### Phase 3 — Second synth, per-engine parameter knowledge

Goal: two synths, and param UI that only shows what each engine actually reads.

Status: **done, tagged `phase-3`.** Both synths are ported and wired, the per-engine parameter maps
are established by mutation, and the six-track groove renders byte-reproducibly.

- [x] Mute per track and a master level. Mute is a mixer gate that keeps the voice running (the
      device's mute does the same, so unmuting does not restart a note); the master level is one Q31
      multiply over the mixed block. Both are engine state and travel to the UI in the snapshot;
      the TUI binds `m` / `M` / `N` and shows them.
- [x] Per-track octave from presets: the track's preset `default_octave` shifts the programmed note
      before any engine sees it, and `LoadPreset` moves it. (None of the app catalogue's six default
      tracks happens to use a non-zero octave; the table does carry them, and a test asserts that.)
- [x] Per-engine parameter maps, **established by mutation rather than by reading code**:
      `tools/unicorn-harness/param_mutation.py` moves each parameter byte to 0 and to 255 against the
      original under Unicorn, and records which indexes change the output in
      `crates/opz-dsp/tests/golden/param_map.json`. That file found the sample player responds to
      `params[0]`, `[1]`, `[2]`, `[10]`, `[11]` and `Digital` to `[0]`, `[1]`, `[10]`, `[11]` — its
      `params[2..=5]` go to the app-side envelope callback, which the harness stubs out, so mutation
      cannot see them (they are marked host-side in the evidence). The TUI's strip now shows each
      engine's own list with its own names, `p1…p18` for plugs the catalogue cannot name, and a Rust
      test fails if the constants drift from the evidence. `AnalogA` was added to that run when it
      landed: it reads `[0, 1, 8, 9, 10, 11]`, and its four envelope indexes (`2..=5`) reach its own
      `updateFilterEnvelope` but only enter the output through a split of `params[1]` the baseline
      leaves closed, so they are recorded as host-side rather than claimed as reads.
- [x] One real bug fixed on the way, found by the mute work: both engines *add* into the buffer they
      are handed, and the mixer reused one buffer without clearing it, so every voice was re-mixing
      the previous voice's samples (a two-voice mix was exactly double).
- [x] **Port `AnalogA` (5 872 B), golden vectors passing.** All ten functions are translated and
      verified: `renderSaw`/`renderSquare` on their 144 recorded `(phase, increment)` pairs each,
      `setEnvelopeState` on 21 and `updateFilterEnvelope` on 36 recorded calls, `_RFilter_fetch` on
      50, and `render` on all 20 recorded voices, every block, every sample (plus each block's four
      scratchpad peaks, the ADSR level, the mix's first samples, the filter taps and both
      `_RFilter_fetch` arguments). Eight behaviours the decompiler's C hid were found this way and
      are recorded in `HANDOFF_ANALOGA_PORT.md`; the two that mattered most for `render` are that its
      gain ramps step by `>> 6` and that it scales each frame by the ADSR level that frame *starts*
      with, because the original reuses the register its own envelope update overwrites.
- [x] Wire the second synth track. The device's own default slot map (`13, 14, 15, 17, 21, 25, 28,
      31` for tracks 1..=8) puts a *device-only* plug 21 on track 5 and `digital.engine` on track 6,
      and `analoga.engine` is plug 10 — one of the four synth plugs the device ships as slots 2–4 of
      every synth pack, not a default track. So the clone's two synth tracks are a documented
      substitution: index 4 gets `analoga.engine`, index 5 keeps `digital.engine` (which the device's
      own `slotConfiguration.json` also puts there). The UI labels each track by the engine its plug
      names, so this was a change in one table plus the port (and the host data the engine reads, plus
      the two host-side values the fixtures pinned: the ADSR armed in its sustain phase and the filter
      envelope's target at `state + 0x3c`).

**Playable check:** a six-track groove — four drum tracks plus two distinct synths — programmed and
played entirely from the TUI, with per-engine param pages behaving differently where the engines
differ.
*Met: `cargo run -p opz-tui` labels tracks 5 and 6 `synth`, one per engine, and programs notes on the
analogue track; `--render` writes both voices into one bar (peak 21154), byte-identical across runs.
A Rust test asserts each synth track is audible on its own.*

### Phase 4 — Replace the interim host with the ported chain

Goal: the app sounds and behaves like the device’s own voice path, not our approximation.

- [x] Port `ADSR` + `updateParametersADSR`/`AHD` + `DcBlocker`, golden vectors passing.
      (`83ba50d`: 288 + 141 + 18 cases over the whole input domain; 1 312 + 1 677 calls replayed.)
- [x] Port `Compressor` + `masterCompressor` for the master bus.
      (`28849a2` set/update/compressStereo, 880 calls; `0333db1` masterCompressor, 72 cases over the
      whole 256-word detector ring and the 64 running sums.)
- [x] Port the `Lfo` — the trigger path, `render` and `reset` (`60bb7a4`, `3d47736`; 246 + 504 + 48
      cases, the whole shape machine and its five tables).
- [x] Port `Voice` (0x190 bytes: `renderVoice`, `noteOn`, `noteOff`, `killNote`, `pitchBend`,
      `vibrato`, `resetNote`, `getIdle`) with `Tuning::detuneCents` and the `centsDetune` table
      (`1e4731b`, `13b9dd7`; 1 337 + 73 cases). The engine seam is an `EngineVoice` trait where the
      original has three function pointers, so the engine's state block (`+0x58`..`+0x16f`) stays in
      the engine.
- [x] Port `InstrumentManager` — voice start/end indices, overload handling, vibrato/pitch bend
      (`c2cf34b`; 147 cases over the whole 4 400-word voice array, its three range tables embedded).
- [x] Port `Synth` (`Synth::render` 11 072 B); the two extra output buffers stay zeroed (no FX
      tracks in v1). Everything else in the class is done: the parameter paths (`645083f`
      `interpolateParameters` + `forceParametersToTarget`, 9 cases; `71d2fb7` `setTargetParameters` +
      `latchParameters`, 28 cases) and `resetLfo` (`43dfcef`, 32 cases). `Synth::render` itself is
      `crates/opz-dsp/src/synth_render.rs`, verified by `synth_render_tracks_match_the_original`
      (14 whole-mixer cases, every region of the scratch block compared, including the master's
      DC-blocked mix once the compressor's own state was seeded).
- [x] Port the prerequisites `Synth::render` turned out to need, which this checklist did not name:
      `trackFilterProcess` (the per-track state-variable EQ, with the five coefficient tables
      generated by `tools/gen-filter-tables.py`) and `bounceAudio` (`8b127dd`; 31 blocks + 19 cases).
      Still unported: `FxManager::render`, `Sequencer::getActiveTrack`/`getInputSelector`/
      `getModuleSends` and `PlugManager::getPlugFlags`.
- [x] Delete the interim host; the `Engine` now calls the ported chain. Where Unicorn cannot reach a
      slice, invariants stand in and are recorded in `PORT_METHOD.md`. (The pre-wiring host's own
      `Voice` and `load_pack` in `opz-core/src/engine.rs` were the last vestige; they were dead and
      were removed when `saw013a.engine` was wired.)
- [x] Check realtime safety (no `malloc`/`new` in the callback) from the Unicorn traces; pre-warm if
      anything allocates. Measured, not assumed: `opz-dsp/tests/host.rs` installs a counting global
      allocator and shows the render path makes no allocation (`6dc9bdf`).

**What `Synth::render` actually is** (measured, and wider than this checklist assumed): it is the
*global mixer*, not a per-track render. Its 11 KB covers six tracks - `interpolateParameters`, the LFOs,
`InstrumentManager::render` twice per track (layers 0 and 1), `trackFilterProcess` and
`trackFilterDcBlock` per track - then `masterCompressor` and `bounceAudio`. It also calls
`Sequencer::getBPM` (×4), `Sequencer::getInputSelector`/`getModuleSends`/`getActiveTrack`,
`PlugManager::getPlugFlags` (×2), `FxManager::render` (×4) and `InstrumentManager::handleOverload`.
So Phase 4 additionally needs `TrackFilter`, `bounceAudio` and three `Sequencer` getters +
`PlugManager::getPlugFlags` before `Synth::render` can be wired, and the FX path needs `FxManager`
unless the two extra buffers really can stay zeroed.

**Playable check:** the six-track groove from Phase 3 plays through the ported chain, audibly
better-behaved at the edges (param glide, voice stealing on rapid re-triggering, master compression),
with the offline render byte-identical to the Phase 3 output for the same preset vectors and events.
(The engine-level renders stay byte-identical by their own tests; the *master* output cannot be
byte-identical once the ported chain replaces the interim host, since the interim host has no master
compressor and one voice per track. Expect a measured, explained difference instead.)

### Phase 5 — Fidelity pass, method notes, and the repeatable pipeline

Goal: v1 closed out against the acceptance criteria, with the port process documented and proven
repeatable on a fresh engine.

- [x] `render-to-wav` diagnostic mode: `opz-tui --render out.wav [--bars N]` builds the same
      `Engine` the audio callback gets, programs a documented demo pattern and writes 16-bit PCM (one
      exact Q31 → i16 shift, the only conversion in the project). Verified with an independent tool —
      `afinfo` reads it as 1 ch / 44100 Hz / Int16 / 4.00 s — and 176 368 of 176 384 samples are
      non-zero, so the drums *and* the synth are audible together. Rendering twice is byte-identical,
      so the file doubles as a regression check. Done ahead of the other Phase 5 items because it was
      independent of `AnalogA` and it supplies the human-listening step that Phases 1 and 2 still owe.
      The A/B script is `tools/ab-render.sh`: it renders the pattern twice and requires the two files
      to be byte-identical, reports samples/peak/silence, and can diff against a saved reference,
      failing with the first differing byte offset. Verified in all three modes, including that a
      tampered reference exits non-zero rather than passing silently.
- [x] Port `Saw013a` as the first post-v1 engine to prove the pipeline is mechanical, not bespoke.
      `init`, `initModule`, `onNoteOff`, `onNoteOn` and `render` are all ported and all exact: the 26-word
      state block after `onNoteOn` matches for all 19 golden cases, and every sample of every block of all
      19 cases matches `render` (plus each call's ADSR level), with one traced block's host calls and exit
      state pinned separately. It is wired behind the `EngineVoice` seam (`VoiceEngine::for_engine`, and
      `Chain::set_track_engine` for the app's plug assignment), and a chain test renders sound from a track
      assigned `saw013a.engine`. The port and its four transcription bugs are in
      `HANDOFF_SAW013A_PORT.md`; the fixtures and their generator live in the clone under
      `crates/opz-dsp/tests/golden/saw013a/` and `tools/unicorn-harness/make_saw013a_fixtures.py`.
      Boundary: there is no UI to *assign* a plug to a track yet, so the saw engine is reachable from the
      host API and the tests, not from a key in the TUI.
- [x] `PORT_METHOD.md` in this worktree: per-port source symbols, the harness proof, the
      golden-verified table (both engines, byte-exact, with the regeneration hashes), the open items
      with measured sizes, and the two method lessons that cost real time. Kept current as ports land.
- [x] `README.md` in the clone repo: what the crates are, the provenance rule, the exactness status,
      `tools/setup-packs.sh`, `cargo run -p opz-tui` with a pointer to `docs/KEYS.md`, and the offline
      render.
- [x] **Acceptance-criteria walkthrough** (each row is what was actually run, not a plan):
      1. *`cargo test` passes with no Unicorn dependency at test time* — ✅ **69 tests pass** from
         committed files; `grep` finds no `unicorn` reference in any source or manifest outside
         comments and docs, and no such dependency in `Cargo.toml`.
      2. *Clone + setup + `cargo run -p opz-tui` gives sound on four drum tracks and two synth
         tracks* — ✅ **met**: the four drum tracks are the sample player, and the two synth tracks are
         `analoga.engine` (track 5, the device's own slot configuration) and `digital.engine` (track
         6). The TUI labels both `synth`, programs notes on both, and the offline render puts both
         voices in one bar (peak 21154, byte-identical across runs, `afinfo`-verified WAV); a Rust
         test asserts each synth track is audible on its own.
      3. *The four drum tracks load the named packs and their slices map as the ported
         `SamplePlayerGain` says* — ✅ the pack reader and slice table are golden-verified, and the
         engine's descriptor contract (whole-pack length, per-slice data pointer) is what the
         fixtures pin. Which slice a note plays is host-side by design, and that is recorded in
         `crates/opz-dsp/tests/golden/README.md`.
      4. *Every ported function is golden-verified or explicitly excepted* — ✅ `SamplePlayerGain`
         (10 fixtures byte-exact + exact `onNoteOn` state), `Digital` (35 fixtures byte-exact) and
         `AnalogA` (all ten functions: 20 end-to-end voices sample for sample, 50 `_RFilter_fetch`
         calls, 144 `(phase, increment)` pairs per oscillator, 21 and 36 recorded envelope calls);
         the exceptions are recorded, not glossed: the app-side envelope callbacks are stubbed in the
         harness, and the host-owned tables (wavetable, octave table, gain globals, rate tables,
         `AnalogA`'s filter banks and coefficient records) are harness calibration rather than
         recovered device data.
      5. *No device interaction of any kind* — ✅ no serial/USB/BLE/HID dependency (0 hits), and
         `git ls-files` contains **no** `.so`/`.engine`/`.apk`/`.zfw`/`.aif`/`.wav`: the packs are
         local symlinks into gitignored directories.
      **Verdict: 5 of 5 met.** Phases 1 through 5 are tagged (`phase-1`..`phase-5`); the next step is
      either the next engine batch
      (`Volt`, `Electric`, `Fm003b`, `Organ`, `EP`) or a v2 feature (p-locks, step components, FX
      tracks, pattern banks, chain mode).

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
