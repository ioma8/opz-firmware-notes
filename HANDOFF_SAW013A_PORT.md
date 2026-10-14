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

### The ADSR level *is* the first zero, and the second one is the lane accumulator

Re-running the trace with the ADSR's level and `mul` set to `0x7fffffff` changes the picture exactly where
the last note said it would:

```text
x13 changes in the first block, with the level set:
  ... 0x124484 -> 0x0000000080000000
      0x1244ac -> 0x0000000000c265db
      0x1240ac -> 0x006132ed7db8ce6f     <- nonzero now
```

So `0x1240a8`'s `mul x13, x14, x13` is healthy once the ADSR's level is set, and the prologue's gain is no
longer the problem.

What is still zero is the **lane accumulator**: the loop multiplies that gain into `x15` at
`0x1242bc` (`mul x15, x13, x15`), and `x15` at that point is the value built by the per-table contributions.
Those were measured healthy at their *first* accumulation (`0x12425c`: `x15 = 0x3fe395bd`,
`x16 = 0x3790f359`), and `x15` is `sxtw`-ed at `0x1242a0` before the multiply - so the question is whether the
accumulation *finishes* nonzero, which is one more trace away (the same hook, on `x15`, from `0x1241b0` to
`0x1242bc`).

**So the engine's silence is two zeros, not one**: the ADSR's level (found, and fixable by the harness
setting it - or by servicing the first interface call, which is what the device's app does), and whatever the
lane accumulator ends at. The first is understood; the second is now the only unknown, and it is inside the
loop's opening, not the prologue.

### The gain is zero on the loop's first iterations and nonzero later

With the ADSR's level set, reading the `mul x15, x13, x15` at `0x1242bc` directly, per iteration:

```text
at mul x15,x13,x15  (x13, x15):
  ('0x0',        '0x77748916')     first iteration
  ('0x0',        '0x77748916')     second
  ('0x12b2f1a',  '0x77748916')     third
```

So the lane accumulator `x15` is healthy throughout (`0x77748916`), and the **gain `x13` is zero on the first
two iterations, then nonzero**. `x13` is not written anywhere between the prologue and `0x1242bc` per the
change-log, so the zero that matters is in the loop's *own* opening - and it is per-iteration, which is a
different shape from everything measured so far (all the earlier zeros were constant).

**Where that leaves the engine**: two distinct zeros, one understood and one not.

1. **The ADSR's level** - `mul x13, x14, x13` at `0x1240a8` reads `[ADSR + 4]`. Setting it makes the
   prologue's gain nonzero (`0x006132ed7db8ce6f`). On the device this is the first interface call's job (the
   host runs the envelope update, and the engine hands it the ADSR for exactly that). The harness should
   service that call rather than the fixture setting the field directly - and that is a change worth making
   before the next measurement, because it is what the device actually does.
2. **The per-iteration gain** - zero on the loop's first passes. The next trace is `x13` alone over the loop
   body from `0x1241b0` to `0x1242bc`, logging every write, which will show which of the loop's own
   instructions sets it and from what.

### Two measurements disagree, and that is the next thing to settle

The change-log over the whole render says `x13` is **not written** between the prologue and `0x1242bc`, and
its last recorded change is to a nonzero value (`0x006132ed7db8ce6f` at `0x1240ac`). The per-iteration probe
at `0x1242bc` says `x13` is **zero** on the first two iterations. Both cannot be true of the same run.

The two probes are separate `render` calls with the same setup on paper (variant 5, the constants at full
scale, the ADSR's level and mul at `0x7fffffff`, `note_on(60, 100, params)`), so one of them is not what it
looks like. The likely candidates, in order:

1. **the ADSR writes land before `onNoteOn` runs**, and `onNoteOn` rewrites the level - in which case the
   trace run (which wrote them before `note_on`) and the probe run (same order) would agree, so this is only
   ruled out if the orders actually differ in the two scripts;
2. **the change-log's hook range** (`0x123994`..`0x1245ff`) does not cover a write that happens on a path
   taken only in the probe run - the loop's first iterations may take a branch the trace run did not;
3. **`x13`'s value at the loop is set by the *prologue's tail* through a register the log does not track**,
   e.g. a `mov x13, xN` where `xN` was already zero, which *is* a change and would have been logged.

Settling it is small and mechanical: run **one** script that does both - the change-log hook and the
`0x1242bc` probe - in the same `render` call, and print the log entry immediately preceding each probe
result. That removes the possibility of two differing runs and makes the answer self-consistent.

**Why this is worth writing down**: three consecutive rounds have now produced a measurement that a later
measurement contradicted, and every one of those was a *measurement* problem rather than a finding. The
engine's inputs are verified, the prologue's gain is understood and fixable, and the remaining question is
one register inside the loop's opening - so the cost of one more careful, self-consistent measurement is
small, and the cost of acting on a contradictory one is large.

### Self-consistent measurement: `x13` at the multiply is the state's `+0x5c`

Running the change-log and the probe in **one** render call (the fix for the disagreement) gives a consistent
answer:

```text
probe (x13 at 0x1242bc, last write pc):
  ('0x0',       '0x1244ac')     first iteration
  ('0x0',       '0x1244ac')     second
  ('0x12b2f1a', '0x124184')     third
```

and the instruction at the loop's head explains the first two:

```text
0x124494  ldp  w11, w14, [x19, 0x5c]   ; w11 = state[+0x5c], w14 = state[+0x60]
0x1244a8  sxtw x13, w11                ; x13 = the *previous* frame's phase
0x1244b0  stp  w14, w8, [x19, 0x5c]    ; and this frame's is stored back
```

So `x13` is the state's `+0x5c` - the previous phase - and the `mul` at `0x1242bc` multiplies the lane
accumulator by it. Early samples being *exactly zero* is then **by design**: a saw's first sample is at phase
zero. The earlier probe reading zeros was reading the first iterations, not a fault.

**But the output is still all zero even later**, where `x13` is nonzero (`0x12b2f1a`) and `x15` is
`0x77748916` - so the product is nonzero and something *after* it, in the blend or the store, drops it.

**Where the port stands, stated plainly**: one register (`x13` = the previous phase) is now *explained*
rather than suspicious, the ADSR's level is *understood* (the first interface call's job), the harness
executes the whole engine, and every input upstream of the loop has been verified by measurement. What is
missing is the last hop: the product reaching `param_1` through the packed select at `0x124360`-`0x1243a4`.
The next measurement is the blend's *mask* - the `bic`/`orr` pair uses a sign-derived mask, and if that mask
is uniformly one way the blend selects the wrong operand.

### The store is zero 64 times out of 64

Hooking the store (`str d3, [x23, x9]` at `0x1243a8`) for the whole block, with the ADSR's level set:

```text
store count 64, nonzero stores 0
last three stores (offset, lo, hi): [(488, 0, 0), (496, 0, 0), (504, 0, 0)]
```

64 stores of 8 bytes each is the 512-byte block the loop's `lVar19 != 0x200` bound implies (two words per
iteration, the interleaved stereo pair the other engines also write). They are **all zero**, including the
late iterations where `x13` (the previous phase) is `0x12b2f1a` and the lane accumulator `x15` is
`0x77748916` - so a nonzero product exists in the registers and never reaches the buffer.

