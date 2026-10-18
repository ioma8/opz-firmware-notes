# Installing a new engine on a real OP-Z

This document records how a new `.engine` — a from-scratch synthesizer module, not a factory one — was put on
a physical OP-Z and made to play. It is written as a procedure with its evidence attached: every step below
was executed, every claim marked *verified* was read back out of the device or its logs, and the two routes
that failed are kept because their failure messages are the most useful part.

The engine used as the vehicle is `struck`, a six-mode modal resonator built for slot 63; the install machinery
is `toolkit/install_struck.py`. Nothing in the procedure depends on that particular engine except the file
name and the plug id.

## 12.1 What "installed" actually means

Three separate things have to be true, and they are written to three different places. Confusing them is the
main reason the first two attempts looked like they should have worked:

| part | where it lives | who writes it | checked by |
|---|---|---|---|
| the module file | `/yaffs2/system/content/engines/<name>.engine` (also `/yaffs2/user/engines/`) | the update payload | file present, correct size |
| the registry entry | `/yaffs2/system/content/settings/plugs_patch.json`, an `auto_import` array | the update payload | `auto_import` holds the plug id |
| the assignment | 0-byte `~<id>.engine` markers under `/yaffs2/user/samplepacks/<track>/<slot>/` | **the device itself** | markers exist after boot |

The third row is the one to look at first when diagnosing, because the device writes it only after it has
accepted the registry entry. A plug that is registered but whose module fails to load still gets its marker;
a plug the OS does not know never gets one.

## 12.2 The evidence chain

Each attempt was a hypothesis with a test attached. This is the order they were tried, including the control
experiment that overturned the first reading — the same discipline doc `09` describes, applied to hardware
rather than to disassembly.

### Attempt 1: copy the file onto the content disk — refused, and not for the expected reason

Content mode exposes `/yaffs2/user/` as a FAT volume with `samplepacks/`, `config/`, `projects/`, `bounces/`
and `rejected/`. The obvious move is to drop the engine into a sample-pack slot. `samplepacks/6-lead/08/struck.engine`
produced, in `/Volumes/OP-Z/import.log`:

```
[IMPORT STARTED]
Reading content disk...SUCCESS
  rejecting invalid engine : /samplepacks/6-lead/08/struck.engine
Calculating used sample space...0.8/24.0 MB
  rejecting invalid engine : /samplepacks/6-lead/08/struck.engine
```

The natural reading — "my module is malformed" — is wrong, and the error message alone cannot distinguish the
two possibilities. The **control experiment** does: a pristine factory `chorus.engine`, byte-identical to the
module shipped on that very device, was placed in the same kind of slot under the name `probe.engine`. It was
refused with the identical message.

*Identical bytes, different name, same refusal* — therefore the check is a **plug-registry lookup, not a file
check**. The OS has already decided which engines are legitimate (the `auto_import` entries of
`plugs_patch.json` plus the plugs it ships with), recognises `.engine` as a type — the sibling string
`Ignoring file of wrong type: %s` exists for extensions outside `wav|aif|aiff|engine` — and then judges the
file by *identity*. A file whose name corresponds to no known plug can never be accepted, no matter how valid
its container is.

**Consequence:** a new engine cannot be side-loaded. The registry entry must exist *before* the OS will look
at the module, and that registry lives in system content, which content mode does not expose.

Two side observations from this attempt: the rejection is logged twice (once while reading the disk, once
while assigning), and a `.txt` file in the same slot produced *no* log line at all — so silence in
`import.log` does not mean "accepted", it usually means "never considered".

### Attempt 2: a three-entry update zip — refused before extraction

Update mode exposes a much smaller volume carrying only `systeminfo/`. The updater is fed
`firmware_bin_only_with_bootloader.zip` at the volume root. A zip containing just the engine and a patched
`plugs_patch.json` was refused, and `systeminfo/upgrade.log` recorded exactly why:

```
[2026-10-17 15:35] upgrade started
failed to find ble firmware file
[2026-10-17 15:35] upgrade not compatible with this device
```

The archive is validated as a *firmware* archive **before anything is extracted**, and the first component it
looked for was the BLE image. The strings in `bootloader.ldr` enumerate the whole set it expects under
`/yaffs2/upgrade/`:

```
firmware/firmware.version
firmware/blackfin/bin/opz.ldr              firmware/blackfin/bin/opz.crc32
firmware/blackfin/bin/bootloader.ldr       firmware/blackfin/bin/os.version
firmware/blackfin/bin/bootloader.version
firmware/nordic/bin/nrf52832_opz.bin       firmware/nordic/bin/nrf52832_opz.dat
firmware/nordic/bin/nordic.version
firmware/psoc_keyboard/bin/SnakeKeyboardModule_*.cyacd
firmware/psoc_keyboard/bin/keyboard.version
firmware/blackfin/system/content/          <-- content, and therefore engines
```

That last line is the key: the updater installs `firmware/blackfin/system/content/` wholesale, so content
files — including a new engine and a patched registry — can ride inside a firmware archive.

### Attempt 3: the whole firmware tree plus the engine — accepted

Repacking the unit's own 1.2.45 tree with the engine added was accepted. The payload was 32 entries,
`ZIP_STORED`, every entry's CRC correct, no macOS `._` files, and it differed from a stock archive in exactly
two places:

```
firmware/blackfin/system/content/engines/struck.engine              7,136 B
firmware/blackfin/system/content/settings/plugs_patch.json          1,924 B  (6 auto_import entries)
```

**Verification that it worked** — the device's own record, read from the content volume afterwards:

```
/Volumes/OP-Z/samplepacks/5-bass/05/~160.engine
/Volumes/OP-Z/samplepacks/6-lead/08/~160.engine
/Volumes/OP-Z/samplepacks/7-arpeggio/09/~160.engine
/Volumes/OP-Z/samplepacks/8-chord/07/~160.engine
```

Four 0-byte markers, one per synth track, exactly matching the `tracks: [4,5,6,7]` of the registry entry
(0-based: bass, lead, arpeggio, chord). The engine then played a note in tune, which is the audio check
detailed in §12.5.

## 12.3 The working recipe

