# 11. The `.engine` module format and ABI

Everything in this document was read out of the shipped modules and out of `opz.ldr` itself, then
machine-verified: `toolkit/opzengine.py verify engines-official/*.engine` repacks all 21 factory engines
and reproduces every byte. Where something is still unknown it says so rather than guessing.

The point of the document is to make a *new* engine possible, so it is written as a specification of what
a module must contain rather than only as a description of what the existing ones do.

## 11.1 A module is a list of load segments, not an image

An `.engine` file is not an ELF and not a flat binary. It is a sequence of segments, each introduced by a
16-byte header:

```
+0x00 u16  flags       bit 15 = last segment, bit 8 = fill (zero) instead of copy
+0x02 u8   checksum    XOR of the other 15 header bytes
+0x03 u8   0xAD        magic
+0x04 u32  destination absolute Blackfin+ address
+0x08 u32  length
+0x0c u32  fill value  only meaningful when flags bit 8 is set
```

followed by `length` bytes of payload — **except** for a fill segment, which zeroes `length` bytes of memory
and carries no payload at all. That asymmetry is the one easy way to get a parser wrong: it is what
distinguishes the two largest factory engines (`ep`, `organ`) from the other nineteen, and a parser that
assumes a payload for fill segments desynchronises roughly two thirds of the way through each of them.

The loader that consumes this is `FUN_8002ac00` (unanalysed on disk; established by hand from its `LINK`):

1. reject the module if `header[3] != 0xAD` (`Bad header`, `dlm.cpp:0x43`);
2. reject it if the XOR checksum disagrees (`Bad header checksum 0x%02x != 0x%02x`, `dlm.cpp:0x48`);
3. reject it if any destination falls outside the window the caller supplied (`Bad address`, `dlm.cpp:0x57`);
4. reject it if a payload would run past the end of the buffer (`Data outside buffer`, `dlm.cpp:0x66`);
5. copy (or zero) each segment, then flush the instruction cache over the covered range.

So the module's load addresses are **absolute and pre-linked**. An engine is not position independent and
cannot be relocated by the loader; a new engine has to be built for the address range it will occupy.

A factory module is five segments, in this order:

| segment | destination | typical length | contents |
|---|---|---|---|
| preamble | `0x11a00000` (L1 instruction) | 0 | the fill field carries the total payload size |
| module header | DDR, e.g. `0x81be2400` | 56 | the two magics and the export table |
| code | DDR, header + 0x38 | 760–9792 | code *and* the rodata strings |
| variables | DDR, directly after the code | 8–424 | the module's zero-initialised working area |
| terminator | `0x11a00000` | 0 | flags `0xad9c8000`, marks the last segment |

Two details worth stating plainly, because both are surprising:

- **Code runs from DDR, not from L1.** The destinations are `0x81xxxxxx` (external memory); the `0x11a00000`
  segments carry no bytes. Engines execute through the L1 cache, which is why the loader finishes by
  flushing it.
- **Every factory module ends with the identical terminator** `00 80 9c ad 00 00 a0 11 00 00 00 00 00 00 00 00`.

## 11.2 The module header is 56 bytes: two magics and five export pairs

```
+0x00 u32  0xfeed0ad1
+0x04 u32  0xad1facef
+0x08      five pairs of (name pointer, function address), 32-bit absolute
```

The five names are, in every one of the 21 factory engines, exactly:

| name | role |
|---|---|
| `initModule` | module construction |
| `init` | per-instance initialisation |
| `render` **or** `renderFX` | the DSP entry point — never both |
| `onNoteOn` | note start |
| `onNoteOff` | note end |

The loader resolves them **by name** (`FUN_8002abe4(name, handle)` walks the pairs), and then requires
`init`, `onNoteOn` and `onNoteOff` to be non-zero and at least one of `render`/`renderFX` to be non-zero,
or it reports `Could not lookup symbols for engine %s` (`dlm.cpp:0xcd`). The resolved pointers are stored in
the OS-side record as:

```
+0x00 init      +0x04 renderFX      +0x08 render      +0x0c onNoteOn      +0x10 onNoteOff
```

Thirteen engines export `render` (instruments) and eight export `renderFX` (effects); the split is enforced
by which name resolves, so an engine is an instrument or an effect depending on what it publishes.

## 11.3 `initModule` hands the engine a host services table

```
int initModule(int module_id, void *host_table, int *out)
{
    if (module_id != <the module's own expected constant>) return 0;
    <module global> = host_table;      /* saved, used during render */
    *out = 0;
    return 1;
}
```

Read from `chord.engine` (`0x81be2444`) and cross-checked against `volt` and `digital`. The return value is
the loader's `ret not ok` gate, so a module that returns 0 fails to load. The `module_id` check means the OS
passes an identifier the module must already know — a module cannot be validated against itself, so a new
engine needs to know what value it will be handed.

The **host table is the engine's only way back into the OS** — modules import nothing, they are self-contained
code with absolute addresses. `chord.engine` calls `host_table[7]` (offset `+0x1c`) during render with five
arguments. The full table layout is not yet mapped; only that one entry is known to be used by `chord`.

## 11.4 `init` and the two render signatures

```
void init(void *ctx, int variant);        /* zeroes 0x20 bytes, then selects a table by variant */
void    render  (int *ctx, int a2, int a3, int *state, int *plug, int voice);   /* instruments, 6 args */
void    renderFX(int *ctx, int a2, int *state, int *in, int *out);              /* effects,     5 args */
```

