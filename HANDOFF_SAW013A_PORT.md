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

### The harness runs `render` now

Three things were wrong, and all three are fixed:

1. **The interface object carries the slots itself.** The call site is
   `ldr x8, [x25]` / `ldr x8, [x8, 0x38]` / `blr x8`, so what the engine reads at `+0x38` is a field of
   the object `initModule` was handed - not of a vtable that object points at. The host writes the callback
   (and the table pointer) into the interface *and* keeps a vtable pointer at `+0x00`, because the C's
   `*(long *)puVar10 + 0x38` implies one.
2. **`UC_ARM64_REG_X4` was not imported** in `opzso.py`, so the callback raised `NameError` and the harness
   reported it as a fault at the stub address - a misleading symptom for a one-line cause.
3. **The table at `vtable + 0x28` is a table of pointers.** Zero-filled it renders silence; filled with a
   constant it faults on an unmapped read, because the engine follows what it holds.

With those, `init`, `initModule`, `onNoteOn` and `render` all run, and the callback fires twice per block
with four values (`0x40404040`-derived in the first call, and three state-derived ones plus a phase in the
second). The output is silent because the host data behind that table is missing.

**Next**: read the `plVar29` uses in `SAW013A-decomp.c` (it is assigned at line 556 and dereferenced after)
to learn the table's shape, fill it with the documented pattern the way `AnalogA`'s banks are filled, and
then the engine should produce a block - which is the point where `make_saw013a_fixtures.py` becomes worth
writing.

### The host table is a wavetable, and the engine is still silent

`vtable + 0x28` is an **array of five pointers**, each to a wave table the engine reads as
`table[0x410 + 4 * index]` with a seven-bit index taken from the phase:

```c
plVar29 = *(long **)(*(long *)puVar10 + 0x28);
iVar13 = (int)(uVar23 * *(int *)(*plVar29        + 0x410 + lVar15) >> 0x1f);
iVar14 = (int)(uVar26 * *(int *)(*plVar29        + 0x410 + uVar25) >> 0x1f);
... the same for plVar29[1] through plVar29[4] ...
uVar25 = (uVar1 >> 0x19) << 2;      // a seven-bit index, byte offset
lVar15 = uVar25 + 4;                // and the next entry, for linear interpolation
```

That is `Digital`'s host-wavetable arrangement exactly, and it explains both earlier symptoms: a
zero-filled table leaves the engine silent (it multiplies by what it reads), and a constant-filled one makes
it read unmapped memory (the pointers are followed). The harness now allocates five Q31 sine tables, each
with the 130 entries the interpolation needs.

**The state `onNoteOn` leaves**, which the harness reads back:

| offset | value |
|---|---|
| `+0x10` | `0x7fffffff` |
| `+0x18`, `+0x1c` | `1` |
| `+0x4c`..`+0x58` | nonzero (the NEON block) |
| `+0x64` | the velocity, `100` |

**Still silent.** Setting the five constants to full scale, and the ADSR's level and mul to `0x7fffffff`
with `add = 0`, each in turn, leaves every sample zero. So the gain the oscillator multiplies with is still
zero somewhere, and the candidates are:

1. a **host input not yet identified** - the four values the `+0x38` callback receives (the harness records
   them: `0x40404040`-derived in the first call and three state values plus a phase in the second) suggest
   the engine expects something *back* from it, rather than treating it as a pure notification;
2. the **`+0x65` countdown**, which `init` leaves zero and `render` treats as "return early" only when
   nonzero - so it is not the gate;
3. the **ADSR's `+0x14` byte**, which the analogue engine also consults and which the harness never sets.

The cheapest next measurement is to read the callback's *return* expectations out of the C - whether the
four arguments are an output the engine then reads back - and, failing that, to watch `param_1`'s store in
the loop with a code hook to see which register value it writes.

### The silence is upstream of the wavetable

Hooking the loop's output store (`str d3, [x23, x9]` at `0x1243a8`, `x23` = `param_1`, `x9` the byte
offset) settles where the zero comes from:

```text
stores (offset, lo, hi, x8): [(0, 0, 0, 12740059), (8, 0, 0, 25480118), (16, 0, 0, 38220177), ...]
```

`x8` is the running phase - one increment per *frame* (`12740059`, twice it, three times it), exactly the
128 frames the loop covers. So the phase accumulator, the increment argument and the loop count are all
right, and **every stored sample is zero**.

