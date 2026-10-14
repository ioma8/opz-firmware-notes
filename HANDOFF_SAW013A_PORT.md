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