The instrument signature is identical across `chord`, `digital` and `volt` — three independent engines, same
six arguments — so the shape is reliable even though the argument *names* still are not. What is known
about the effect side is much more complete, because effects must actually touch the audio:

- `in` is read and then advanced by **2 words per iteration**; `out` is written and advanced by 2. So audio is
  **32-bit words, interleaved stereo, two per frame**;
- `state` is a small array written back before returning (`state[0..5]` in `crush`);
- `a2` is clamped to `>= 0` and `<= 0x8000` before use, which is a Q15 parameter with a `0x8000` full scale;
- a phase accumulator advances by `0x10000` per frame, i.e. Q16 phase;
- a module global holds a pointer to per-instance storage, so engines keep their working area in their own
  variables segment and a pointer to it.

For instruments, the observable facts are: `voice+0x10` is tested and an early return happens when it is
zero (a gate); `plug` is an array of per-track values a few of which are frequencies; one entry of `plug`
(`plug[4]` in `chord`) is an object whose `+0xc` is dereferenced as a table indexed by a shifted phase — a
sample or wavetable read. **Which argument carries the output buffer for an instrument is not established**,
and it is the single thing that must be settled before a new instrument can make sound.

## 11.5 The surrounding structures

| thing | value | source |
|---|---|---|
| plug array | `0x80045ac8`, stride `0x7ac`, 200 entries (`0x5fe60` B) | `FUN_800feca0`, `FUN_800ff454` memset |
| plug slot allocator | `FUN_800fb5e4`, scans for a free entry, returns `-1` when full | `plug count full`, `PlugManager.cpp:0x2be` |
| plug definitions | rebuilt from `settings/plugs.json` (`memoryslot`, `version`, `plugId`) | `FUN_800ff454` |
| engine record | `init`, `renderFX`, `render`, `onNoteOn`, `onNoteOff` at `+0x00`, `+0x04`, `+0x08`, `+0x0c`, `+0x10` | `FUN_8002b02c` |
| module loader | `FUN_8002ac00` (segments), `FUN_8002ae50` (open), `FUN_8002b02c` (symbols) | `dlm.cpp:0x43–0xcd` |
| host services | passed to `initModule`, `+0x1c` used by `chord` | `chord.engine` |

`plugs.json` itself carries no parameter metadata — only engine path, flags, id, samples and version per
plug — so the eight knob values an engine sees are produced on the device, not configured in that file.

## 11.6 What is still missing for a new engine

1. **The instrument render's argument meanings**, specifically which one is the output buffer and which is
   the frame count. This is the blocking unknown.
2. **The module identifier** the OS passes to `initModule`, which a module must match to load at all.
3. **The load window rule.** Factory engines sit at distinct absolute DDR bases (`0x81b32000` … `0x81c07c00`)
   and `plugs.json` names a `memoryslot` per engine, but no table mapping slot to address exists in the
   image as a plain dword array, so whether the window is derived from the module's own addresses or from a
   reserved arena is unresolved.
4. **Whether the hardware CRC unit is applied to engine modules.** `bf_crc.cpp`'s init (polynomial
   `0x4c11db7`, DMA mode) runs in this neighbourhood, and the engine install path is known to be gated only
   by the ZIP entry CRC, so a load-time CRC over the module would be a second gate that a hand-built engine
   must satisfy.

## 11.7 What is already solved

- the segment container, its magic, its checksum, its fill semantics and its terminator — verified by a
  byte-exact round trip over all 21 factory engines (`toolkit/opzengine.py verify`);
- the 56-byte module header, the two magics and the five named exports, including which of them are
  mandatory;
- the OS-side record layout and the loader's validation order and messages;
- the effect-side render signature, buffer layout and fixed-point conventions;
- the plug array, its stride, its 200-entry limit, and the fact that plug definitions come from
  `settings/plugs.json` rather than from the modules.

## 11.8 Reproducing any of this

```bash
T=toolkit/opzengine.py
GH=/path/to/Ghidra_12.1.4/support/analyzeHeadless

python3 $T dump   engines-official/chord.engine    # segments + the five exports, resolved
python3 $T expand engines-official/chord.engine    # -> chord_flat.bin, a loadable image
python3 $T verify engines-official/*.engine        # byte-exact repack, 21/21

$GH /tmp/eng ENG -import chord_flat.bin \
    -processor "blackfinplus:LE:32:default" \
    -loader BinaryLoader -loader-baseAddr 0x81be2400
```

Two things to get right, both of which cost time when wrong:

- **The language id is `blackfinplus:LE:32:default`** — lowercase, with the `+`, an artifact of the separate
  Ghidra BlackFin+ extension. `Blackfin:LE:32:default` is rejected outright with `Unsupported language`, and a
  `.ldr` never shows you this because its own loader auto-detects the language from the boot-stream header.
  Only the *engines*, which are headerless once expanded, need it spelled out.
- **The load base is the module's own first data destination** (chord's is `0x81be2400`, which is the `0x04`
  field of its second segment). Getting it from anywhere else — the `0x11a00000` preamble in particular —
  produces an image that disassembles into nonsense.

The Ghidra project directory must also already exist: `analyzeHeadless` reports `Directory not found` for the
project path rather than creating it.

## 11.9 The argument semantics, resolved

Section 11.6 previously listed four unknowns. Three are now settled; the fourth is reduced to a single
hardware check. Everything below was read from the callee's own prologue and loop body, not from the
decompiler, because the decompiler hides register-carried arguments (doc `09` §9.4).

