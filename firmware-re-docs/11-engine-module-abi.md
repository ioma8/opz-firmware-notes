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

### What still needs the device

One thing: whether `onNoteOn`'s `R1` is a note number or an already-scaled frequency, and therefore whether an
engine should derive pitch from `R1` or simply use `render`'s Q16 frequency argument. The Q16 reading of
argument 2 is strongly supported but rests on the octave ratios rather than on a units string. The decidable
test is one note long — render a note, measure the output frequency, and compare against 440 Hz for A4; a
wrong assumption shows up as a constant ratio, not as noise.

An engine that ignores argument 2 and computes its own increment from `R1` at note-on is therefore the safer
first build: it depends on only one unverified assumption instead of two.