That makes the **packed select** at `0x124360`-`0x1243a4` the last suspect, and the listing shapes it
clearly:

```text
0x124360  bic v3.8b, v3.8b, v5.8b
0x124364  bic v5.2s, 0x80, lsl 24     ; clear the sign bit
0x12436c  bic v6.2s, 0x80, lsl 24
0x124380  orr v3.8b, v5.8b, v3.8b
0x124388  orr v4.8b, v6.8b, v4.8b
0x12439c  sqadd v3.2s, v3.2s, v4.2s
0x1243a4  sqadd v3.2s, v5.2s, v3.2s
0x1243a8  str  d3, [x23, x9]
```

A `bic`/`orr` pair against a sign-derived vector is a bit-select, and if its mask is uniformly one way the
blend consistently keeps the zero operand. The next measurement is that mask's origin - the instruction that
produces `v3`'s sign bits just before `0x124360`, which the loop's listing shows is a comparison of two
accumulated lane values.

**Summary of the state of this engine**: 3 180 bytes of dense NEON arithmetic, of which every *input* is now
verified by measurement (wavetable, index, fraction, operands, contributions, both host seams, the state map,
the phase pair) and one *bit-select* is unaccounted for. That is the port's remaining blocker, and it is one
instruction's provenance rather than a missing host input.