```bash
# 1. build the engine and the payload (--full uses the unit's own firmware tree as the base)
python3 toolkit/install_struck.py -o /tmp/payload.zip --full

# 2. put the unit in UPDATE mode (the volume must show systeminfo/ and nothing else)

# 3. stage it, and remove the AppleDouble file macOS always leaves behind
cp /tmp/payload.zip "/Volumes/OP-Z/firmware_bin_only_with_bootloader.zip"
rm -f "/Volumes/OP-Z/._firmware_bin_only_with_bootloader.zip"
sync

# 4. eject, let it flash and reboot on its own
diskutil eject /Volumes/OP-Z
```

Then select the plug on a synth track (a synth track shows it by name), play a note, and confirm the markers
appear on the content disk as in §12.2.

The registry entry it writes, appended after the five factory patches so none of them are lost:

```json
{"engine": {"memoryslot": 63, "path": "engines/struck.engine", "version": 1},
 "plug": {"engine": "engines/struck.engine", "flags": 0, "id": 160,
          "memoryslot": 63, "name": "struck", "samples": "", "version": 1},
 "tracks": [4, 5, 6, 7]}
```

`memoryslot` is not decoration: it is what makes the OS load the module at the address the module was linked
for, and the slot→address law is doc `11` §11.15. Slot 63 is `0x81be7400`, whose three 0x1400-byte slots end
exactly where `reverb` begins.

## 12.4 Three traps, all about *where* rather than *what*

1. **A zip staged in content mode is eaten silently.** The content importer consumes unknown files at the
   volume root, logs nothing, and `upgrade.log` never gains an entry — so the archive simply disappears and
   the next boot looks normal. One attempt was lost this way and initially looked like a validation failure.
   The tell is that `upgrade.log`'s mtime is unchanged. **Stage only while the volume shows `systeminfo/`.**
2. **macOS pollutes FAT volumes.** Every file written from Finder or `cp` on some setups brings a 4 KB
   AppleDouble `._<name>` companion. Those are unexpected entries in an update payload and unexpected files in
   a sample pack. Remove them (`dot_clean -m <dir>`), and re-check after copying.
3. **`systeminfo/` only exists on the update volume.** It is the only place `system.log`, `upgrade.log`,
   `import.log`, `version.txt` and `serial.txt` can be read. If the logs look stale, the volume is in the wrong
   mode, not the device.

## 12.5 Verifying that it actually works

Three checks, cheapest first. The first is a file listing, the second is a log read, and only the third needs
ears.

**1. Assignment markers** (§12.2) — one `~<plugid>.engine` per target track. No marker means the registry
entry was not accepted, and nothing about the module matters yet.

**2. The boot log.** In update mode, `systeminfo/system.log` gains a session per boot. For a healthy install
there is no `Can't load engine <id>` line. For a failed one there is, and the neighbouring `dlm:` lines give
the loader's own reason — `Bad header`, `Bad header checksum`, `Bad address (…)`, `Data outside buffer`. Note
the factory engines themselves emit five `dlm: Unsupported fill value` lines per boot; those are benign and
are a handy baseline for "the log is from a real boot".

**3. The audio check.** Select the plug on a synth track and play:

| observation | conclusion |
|---|---|
| a pitched note, in tune with the keyboard | the note→coefficient mapping and the load base are both right |
| the tail shortens as the decay macro is turned down | the `params` binding is right (doc `11` §11.14) |
| silence for every note | the module loaded but the gate or the note path is wrong — check the boot log first |
| sound but wrong pitch, or a fixed pitch | the coefficient row indexing is wrong; compare against the table dump |

For `struck` all three passed: the plug is assigned on four tracks, the module loads, and it plays in tune.

## 12.6 What was still unproven at that point

Recorded honestly, because an install that works is not the same as an ABI that is fully characterised:

* whether the decay macro is bound to the *intended* knob. `params[2]` is an engine-author choice, not a
  recovered mapping — plug metadata carries no parameter names, ranges or curves.
* the exact rounding the hardware applies to the `(T)` multiply extraction, which the simulator models as
  truncation (doc `11` §11.12). The engine sounds correct, so truncation is at worst very close, but "sounds
  correct" cannot distinguish a one-LSB difference.
* whether the installer skips components whose versions match. The payload re-applies the same 1.2.45 build,
  so this never had to be resolved to install an engine.

## 12.7 Reproducing this procedure for a different engine

Only four things are engine-specific: the module file, its `memoryslot`, the plug `id` and the `name`. Choose
a free slot inside a verified bank (doc `11` §11.15) and build the module for the address that slot maps to;
pick a plug id above the factory range and below the large user id; keep `tracks` to the tracks the plug
should appear on. Everything else — the firmware tree in the payload, the staging procedure, the marker check
— is identical, which is what makes this a procedure rather than a one-off.

## 12.8 Auditioning a module before flashing it

Flashing to try a change costs a reboot cycle per iteration, which is a bad way to tune an instrument. The
harness for that is `toolkit/opzenginetool.py`, a desktop window that loads a `.engine` file and runs **the
real module bytes** in the same interpreter the validation suite uses, so what comes out of the speakers is
what the device will compute rather than a model of it.

```bash
python3 toolkit/opzenginetool.py              # pick a module, set a note, move the knobs, Render & play
python3 toolkit/opzenginetool.py --selfcheck  # render one clip and print stats, no window
```

The page shows the module's size, load base and export addresses, a note, a clip length, and eight
`params[]` sliders - the same array the OS passes to `render()`, so a slider is a knob. It plots the envelope,
reports the peak level and offers the rendered WAV for download, which is how a saturation or a runaway shows
up before it reaches the unit. Any `.engine` can be opened by dropping its path into the box above the list,
so a module built anywhere - not just in the repo - can be auditioned.

It is a local web page rather than a desktop toolkit window for a concrete reason: Apple's system Tk is
version 8.5, which draws a **blank white window** on current macOS, so a Tk harness cannot be handed to
anyone without first fixing their Python installation. `http.server` plus the browser's own audio path needs
nothing installed beyond the standard library.

Two engineering realities shaped it, and both are stated in the tool rather than hidden:

* **Rendering is offline.** The interpreter runs at about 0.23x realtime (7,017 instructions per 64-frame
  block), so a one-second clip takes roughly four seconds. Renders are cached on disk by content hash, so the
  first play of a setting is slow and repeats are instant.
* **Factory engines execute, but they are silent.** Completing the interpreter took sixteen instruction
  classes, every one read out of the Ghidra SLEIGH sources rather than guessed: `LINK`/`UNLINK`, the
  absolute-address and indexed and post-modify load/store forms, the displacement and frame-relative
  `[FP - n]` spills, `CallA` (32-bit pcrel call), `LSETUP` hardware loops (with the loop-end redirect and
  the `lc+1` iteration convention), the whole conditional machinery (`CCFlag`, `CCMV`, `CC2Dreg`,
  `CC2Stat`), multi-register and single-register push/pop, the `Dsp32` Mac/Alu/Shift families including
  pack/extract/signbits/popcount and the `DIVQ`/`DIVS` divide step, `ALU2op`, `Logi2Op`, `Ptr2op` and
  `NOP32`. All 21 factory engines now load and run to completion. **They produce no audio**, because their
  output depends on voice and envelope state the operating system maintains (the amp object's state
  machine, per-voice parameters, and the results of host-service calls into `opz.ldr`); the harness maps
  unmapped memory to zero and stubs host calls to a zero return, which is enough to execute them and not
  enough to make them sound. Making them audible is a separate piece of work: characterise the 13-entry
  host-services table at `0x81003850` entry by entry.

One interpreter bug found on the way is worth recording because it affects the emitted code*, not just the
tool: the multi-register push encodes the **lowest** register of the group and the group runs *upward*
(`(R7:4)` encodes as 4), and the pointer group tops out at **P5**, not P7. Emulating it with a downward range
pushed five pointer registers instead of three, which shifted the entire argument frame by two words and made
`render` read a garbage `params` pointer. The engine's own argument walk is order-independent (it counts
words), so the fix was invisible to `struck` - and would have been invisible to any engine that only ever
reads its arguments by counting.

## 12.9 Playing a module live, and why the native path exists

`toolkit/opzplay.py` plays a module from the keyboard: `a s d f g h j k l ;` are the notes of the current
scale, `z`/`x` change octave. It works because the module's machine code is **translated to C and compiled**
(`toolkit/opzjit.py`) rather than interpreted:

| path | cost per 64-frame block | realtime factor |
|---|---|---|
| interpreter (`opzsim.py`) | ~5.8 ms | 0.23x |
| translated C (`opzjit.py`) | **6.8 us** | **197x** |

A block's budget at 48 kHz is 1333 us, so the translated engine leaves room for ~196 voices, and the player
runs four with a measured 46x headroom end to end (`opzplay.py --selftest`).

Two things make this trustworthy rather than merely fast. First, the generated code is a switch dispatch over
instruction addresses - the same shape as the interpreter - so its semantics are the interpreter's by
construction. Second, the gate is **bit-exactness**: the same module, note and parameters must produce
identical samples from both paths, and they do (`opzjit.py` was validated that way before anything was built on
it). Anything the translator does not support raises `Unsupported` rather than emitting a guess.

Audio output needs nothing installed: `toolkit/audiosink.c` is a ~100-line CoreAudio `AudioQueue` helper that
plays raw PCM from stdin, compiled on first use. Python cannot open a low-latency device without a third-party
package, and the harness stays dependency-free.

### The host memory a factory engine needs

Chasing the silence of the factory engines turned up the missing piece, and it is not an instruction: an
engine is **not self-contained**. `initModule` receives a pointer to the OS's host-services table, and the
engines store it in their own data and read through it while rendering. `chord` keeps it at `0x81be2d58`; in
its render loop it reads `[table + 0xc]`, which is `0x0800bb44` - a 2048-entry Q31 **sine table** the OS keeps
in L2 SRAM for exactly this purpose. A harness that returns zero there produces silence no matter how correct
its emulation is.

`toolkit/opzhost.py` extracts the two regions that matter from the OS image and caches them outside the
repository (`~/.cache/opzenginetool/hostmem.json`):

```
0x0800b000 + 0x3000   L2 SRAM, containing the shared sine table at 0x0800bb44
0x81003850 + 0x40     the 13-entry host-services table itself
```

With that memory present, the engines get further but still do not all reach their sample loops; the remaining
gap is the voice and envelope state the OS maintains around them, which is a separate piece of work and is
recorded as such rather than papered over.

### What still stands between a factory engine and sound

Three things, and they are now named rather than suspected, which is the useful part:

1. **`RETS` is a register, and I had it at zero.** `RTS` is `return [RETS]`, and `CALL` sets it; `LINK`
   pushes it and `UNLINK` restores it. Compiled engines save it into a pointer (`MvRegToReg P2 = RETS`) before
   calling helpers, and restore it before returning. With `RETS` reading as zero, any engine that touched it
   returned to address 0 - which the harness then treated as a host call and silently terminated the render.
   The interpreter now models it (`opzsim.Machine.rets`), set by every call form and by the harness entry.

2. **They need the OS's sine table, which is now provided.** Covered above: `[host_table + 0xc]` is
   `0x0800bb44`, a 2048-entry Q31 sine table in L2 SRAM. `opzhost.py` supplies it.

3. **The calling convention on silicon pushes nothing.** `chord`'s software divider at `0x81be2c32` is a
   leaf reached with `CALL 0x81be2c32`, and its first two instructions store working values straight into
   `[SP]` and `[SP+4]` (`_StDregToM32bit [SP] = R4`, `[SP+0x4] = R5`). A callee may only do that if the call
   did **not** put a return address on the stack: on silicon `CALL` sets `RETS` and touches no memory, and
   `RTS` is `return [RETS]`. The helper returns with `JUMP (P2)` where `P2 = RETS` was saved at entry, which
   is the same fact stated the other way. Ghidra's SLEIGH shows `call`/`return [RETS]` as pushing and popping
   because that is how a decompiler models them - treating it as the hardware stack behaviour is wrong, and
   it is why the interpreter has to keep a separate `RETS` register rather than relying on its own push.
   Engines reached from the OS still see one word above their arguments, so the OS's dispatcher evidently
   supplies its own frame word; that is the only way to reconcile `struck` reading its arguments through a
   pushed word on real hardware with the leaf-function scratch use above.