**`initModule` receives `(0, 0x81003850, out)`.** The call site in `FUN_8002ae50` is unambiguous:

```
8002af8e  R0 = R0 - R0 (NS)     ; module id = 0
8002af96  R1 = 0x81003850       ; host services table
8002af92  R2 = [SP + 0x38]      ; out pointer
8002af9e  Call CALL (P1)        ; initModule
```

The module's own copy of the expected id is a variable in its data segment, and in `chord` (`0x81be2d70`)
it is **0** — so the guard is an ABI-version check, not a per-engine identity. A new engine must expect 0.

**The host services table is 13 pointers at `0x81003850`.** Entries 0–12 mix code from three memories — L2
(`0x0800bb44`), the L1 overlay (`0x11b019e8`), DDR (`0x8010xxxx`, `0x8003xxxx`) — with three data pointers
(`0x81128264`, `0x815c8070`, `0x815c7e70`). `chord` calls entry 7 (`0x800314c0`) with
`(env, params[2], params[3], params[4], params[5])`, and that function is a **parameter smoothing service**:
it reads `env[4]` as a state machine, writes `env[0]` as the current value, and indexes the curve tables at
`0x815c7c70` and `0x815c7e70` by the top byte of its scalar arguments — the second of which is itself
`host_table[6]`. So the table is the engine's route to OS-wide helpers, and the curve tables are shared.

**The instrument render is `render(out, freq_q16, offset, state, params, env)`**, established from `chord`'s
prologue and loop:

```
81be2552  P4 = R0              ; arg 1 -> P4
81be2550  P1 = [FP + 0x14]     ; arg 4 -> per-voice state
81be2554  P5 = [FP + 0x18]     ; arg 5 -> parameter array
81be254c  P3 = [FP + 0x1c]     ; arg 6 -> amp/envelope object
81be2548  R7 = R1              ; arg 2
...
81be2794  LSETUP (0x81be290c) LC0 = 0x40      ; 64 frames
81be28ba  [P4++] = R0                         ; left
81be28ce  [P4++] = R0                         ; right
```

So **argument 1 is the audio output buffer**, interleaved 32-bit stereo, two words per frame, and the block is
**64 frames**. `param_6`/arg 6 is not a buffer at all: `voice+0x10` is the amp state machine and zero there
means idle, which is the early return every instrument render starts with. Argument 2 is a **frequency in
Q16** (`f x 65536`): `chord`'s octave thresholds in its data segment are `0x00184cbb`, `0x00309977`,
`0x006132ee` and `0x0184cbb7` = 1,592,507 / 3,185,015 / 6,370,030 / 25,480,119, which are 24.30, 48.60, 97.20
and 388.8 Hz — exactly a factor of two apart, at G0/G1/G2/G4 pitch. Argument 3 is added to argument 2 before
scaling (a bend or detune term). Argument 5 is a read/write parameter array: `chord` reads indices 0–5, 0x10,
0x14, 0x28 and 0x2c, and `volt` reads 0, 1, 4, 5, 0x10 and 0x14.

**The effect render is the same shape with five arguments** — `renderFX(ctx, scalar, state, in, out)` — and it
hardcodes the same block size: `crush` sets `iVar28 = 0x40` before its loop. Input is read and output written
through post-incremented pointers, two words per frame.

**`onNoteOn` receives a pitch and the voice context.** `chord`'s prologue zeroes `R2` through
`FUN_81be2474(R2, 0, 0x20)`, which is the same 0x20-byte clear `init` performs, so **`R2` is the voice
context**; `R1` feeds `0x1020408 * R1 + (R1 >> 4)` and is then scaled by a constant at `ctx+0x2c`, which is
the shape of a note-to-frequency exponential with a per-module tuning factor.

**Caveat on `onNoteOn` being called at all.** Tracing the OS side of the contract (doc 12 §12.10) puts a
serious qualification on this section: the sequencer's note-start path calls `init` (`FUN_8012d278`) and then
`render` (`FUN_8012e2c0`) every tick, and **nothing in that path invokes `onNoteOn`**. A complete scan of the
image's 1020 indirect call/jump sites turns up no site that loads the instrument record's `+0x08` slot, which
is where `onNoteOn` is stored. The export is resolved and its address is kept, so the engine must still
*provide* it - the loader rejects a module without it - but on this evidence it is not what starts a note in
the sequencer. Pitch therefore comes from `render`'s argument 2 (Q16), not from `onNoteOn`'s `R1`, which
answers the question left open below in favour of `render` while leaving `onNoteOn`'s own arguments unverified.

### What still needs the device

One thing: whether `onNoteOn`'s `R1` is a note number or an already-scaled frequency, and therefore whether an
engine should derive pitch from `R1` or simply use `render`'s Q16 frequency argument. The Q16 reading of
argument 2 is strongly supported but rests on the octave ratios rather than on a units string. The decidable
test is one note long — render a note, measure the output frequency, and compare against 440 Hz for A4; a
wrong assumption shows up as a constant ratio, not as noise.

An engine that ignores argument 2 and computes its own increment from `R1` at note-on is therefore the safer
first build: it depends on only one unverified assumption instead of two.

## 11.10 Tooling status

Two tools exist and both self-verify:

| tool | does | proof |
|---|---|---|
| `toolkit/opzengine.py` | parse, dump, expand and repack `.engine` containers | `verify` repacks all 21 factory engines byte-exactly |
| `toolkit/opzasm.py` | encodes the Blackfin+ subset an engine needs | `selftest` matches 10 encodings against bytes taken from `volt`/`chord` |