### The products are zero in all 64 iterations - the loss is in the lane pair

Reading the pair the select narrows (`q3`/`q4` at `0x124338`, `shrn v3.2s, v3.2d, 0x1f`):

```text
iterations 64 with a nonzero product 0
last two (q3, q4): [('0x0', '0x0'), ('0x0', '0x0')]
```

So the packed select is not dropping anything: **its operands are already zero**, every iteration. And the
select itself is now understood - it is the 2^62 sentinel blend, the same idiom the port already has:

```text
0x124334  cmeq v5.2d, v3.2d, v0.2d   ; v0 = 2^62, so v5 = "this lane's product is the sentinel"
0x124338  shrn v3.2s, v3.2d, 0x1f    ; the product narrowed by 31
0x124350  xtn  v5.2s, v5.2d
0x124364  bic  v5.2s, 0x80, lsl 24   ; the mask with its sign bit cleared
0x124380  orr  v3.8b, v5.8b, v3.8b   ; blend: narrowed product, or 0x7fffffff where the sentinel was
```

The scalar lane accumulator `x15` is nonzero in those same iterations (`0x77748916`), so the scalar path and
the vector path part company somewhere between the accumulator and the `zip1`/`zip2` that build this pair
(`0x12409c`/`0x1240a0`). That is the last gap, and it is a short one: the pair's two source registers at
`0x12409c` are the next thing to read.

**Honest summary of this engine's state after this round**: the select is *explained* (sentinel blend, same as
the port's other engines), the store is *explained* (accumulate-into, 64 interleaved pairs), the products are
*pinned* as the first zero going backwards, and everything upstream has been verified. One vector pair's
provenance remains.

### The lane pairs' sources are zero as well - the pair-building loop

Reading `q1`/`q2` at `0x12409c` (`zip1 v3.2s, v2.2s, v1.2s`), the instruction that builds the pair whose
narrowing the store sees:

```text
iterations 64 with nonzero sources 0
last two (q1, q2): [('0x0', '0x0'), ('0x0', '0x0')]
```

Both zero, all 64 times. And this address sits inside the *prologue's own loop* - the `0x124098`/`0x1240ac`
pair that the earlier trace showed repeating - so the prologue builds 64 lane pairs and every one is built
from zero sources.

That is one loop earlier than `0x124338`, and it means the zero is not in the store, the select, or the
sample loop at all: it is in the **prologue's pair construction**, whose inputs are the values the second
interface call is handed and the `+0x28`/`+0x30` sub-state fields the engine re-reads afterwards.

**The chain, from the store backwards, as it now stands:**

| site | value | verdict |
|---|---|---|
| `0x1243a8` store | 0 | explained: accumulate-into, 64 interleaved pairs |
| `0x124338` product pair | 0 | the first zero found going back |
| `0x12409c` pair sources (`q1`/`q2`) | 0 | one loop earlier, still zero |
| prologue inputs | `x17 = 0x55aded23`, `x16 = 0x507aaef2`, `[ADSR+4]` once set | nonzero |

So the two ends of the prologue are healthy and its middle - the pair construction that consumes the
`+0x28`/`+0x30` sub-state - produces zeros. Those two fields are the ones the engine re-reads after the
second interface call, and the callback is what the device's host uses to fill them.

**The next action, and it is the decisive one**: service the second interface call by writing the four
values it is handed into `+0x28` and `+0x30` (four words each) *and* re-running the measurement above, rather
than writing them into `+0x20` as the earlier attempt did. If the pair sources become nonzero, the engine is
solved; if they do not, the fields are not what the callback is for and the C's re-read list is the thing to
re-read.

### The second callback's four values do not fill the pair inputs either

Servicing the second interface call by writing its four arguments into `+0x28` and `+0x30` (four words
each, the fields the C re-reads) leaves the output silent. Combined with the earlier write into `+0x20` and
the eight-word write at `+8`, all three plausible shapes for that callback have now been tried.