4. **They need an accurate DSP accumulator, and this is the real remaining gap.** `chord`'s arithmetic helper
   (`0x81be2c32`) is a software divider built on `Rot32` (rotate through carry), `MvToCC_STAT CC = AC0` and
   `MvRegToRegCond`, with an `LSETUP` loop. It is not approximate arithmetic: it reads the accumulator carry
   flag `AC0` on almost every iteration. The emulator tracks only what `CC2Stat` moves explicitly, so `AC0` is
   always zero and every divide comes out wrong. Making factory engines audible means implementing the 40-bit
   accumulators `A0`/`A1` with their flags (`AC0`, `AC1`, `AV0`, `AV1`, `AQ`) and the `Dsp32Mac` multiply-
   accumulate family that drives them - a bounded but real piece of emulator work, not a tweak.

Beyond the arithmetic, the engines also expect the per-voice and envelope state the OS maintains around them,
which is the same class of problem as the host table: the harness has to supply it, and what to supply is only
knowable by reverse engineering `PluginManager`/`Voice` rather than by reading an engine.

### The engine execution model, as measured on the factory engines

Everything below came out of running the 21 official engines and watching where they stop. Each item was a
wrong assumption in the emulator, and each is now either fixed or named as a gap.

**`RETS` is a register, not a stack slot.** `RTS` is `return [RETS]`; every call form sets it; `LINK` pushes it
and `UNLINK` restores it. Compiled engines also save and restore it by hand (`MvRegToReg P2 = RETS` at
`0x81be2b78`, then `jump (P2)` at `0x81be2b74` to return). An emulator with `RETS` reading zero sends every
such engine to address 0.

**On silicon a call touches no memory.** chord's software divider at `0x81be2c32` is reached by `CALL` and its
first two stores are `[SP] = R4` and `[SP + 0x4] = R5` - a callee may only use the stack pointer as scratch
if the call did not push a return address. Ghidra's SLEIGH renders `call`/`return [RETS]` as push/pop because
that is the decompiler's model, and it is not the hardware's. Engines still read their own arguments from the
stack, so the OS dispatcher supplies one frame word above them; the interpreter keeps that frame word at the
harness entry point and nothing else.

**Addresses are unsigned, registers are signed.** A pointer register loaded with `LdM32bitToDreg` holds an
`int`; jumping through it must mask to 32 bits or the program counter becomes negative. The symptom is
`0xDEAD0000` arriving as `-559087616`, which then reads as neither the sentinel nor an outside address and
spins. Mask at every dispatch point, and store `RETS` masked.

**`LSETUP` has four forms, not one.** Signature `0x1C1` at bits 7-15 covers all of them: `rop` at bits 5-6
selects *leave the counter alone* (0), *counter = Preg* (1), *counter = immediate* (2) or *counter = Preg>>1*
(3); `lop` at second-half bits 10-11 selects plain `LSETUP` or `LSETUPZ`, which skips the body when the
counter is zero. The loop start is `inst_start + soff*2` with `soff` from the first half - *not* the following
instruction, which is only equivalent when `soff` happens to be 2 - and the end is `inst_start + eoff*2`.
chord's divider uses `LSETUP(0x81be2c7c, 0x81be2c88) LC0 = P1`, so treating the count as immediate iterates a
garbage number of times.

**`TESTSET` is a lock, and it sits inside render loops.** `ProgCtrl` opcode `0xb` reads a byte through a
pointer, sets `CC` when the byte was zero, and then sets the byte's top bit. chord executes one at
`0x81be2796`, immediately inside its 64-frame sample loop at `0x81be2794`. Unmapped audition memory reads as
zero, which is what makes the first acquisition succeed.

**The accumulators are real state, and they are only partly modelled.** `A0`/`A1` are 40-bit; `RegMv` group 4
exposes `A0.W`, `A1.W` (registers 1 and 3) and the extension bytes `A0.X`, `A1.X` (0 and 2). The emulator now
holds them, plus `AV0`/`AV1`, and `AddSubAC0` updates `AC0` (ASTAT bit 4) from the carry out of bit 31. What
is still missing is the `Dsp32Mac` multiply-accumulate family that produces the values these accumulators
carry for the synthesis path.

**What is left between a factory engine and audio is OS state, not arithmetic.** With all of the above fixed,
chord reaches and executes its 64-frame render loop and then calls out of the module from inside it: the host
service at `0x800314c0` (host-table entry 7) and, at `0x81be27ca`, a load through a pointer that is zero.
That is a per-voice callback the OS installs; the engine calls it every sample. No amount of emulator work
supplies it - the `PluginManager`/`Voice` side has to be reverse engineered to know what the OS puts there.
The sweep therefore stands at **21/21 executing, 0/21 audible**, and the next unit of work is the voice
state contract rather than the instruction set.

**Where chord's samples actually go, and why the harness cannot supply it.** chord never stores through
argument 1. Its 64-frame loop emits each sample through `I1` (`StDregToM32bit [I1++]`-style stores at
`0x81be282e` onward), and inside the same loop it performs four loads per sample through pointers that are
zero - addresses `0x0` and `0x4` - which are the phases/coefficients it expects from the OS-populated voice
state. Setting `I1` to the output buffer and sweeping both stack layouts was tried: every combination of
`I0`/`I1` = output and *with/without* the extra padding word renders exactly `0.0000`. The argument layout
itself is now confirmed independently, since the disassembly reads the context at `[FP + 0x14]`, the
parameters at `[FP + 0x18]` and the amp object at `[FP + 0x1c]`, which is exactly what the harness's
five-word stack produces (and one word *more* padding than that reads the wrong slots and silences the
engine while still "completing" - a trap worth remembering).

### The OS side: what the plug object looks like

The engine-facing half of the contract is now read out of the OS rather than inferred, which is what any
future voice-state work needs as a starting point.

`FUN_8002b02c` is the symbol resolver the loader runs over a freshly loaded module, and it writes the resolved
entry points into a **plug object** at fixed offsets:

| offset | symbol | notes |
|---|---|---|
| `+0x00` | `init` | `FUN_8002abe4(s_8100381c, ...)` |
| `+0x04` | `renderFX` | only resolved (and only required) when `render` is absent |
| `+0x08` | `render` | instruments |
| `+0x0c` | `onNoteOn` | |
| `+0x10` | `onNoteOff` | |
| `+0x14` | `initModule` | filled by `FUN_8002ae50`, which also loads the file |

It returns 1 only when `init`, `onNoteOn`, `onNoteOff` **and** exactly one of `render`/`renderFX` are non-null,
which is the same five-symbol rule doc 11 states from the module side - the two views agree.
`FUN_800fff1c` is the caller that loads a module from a path (`/yaffs2/user/...`), resolves its symbols, and
copies the plug object onward; `FUN_80038174` is the reject path for an invalid engine.

**A durable tooling note:** the Ghidra project for `opz.ldr` was imported with analysis disabled, so every
script run with `-noanalysis` reports *zero* cross-references - which reads exactly like "nothing references
this address". Running the project once **without** `-noanalysis` (a full analysis of the OS image takes about
90 seconds) populates the reference database, after which `ghidra-scripts/CallersOf.java` answers properly.
That is how the plug object above was found: references to the export-name strings at `0x810037f8`
(`initModule`), `0x8100383c` (`render`) and `0x81003a9c` (`Could not lookup symbols for engine`) lead straight
to the resolver. `FindDword.java` also had to skip uninitialised memory blocks, which it previously crashed on.

What is still missing is the same thing as before, only better located: nothing in the OS image references the
host-services table by value (the address is computed), and the render dispatch itself is reached through a
plug object in RAM, so it has to be found by reading the sequencer's voice code rather than by xref. The
`Synth.cpp` strings resolve to `FUN_80117b3c`/`FUN_80118204`, which are not the dispatch.

### Measuring "audible", and the two bugs that hid behind a peak check

Two factory engines looked audible and were not, which is why an audibility claim now has to pass three
tests rather than one:

* `ministringshort` reached **peak 0.986** - a two-sample start-up spike, then silence.
* `volt` reached **peak 1.000** and a tail RMS of 0.95 - a full-scale **DC** offset, with zero crossings of
  zero, i.e. no pitch at all.

So `toolkit/opzenginesweep.py` judges an engine only when tail RMS (energy *after* the first block) exceeds
0.002, the signal holds more than a dozen distinct values (so DC cannot pass), and zero crossings land within
8% of the requested note. Its current verdicts over the 21 official engines:

| verdict | count | meaning |
|---|---|---|
| `silent` | 14 | executes and returns normally, writes nothing |
| `loops` | 4 | never returns within the step budget |
| `needs-state` | 2 | calls a null function pointer with no usable return address, or leaves its module |
| `detuned` | 1 | `volt`: full-scale DC, no pitch |
| `AUDIO` | **0** | none |

Those numbers only became trustworthy after two harness fixes, and the earlier table they replace was
**confounded by a wrong call layout**: the sweep was passing five stack words (`0, 0, ctx, prm, amp`) while the
harness that actually plays an engine (`opzenginetool.render_clip`, verified on `struck`) passes three,
`(ctx, prm, amp)`, and calls `onNoteOn(0, note, ctx)` rather than `onNoteOn(ctx, note, velocity)`. With the
padded layout several engines errored or ran off the rails, and I read that as missing OS state. With the
correct layout all thirteen instruments execute and return cleanly and simply write zeros - which is much
better evidence for the same conclusion, because nothing is crashing any more.

A decoder bug fell out of the same pass: `RegMv`'s class-2 `h` selectors live in the **second** halfword
(`rmvSrcH` at bit 2, `rmvDstH` at bit 5), and reading them from the first halfword turned every I-register
access into an M-register access - `organ` reported exactly that as `regmv: unsupported source class gs=2`.


A null callback whose return address *is* valid is now emulated the way an in-window host call is: the
service answers 0 and the engine continues. That is what `ministringshort` does - it calls null from
`0x81bff33e` with `RETS = 0x81bff340` - and answering 0 turns its hard failure into the `flat` verdict above,
which is the honest result: it keeps running and still writes no tone. Engines that arrive at address 0 with
`RETS = 0` (chord, fm003b, reverb) returned through a zeroed `RETS` instead, and those stay `needs-state`.

Two real defects were fixed while getting there:

**The immediate `LSETUP` form starts at the *following* instruction, not at the start-offset field.** The
SLEIGH's immediate form sets `LT0 = inst_next`; only the register forms take their start from `soff`. Using
`soff` for the immediate form makes the loop start at the `LSETUP` itself whenever `soff` is 0 - an infinite
loop that looks like "this engine hangs". `crush`'s `LSETUP (0x81bfb5ce) LC0 = 0x3f` is exactly that shape, and
fixing it let three effects (`crush`, `chorus2`, `dist`) complete a render for the first time.

**Effects take a different stack shape from instruments.** `renderFX(ctx, freq, state, in, out)` puts `in` and
`out` at `[FP+0x14]` and `[FP+0x18]` - the two *deepest* stack words, verified in `crush`'s prologue, not the
two shallowest ones the instrument layout would suggest.

And `opzsim.call` now names the null-pointer case instead of spinning: an engine that calls through a zero
pointer raises `engine called a null function pointer: it wants OS-populated state`, which is what turns a hang
into a diagnosis in the table above.

### Two engines that are close, and what "close" looks like

`volt` is the clearest case of an engine that is *running correctly and still wrong*, which is why the sweep
reports it as `flat` rather than `silent`. It executes its accumulation loop and writes into the output through
`[P5++]` at `0x81bf0678`, but what it accumulates is a constant: the left channel receives
`0x0c000000, 0x18000000, 0x24000000, 0x30000000` - a phase ramp that rises by `0x0c000000` per sample and
saturates - while the right channel gets `0`. So the loop, the store and the output pointer are all right; the
*waveform* that should be summed into the buffer is missing, which is the same missing-state story told from the
other side. A saw oscillator whose phase accumulator never wraps produces exactly this.