`opzasm.py` deliberately raises `Unsupported` rather than emitting a guess: a wrong encoding yields an engine
that loads and misbehaves, which is far worse to debug than one that refuses to build. Encodings are
transcribed from the processor module's SLEIGH source, then confirmed against real instruction bytes — the
verified set is 16-bit register move (`P4 = R0` → `2032`) and 16-bit add/subtract (`R1 = R7 + R1` → `4f50`),
with the field layouts for `LdImmHalf` and `Dsp32Mult` already read out of the same source.

**What remains before an engine can exist**: encode the load/store forms (`[P++] = R`, `R = [P + off]`), the
32-bit multiply, the branches and the epilogue; write the modal DSP against the ABI in §11.9; emit the
container; then the one hardware test in §11.9 that settles whether `onNoteOn`'s `R1` is a note number.
None of that can be validated by static analysis alone, which is why §11.9 states the hardware check
explicitly instead of assuming the answer.

## 11.11 The struck-body DSP, validated as an algorithm

`toolkit/opzstruck.py` is the modal resonator written as fixed-point reference code — the same integer
arithmetic the engine will run — with a self-test that measures the result instead of trusting it:

```
PASS  pitch 110 Hz       measured 110.5 Hz (0.48% error)
PASS  pitch 220 Hz       measured 220.4 Hz (0.18% error)
PASS  pitch 440 Hz       measured 439.5 Hz (0.11% error)
PASS  pitch 880 Hz       measured 876.4 Hz (0.41% error)
PASS  decay grows with macro   T60 0.46 < 0.94 < 1.84 s
PASS  inharmonicity keeps pitch  220.4 vs 220.4 Hz
PASS  peak stays in range      peak 0.800 full scale
PASS  decays to silence        tail 1.05e-06
PASS  deterministic            identical buffers
```

Two findings from building it are worth keeping, because both would have cost hours on hardware:

**Direct form II does not fit this core's arithmetic.** The textbook two-pole recursion needs
`a1 = 2*r*cos(w)`, which reaches almost 2.0 — outside Q31, whose maximum is just under 1.0. In the first
build that coefficient saturated, and the resonator then oscillated at the wrong frequency. The fix is the
coupled (rotation) form, `y1' = r*cos(w)*y1 - r*sin(w)*y2`, `y2' = r*sin(w)*y1 + r*cos(w)*y2`, whose two
coefficients are inside ±1 by construction and whose decay comes from `r < 1` shrinking the state each
sample. It costs four fractional multiplies per mode per sample instead of two, which is the right trade.

**A correctly interleaved block looks like a subharmonic if you forget it is stereo.** The self-test first
reported *exactly half* the requested pitch at every frequency. The control experiment — the same estimator
run on a pure sine — returned the right answer, which localised the fault to the code under test rather than
the measurement. The block writer was right: it emits two words per frame as the ABI demands, so every
sample appears twice, and the analysis was reading the interleaved buffer as mono. Any future measurement
of engine output must take one channel. The estimator itself is a direct DFT peak scan; autocorrelation was
tried first and produced octave errors (56 Hz for a 220 Hz note) because an unnormalised sum on a decaying
multi-mode signal is dominated by short lags.

## 11.12 Encoder coverage, form by form

`toolkit/opzasm.py` states its own coverage in `selftest`, which compares every emitted form against bytes
lifted from `volt`/`chord`. This table is the same information as a plan:

| form | SLEIGH source | status | evidence / note |
|---|---|---|---|
| `P = R`, `P = P`, `I = P` | `11-RegMv` | **verified** | `P4 = R0` → `2032`; gd 1 = P, 2 = I; gs 0 = R, 1 = P, 2 = I |
| `Rd = Rs0 ± Rs1` | `15-Comp3op` | **verified** | `R1 = R7 + R1` → `4f50`; opc@9-11, dst@6-8, src1@3-5, src0@0-2 |
| `[P++] = R`, `R = [P++]` | `18-LdSt` | **verified** | `[P4++] = R0` → `2092`; store sets bit 9; ptr@3-5, reg@0-2, sz@10-11 |
| `LINK n`, `UNLINK`, `RTS` | `35-Linkage`, `01-ProgCtrl` | **verified** | `LINK 0x78` → `00e81e00` (the frame field is in **words**: 0x1E); `UNLINK` → `01e8`; `RTS` → `0010` |
| `JUMP.S` | `10-UJump` | **verified** | 12-bit half-word offset from the instruction: `bc22` reaches +0x578 |
| `Rd = Rs0 * Rs1 (T)` | `26-Dsp32Mult` | **verified (layout)** | second half solved: `h2 = 0x2000 | dst<<6 | src0<<3 | src1`; the first half appears as `0xca31` or `0xc231` for the same displayed form, differing in bit 11 |
| `Rd = imm7` | `16-CompI2op` | **verified** | `R2 = 0x20` → `6102`, `R1 = 0` → `6001`; 13/13 exact across both engines |
| `Rd = imm32` | `instr64/38-LdImm` | **verified** | an **eight-byte** instruction: `0xDA00|reg`, immH, immL, dummy. `R2 = 0x7fffffff` → `02daff7fffff0000`. 18/18 exact |
| `if CC JUMP`, `if !CC JUMP` | `09-BrCC` | **verified** | `if !CC JUMP +4 (BP)` → `0214`; 13/13 exact across both engines |
| `Rd = Rs >>> n` | `29-Dsp32ShfImm` | **partially solved** | second half: sop@14-15, hls@12-13, dst@9-11, imm@3-8 **signed**, src@0-2. For the logical form (sop 0) the field holds **-n**: n = 6, 1 and 31 encode as 58, 63 and 33. The arithmetic form (sop 2) does not follow that rule in the samples collected and is unresolved |
| `P += imm`, `[P + off]` | `13-Ptr2op`, `17-LdStPmod` | **deliberately avoided** | `P1 += 8` is a 32-bit instruction (`416c 88e4`) whose immediate field (`6f81` for -0x10, `6c41` for +8) is not yet decoded. The engine design does not need it: per-mode state is walked with post-increment, and a second pointer is obtained with the register move `P3 = P4` instead of an offset |

