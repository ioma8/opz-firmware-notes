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

## `init` (0x1238e4): the state block, read off the disassembly

```text
movi  v0.2d, 0
w8 = variant - 4 ; cmp w8, 3
str   xzr, [state + 0x60]
stp   q0, q0, [state + 0x40]
stp   q0, q0, [state + 0x20]
stp   q0, q0, [state + 0x00]        ; state + 0x00..0x67 zeroed
b.hi  0x123930                      ; variant outside 4..7
adrp/add x9, 0x7d000 + 0xb0e        ; a 4-byte dispatch table, indexed by variant - 4
br    x10                           ; ... to one of four arms
```

The four arms are the variant matrix:

| arm | constant folded in | source word |
|---|---|---|
| `0x12391c` | `0xeccc3340` | `[0x124a5d0]` |
| `0x123940` | - | `[0x124a5d4]` (stored straight to `+0x38`) |
| `0x123950` | `0xe66699a0` | `[0x124a5d8]` |
| `0x123964` | `0xf333ccd0` | `[0x124a5dc]` |
| variant outside 4..7 | - | `[0x124a5cc]` (stored straight to `+0x38`) |

Three of them end at `0x123974`, which is the same shape the ported engines already use for a Q31
multiply-and-clamp:

```text
x9 = x8 * x9            ; the source word times the arm's constant
x9 = x9 >> 31 (logical)
w8 = w8 + w9 (saturating adds, `adds`)
w9 = w8 >> 31 (arithmetic) ; eor 0x80000000 ; csel w8, w9, w8, vs
state[+0x38] = w8
```

So: **the state block is at least `0x68` bytes**, `init` zeroes `0x00..0x67` and then writes **one word at
`+0x38`**, whose value depends on the variant through one of five `.bss` words
(`0x124a5cc`/`0x124a5d0`/`0x124a5d4`/`0x124a5d8`/`0x124a5dc` - host-filled data, the same situation as
`AnalogA`'s tables, so they will be harness calibration unless the firmware's values can be pinned).

That is the first concrete porting step: the state struct and `init`'s variant matrix, both readable
directly from the listing.
