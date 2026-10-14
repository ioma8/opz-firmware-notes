# Saw013a: Phase 5's engine port

Phase 5's only unchecked item is "port `Saw013a` as the first post-v1 engine to prove the pipeline is
mechanical, not bespoke". This file is the working material for it; `SAW013A.asm` next to it is the
disassembly.

## Inventory (from `~/.opz-decode/opzso/syms.json`, `libSnakePlugin.so`)

| symbol | vaddr | size |
|---|---|---|
| `Saw013a::initModule(unsigned, const ModuleCallbackInterface*, unsigned*)` | `0x1238c4` | 32 B |
| `Saw013a::init(void*, unsigned, unsigned, void*, void*)` | `0x1238e4` | 176 B |
| `Saw013a::render(fract32_t*, unsigned, int, void*, const unsigned*, ADSR*)` | `0x123994` | **3 180 B** |
| `Saw013a::onNoteOn(int, unsigned char, void*, const unsigned*)` | `0x124480` | 996 B |
| `Saw013a::onNoteOff(int, void*)` | `0x124864` | 4 B |
| `Saw013a::interface` | `0x124a30` (data) | 8 B |

`SAW013A.asm` contains `initModule`, `init`, `render` (800 instructions), `onNoteOn` and `onNoteOff`. The
`onNoteOn` block runs a few instructions past `0x124864`, so its tail is `onNoteOff` plus the start of the
next function - the boundary is marked by the size table above.

Facts already recorded elsewhere: the plug is id 26, named `saw`, engine `saw013a.engine`, `trackmask` 240
(the synth group), and its catalogue `parameterNames` are `["offset", "space"]` - the same two the
`digital.engine` plug carries, so the app's parameter plumbing needs nothing new. Its engine `api_path`
prefix is `671de54c`, and the app catalogue already lists it (`crates/opz-core/src/plugs.rs`), so a track
can name it today; only the engine behind it is missing.

## The signature is the standard one

`render(out, increment, delta, state, params, adsr)` and `onNoteOn(note, velocity, state, params)` are
exactly the shape the port's `EngineVoice` trait already has (`opz-dsp/src/voice.rs`), and `onNoteOff` is a
4-byte `ret`, matching `Digital` and `AnalogA`. So the port is an `impl EngineVoice for Saw013a` plus the
`init`/`initModule` bookkeeping, not a new seam.

## The plan, following the method that worked for `Digital` and `AnalogA`

1. read `SAW013A.asm` and write `crates/opz-dsp/src/saw013a.rs` (the state block first, from `init` and the
   fields `render` touches);
2. add a `make_saw013a_fixtures.py` modelled on `make_analoga_fixtures.py` - it should record, at minimum,
   the per-case input state, the 64-frame output block(s) for `render`, the `onNoteOn` state delta, and
   `filter_args`-style traces for anything it calls into;
3. add `saw013a_matches_the_original` to `crates/opz-dsp/tests/host.rs`;
4. add an `opz-dsp`-side `HostTables`-equivalent if the engine needs host tables (the analogue engine did:
   filter banks, rate tables), and record which are harness calibration rather than recovered data;
5. add the `VoiceEngine::Saw` variant in `opz-core/src/engine.rs` and route it through `engine_for_track`,
   then a test that a track with `saw013a.engine` makes sound - the Phase 5 playable check says
   "`Saw013a` available on a track, and the whole thing still playing after the host swap";
6. update `PORT_METHOD.md` with the symbol table, the golden-verified row and any exceptions.

**Status**: inventory and disassembly done; nothing ported yet.