Since the stored value is the wavetable interpolation's result, and a zero scale makes the index
`(uVar1 >> 0x19)` zero, which lands on `table[0x410] = sin(0) = 0`, the zero is *upstream* of the lookup:
the amplitude that scales it is zero. Things already tried, each in isolation, none of which moved it:

* the five firmware constants at full scale;
* the ADSR's `level` and `mul` at `0x7fffffff` with `add = 0`;
* five Q31 sine tables behind the `vtable + 0x28` pointer array;
* making the `+0x38` callback return `0x7fffffff` in case the engine reads it back.

That leaves the prologue's gain chains between `params`/the state and the loop as the place the zero is
introduced. The next measurement is a code hook on the loop's *first* instruction that records the registers
the loop's body reads (the decomp's `uVar26`, `uVar23`, `uVar6`, `uVar1` and the two `iVar`s it enters
with), then the same hook stepping forward until one of them is zero - the registers are visible at every
instruction address, so this localises the stage without guessing which host input is missing.

### The wavetable lookup is not the silence either

The index site is `0x1241dc` (`asr w3, w14, 0x19` - the seven-bit index), and `w14` there reads
**`0x310f6c19`** on every frame. So the index is `0x18` = 24 and the fraction `(w14 << 6) & 0x1ffffff` is
nonzero: the interpolation has real entries to work with and the host tables are doing their job.

The access pattern around it, read off the listing, confirms the shape the C described:

```text
0x1241ac  ldr x15, [x25]           ; the interface
0x1241b4  ldr x15, [x15, 0x28]     ; the pointer array
0x1241c4  ldp x17, x0, [x15]       ; table[0], table[1]
0x1241d8  ldp x1, x2, [x15, 0x10]  ; table[2], table[3]
0x1241d4  ldr x16, [x15, 0x20]     ; table[4]
0x1241dc  asr w3, w14, 0x19        ; the index
0x1241e4  sbfiz x17, x3, 2, 0x20   ; index * 4
0x1241ec  add x6, x17, 4           ; the next entry
0x1241f8  ubfiz w14, w14, 6, 0x19  ; the fraction
0x124208  eor w4, w14, 0x7fffffff  ; its complement
0x124200  ldrsw x3, [x15, x17]     ; table[0][index] ...
```

So the zero is *after* the lookup. What the store actually is, from the C:

```c
uVar32 = NEON_sqadd(*(undefined8 *)(param_1 + lVar19), uVar32, 4);
*(undefined8 *)(param_1 + lVar19) = uVar32;
```

- the output buffer is **accumulated into**, not written over (so a fixture must hand it a zeroed block,
  and the harness does);
- the sample is a *packed select* built from a long `CONCAT`/`|`/`&` chain immediately before the store.

The next measurement is therefore on **that blend**: the two operands the select chooses between are the
last places a zero can come from. Hooking the `ldrsw`s at `0x124200` onwards and following the values into
the `str` at `0x1243a8` shows which of the two is zero - and the answer names the model parameter the engine
expects the host to supply.

### Where the zero is now bounded to

Three measurements, in order, each one narrowing it:

| measured | result |
|---|---|
| the wavetable load at `0x124200` (`[table0 + 0x410 + 4*index]`, `index` = 24) | **1984016187** - nonzero, so the host tables and the index/fraction arithmetic are right |
| the NEON registers entering the store (`q1`..`q9` at `0x1243a0`) | **all zero** |
| the store (`str d3, [x23, x9]` at `0x1243a8`) | zero |

So the zero enters *between* the table load and the store - the interpolation and the per-table scaling.

**The lead worth following** is the callback. The C shows it called with the engine's sub-state and four
values:

```c
(**(code **)(*(long *)puVar10 + 0x38))((long)param_4 + 8, uVar21, uVar1, uVar3, uVar24);
```

and immediately *after* it the engine re-reads the state it handed over:

```c
uVar24 = *(uint *)param_4;            // +0x00
uVar21 = *(uint *)((long)param_4 + 4); // +0x04
uVar17 = *(uint *)((long)param_4 + 0x20);
uVar32 = *(undefined8 *)((long)param_4 + 0x28);
uVar34 = *(undefined8 *)((long)param_4 + 0x30);
```

So the callback is an *input*: the host is expected to leave values in `param_4 + 8` and the engine picks
them up. Filling the eight words at `state + 8` with `0x40000000` from the stub does not lift the silence,
so the shape of what it wants (how many words, at which offsets, and whether it wants a count or a pointer)
is still unknown - the same question `AnalogA`'s `_RFilter_fetch` answered by being a *returning* call.