`delay` fails earlier and differently: its `init` enters the buffer-fill helper at `0x81be4cf8`, whose
`LSETUP(0x81be4d06, 0x81be4d06) LC0 = P2` is a *single-instruction* fill loop (`[P0++] = R3` with the count taken
from `P2 = P1 >> 1`). Start and end being equal is legitimate there - the body is one instruction - but the count
comes out around 404,000 because `P1` is a length the engine derives from state it does not have. Raising the
step budget lets `init` finish, and it then returns 0 and renders nothing.

The lesson generalises across the remaining engines: when a factory engine loops for hundreds of thousands of
iterations or writes a constant, that is not an emulator bug to chase in the instruction decoder - it is the
engine acting on a state value the OS would have supplied.

### The instrument record: where the engine's state actually lives

Chasing "why is every factory engine silent" into the OS finally turned up the structure that answers it.
The synth keeps its instruments in an array of **`0x17c`-byte records** based at synth-object `+0x480`
(`iVar14 = iVar11 + 0x480` in `FUN_801184c0`, the per-tick synth function). A record holds the engine's
resolved entry points and the state the engine is given:

| offset | contents |
|---|---|
| `+0x00` | `init` |
| `+0x04` | `render` |
| `+0x08` | `onNoteOn` |
| `+0x0c` | `onNoteOff` |
| `+0x10` | byte: the selected engine id (`*(char *)(param_1 + 0x10) = (char)param_4`) |
| `+0x14` | int: engine id used for selection |
| `+0x1c` | a value from `FUN_800fc160(DAT_81059280)` |
| `+0x48` | **the engine's state block** - this is the pointer passed as `init`'s first argument |

`FUN_8012d278` fills the record: it asks the plugin registry (`FUN_800fc104(DAT_81059280, engine_id)`) for
the plug object, copies `plug[0]`/`plug[2]`/`plug[3]`/`plug[4]` into `+0x00`/`+0x04`/`+0x08`/`+0x0c`, and then
calls

    (*pcVar14)(puVar15 + 0x12, param_2, uVar5, uVar5, &DAT_8156f2b8);

i.e. **`init(state, voice_index, x, x, &DAT_8156f2b8)`** - five arguments, of which the harness has been passing
two. The fifth points at `0x8156f2b8`, which reads as zeros in the image (runtime-filled RAM).

Two things follow, and both are useful even though neither made an engine sing yet:

1. The state is a plain `0x134`-byte block *inside* the OS's record, not a set of OS-maintained pointers. The
   OS does not pre-fill it with callbacks; it calls `init` and lets the engine set itself up. That weakens the
   "needs OS-populated state" explanation I have been repeating and points instead at the arguments and
   ordering still being wrong.
2. Retrying every instrument with a five-argument `init` changes behaviour (`cluster` and `volt` now reach
   full-scale output instead of silence) without producing tone, so the extra arguments matter but are not
   sufficient.

Source paths located for the next step: `InstrumentManager.cpp` at `0x815c7b30` (referenced by
`FUN_8012d638`, `FUN_8012d524`, `FUN_8012d278`), `FxManager.cpp` at `0x8156f22c`, and `Voice.cpp` at
`0x815c828b` - the last has no cross-references in the image, so it is reached through a pointer.

### A tooling trap that cost a whole round: listing-based scans under-count

The first version of `ghidra-scripts/FindIndirectCalls.java` walked the program listing and reported **662**
indirect call/jump sites. That number was wrong: large parts of `opz.ldr` have no instructions in the listing
until something asks for them, so a listing walk silently skips whole regions. The engine's own `init` call
site - `0x8012d41a`, `Call CALL (P0)`, the very call whose arguments this doc documents - was one of the
missed ones, which is why "there are no indirect calls in the plugin-manager region" looked true and was not.

The script now scans the bytes of every executable block for the Blackfin `ProgCtrl` indirect encodings
(bits 8-15 zero, `opc` 5-8), disassembles each candidate on demand, and keeps the ones that come back as an
indirect `Call`/`Jump`. That reports **1020** sites and finds `0x8012d41a`. The same trap applies to any
listing-based search over this image, including `CallersOf.java`: absence of a hit means absence *in the
listing*, not absence in the image.

What is still missing is the `render` call site: the record's `+0x4` slot is never loaded near an indirect
call in the synth region (201 sites scanned), so it is reached through a register computed further away, and
the remaining candidates are the `+4`/`+8`-loading sites in `FUN_8010fd48` (`0x80110032`, loads `[P1+0x8]`)
and `FUN_801149e4`/`FUN_80115fb4` (`0x80114a26`, `0x8011601a`, load `[P1+0x4]` with `R2 = FP`).

### The render call, read out of the OS

`FUN_8012e2c0(param_1, param_2, param_3)` is the per-voice engine tick - it advances the envelope, converts
the level, and then dispatches into the engine:

```c
(**(code **)(param_1 + 4))(
    param_2,                                    /* output buffer                        */
    *(int *)(param_1 + 0x168),                  /* pitch, Q16, from the record          */
    iVar7 - *(int *)(param_1 + 0x168) >> 6,     /* bend: target - current, >> 6         */
    param_1 + 0x48,                             /* the engine's STATE                   */
    param_3,                                    /* the params object                    */
    param_1 + 0x30);                            /* the AMP object                       */
```

That fixes, in one place, everything doc 11 has been inferring from engine behaviour:

* `render(out, pitch_q16, bend, state, params, amp)` - six arguments, matching the six-slot stack the
  harness already builds.
* the state is `record + 0x48`, exactly the pointer `init` receives;
* **the amp object is `record + 0x30`, i.e. `state - 0x18`** - it is not an arbitrary pointer the OS hands
  over separately but a fixed 24-byte slice of the same record, immediately below the state;
* pitch comes from `record + 0x168` and the bend is the difference between the envelope's target and that
  pitch, shifted right by 6.