Two consequences worth carrying forward. First, **`LINK`'s frame field is in words, not bytes** — a reader who
assumes bytes builds a frame four times too large and corrupts the caller's stack. Second, the shift field's
sign convention means a logical right shift is written as a negative count, which is exactly the kind of
detail that produces code that assembles, loads and computes nonsense.

The encoder now covers every form the DSP needs — **26/26 verified against factory-engine bytes**, including
three found this round: conditional branches, the 7-bit immediate and the eight-byte 32-bit immediate. Two
are worth spelling out because both disguise their shape:

- **`Rd = imm32` is eight bytes**, not four (`0xDA00|reg`, immH, immL, dummy). Reading four bytes of it makes
  the immediate look half-encoded, which is exactly the misreading that stalled this earlier.
- **`LINK`'s frame field is in words**, so `LINK 0x78` stores `0x1E`.

A third trap belongs to the harness rather than the ISA: hand-written byte expectations in `opzasm.SELFTEST`
were wrong three times on 32- and 64-bit forms, always by writing the half-words in big-endian order. The
programmatic check — re-encode every instruction found in a real engine and compare against the bytes in the
image — was right every time. **Expectations should be lifted from the image, never typed from the listing.**

### The multiply's extraction mode is a choice, not a given

`Mult32` is really `Mult32` plus an *extraction* operator, and the modifier bits select which one runs
(`26-Dsp32Mult.sinc`): `strunc4_sat` and `trunc4_sat` apply a four-bit truncation and saturation, the
`dxM32I & dxM32TNS` variant writes the raw low word with no shift at all, and the `Reg8` variants extract
eight bits signed or unsigned. The seven modifier strings — `(T)`, `(IS)`, `(NS)`, `(M)`, `(M,T)`, `(M,IS)`,
… — are selects into that set.

The practical consequence: **the engine must pick the variant that performs the Q31 fractional shift, and the
choice is a decision to be made deliberately and then measured, not copied from whatever the compiler happened
to allocate.** The factory samples collected here are all the `(T)` form, and their extraction is not the plain
`(x*y) >> 31` that `toolkit/opzstruck.py` uses — so the reference implementation and the emitted code are not
yet bit-identical, and that difference is the last thing standing between "the algorithm is validated" and
"the module is validated". It is measurable on the device: a wrong extraction shows up as a level error or
as truncation noise, and the self-test's pitch and decay measurements would fail the same way they did when
the Q31 coefficient overflowed.

## 11.13 The engine builds

`toolkit/build_struck.py` assembles the module and writes a loadable `.engine`:

```
$ python3 toolkit/build_struck.py struck.engine
wrote struck.engine (6848 B)
  header 56 B @0x81c0a000   code 504 B @0x81c0a038   data 6208 B @0x81c0b000
  container round-trip: parsed OK
    initModule   0x81c0a038
    init         0x81c0a058
    render       0x81c0a0d6
    onNoteOn     0x81c0a07e
    onNoteOff    0x81c0a0c6
```

It round-trips through `opzengine.py` (segment magic, checksums, the five exports), and the emitted
instruction stream decodes back to what was intended — including the two things composition can break: the
patched branch offsets (`if !CC JUMP 0x81c0a054` lands exactly on the `im_fail` label) and the absolute
addresses (`R0 = -0x7e3f4ff8` is `0x81c0b008`, the host-table slot).

Design as built: monophonic, six inharmonic modes, state in the module's data segment so `render` reads only
R0 and R1 and never touches stack arguments; a 128-entry coefficient table computed at build time by
`opzstruck.py` so the engine contains no transcendentals — a note is an index. Registers render needs beyond
the volatile set are saved with the verified push/pop pair.

**Stated assumption, not a hidden one:** the decay macro is read from `params[2]`. The mechanism is right —
argument 5 is a *stack* argument, reached with nine discarded post-increment loads because the encoder has no
displacement load — and the mapping is accurate, with buckets landing within 1 % of their target T60. But
*which* entry of `params[]` the OS binds to the decay knob has not been confirmed on hardware. If it is the
wrong index, then a different knob will move the tail.

The coefficient table itself carries **no** damping: `r = 1.0`, so the rotation is exactly norm-preserving and
the entire tail comes from a per-block gain. That separation is what makes the macro map to an absolute T60
instead of stacking on a baked value — the first build did both, and decayed twice as fast as either. Collapse
of the mode state by `g` once per block is mathematically the same decay as scaling every sample, and costs 12
multiplies per block instead of 12 per sample.

### The (T) extraction is `>> 32`, and the engine compensates