**Next**: diff the state before and after the callback (`param_4` fully, not just `+8`) to see which fields
the engine actually consumes after the call, then try the values the callback was *given* as the ones it
should write back - the C passes four values in, and a callback that stores them somewhere sensible is the
common shape.

### There are *two* interface calls, and the first is handed the ADSR

The prologue calls the same `+0x38` slot twice, which the earlier "one callback" reading missed:

```c
(**(code **)(*(long *)PTR_interface_002d6010 + 0x38))(param_6, param_5[2], param_5[3], param_5[4], param_5[5]);
(**(code **)(*(long *)puVar10 + 0x38))((long)param_4 + 8, uVar21, uVar1, uVar3, uVar24);
```

* the **first** is handed the **ADSR** (`param_6`) and `params[2]..params[5]` - on the device that is the
  host's envelope update, the thing that turns the plugin's rates into the `mul`/`add` the engines run;
* the **second** is handed the engine's sub-state (`param_4 + 8`) and four gain values, and the engine then
  re-reads `param_4` for the table gains.

The harness's stub records *both* (that is why the earlier trace showed two calls per block). Servicing the
first by ramping the ADSR's level does not lift the silence, and the level reads back zero afterwards - so
either the engine resets it, or the amplitude does not in fact come from the ADSR.

**What the amplitude chain uses**, read from the C:

```c
lVar22 = lVar22 * *(int *)((long)param_4 + 0x38);          // the init word
lVar19 = ((byte *)(param_4 + 100) * 0x1020408 + ...) * param_5[0xb];   // velocity fraction times params[11]
uVar32 = NEON_sqsub(CONCAT44(lVar15 * uVar17 >> 0x1f, lVar19 * (iVar13 + 0x40000000) >> 0x1f),
                    *(undefined8 *)((long)param_4 + 0x28), 4);
uVar34 = NEON_sqsub(CONCAT44(lVar15 * uVar6   >> 0x1f, lVar38 * (iVar20 + 0x40000000) >> 0x1f),
                    *(undefined8 *)((long)param_4 + 0x30), 4);
```

So `uVar32`/`uVar34` - the pair the loop post-accumulates - are `NEON_sqsub`s of the pan/gain products
against the state's **`+0x28` and `+0x30`**, and *those two* are the fields the callback is expected to
supply (it is handed `param_4 + 8`, and `+0x28`/`+0x30` are inside that). The harness leaves them zero, and
a `sqsub` against zero is a no-op - which is consistent with everything measured so far.

**Next**: fill `state + 0x28` and `state + 0x30` (four words each) with the values the second call is handed
(the C passes `uVar21`, `uVar1`, `uVar3`, `uVar24` into the callback, and those four look like exactly this
pair), then re-run. That is the last untried input the C points at.

### The zero is one operand of the pan/gain product

`0x124394` is where the loop's post-accumulated pair begins (`subs w14, w15, w14`), and the operands there
read:

```text
at 0x124394 (x16, x8, q3lo, q4lo): [('0x0', '0xc265db', 0, 0), ('0x0', '0x184cbb6', 0, 0), ...]
```

`x8` is nonzero and advances by one increment per frame (the phase), while **`x16` is zero on every frame** -
so of the two operands the pan/gain product is built from, one is zero and the other is fine. The product
itself (`q3`/`q4`) is therefore zero, which is what the loop accumulates and stores.

That is as far as measurement has taken it, and it is a sharp place to pick up: walk the assembly backwards
from `0x124394` for the instructions that define `x16` and find which of the prologue's chains leaves it
zero. Everything downstream has been checked - the tables, the index, the fraction, the state fields, and
both interface calls - and the remaining unknown is one register's origin.

**Tried and ruled out so far** (each in isolation, none lifting the silence): the five firmware constants at
full scale; the ADSR's level and mul at `0x7fffffff`; five Q31 sine tables behind the pointer array; making
the `+0x38` callback return a value; servicing the first call by ramping the ADSR; writing the second
call's four arguments into `state + 0x20`; filling eight words at `state + 8`.

### Correction: that `x16` reading was a stale register

Reading the instructions around `0x124394` shows what `x16` actually is there:

```text
0x124374  lsr x16, x14, 0x1f       ; x16 = the saturation sign of x14
0x12437c  cmp x14, x27             ; against the 2^62 sentinel
0x12438c  csel w14, w28, w16, eq   ; w14 = sentinel-or-sign
0x124390  subs w14, w15, w14       ; the saturating subtract
0x124394  asr w15, w14, 0x1f
```