The surrounding envelope work is what populates the amp object before the call - `FUN_8012e0a4` stores into
`amp+0x10` (`[P5 + 0x40]` with `P5 = record + 0x30`), a byte at `amp+0x14`, and keeps the working values in
`record+0x160`, `+0x164`, `+0x16c`. Building the record exactly as the OS does (`+0x00/+0x04/+0x08/+0x0c`
entry points, amp at `+0x30`, state at `+0x48`, zeroed elsewhere) and calling with the OS's own six arguments
still renders silence for all thirteen instruments, with `volt` alone reaching full-scale DC - so the ABI is
no longer a guess, and the gap is now strictly the *contents* of the amp object and of the state after the
OS's envelope pass.

### What the OS writes into a record when a note starts

`FUN_8012e0a4` is the voice's note-start routine (called by the instrument manager right after it fills the
record). It writes the record fields the tick then reads:

| field | value at note start |
|---|---|
| `record + 0x40` (**`amp+0x10`**) | `5` - the amp state the engines test against zero |
| `record + 0x38` (**`amp+0x08`**) | `0x7f000000` - a full-scale gain |
| `record + 0x3c` (**`amp+0x0c`**) | `-(record[0x34] * [0x815c8088])` |
| `record + 0x44`, `+0x45` (**`amp+0x14`**, **`amp+0x15`**) | bytes from the caller |
| `record + 0x168` | the pitch passed as `render`'s second argument |
| `record + 0x160`, `+0x164` | envelope level and target |
| `record + 0x16c` | envelope counter |
| `record + 0x18`, `+0x20`, `+0x28`, `+0x10`, `+0x25`, `+0x2c`, `+0x2d`, `+0x178` | assorted voice state |

Two things worth recording because they close off avenues:

* **This function contains no indirect call**, so the OS's note-on path does not invoke the engine's
  `onNoteOn` export: it calls `init` (in `FUN_8012d278`) and `render` (in `FUN_8012e2c0`) and nothing else. The
  export exists in the plug object and must be called from somewhere, but it is not part of starting a note.
* Feeding the tick the OS's own note-start amp values (`amp+0x08 = 0x7f000000`, `amp+0x10` swept 1-6,
  `record+0x168` = 440 in Q16) still renders `0.0000` for all thirteen instruments, `volt` alone reaching DC.
  So the amp contents are not the missing piece either, and what remains is the *state block's* contents after
  `init` - the one thing this harness hands over empty.

### The ABI detail that made every factory engine look state-starved

For many rounds the sweeping conclusion here was "the factory engines are silent because their per-voice state
is missing". That conclusion was wrong, and the correction is simple: **this ABI pushes every argument onto the
stack as well as passing the first three in `R0`-`R2`, and the engines read them from the stack.**

The evidence is in the offsets. `FUN_8012e2c0` calls an instrument as

    (*render)(out, record[0x168], target - record[0x168] >> 6, record + 0x48, params, record + 0x30)

and chord's prologue reads its context at `[FP+0x14]`, parameters at `[FP+0x18]`, amp at `[FP+0x1c]`. `LINK`
pushes `RETS` and `FP` and sets `FP = SP`, so those offsets are stack words 4, 5 and 6 - i.e. the engine reads
the *stack copies* of arguments 4, 5 and 6. A harness that pushes three words (`ctx, prm, amp`, the register
arguments only) leaves those slots zero, and the engine sees no state even though it was passed correctly in
registers.

Switching to six stack words changed the sweep immediately: with the same state, same amp values and same
engine files, `digital` and `electric` went from writing nothing to writing signal, `cluster` from silence to a
0.016 peak, and several engines that previously hung now run far enough to fail on a concrete decoder gap
instead (`analoga` on instruction `0xf64f`). The current table is 6 silent, 5 loops, 5 needs-state, 4 flat,
1 error, 0 fully audible - still not tone, but no longer because the arguments were in the wrong place.

Two decoder gaps surfaced in the same pass and are now implemented: `Dsp32Shf` `dsSopc=0x07` (**ExpAdj**, a
normalising helper: the sign-bit count of `src0` - or of one half, or the worse of both - clamped by `src1`),
and `RegMv`'s M-register forms (source index in bits 0-1, destination in bits 3-4).

### What the corrected ABI changed, engine by engine

With all six arguments on the stack, `chord` stops returning early and **reaches its 64-frame sample loop**
(`0x81be2794`) for the first time, writing real samples into the output buffer - peak 0.037 with `amp+0x10 = 1`.
It then corrupts its own caller's frame: at the `UNLINK` at `0x81be2930` the saved words at `FP` and `FP+4`
read `0` instead of `(entry FP, 0xDEAD0000)`, so `UNLINK` restores `RETS = 0` and the `RTS` at `0x81be2934`
jumps to address 0. The stack pointer itself balances exactly (entry `0x81c22ed8`, exit `0x81c22ed8`), so this
is not a push/pop fault in the interpreter: the engine wrote over the frame because a pointer it computed from
its empty state block points at the wrong place.

That is the shape of the remaining work in one sentence: engines now receive their arguments correctly, run
their DSP, and then damage themselves with pointers derived from a state block that `init` leaves empty.
`digital` (peak 0.007) and `electric` (peak 0.986) write signal, `cluster` reaches 0.016, and none of them yet
holds a pitch - every one of those numbers is a transient rather than a tone.

### Who zeroes chord's frame, and where

The frame damage is chord's own doing, and it is two instructions: at `0x81be2752` and `0x81be2758` it stores
`[P0 + 0x8] = R3` and `[P0 + 0x4] = R5`, where `P0` was loaded from its own stack local `[SP + 0x38]` at
`0x81be26ec`. In the harness that local holds `0x81c22ecc`, so the two stores land exactly on the caller's saved
`RETS` and `FP` - `0x81c22ed4` and `0x81c22ed0` - zeroing both, which is why the `RTS` at `0x81be2934` jumps to
address 0. The store pattern (`P0+4` and `P0+8`, two words past some base) reads like writing a pair of results
immediately after a structure, so the local is almost certainly meant to hold a pointer derived from engine state
rather than a stack address.

### The one-word stack error, and how it was caught

The harness used to push a spare word ahead of the arguments - a stand-in for a saved return address - and only
the arguments belong there. The consequence was systematic: every `[FP+n]` a callee read was one word off, so
`chord`'s `P1 = [FP + 0x14]` (its state) received the third stack argument instead, and its parameters and amp
slots were wrong in the same way. The engines did not "lack state"; they were reading the wrong slots.