Resolved from the SLEIGH source rather than from hardware. With `(T)` the modifier bits select
`dx32ExtrRnd`'s `rounding(rnd, acc, 4)` variant, and `rounding` clears the low `rem_size` **bytes** before
`strunc4_sat` truncates to 32 bits. Four bytes is 32 bits, so the extraction is `>> 32` — not the `>> 31` a Q31
fractional multiply needs. Compiled factory code therefore returns **half scale**, and an engine that ignores
this loses 6 dB per sample and goes silent almost immediately.

The fix costs one add per mode output: double the result back into Q31 (`R4 = R4 + R4`). `opzstruck.py` now
implements exactly that arithmetic — `frac()` is `(a*b) >> 32` with saturation, and the rotation uses
`frac_q31()` = two extra adds — and **still passes all nine measurement checks**, including pitch within 0.5 %
and the doubling of T60 across the decay macro. So the reference and the emitted instruction stream now
compute the same thing, which is what makes the measured behaviour evidence about the binary rather than only
about the idea.

### A tooling ambiguity worth knowing

On a raw-binary import Ghidra decodes some 16-bit `LdSt` forms as the *32-bit* `LdStIdxI` class instead —
`0b 90 31 ca` becomes a two-byte `R3 = [P1++]` followed by a `Mult32`, or one four-byte indexed load,
depending on the consumer. Factory code contains the same two-byte sequences, so the 16-bit reading is the
one the hardware uses; the ambiguity is Ghidra's, not the encoding's. It does mean emitted code should be
verified by re-encoding and comparing bytes, not only by reading a disassembly back.

## 11.14 The engine runs, and the numbers are measured from its own output

Everything above validates descriptions. `toolkit/opzsim.py` executes the module: it is a small interpreter
for exactly the forms `opzasm.py` emits, faithful to the SLEIGH semantics each encoding was derived from, and
it refuses any instruction it does not implement rather than guessing. Its self-test now includes the two
measurements that matter:

```
PASS  engine pitch note 69     439.5 Hz vs 440 Hz (0.11%)
PASS  engine pitch note 57     220.4 Hz vs 220 Hz (0.18%)
PASS  engine pitch note 81     876.4 Hz vs 880 Hz (0.41%)
PASS  engine pitch note 45     110.5 Hz vs 110 Hz (0.48%)
PASS  engine decay             T60 1.17 s (table bakes ~1.2 s)
PASS  engine decays to silence
PASS  energy decays over 16 blocks   1.956e18 -> 1.485e18
PASS  gate off -> silence
PASS  stereo channels equal
PASS  initModule(1,...) -> 0   rejects a foreign id
```

So the emitted instruction stream is not merely well-formed: it computes a sixth-order modal resonator at the
right pitch, with the designed decay, that goes silent when the gate closes.

### Three real bugs it caught, which no amount of reading would have

1. **The fractional multiply used as an integer multiply.** Row lookup was `index * 48` via `mul32`, which is
   `(a*b) >> 32` — so `69*48 = 3312` became **0**, and every note played table row 0 (8.18 Hz). Symptom:
   identical pitch for every note. Fix: build the row offset from two shifts, `(index<<4) + (index<<5)`.
2. **The coefficient row pointer was never rewound.** `P1` advances 96 bytes per 64-frame block, so from the
   second block onward it read past the row. Fix: save the row pointer in a data word and restore it each
   block, the same way the state pointers are restored.
3. **Nothing had ever run it.** Both bugs are invisible to static checking — the container is valid, the
   encodings match factory bytes, and the reference implementation is correct; only execution shows the
   engine ignoring the note.

Two more, found once the decay macro was wired:

4. **Per-block scaling applied inside the per-sample loop.** The gain belongs to a 64-sample block; placing the
   scaling inside the loop made it act 64 times per block, and `0.99885^64 = 0.929` is a 7 % collapse per block
   — which is exactly what the simulator measured. Symptom: T60 of 0.13 s where 8 s was asked for.
5. **A conditional branch used as an unconditional jump.** The builder's `branch()` always tests `CC`, so an
   "unconditional" jump inherited whatever flag was last set. The null-argument guard was added, and the code
   after it silently depended on the flag from that comparison. Fixed by giving the builder a real `JUMP.S`
   fixup.

The interpreter had two bugs of its own, both worth recording because they are the same class of mistake:
registers were not held as signed values, so an address like `0x81c0b060` counted as a positive overflow and
every add saturated; and it decoded the shift form as a multiply, because the DSP sub-opcode for the multiply
is `0x4` (not the `0xA` the first derivation suggested) and for the shift is `0xD`.

## 11.15 Placement, and how a new plug is registered

Two gaps closed, both from device data rather than inference.

### The arena is a 0x1400-byte grid, and the slot rule fits the bank that matters

Pairing each factory engine's module base (its first segment's destination) with the `memoryslot` that
`plugp.json` assigns it gives a table that is not random. For every engine in slots 59–89 — fourteen of them —
the mapping is exactly

```
base = 0x81be4c00 + (slot - 61) * 0x1400
```

chord (59) → `0x81be2400`, chorus (60) → `0x81be3800`, digital (62) → `0x81be6000`, reverb (66) → `0x81beb000`,
fdnreverb (89) → `0x81c07c00`. The same arithmetic does **not** hold for the low slots: engines in slots 4–27
sit on a 0x2800 stride in a different bank (`0x81b32000` upward), so the arena is not one formula. It is a grid
of 0x1400 slots with at least two allocation regions, and only the 59–89 region is regression-verified.