`x16` is set at `0x124374` and consumed by the `csel` at `0x12438c`, so by `0x124394` it is a leftover
register, not one of the value's operands. The probe reading `x16 = 0` therefore says nothing about the
product; the operands that matter are **`x14` and `x15`** (and `x27`, the sentinel). My earlier note calling
`x16` "one operand, therefore the zero" was wrong, and the honest state is that the operand values at
`0x124394` have not been read yet.

This is the same trap the mixer's port hit with Ghidra's reused names, one level down: a register that is
*correct* to print at one address is *misleading* a few instructions later. The measurement to run is the one
for `x14` and `x15` at `0x124394`, and if those are fine then the zero is in whatever produced them - which
the listing shows is the `NEON` product chain ending at `0x12438c`'s inputs, not the phase.

### The corrected reading, and its own caveat

`x14` and `x15` at `0x124394` both read zero in their **low 32 bits**, `x27` zero likewise, and `x28`
`0x7fffffff`:

```text
at 0x124394 (x14, x15, x27, x28): [('0x0', '0x0', '0x0', '0x7fffffff'), ...]
```

The probe masked each register to 32 bits, so "zero" there means the low word is zero - which is *also* what
a 2^62 sentinel looks like in its low word (`0x4000000000000000` ends in eight zero bytes). So this reading
does not yet distinguish "the operand is zero" from "the operand is the sentinel", and the sentinel is
exactly what `x27` is expected to hold at the comparison on the line before.

The next measurement has to print the **full 64-bit** registers (`x14`, `x15`, `x27`) rather than their low
words, and at the *first* instruction of the loop rather than mid-body, so the values are the ones the body
starts with instead of wherever a later instruction left them.

Two rounds of measurement have now been lost to the same mistake in two forms - a reused Ghidra variable
name, and a stale/low-masked register - so the rule for the rest of this port is: read the value at the
instruction that *consumes* it, at full width.

### The interpolation is healthy - full width, at the consuming instruction

Applying the rule (read at the consuming instruction, at full width) immediately gave a clean answer. At
`0x124218` (`mul x3, x4, x3`, the first interpolation product):

```text
x3  = 0x7641af3b    the table entry the index selects
x4  = 0x3c24f9bf    the fraction's complement (w14 ^ 0x7fffffff)
x14 = 0x43db0640    the fraction itself
x15 = 0x78848412    the next table entry
```

All four are nonzero, and `0x7641af3b` is *exactly* `sin(2*pi*24/128) * 0x7fffffff` - so the host sine tables,
the index (`24`), the fraction and the interpolation's operands are all correct.

**So the zero enters between `0x124218` and the store at `0x1243a8`.** That window contains the
saturating adds that combine the five table contributions, the packed select that blends the two pan lanes
(`bic`/`orr` against a sign-derived mask at `0x124360`-`0x124388`), and the final `sqadd` against the output
buffer. The next measurement is a hook midway - `0x124280` after the first `adds`/`csel` pair - to see
whether the per-table contributions survive their summation, and then at `0x124360` for the blend's mask.

Everything before that window is now positively verified: the tables, the index, the fraction, all five
entries, and both interpolation products' operands.

### The lane value is zeroed by its own saturation chain

At `0x1242f4` (`dup v4.2s, w15`, where the per-lane value is broadcast for the blend):

```text
w15 = 0x0          the lane value that becomes v4
w16 = 0x0
w12 = 0x77748916   the running sum (nonzero)
w0  = 0x77748916
w1  = 0x77748916
```

So the *sums* are healthy (`0x77748916`) and the lane value is zero. The three instructions before it are
the saturation idiom:

```text
0x1242d8  adds w12, w15, w12        ; the sum
0x1242dc  asr  w15, w12, 0x1f       ; its sign
0x1242e0  eor  w15, w15, 0x80000000 ; the saturating clamp value
0x1242e4  csel w15, w15, w12, vs    ; and the select on overflow
```

`csel w15, w15, w12, vs` takes w15 *when vs is set* - so on a *signed overflow* the clamp value wins over
the sum. `w15 = 0` therefore means the select took the `eor`-derived operand, and for it to be zero the
`asr` must have produced zero, i.e. the sum was non-negative *and* the overflow flag was set. That can only
happen if the operand *before* the add was not what this reading assumes, so the next step is to read
`w15`'s value at `0x1242d8` - the instruction *before* the add, at full width - rather than three
instructions later.