**What that means**: the callback's *arguments* are not what the engine wants back - so the C's
`(**(code **)(*(long *)puVar10 + 0x38))((long)param_4 + 8, uVar21, uVar1, uVar3, uVar24)` is a *notification*
with state-derived values, and the pair construction's zeros come from somewhere else entirely.

**Ruled out for the pair construction**, each by a measurement rather than an argument:

* the ADSR's level (set, and the prologue's gain became nonzero);
* the five constants (at full scale);
* the callback's four values, written to `+8`, `+0x20`, `+0x28`, `+0x30`;
* the host tables' contents (Q31 sines, and the load was verified nonzero);
* the first callback serviced by ramping the ADSR.

**What has not been checked**: the *scalar* register file between the prologue's verified inputs
(`x17 = 0x55aded23`, `x16 = 0x507aaef2`, and the products at `0x124218`) and the pair construction at
`0x12409c`. The trace method that found `x20` = ADSR and `x13` = the previous phase works; it has not yet
been run over `0x123994`..`0x124098` for the *specific* registers the `zip` at `0x12409c` consumes (`v1` and
`v2`'s scalar ancestors).

## Audit against the objective (this round)

The objective is: finish every phase, each verified exact to the original library functions, committed and
tagged. Checked against the repo, not against memory:

| phase | state | evidence |
|---|---|---|
| 1 | **done, tagged** | `phase-1` |
| 2 | **done, tagged** | `phase-2` |
| 3 | **done, tagged** | `phase-3` |
| 4 | **done, tagged** | `phase-4`; `Synth::render` 14/14 whole-mixer cases with the `CHECK_MASTER` gate removed; the ported chain wired into `Engine` and merged to `main`; realtime safety measured |
| 5 | **not done** | `Saw013a` is the one outstanding item: `init`/`initModule`/`onNoteOff` are ported and C-verified, `render`/`onNoteOn` are **not ported**, the harness drives the whole engine but it renders silence, there are **no fixtures** for it, it is **not wired** into a track, and Phase 5 is **untagged** |

Everything is committed: the clone's `main` is clean with the Saw013a harness work at `261b624`
(`c80f660`, `8d3cfae`, `99880a4`, `871d6dc`, `d215af5`, `261b624`), and this worktree holds `SAW013A.asm`,
`SAW013A-decomp.c` and this file.

**The honest position**: after many rounds on this engine the blocker is a single unknown inside one dense
3 KB function - the pair construction at `0x12409c` - while every input around it is verified by measurement
and two of its registers (`x20` = the ADSR, `x13` = the previous phase) are now *explained* rather than
suspicious. The three frames that were checked and found wanting (a patch file for the wiring, single-address
register probes, and the low-word/truncated-log readings) have all been replaced by working ones: the wiring
is a git branch, and the trace-based measurement has not produced a wrong answer yet.

**The next concrete action** is the one written above and not yet run: trace the scalar ancestors of the
`zip` at `0x12409c` (`v1` and `v2`'s sources) across `0x123994`..`0x124098`, the same way `x20` and `x13`
were found.

### The pair's sources are healthy and the pair is still zero: the loss is one multiply-subtract

Reading the four scalars the pair is built from, at `0x123ff4` (`mov v1.s[1], w13`):

```text
at 0x123ff4 (w12, w13, w14, w9): [('0x80000000', '0x1', '0x7fbfbfbf', '0x404041')]
```

All four nonzero. And reading the packed result only a few instructions later, at `0x124054`
(`sshr v8.2s, v1.2s, 8`, i.e. right after `sqsub v1.2s, v1.2s, v3.2s`):

```text
at 0x124054 (q1, q2, q8): [('0x0', '0x0', '0x0')]
```

So between `0x123ff4` and `0x124054` the value is lost, and that window is short and fully listed:

```text
0x123ff4  mov   v1.s[1], w13
0x123ffc  mov   v2.s[1], w9
0x124004  ushll v1.2d, v1.2s, 0     ; widen the pair
0x124008  ushll v2.2d, v2.2s, 0
0x12400c  fmov  x9, d1              ; x9 = v1.d[0]
0x124010  mov   x12, v1.d[1]
0x124018  mul   x9, x11, x9         ; the per-lane product
0x124024  mul   x11, x8, x12
0x124028  fmov  d1, x9
0x124034  mov   v1.d[1], x11
0x124040  shrn  v1.2s, v1.2d, 0x1f  ; narrow by 31
0x12404c  sqsub v1.2s, v1.2s, v3.2s ; minus the state's 0x4c block
0x124054  sshr  v8.2s, v1.2s, 8
```

Two candidates inside it, both cheap to separate:

1. **the multiply** (`0x124018`/`0x124024`): its second operands are `w11` and `w8`, and the state's `+0x50`
   and `+0x58` load into that area earlier (`ldp w16, w14, [x19, 0x54]` and friends). If either is zero the
   product is zero;
2. **the `sqsub` at `0x12404c`**: subtracting the state's `0x4c` block (`ldur q1, [x19, 0x4c]` at `0x123d74`)
   will cancel the value exactly if the two are equal; in the harness `+0x4c` holds `0x55aded23`, which
   `onNoteOn` wrote, so this is the more suspicious of the two.

The measurement that separates them is a hook at `0x124040` (the narrowed product, before the subtract) and
at `0x12404c` (the subtrahend `v3`), which the trace pattern gives directly.

### The pair's multiplier `w11` is zeroed at `0x124024`

Tracing `x11` across the prologue gives its last writes:

```text
0x123f88 -> 0x0
0x124020 -> 0x7fbfbfbf
0x124028 -> 0x0            (the effect of 0x124024's `mul x11, x8, x12`)
```

So the multiplier the pair is built with is **zeroed by `mul x11, x8, x12` at `0x124024`**, and the earlier
direct probe at `0x12404c` confirms the consequences: `w11 = 0`, `x9 = 0` (`mul x9, x11, x9`), the narrowed
pair `q1 = 0`, and the `sqsub`'s subtrahend `q3 = 0` as well.

Two facts worth keeping from that probe:

* `x8` at that point held a **harness address** (`0x200000111314` - inside the stub page the harness
  allocated for the engine's callbacks), which means `x8` is a *host pointer* the engine is multiplying
  *by*; that is worth checking against the C, because a pointer used as a multiplicand suggests the register
  holds something else by then;
* `x12` = `1`, so the `mul`'s zero must come from `x8`.

**Next**: read `x8` and `x12` at `0x124024` itself (full width), and if `x8` is genuinely zero there, trace
`x8`'s writes over the same range. The trace pattern has now found four registers' stories - `x20` = the
ADSR, `x13` = the previous phase, `x11`'s last write, and the pair's zeroing - so it is the right tool for
the last link too.

### The zero is a halfword host table the harness never fills

`x8`'s last write in the prologue is at `0x123eb0`, and the listing shows what that address really does:

```text
0x123ea4  add   x11, x11, 0x890            ; the table base
0x123ea8  mov   w12, -0x80000000
0x123eac  ldrsh w8, [x11, w8, uxtw 1]      ; x8 = a *signed halfword* table entry, indexed by the old x8
0x123eb0  ldrsh w9, [x11, w9, uxtw 1]      ; and the same for x9
0x123eb4  mov   w11, 0x7fff
0x123ec0  sub   w9, w9, w8                 ; their difference
```

`x8`/`x9` therefore come from a **16-bit table at `x11 + 0x890`**, indexed by two small integers (the trace
showed the indices passing through 3 and 4), and the table is **all zero in the harness** - so `x8` = 0,
`w11` = 0, the pair's products are 0, and the engine renders silence.

**This is the same class of missing input as the wavetables**, and it is the root cause of everything
downstream: one more host table the fixtures have to fill, exactly as `AnalogA`'s filter banks and rate
tables had to be.

**Next**: find the base address of that table - `x11` before the `add 0x890`, which the same trace pattern
gives in one pass - and fill it with a documented ramp, then re-run. Given the pattern of this engine's other
host data (five sine tables behind a pointer array, five constants in `.bss`), this is most likely another
`.bss`/`.rodata` block the firmware populates, and a documented monotone ramp is the calibration the
fixtures should record.

**Why this is the important result of the round**: three registers' stories (`x20` = ADSR, `x13` = previous
phase, `x11`'s zeroing) all pointed at the pair construction, and this closes it - the zero is not arithmetic
at all but a table the host must supply, which is precisely the kind of gap the fixture harness exists to
find.

### The table's base, and what filling it does

The base is `0x124a890` (probed at `0x123eac`, with indices 4 and 5 in the run) - the same `.data`/`.bss`
region as the five constants (`0x124a5cc`..`0x124a5dc`), and zero in the shipped library, so it is firmware
data the same way they are.

Filling it does **not** simply make the engine sound. Both attempts - a full-scale ramp across 64 `i16`
entries and a small ramp (`1..64`) - make `render` fault on an **unmapped read** instead. That is
informative rather than discouraging: it says the entries are not consumed as plain scalars but steer a
further dereference, so this table's *values* index or point at more host data the harness does not have
either.

**So the remaining gap is host data, and it is layered**: one halfword table at `0x124a890` whose contents
select what comes next. That is exactly the shape `AnalogA` needed (five filter banks behind an interface
pointer, plus coefficient records and rate tables), and it is the shape the fixtures exist to record.

**The two candidate routes from here**:

1. **find the firmware's values.** The engine ships as a `dlc-asset` with no data, so this means the app's
   own `.bss` initialisation - the same place `AnalogA`'s banks and `Digital`'s wavetable come from. If those
   were recovered from the firmware image, this table's contents should be there too;
2. **take it as harness calibration**, the way the analogue engine's banks were taken, with a documented
   monotone ramp - but only after finding what the entries are *used* for, since the unmapped read says the
   choice of values changes the path rather than just the level.

**What this round establishes**: the engine's silence is not arithmetic. Every register story traced
(`x20` = ADSR, `x13` = the previous phase, `x11`'s zeroing, `x8`'s load) converges on a **16-bit table at
`0x124a890` that the harness leaves zero**, and filling it changes the control flow. That is the port's
remaining blocker, stated as a data gap rather than a code one.

### The values exist locally: the firmware image is on this machine

Two things this round settled, and they point the same way.

**1. The table is real and its values are the missing input.** Verifying the write landed (`read back: 32767`)
and hooking the load (`x8 after the ldrsh: ['0x7fff']`) shows the entry is loaded correctly - and a *nonzero*
entry then drives the engine into an **unmapped read**. So the entries are not a unity table: their magnitude
steers a further dereference, which is why a flat `0x4000`, a small ramp and `0x7FFF` all fault while zero
happens to keep the engine on a safe path.

**2. The harness already documents this class of table.** `opzso.py` carries

```python
GAIN_CONST_5CC    = 0x124A5CC    # i32 used as a Q31 multiplier in the gain chain
PER_OCTAVE_TABLE  = 0x124A7B0    # 16 x i16, indexed by octave in onNoteOn and by the count class in render
DEFAULT_HOST_TABLE = 0x7FFF      # unity for PER_OCTAVE_TABLE
```

with the comment "Addresses inside the library's `.bss` that the *firmware host* fills; the `.so` ships them
zeroed. Measured, not guessed". `0x124A890` is a third table in that same region (`0x124A7B0` + 0xE0), so it
belongs in that list - with the *firmware's* values, not a guess.

**And the values are available**: `~/.opz-decode/` holds `z_firmware_1_2_45.zfw` plus raw installs
(`raws/install_z_firmware_1_2_45_*.bin`), and this worktree has `decrypt_zfw.sh`. Finding the table's contents
there is a local, offline job - no device interaction, so it does not touch Phase 5's "no device interaction of
any kind" criterion.

**Next**: decrypt or read the firmware image and locate the block that initialises `0x124A890`'s region
(alongside `0x124A5CC` and `0x124A7B0`), then fill the harness from it - the same way the wavetable and the
five constants were filled, but with recovered values rather than calibration. If the image turns out to be
encrypted beyond what `decrypt_zfw.sh` handles, that is the blocker to report, with the exact file and the
script's failure.