That is enough to place a new engine *by rule* instead of by guess. Slot 63 is unused, and its three slots
(`0x81be7400`, `0x81be8800`, `0x81be9c00`) end exactly where reverb begins at `0x81beb000` — a real gap between
digital (ends `0x81be6a80`) and reverb. The struck-body module is built for that base and occupies
`0x81be7400`–`0x81be8fdc`, comfortably inside its three slots. A mis-chosen slot would be caught by the
loader's own `Bad address` check rather than by corrupting a neighbour.

### `plugs_patch.json` is the registration route, and its schema is now known

The firmware's own `system/content/settings/plugs_patch.json` carries an `auto_import` array, and each entry
registers one plug:

```json
{ "auto_import": [ { "engine": { "memoryslot": 27, "path": "engines/analoga.engine", "version": 1 },
                     "plug":   { "engine": "engines/analoga.engine", "flags": 20, "id": 10,
                                 "memoryslot": 27, "name": "analoga", "samples": "", "version": 25 },
                     "tracks": [ 4, 5, 6, 7 ] } ] }
```

The shipped file holds five entries (analoga, organ, ep, fdnreverb, chorus2) — which is exactly the set that
mis-loads on a unit whose engines were replaced, so this file is the mechanism the vendor uses to re-register
a plug even though `settings/plugs.json` is app-owned. `tracks` is 0-based: `[4,5,6,7]` are the four synth
tracks.

`toolkit/install_struck.py` builds the engine, appends one entry (memoryslot 63, plug id 160, tracks 4–7),
and writes a `ZIP_STORED` payload containing

```
../user/engines/struck.engine
../system/content/engines/struck.engine
../system/content/settings/plugs_patch.json
```

which is the documented entry-path write primitive, and leaves staging as the ordinary update-medium
procedure. What remains after that is hands on the device, not code.

## 11.16 Per-voice state, and the sequence that makes it work

An engine that keeps its state in module globals is wrong the moment the OS runs more than one voice:
`render` is called per voice, so every voice would read and write the same state and they would all play
whichever note was struck last. The struck-body engine keeps everything in the context the OS passes in —
`init` (arg 1), `onNoteOn` (arg 3), `render` (arg 4):

```
ctx+0x00  gate
ctx+0x04  note
ctx+0x08  coefficient row pointer (saved, because P1 advances past the row within a block)
ctx+0x0c  reserved
ctx+0x10  state: six modes x (y1, y2)  -> ends at 0x40
```

Only the coefficient and gain tables remain in module data, where they are read-only and shared. The
simulator now proves the isolation rather than asserting it: two contexts are initialised with different
notes, voice A's state is snapshotted, voice B is rendered in between, and voice A's state is compared —
identical. Each voice rendered alone still measures its own pitch (876 Hz for note 81).

### The bug this refactor introduced, and why it was subtle

After the first version, the output collapsed within two blocks — energy 1.8e17 → 4.8e5 → 0. The cause was
**ordering inside the per-block rewind**: the state pointers were reset before the saved row pointer was read
back, and that read advances its own pointer by one word, leaving `P0` at `ctx+0x0c` instead of `ctx+0x10`.
The next frame then read the reserved word as `y1` and every state word was shifted by one. Reading the row
pointer first and setting the state pointers last fixed it.

Two lessons worth the space. **Pointer-walking code has no visible offsets** — the arithmetic is a side effect
of how many reads happened, so a single `[P0++]` in the wrong place silently shifts a whole structure. And
**the failure looked like excessive damping, not like misalignment**, which is exactly the shape of bug that a
"does it make sound?" test passes: it did make sound, for one block.

## 11.17 Installing a new engine on a real unit: what actually works

Three routes were tried on hardware (firmware 1.2.45 / OS 1.2.43). Only the third worked. The full procedure,
its verification steps and its failure-mode table are doc `12`; this section keeps the diagnostic conclusions,
because the two failures each answered a question that reading code had left open.

### Route 1 - copy the .engine onto the content disk: refused by name, not by content

`struck.engine` placed at `samplepacks/6-lead/08/` produced:

```
[IMPORT STARTED]
Reading content disk...SUCCESS
  rejecting invalid engine : /samplepacks/6-lead/08/struck.engine
```

The obvious reading - "my module is malformed" - is wrong, and one control experiment disproves it: a
**pristine factory `chorus.engine`, byte-identical to the shipped module, was rejected the same way once
renamed** to `probe.engine`. Identical bytes, different name, same refusal. So the check is a **plug-registry
lookup, not a file check**: the OS only accepts an engine whose plug it already knows. That also explains the
message's other half from doc 02: `Ignoring file of wrong type: %s` exists for extensions outside
`wav|aif|aiff|engine`, so `.engine` is recognised as a type and judged by identity afterwards.

Consequence: a new engine can never be installed by dropping a file on the content disk. The registry entry
has to exist first, and that file lives in system content, which content mode does not expose.

### Route 2 - a three-entry update zip: refused before extraction

Staging `firmware_bin_only_with_bootloader.zip` containing only the engine and a patched `plugs_patch.json`
never reached extraction:

```
[2026-10-17 15:35] upgrade started
failed to find ble firmware file
[2026-10-17 15:35] upgrade not compatible with this device
```

The updater validates the archive as a *firmware* archive before it extracts anything, and the component it
wanted first was the BLE image. The strings in `bootloader.ldr` name the whole set it expects under
`/yaffs2/upgrade/`: `firmware/firmware.version`, `firmware/blackfin/bin/{opz.ldr,opz.crc32,bootloader.ldr,
os.version,bootloader.version}`, `firmware/nordic/bin/{nrf52832_opz.bin,nrf52832_opz.dat,nordic.version}`,
`firmware/psoc_keyboard/bin/{SnakeKeyboardModule_*.cyacd,keyboard.version}` and
`firmware/blackfin/system/content/` - the last being exactly where an engine belongs.