Same lesson as the last two rounds, one more time: **read the register at the instruction that consumes
it**. Every value in this function is a reused register a few instructions on.

### The summation's operands are zero even though the products are not

At `0x1242d8` (`adds w12, w15, w12`, one of the per-table accumulations):

```text
x15 = 0x0   x12 = 0x0   x13 = 0x0
```

Three instructions later, at `0x1242f4`, `w12` reads `0x77748916` - because `0x1242e8` does
`sxtw x12, w0`, overwriting it with an interpolation product. So the earlier note's "the sums are healthy"
was reading a register that had already been reassigned; the *accumulation* itself receives zero from both
operands.

Meanwhile the products are healthy: `x3`/`x4`/`x14`/`x15` at `0x124218` are all nonzero, and the table
values are the host sine entries. So the per-table *contribution* - the `mul` then `lsr #31` that turns the
64-bit product into the 32-bit addend - is where a nonzero product becomes a zero operand.

**Next**: read the registers at the *first* accumulation (`adds w15, w16, w15` at `0x12425c`) and at the
`lsr`s immediately before it. Those are the contribution values themselves, and one of them is the first
zero in the chain - which is the value the port has to reproduce.

**Ruled out, positively or by elimination**: the host sine tables, the index (`24`), the fraction
(`0x43db0640`), both interpolation operands, the five constants, the ADSR's level/mul, the pointer array's
shape, and both interface calls' argument shapes. The output buffer is accumulated into (`NEON_sqadd`), so a
fixture must hand it zeros.

### The contributions are healthy - the window is between two accumulations

At `0x12425c` (`adds w15, w16, w15`, the *first* per-table accumulation):

```text
x15 = 0x3fe395bd
x16 = 0x3790f359
x3  = 0x1bc879ac96be2005   (the 64-bit interpolation product)
x30 = 0x1bc879ac96be2005
x5  = 0x1bc879ac96be2005
```

All nonzero, and `x3` is the product of the table entry and the fraction whose operands were verified two
rounds ago (`0x7641af3b * 0x3c24f9bf`). So the per-table contributions start healthy.

At `0x1242d8`, the *next* accumulation in program order, both of its operands read zero. The window between
the two is therefore where the value is lost, and it is a short one:

```text
0x124260  lsr  x3, x5, 0x1f        ; the contribution's narrowing
0x124264  asr  w5, w15, 0x1f       ; the saturation sign
0x12426c  eor  w5, w5, 0x80000000
0x124274  csel w15, w5, w15, vs
0x124278  adds w0, w3, w0
0x12427c  asr  w3, w0, 0x1f
0x124284  eor  w3, w3, 0x80000000
... to 0x1242d8
```

Reading `w15` and `w0` at *each* of those addresses - at the instruction that consumes them, full width -
will show the first one that reads zero, and that instruction is the bug.

**Progress so far, stated plainly**: the engine's *inputs* are now positively verified (host sine tables,
index, fraction, both interpolation operands, both interface calls' shapes, the state map), the per-table
contributions are healthy at their first accumulation, and the loss is inside one short saturation run in
the prologue. Everything measured is in this file with its numbers.

### The gain chain, link by link, and the data angle

Following the zeros backwards through the prologue's gain chain, reading each register at the instruction
that consumes it:

| site | what it computes | value |
|---|---|---|
| `0x124150` | `lsr x13, x13, 0x1f` (a `mul31`) and `w14` - the add's operands | **both zero** |
| `0x12416c` | `mul x13, x13, x17` - the gain times a state-derived factor | `x13` in = zero, `x17` = `0x55aded23` |
| `0x124180`-`0x12418c` | the 2^62 sentinel and the `x28` clamp | `x13` out = zero |
| `0x1242bc` | `mul x15, x13, x15` - the accumulated lane value times that gain | `x13` = zero, so the lane value becomes zero |

So the lane value is zero because **the gain `x13` is zero**, and `x13` is zero because its own chain starts
from a zero - every link that has been read is zero while its *other* operand is fine (`x16` = `0x507aaef2`,
`x17` = `0x55aded23`, the products `0x1bc879ac96be2005`).

**The data angle is a dead end for this**: the app catalogue's `saw013a.engine` entry is a `dlc-asset` with
only an `api_path`, `version: 2` and `memoryslot: 16` - no host data at all - and `assets-listing.json` has
the same fields. The wavetables and constants live in the firmware, not in anything fetched alongside the
engine.

