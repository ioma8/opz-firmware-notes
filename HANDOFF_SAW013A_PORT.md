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

### The variant matrix, resolved

The dispatch table is at **`0x7db0e`** (`adrp x9, 0x7d000` then `add x9, x9, 0xb0e` - reading `0x7d0b0`
gives a different table). Its first four bytes are `00 09 0d 12`, and the arm is `0x12391c + byte * 4`:

| `init`'s variant | arm | constant | `.bss` word |
|---|---|---|---|
| 4 | `0x12391c` | `0xeccc3340` | `0x124a5d0` |
| 5 | `0x123940` | - (stored straight) | `0x124a5d4` |
| 6 | `0x123950` | `0xe66699a0` | `0x124a5d8` |
| 7 | `0x123964` | `0xf333ccd0` | `0x124a5dc` |
| outside 4..7 | `0x123930` | - (stored straight) | `0x124a5cc` |

All five source words are zero in the shipped `.so` (`.bss`, firmware-filled), so they are **host input**
for the port - the same situation as `AnalogA`'s filter banks and rate tables, and they belong in a
`HostTables`-equivalent.

### `render` (0x123994), the preamble

The first instructions, read straight off `SAW013A.asm`:

```text
sub sp, sp, 0xb0 ; the frame
ldr  w8, [x5, 0x10] ; the ADSR's phase
cbz  w8, 0x1245ac   ; phase 0 renders nothing - the same gate as Digital and AnalogA
ldrb w8, [x3, 0x65] ; a state byte
cbnz w8, 0x1245f0   ; ... which selects a second path
ldpsw x8, x9, [x4]  ; params[0] and params[1], sign-extended to 64 bits
```

Then the arithmetic starts, and its shape is familiar from the other engines: pairs of
`subs`/`asr #31`/`eor 0x80000000`/`csel ..., vs` (a saturating subtract), `mul` + `asr #0x20` (a
multiply narrowed by 32), and `umull` for unsigned 32×32 products. The constants it loads in the first
few dozen instructions are `0x7fffffff`, `0xd5504300`, `-2`, `0x73ef0d00`, `-0x8a00` and `-0xc000` - so
it mixes Q31 gains with integer steps, as the other engines do.

**Scope**: 800 instructions in `render` alone (plus 260 in `onNoteOn`), against ~1-2 KB for the engines
already ported - so this is a multi-pass job in the same class, not a quick one. The right next move is to
read `render` in the order the state is touched, write the state struct from those offsets, and port the
per-frame loop, exactly as `Synth::render` and `AnalogA` were done.

### The decompilation, and what it caught

Ghidra is installed after all - `~/Applications/Ghidra_12.1.4/support/analyzeHeadless` - and `/tmp/ghidra-p4`
already holds an analysed `libSnakePlugin.so` from the Phase 4 work, so no re-import or re-analysis is
needed:

```sh
analyzeHeadless /tmp/ghidra-p4 p4 -process libSnakePlugin.so -noanalysis \
    -scriptPath tools/ghidra-scripts -postScript DecompileTo.java "Saw013a" /tmp/decomp-saw.txt
```

Seconds, five functions, 986 lines. `SAW013A-decomp.c` next to this file is the result.

**It immediately caught three errors** in the constants I had read off the assembly by eye:

| arm | I wrote | the C says |
|---|---|---|
| variant 4 | `0xeccc3340` | **`-0x13333340`** |
| variant 6 | `0xe66699a0` | **`-0x199999a0`** |
| variant 7 | `0xf333ccd0` | **`-0xcccccd0`** |

The `mov`/`movk` pairs in the listing are easy to mis-read; the C is not. Everything else about `init`
matched: the same clearing of `0x00..0x67`, the same variant matrix, and the same
`mul` / logical-`>>31` / saturating-add / clamp sequence.

**`render`'s setup**, from the C:

```c
if (*(int *)(param_6 + 0x10) == 0) goto LAB_002245ac;      // the ADSR phase gate
if (*(char *)((long)param_4 + 0x65) != '\0') {             // a countdown byte in the state
    *(char *)((long)param_4 + 0x65) = *(char *)(...) + -1;
    goto LAB_002245ac;
}
uVar21 = *param_5;  uVar24 = param_5[1];                   // params[0], params[1]
... 0x7fffffff - uVar21 (saturating)                       // the same complement pairs as AnalogA
uVar25 = uVar26 * 0xfffffffe >> 0x20;                      // times -2, narrowed by 32
iVar13 = (int)((lVar19 * 0xd5504300 >> 0x20) * uVar23 >> 0x1f);
iVar20 = (int)(uVar25 * uVar23 >> 0x1f);
```

So the engine opens with the same shape `AnalogA` uses - a saturating complement of each of the first two
parameters, then pan/gain pairs narrowed by `>>31` - and the state's `+0x65` is a countdown rather than a
flag.

**Next**: read the rest of `render` (690 decompiled lines) in the order the state is touched, write the
state struct from the offsets it uses, and port the per-frame loop. The C makes that a reading job rather
than a disassembly one.

### `render`'s state map, from the C

Every access to the state block (`param_4`), which fixes the struct:

| offset | width | use in `render` |
|---|---|---|
| `+0x00`, `+0x04` | word | read into `uVar24`/`uVar21` after the interface call |
| `+0x08` | - | passed as the *first argument* of the interface call (see below): the engine's own state block |
| `+0x20` | word | read into `uVar17` |
| `+0x28`, `+0x30` | 2 words each | read as 8-byte values (`uVar32`, `uVar34`) |
| `+0x38` | word | the `init` word: `lVar22 = lVar22 * *(int *)(param_4 + 0x38)` |
| `+0x4c` | 4 words | a NEON block: `auVar30 = NEON_sqsub(auVar30, *(param_4 + 0x4c))`, i.e. a saturating packed subtract |
| `+0x5c`, `+0x60` | word | read, then written back *swapped* (`+0x5c` gets the old `+0x60` and vice versa) |
| `+0x64` | byte | `*(byte *)(param_4 + 100)`: scaled by `0x1020408` plus `>> 4`, then times `params[0xb]` - the same velocity-fraction shape `AnalogA` uses |
| `+0x65` | byte | the countdown: nonzero decrements and returns |

`init` clears `0x00..0x67`, so 26 words is the block size and every one of these fits.

**The interface call.** `render` reaches a host callback:

```c
(**(code **)(*(long *)puVar10 + 0x38))((long)param_4 + 8, uVar21, uVar1, uVar3, uVar24);
```

`puVar10` is `PTR_interface` - the same `Saw013a::interface` object `initModule` stores - and slot `+0x38` is
called with the engine's sub-state (`state + 8`) plus four values. So the port needs a host seam here, the
way `AnalogA` needed one for `_RFilter_fetch`: a trait the engine calls, with the fixture recording its
arguments and return the same way.

### `render`'s shape

Three parts:

1. **the prologue** (decomp lines 79-410): the ADSR gate and the `+0x65` countdown, then a long run of
   multiply chains that build the per-note gains, then the interface call. Nothing here is per-sample.
2. **the sample loop** (lines 411-750): `do { ... } while ((int)lVar19 != 0x200)` - 512 bytes of output,
   which at two words a frame is the same 128-word block the other engines render.
3. **the epilogue** (lines 680-771): the state write-back and the ADSR update.

**The phase accumulator is `+0x5c`/`+0x60`**, and the loop's first statements say exactly how:

```c
uVar17 = uVar17 + param_2;                     // param_2 is the increment
uVar6  = uVar17 ^ 0x80000000;
*(int *)(param_4 + 0x5c) = iVar14;             // last iteration's phase
*(uint *)(param_4 + 0x60) = uVar17;            // this iteration's
```

So `+0x60` is the running phase (advanced once per *frame* by the increment, which is the second
argument, `param_2`) and `+0x5c` is the previous frame's value - the same "phase, previous phase" pair
`Digital` and `AnalogA` keep, and the wrap detection that follows (`uVar6 < param_2`) is the overflow test
that turns the phase into a per-frame fraction:

```c
iVar13 = 0x7fffffff;
if (uVar6 < param_2) {                          // the phase wrapped
    lVar22 = ((long)uVar6 << 31) / (long)param_2;   // the fraction of the way through
    ... clamp to +/-0x7fffffff ...
    lVar15 = lVar22 * lVar22 * 2 >> 0x20;       // squared, the usual Q31 pair
    iVar16 = (lVar15 * lVar22) >> 0x1f;         // cubed
    ... iVar16 - ((iVar16 * (iVar28 >> 1)) >> 31) ...   // the soft ramp the engines share
}
uVar6 = iVar14 - iVar16 ...                     // and the previous phase minus it
```

That is the oscillator's per-sample shape, and it is built from the same primitives the port already has
(`mul31`, saturating add/sub, `>> 0x1f`, `>> 0x20`). The work left is transcription, not decoding.

**Next pass**: write the prologue's gain chains as Rust functions with the decompilation open beside them,
then the loop body, then the epilogue - checking each against the C as `init` was, since that is what caught
the three constants.

### The host harness, and the seam that is still missing

`tools/unicorn-harness/opzso.py` gained a `Saw013aHost`, modelled on `AnalogAHost`: the state block, the
params buffer, the ADSR, the output buffer and the five firmware-filled constants `init` folds. `init`,
`initModule` and `onNoteOn` run, and the state reads back.

**What this engine needs that `AnalogA` did not.** `AnalogA` dereferences *no* interface slots; `Saw013a`
does. Two things the C makes explicit:

```c
bool Saw013a::initModule(uint param_1, ModuleCallbackInterface *param_2, uint *param_3) {
    *(ModuleCallbackInterface **)PTR_interface_002d6010 = param_2;   // it keeps the *caller's* pointer
}
...
(**(code **)(*(long *)puVar10 + 0x38))((long)param_4 + 8, uVar21, uVar1, uVar3, uVar24);  // the callback
plVar29 = *(long **)(*(long *)puVar10 + 0x28);                                            // a table pointer
```

So the host builds the interface object itself - an interface whose first word is a vtable, `vtable[0x28]` a
host table and `vtable[0x38]` a stub that records its four arguments - and passes it to `initModule`. The
library's own `Saw013a::interface` symbol is *not* what the engine reads.

**Still faulting.** With that in place `render` reaches a null indirect call: `PC = 0`, with `x0` the state
and `x1`/`x2` the first two parameters. That signature is not the `+0x38` callback (which passes
`state + 8` and four values), so there is at least one more host pointer. The way to find it is a code hook
that records the last few PCs before the fault and prints the branch instruction that took it.

**Order of work from here**: fix the harness until `render` produces a block, then write
`make_saw013a_fixtures.py` (modelled on `make_analoga_fixtures.py`, with the same determinism and
not-every-case-silent guards), and only then transcribe `render` against recorded output.