### Route 3 - the whole firmware tree plus the engine: works

Repacking the unit's own 1.2.45 tree (32 entries, `ZIP_STORED`, per-entry CRCs correct) with the engine added
at `firmware/blackfin/system/content/engines/struck.engine` and `plugs_patch.json` carrying six `auto_import`
entries was accepted, and the device recorded the plug by writing its own markers:

```
samplepacks/5-bass/05/~160.engine   samplepacks/6-lead/08/~160.engine
samplepacks/7-arpeggio/09/~160.engine   samplepacks/8-chord/07/~160.engine
```

Four 0-byte `~160.engine` files, one per synth track, matching the `tracks: [4,5,6,7]` of the registry entry -
which is the device's own statement that plug id 160 "struck" is registered and assigned. Installing through
`toolkit/install_struck.py --full`, which builds this payload, is therefore the reproducible route.

Two traps found along the way, both about *where* rather than *what*:

* a zip copied while the unit is in **content mode** is silently eaten by the content importer - no log line,
  no error, and `upgrade.log` never gains an entry, so the zip simply disappears. It must be staged while the
  volume shows `systeminfo/`, which is update mode;
* macOS leaves an AppleDouble `._<name>` alongside every file it writes to a FAT volume. Those must be removed
  from an update payload and from staged content, since they are unexpected entries in both paths.

## 11.18 What makes it sound like wood rather than like glass

The engine worked on the first hardware install but did not sound like the thing it models, and the listening
verdict ("sounds good but not like a wooden marimba") pointed at a modelling error rather than a bug. Two
choices were wrong, and both came from the same shortcut.

### Wrong choice 1: a free-free bar is not a marimba

The mode ratios were a blend of a harmonic series toward the classic free-free beam ratios
`1, 2.756, 5.404, 8.933, 13.34, 18.64`. Those are the partials of an *untuned* bar - what a glockenspiel or a
plain metal bar does. A marimba bar is deliberately **undercut** on its underside so that the first overtone
is tuned to **two octaves above the fundamental, at exactly 4x**, with the next two near 9.2x and 16x. The ear
identifies that tuned 4x partial as wood; the 2.756x partial is what a bell or a glass bar gives.

The engine now uses `MARIMBA = (1.0, 3.93, 9.24, 16.0, 24.0, 34.0)`.

### Wrong choice 2: every mode decayed at the same rate

This was the more audible mistake. The coefficient table was built with `r = 1.0` for every mode - perfectly
norm-preserving - on the reasoning that the per-block decay gain should own "the whole tail". That reasoning
is correct for the *fundamental* and wrong for the rest: a wooden bar's overtones die in tens or hundreds of
milliseconds regardless of how long the note is held, because that damping is a property of the bar, not of
the note. With one shared radius the six modes ring out together and the result is a chord that sounds
metallic, no matter how correct each individual mode is.

The table now carries a **per-mode radius** for every mode above the first:

```python
MARIMBA_T60 = (0.0, 0.45, 0.25, 0.15, 0.10, 0.07)   # seconds; mode 0 is 0 because the macro owns it
r = 1.0 if t60 == 0.0 else exp(-ln(1000) / (t60 * FS))
```

Mode 0 keeps `r = 1.0` so the decay macro still owns the whole fundamental tail and the bucket targets stay
exact - the decay bucket checks still measure 0.10 / 1.59 / 2.99 s against 0.1 / 1.6 / 3.0 targets.

Two smaller changes follow from the same model: the strike position moved from 0.3 to **0.22** of the bar's
length (a marimba is struck nearer one end), and the per-mode excitation taper steepened from `0.55^m` to
`0.42^m` so the fundamental dominates instead of the strike sounding bright.

### The measurements, not the adjectives

Rendered at note 69 (A4, 440 Hz) and analysed with a Goertzel-style single-bin DFT:

| partial | level | what it means |
|---|---|---|
| 1x - 440 Hz | **44.4 dB** | fundamental dominates |
| 2.756x - 1213 Hz | **-12.6 dB** | free-free bar partial is absent, 32 dB under the 4x partial |
| 3.93x - 1729 Hz | **19.9 dB** | the tuned two-octave overtone, i.e. the wood |
| 9.24x - 4066 Hz | 17.5 dB | third partial |
| 16x - 7040 Hz | 12.1 dB | fourth partial |

and the decay behaviour that makes a knock rather than a bell:

```
9.24x overtone   0-43 ms  15.6 dB   ->  150-193 ms  -23.1 dB     (-38.7 dB in 150 ms)
fundamental      0-43 ms  39.1 dB   ->  150-193 ms   21.3 dB
```

Both facts are now gates rather than comments: `toolkit/opzverify.py` asserts that the tuned 4x overtone
stands at least 20 dB above the free-free 2.756x one, and that the 9.24x overtone falls more than 20 dB in
150 ms. The first would fail on the old ratios, the second on the old single-radius table.

One test needed repairing at the same time: `opzstruck`'s "inharmonicity changes the spectrum but not the
pitch" check compared two renders and passed **vacuously**, because woody tuning ignores `inharmonicity`
altogether - both renders were identical. It now asks for `woody=False` explicitly and additionally asserts
that the woody and free-free tunings differ, so the marimba ratios cannot silently stop being used.