**Three candidates remain, in order of likelihood**:

1. the state's `+0x00`, `+0x04` and `+0x20` - the fields the C *re-reads* after the callback, and all zero in
   the harness. Filling them from the callback's four arguments (tried) did not help, but that write was
   inside the stub *after* it recorded the arguments, and the engine may read them before the callback on
   some path;
2. the *interface object's* contents beyond the two slots used - the engine reads `+0x28` and `+0x38`, and
   the object's other fields are the harness's `0x40`-byte zero allocation;
3. a genuine port-side subtlety: the region is dense, and the last three rounds each found a *reading*
   mistake rather than a real zero, so a systematic instruction-level trace of `x13` from `0x123994` to
   `0x1241b0` - logging its value at every write - is the way to settle it rather than guessing.

That trace is the next action: it is mechanical, it is bounded to the prologue, and it cannot be misread the
way single-address probes can.

### The mechanical trace found it: `mul x13, x14, x13` with a zero table entry

Hooking every instruction of the prologue (`0x123994`..`0x1241b0`) and logging `x13` whenever it changes
gives the whole life of the gain in one pass. The tail of the log is the answer:

```text
0x124098 -> 0x000000002d8fdf54     nonzero
0x1240ac -> 0x0000000000000000     zero - and the pair repeats
```

The instruction at `0x1240ac` is `lsr x14, x13, 0x1f` - it writes `x14`, so the *change* the hook saw is the
effect of the instruction before it:

```text
0x124098  ldrsw x14, [x20, 4]      ; a table entry, four bytes into whatever x20 points at
0x1240a8  mul   x13, x14, x13      ; x13 = entry * x13  -> zero
0x1240ac  lsr   x14, x13, 0x1f
0x1240b0  cmp   x13, x27
0x1240b4  csel  w13, w28, w14, eq
```

So the gain is zeroed because **`[x20 + 4]` is zero**, and that pair (`0x124098`, `0x1240ac`) runs more than
once - it is a small loop in the prologue, not a single pass.

This is the systematic answer three rounds of single-address probes did not reach: the trace cannot be
misread, because it shows *every* write rather than a snapshot of a reused register.

**Next**: `x20`'s origin. The earlier reads of this function's prologue show a `ldr`/`adrp` pair building it
(the decompilation's `plVar29` and the interface's table pointers are nearby), so the remaining question is
whether `x20` is the wavetable pointer array, one of the five tables, or another host structure - and then
which of its fields is the entry at `+4` that the harness leaves zero. That is one bounded lookup, and it is
the last unknown before the engine can be expected to produce a block.

### `x20` is the ADSR, so the gain reads the envelope's level

`x20` is set once, at `0x123b18` (`mov x20, x5`), and `x5` is `render`'s **sixth argument - the ADSR** (the
signature is `render(out, increment, delta, state, params, adsr)`, so `x0`..`x5` are out, increment, delta,
state, params, adsr). So:

```text
0x124098  ldrsw x14, [x20, 4]   ; = the ADSR's level, `+0x04` in the struct
0x1240a8  mul   x13, x14, x13   ; and the gain is multiplied by it
```

The harness's ADSR starts with `level = 0` (it only sets the phase, `+0x10`), so the gain is multiplied by
zero on the first pass - **and that is the zero the trace found**. Setting `level` (and `mul`) to full scale
alongside the constants does *not* lift the silence on its own, so either the pair at `0x124098`/`0x1240ac`
runs a second time with a level the engine itself has since rewritten, or another link in the chain is zero
as well.

**What is now positively known about the prologue**, all by measurement:

* `x20` = the ADSR (`mov x20, x5` at `0x123b18`);
* the gain `x13` is multiplied by `[ADSR + 4]` at `0x1240a8`, then narrowed and clamped against the 2^62
  sentinel with `x28 = 0x7fffffff`;
* the pair `0x124098`/`0x1240ac` executes more than once;
* everything upstream of it (the wavetable, index, fraction, both interpolation operands, the contributions
  at their first accumulation) is healthy.

**Next**: run the same instruction-level trace for `x14` (rather than `x13`) across the whole render, not
just the prologue - the hook pattern is proven and it shows every write, so it will identify the second zero
the same way it found the first. Then set the ADSR's level *before* `onNoteOn` rather than after, in case the
engine's own note-on path rewrites it.