It was caught by asking the engine rather than the emulator: after each change, print `[FP+0x14]`,
`[FP+0x18]` and `[FP+0x1c]` at `chord`'s prologue and compare against the pointers the harness passed. Before
the fix those read `0`, `0`, `0`; after it they read `0x81bd2048`, `0x81bc2000`, `0x81bd2030` - exactly the
context, parameters and amp. That check is cheap, unambiguous, and worth repeating for any engine.

Fixing it meant retuning `struck`, whose own argument walk was written against the wrong layout (eight
discarded post-increment loads became seven: seven saved registers are 28 bytes, so seven discards land on the
first stack argument). The JIT needed the same treatment - it now carries a `rets` variable and sets it in
every call form instead of pushing a return address - and after both changes interpreter and JIT are
bit-identical again over 384 samples with `struck` measuring 440.1 Hz.

### Chord's return-address damage, traced to the instruction

With the arguments finally correct, chord's failure has one cause and it is fully traced:

* its frame is at `FP = 0x81c22ee0`, with the saved `FP` at `[FP]` and the saved `RETS` at `[FP+4]`;
* at `0x81be2752` it stores `[P0 + 0x8] = R3` and at `0x81be2758` `[P0 + 0x4] = R5`, with `P0 = 0x81c22edc`
  - i.e. `FP - 4` - so the two stores land exactly on the saved `FP` and `RETS`;
* `RETS` therefore becomes `0x81bd2048`, the engine's own state pointer, and the final `RTS` at `0x81be2934`
  jumps into the state block, where it executes zeros as NOPs until it hits `0x01b8` and stops.

`P0` is loaded from chord's own stack local `[SP + 0x38]` at `0x81be26ec`. Chord fills that local at
`0x81be25f6`, and the arithmetic around it decodes as `MvRegToReg P1 = FP` (`0x81be2856`), `AddImm P1 += -0x20`
(`0x81be2874`) and `AddImm P1 += -0x10` (`0x81be25f0`) - the `-0x20` runs *after* the store on the first pass,
so the stored base is `FP - 0x10`, and `P0` then advances eight bytes before the two stores, putting them at
`FP - 0x04` and `FP + 0x04`.

Checked against Ghidra, those three instructions are decoded correctly, so this is not a decoding error in the
emulator. What it means is that chord's stack usage needs the frame to extend about `0x14` bytes further than
the `LINK` allocates, or that one of the pointer values feeding `P0` differs from silicon. Both readings point
at the same narrow check - the value of `P0`'s base against a disassembly of `0x81be2620..0x81be2760` - rather
than at engine state.

### The decoder bug behind chord's self-destruction: `DspLdSt` mis-claimed as `LdSt`

Chord overwrote its own caller's frame for many rounds. The cause was not engine state: it was the
interpreter decoding `[I0++]` as a `P0` increment.

`DspLdSt` (`instr16/19-DspLdSt.sinc`) carries its signature `0x27` in bits 10-15 and covers `[I0++]`,
`[I0--]`, `[I0]` and `[I0++M]`. The 16-bit `LdSt` class uses bits 12-15 = `0x9`, which is a *prefix* of that
signature, so `0x9c02` - `R2 = [I0++]` - matched `LdSt` first and was executed as a load through `P0` with
post-increment. Chord's loop loads three samples per iteration that way, so each iteration walked `P0` another
twelve bytes up its own frame until the stores at `[P0 + 4]` and `[P0 + 8]` landed on the saved `FP` and
`RETS`, and the final `RTS` jumped into the engine's state block. Every earlier attempt to explain that damage
with engine state was chasing a symptom.

With `DspLdSt` implemented ahead of `LdSt` (including the `[I0++M]` modifier-register form and the 16-bit
half-register loads and stores, which needed real 2-byte accessors so a half store cannot clobber its
neighbour), chord runs its 8,863 instructions, reaches its 64-frame loop, advances `I0`/`I1` from `state + 8`
to `state + 0x10` as the loop reads and writes its working buffer, and **returns through UNLINK/RTS to its
caller**. It writes nothing to the output buffer yet - the samples go into its state working area - but it no
longer destroys itself, and nothing about that change involved guessing at state contents.

### The second silent decoder bug: Comp3op's pointer opcodes

Chasing "chord writes a full block of zeros" produced a second real decoder fault. `Comp3op`
(`instr16/15-Comp3op.sinc`) is one class with eight opcodes: 0-4 are data-register add, subtract, and, or
and xor, while **5-7 write pointer registers** - `dst = s0 + s1`, `dst = s0 + (s1 << 1)` and
`dst = s0 + (s1 << 2)`. The emulator treated every opcode as a data-register add or subtract, so chord's

    PtrOp P1 = P2 + (P1 << 2)        (0x5e4a at 0x81be27c4)

never touched `P1`. Its oscillator-table load therefore used the bare phase index - `0x37` - as a memory
address, read zero from the hole below the module, and every computed sample was zero. It was invisible until
the arguments and the `DspLdSt` mis-decode were fixed, which is why it survived so long.

With the opcodes implemented, chord reads real table data (`0x565d942` at `0x800bc20`) and its loop produces a
growing phase ramp and sine values, `crush` goes from all-zero to 13 distinct output values, and the sweep
reports `crush` as detuned-but-signal rather than silent. Chord still writes zeros to the output buffer,
because the copy path uses a value that remains zero - the next link in the chain - but the oscillator itself
now works, which it never did before.

**Hypothesis ledger.** `HYPOTHESES.csv` now carries this work as a running audit trail: four hypotheses about
where the audio goes were disproved this round (state block, `I0`/`I1` presetting, short loop, no output
writes), and the fifth - "the zero comes from the value chain" - was proved to be this decoder bug. Testing one
hypothesis per iteration, with a written conclusion each time, is what stopped the same ground being covered
twice.

**Practical note on runs:** the toolkit now installs a two-minute watchdog (`toolkit/opztime.py`) on every
tool, because an unmodelled engine loop otherwise hangs a run silently. Override with
`OPZ_TIME_LIMIT=<seconds>`.
