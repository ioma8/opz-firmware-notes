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

### The multiply-scaling question, answered by the modifier field

Resolved: `dxMmod` (bits 5-8) selects the scaling. When `dxM32M`, `dxM32U` and `dxM32I` are all zero the
multiply is the **fractional** form - `res = (src0 * src1) << 1`, then bits 63:32, i.e. a shift of 31. When
any of them is set it is the **integer** form and the product is taken directly, a shift of 32. chord's
multiply is `mmod = 1`, the integer form, which is why a class-wide `>> 31` broke `struck` (also `mmod = 1`)
while changing nothing for chord. Both forms are implemented now, and the earlier split evidence makes sense:
the fractional shift belongs to a form neither engine actually uses.

### Earlier note: why the question could not be answered class-wide

`Dsp32Mult` is the next suspect after the oscillator started working. `instr32/26-Dsp32Mult.sinc` builds
`res = (src0 * src1) << 1` and then extracts bits 63:32, which is a right shift by **31**, while the emulator
shifts by **32**.

The two readings disagree, and the evidence is split in a way that rules out a class-wide answer:

* with `>> 31`, `crush` gets louder and more distinct (peak 0.014 → 0.026, 12 distinct values), and chord's
  products stop vanishing;
* with `>> 31`, **`struck` fails ten tests** - pitch 2304 Hz where 440 was asked, decay buckets never reaching
  T60 - while with `>> 32` it passes all ten and matches the hardware behaviour it was validated against on the
  device (110/220/440/880 Hz, measured within 0.01%).

An engine that sounds correct on real silicon is the strongest evidence available here, so the shift stays at
32 and the hypothesis is recorded as *need more info*: the scaling must be selected by the per-instruction
modifier field (`dxMmod`), with the fractional forms shifting by 31 and the form `struck` emits shifting by 32.
Splitting them is the next step, and it needs chord's modifier decoded rather than a class-wide constant.

### The amp object carries the voice gain, and the harness leaves it zero

Tracing chord's `R1` lifetime pins the last structural gap. At `0x81be278c` chord does `R1 = [P3 + 0x4]`, and
`P3` is argument 6 - the **amp object**. So `amp+0x4` is a per-voice gain the OS fills before the tick, and the
harness was leaving it zero (only `amp+0x08` and `amp+0x10` were being set).

Supplying it is measurable: with `amp+0x4 = 0x7fffffff`, `digital` goes from 7 to **24 distinct output values**
and chord's loop produces real oscillator data (`0x565d942`, `0xab61b1`, `0xac93d17` - growing, then wrapping).
Chord still ends up writing zeros, because after the gain it multiplies by `R2`, a second per-voice coefficient
that is still zero.

That is a different kind of finding from the last three rounds: `DspLdSt`, `Comp3op` and the multiply modifier
were all emulator faults, whereas this is the amp object's contents - the area doc 11 has described all along,
now narrowed to two specific dwords (`amp+0x4` gain, and whatever feeds `R2`).

**Practical note on runs:** the toolkit now installs a two-minute watchdog (`toolkit/opztime.py`) on every
tool, because an unmodelled engine loop otherwise hangs a run silently. Override with
`OPZ_TIME_LIMIT=<seconds>`.

## What the amp object actually carries, and two engines that now sound

The amp object is render's sixth argument (`record+0x30`, a 24-byte slice of the instrument record) and
**the OS fills it, not the engine**: `FUN_8012e0a4` writes `record+0x40` (`amp+0x10`) = 5,
`record+0x38` (`amp+0x08`) = `0x7f000000`, and `record+0x3c` (`amp+0x0c`) =
`-(record[0x34] * [0x815c8088])` — a **negative** scaling. chord loads `amp+0x04` as its voice gain at
`0x81be278c`.

Leaving those fields zero is why every previous sweep reported the factory engines as silent. Supplying
`amp+0x04 = 0x7fffffff`, `amp+0x08 = 0x7f000000` and `amp+0x0c = -0x40000000` moves two engines out of
silence on the same decoder that was already passing every other gate:

| engine | before | after |
|---|---|---|
| chord | silent, peak 0.000 | detuned, peak 0.060, tail-rms 0.0164, 79 distinct values |
| digital | silent, peak 0.000 | detuned, peak 0.121, tail-rms 0.0725, 107 distinct values |
| crush | detuned (unchanged) | detuned, peak 0.014 |

Sweep now reads **3 detuned, 5 loops, 3 needs-state, 10 silent** of the 21 official engines.

Two further facts measured on `digital`, which is the closest to playing:

- its pitch comes from **render's second argument**, not from the note passed to `onNoteOn`. Holding the
  pitch argument at 440 Hz and sweeping the note over 45/57/69/81 gives an identical 750 Hz every time,
  while holding the note at 69 and sweeping the pitch argument moves it (220 Hz → 375 Hz, 440 Hz → 750 Hz).
  This is the same conclusion doc 11 reached about the ABI, now confirmed by measurement on a factory
  engine rather than inferred from the code.
- its output carries a large DC offset (mean ≈ +0.095), so zero-crossing pitch measurement reports
  nonsense; autocorrelation and DFT are the tools that give usable numbers on these waveforms.

Also corrected: `AC0` is ASTAT **bit 12**, not bit 4 (`instr16/05-CC2Stat.sinc`'s `ccsCBIT` name table:
AZ=0, AN=1, ACOCOPY=2, VCOPY=3, CC=5, AQ=6, AC0=12, AC1=13, AV0=16, ...). chord and digital read
`CC = AC0` 57 times per render block, so the flag had been returning the always-zero path. Fixing its
position is correct but does **not** change any engine's verdict on its own.

### digital's render, read from the disassembly

`digital.engine` (base `0x81be6000`, render `0x81be6160`) is a **pitch-band wavetable synth**, and its
prologue explains why it had never sounded:

```
0x81be6168  R7 = R1                      ; R7 = render's pitch argument
0x81be61e8  R0 = [P0 + 0x14]             ; P0 = 0x81be69f0, a table in the module
0x81be61ec  CC = R0 <= R7                ; compare pitch against a band edge
0x81be61f4  R0 = [P0 + 0x28]
0x81be61f8  CC = R0 <= R7
0x81be61fe  CC = R1 <= R7
0x81be6200  R2 = 0xb / R0 = 0xa          ; select band index 10 or 11
0x81be6218  P0 = P0 + (P2 << 2)          ; index the band table
0x81be6222  R3 = R7 - R0                 ; pitch minus the band's base
0x81be62b0  P1 = P1 + (P2 << 1)          ; 16-bit band entry at 0x81be69d4
0x81be62b6  R1 = W[P1]; R3 = W[P1 + 2]
```

So the engine does consume the pitch argument, converting it against a table of band edges.

What it does **not** do is keep any oscillator state between render calls: instrumenting the whole
2608-byte module image across five consecutive renders shows **zero module words changing**, and the only
cross-call state is four dwords of the engine state block. Its output therefore restarts every block, and
the spectrum is dominated by the 64-sample block period (a 750 Hz artifact, since 48000/64 = 750), which is
what every zero-crossing, autocorrelation and DFT measurement keeps locking onto.

That is the concrete, still-open shape of the remaining factory-engine problem: these engines expect the
voice's running phase to be maintained **outside** the engine, in the instrument record that
`FUN_8012e2c0` owns, and no harness field tried so far (`amp+0x04/0x08/0x0c/0x10`, `record+0x160`,
`+0x164`, `+0x168`, `+0x16c`, the whole 0x134-byte state block, params, note) supplies it.

### How the OS actually drives an engine's pitch each tick

`FUN_8012e2c0` recomputes the pitch on **every** tick rather than letting the engine advance it:

```
0x8012e368  R1 = [P5+0x170] ; R1 = R1 * 0xc8 (T)     ; slow glide rate
0x8012e374  R7 = [P5+0x174]                          ; the pitch target
0x8012e378  CALL 0x8011aa1c                          ; note -> pitch conversion
0x8012e380  R1 = R7 * 0x190 (T) ; CALL 0x8011aa1c    ; fast glide rate
0x8012e390  R1 = [P5+0x168]                          ; last tick's pitch
0x8012e39a  R0 = R0 - R1 ; R2 = R0 >>> 6             ; render's bend argument
0x8012e3b0  CALL (P1)                                ; render(out, pitch, bend, state, params, amp)
0x8012e3b2  [P4+0x168] = R7                          ; pitch <- converted target
```

So the six arguments are `(out, record+0x168, (converted_target − record+0x168) >> 6, record+0x48,
params, record+0x30)`, and `record+0x174` is the **pitch target** while `record+0x168` is the value the
engine sees. The two conversions at `0xc8` and `0x190` are a portamento glide: the difference between the
slow and fast conversions is handed to the engine as `bend`.

This settles the pitch question — the harness was already passing the right argument — but it does **not**
explain digital's silence, because digital has no oscillation *within* a block either: autocorrelation
restricted to lags below 64 returns a 2-sample lag at 110, 220, 440 and 880 Hz alike. Its output is a slow
ramp, and the earlier 750 Hz reading was only the 64-sample block repeat.

### digital's band table is intact, and in Q16 Hz

Dumping the two tables digital indexes (from the module image, not through Ghidra) settles the
byte-order and stride questions:

```
0x81be69f0  twelve band edges, Q16 Hz, spaced by octaves:
            12.15  24.30  48.60  97.20  194.40  388.80
           777.59 1555.18 3110.37 6220.73 12441.46 24882.93
0x81be69d4  twelve 16-bit per-band steps: 19661 26214 26214 26214 26214 26214
                                          22938 19661 16384 13107 8192 0
```

The render pitch argument is Q16 Hz (`440 << 16`), so a 440 Hz request falls in the 388.80–777.59 band,
which is what the comparison chain selects. The emulator reads both tables back byte-for-byte identical
to the file, so no decoder or loader fault is involved. Whatever keeps digital from oscillating is in its
own arithmetic over these values, not in the data it reads.

### The OS's own tables next to the amp scaling constant

Reading `0x815c8070`..`0x815c80a0` out of `opz.ldr` settles two conventions at once:

```
0x815c8070  68 84 12 81 8c 8d 12 81 b0 96 12 81 d4 9f 12 81   ; four pointers
0x815c8080  f8 a8 12 81                                      ; 0x8112a8f8
0x815c8084  01 00 00 00                                      ; 1
0x815c8088  ff ff 7f 00                                      ; 0x007fffff  <- the amp scaling constant
0x815c808c  5e 26 0c 00  51 df 0c 00  45 a3 0d 00  df 72 0e 00  d1 4e 0f 00
```

`FUN_8012e0a4` computes `record+0x3c` (`amp+0x0c`) as `-(record[0x34] * [0x815c8088])`, so with
`[0x815c8088] = 0x007fffff` and `record+0x34` near full scale the result is about `-0x3fffff80` — within a
rounding step of the `-0x40000000` the harness already supplies. So `amp+0x0c` is **not** what keeps the
engines from oscillating.

The dwords from `0x815c808c` onward are a semitone table in Q16 Hz — 12.157, 12.870, 13.635, 14.441,
15.311, each `2^(1/12)` above the last — which is the table `FUN_8011aa1c` (called twice per tick from
`FUN_8012e2c0` for the slow and fast glide conversions) walks. That independently confirms the pitch unit
the engines receive is Q16 Hz, the same unit their own band tables use.

## Running the firmware itself: `toolkit/opzos.py`

The conclusion that drove this tool: the factory engines were never silent from a decoder fault. They
multiply a working oscillator by a per-voice coefficient the **sequencer** computes, and no synthetic
harness input reaches it. So instead of synthesising that state, run the firmware and let it compute the
state itself.

What the tool does, and what it establishes:

- `opz.ldr` is the same dlm container as an engine (byte 3 = `0xad`) and parses into **164 segments**:
  83 in the main image `0x80000000..0x815caea0` (648 KB), 75 L1 overlays at `0x11a...`, 6 at `0x08...`.
  The engine windows (`0x81b93800+`) do **not** overlap the OS image, so one flat 32 MB window
  (`0x80000000..0x82000000`) holds both.
- With that mapping, **the OS's own code executes in `opzsim`**. `FUN_8012e2c0` (the per-voice tick) runs
  to completion in 2,121 steps, and `FUN_8012e0a4` (note start) runs to completion and fills the amp
  object by itself — `amp+0x08 = 0x7fffffff`, `amp+0x10 = 1` — which is exactly the state the harness
  could never synthesise.
- Two ISA gaps had to be closed to get there: **`UNLINK` is a 4-byte instruction** (it was consuming 2,
  so every UNLINK executed its own frame halfword), and **`Jump32` (`CALL.A`/`JUMP.A`, `0xDE00`-class)** was
  missing entirely — `FUN_8011aa1c`, the note-to-frequency conversion the tick calls twice, issues
  `CALL.A` on its own.

Remaining block, precisely stated: the tick stops with a null function pointer because the synthetic
record's **patch fields** are not populated. Those are the values the plug manager reads from the plug
definition and hands to the voice; `record+0x34` (which the OS scales by `[0x815c8088] = 0x007fffff` into
`amp+0x0c`) is one of them and is still a guess. Filling them from the real plug data is the next step.

### What the OS-driven path proves, and where it stops

With `toolkit/opzos.py` the whole chain now runs inside `opzsim`, and the call trace is the firmware's own:

```
FUN_8012e2c0 (tick)  ->  FUN_8012e058  ->  FUN_8011aa1c twice (slow/fast pitch glide, note -> Q16 Hz)
                     ->  record+0x04  =  0x81be6160   (the engine's render, called by the OS)
                     ->  0x800314c8                  (a real host service through the OS's own table)
```

15,717 steps per tick, and no part of the argument or state setup is synthesised by the harness any more.

Two things are still missing, and both are visible in the output:

- `record+0x34` **is cleared to 0 by the firmware**, so `amp+0x0c` (which the OS computes as
  `-(record[0x34] * 0x007fffff)`, see above) comes out 0 and the engine's gain path stays dead. The field
  is not a constant the harness can preset; the plug manager computes it per voice.
- the block therefore contains exactly **two nonzero frames** (0.15, -0.999) and 62 zeros - the engine's
  first two samples, then silence. Not audio.

So the remaining work is not emulator correctness and not argument framing: the synthetic record has to be
replaced by a real one, built the way the plug manager builds it (`FUN_800fc104` returns the plug object
that `FUN_8012d278` copies the engine pointers out of, and `FUN_800fc160` returns the registry value passed
to `init`). Driving `FUN_8012d278` itself - the real note-on - instead of hand-filling a record is the next
step, and the OS-emulation harness is now good enough to attempt it.

### The real note-on needs the plug registry, which only exists after boot

Attempting `FUN_8012d278` (the OS's real note-on) instead of hand-filling a record:

- it **runs** - 1,941 steps, returns cleanly - but the plug registry pointer at `0x81059280` is **0**,
  because that global is BSS in the image (it holds `00000000` followed by the string bytes `rb`) and is
  reached through a computed pointer: a literal search of the whole image for `0x81059280` finds **zero**
  references. So the note-on writes an engine id (`0x41`) into the record and leaves the resolved entry
  points null.
- `FUN_8012e0a4` (note start) fills `amp+0x08 = 0x7fffffff` and `amp+0x10 = 1` on its own, but leaves
  `amp+0x04` and `amp+0x0c` at 0 - and `amp+0x0c` is `-(record+0x34 * 0x007fffff)`, so with
  `record+0x34` at 0 it stays 0 and the engine's gain path is dead. The OS-driven render therefore
  produces **two nonzero frames then 62 zeros**, unchanged by moving the record or by presetting the
  envelope fields `record+0x160`/`0x164`.

Also learned the hard way: a scratch record parked at `0x81f00000` gets written through by unrelated OS
code whose pointer aliases it (`B[P5+0x211]`), which mimics "the firmware cleared my field". `opzos.py` now
places its record at `0x81600000`, above the image and clear of the stack.

**Conclusion:** every remaining field is computed by the plug manager, and the plug manager's registry is
built during boot from the settings on the filesystem. Driving the engines through the real sequencer
therefore requires booting the firmware (flash/NAND plus the file layer), not another harness input.

## A fifth decoder fault: `LdImmToReg` into a pointer register wrote a data register

`LdImm32` (`instr64/38-LdImm.sinc`, `liwSig` 0x368) selects the register file with `liwGrp`: group 0 is a
data register and group 1 a pointer register, which is **bit 3 of the first halfword** — `0xda08` loads P0,
`0xda00` loads R0. opzsim matched only the top byte and always wrote the data file, so every
`P0 = <address>` in every engine and in the firmware was inert.

Why it hid for so long: a wrong destination register does not crash, it just leaves the pointer at its old
value, so engines read from address 0 and produce silence or a ramp. It surfaced only when the firmware was
started at its own entry: the boot dispatch reads its vector table through `P0`
(`P0 = 0x11904cf0`, then `P1 = [P0 + (R1 << 2)]`, then `JUMP (P1)`), and with P0 stuck at 0 it jumped to
address 0 on the first dispatch.

After the fix: the firmware's L1 startup code at `0x11900000` executes 4,932 steps (it previously did not
run at all), and the factory-engine sweep changes again to **2 detuned, 2 flat, 3 loops, 4 needs-state,
10 silent** — chord 6040 Hz at peak 0.050, digital unchanged at 0.0725 tail-rms, crush and volt now flat.
All gates stay green: simulator suite (519,370 steps), `struck`, the player, 34/34 encodings and 21/21
containers.

Boot status: `0x80000000` is a vector *dispatcher*, not reset (it takes the vector in R1 and returns for
vector 0), and `0x11900000` is the real startup entry. It now runs until it reaches bytes
`00ec 00ed 00ee` at `0x119027dc` — three consecutive values, i.e. a data table, so something upstream
still diverges. Ghidra cannot help there directly: the L1 segments are not imported into its project.

### The same pointer-group bug in the 16-bit `LdImmHalf` form, and how far the firmware boots now

`LdImmHalf` (`instr32/32-LdImmHalf.sinc`) has the identical `lihGrp` bit at bit 3 — `0xe128` is
`P0 = 0x4000`, `0xe120` would be `R0`. opzsim wrote the data file unconditionally there too, so every
`Preg = imm16` was inert. It mattered the moment the firmware ran: the startup's 16K-word L1 copy is

```
0x11a036a6  P0 = 0x4000          ; halfword 0xe128
0x11a036b2  LSETUP(0x11a036b6,0x11a036ca) LC0 = P0
```

so with P0 never set the loop count was garbage and the copy spun forever. After the fix the firmware
boots from its real entry `0x11a00000` (CSYNC, SYSCFG setup, `SP = 0x11801ffc`, `USP = SP`, FP, loop
registers) for **182,450 steps**, enters the main image, and stops at its first deliberate trap:
`0x11a000bc  RAISE 0xf`.

Sweep after both pointer-group fixes: **2 detuned, 3 flat, 3 loops, 5 needs-state, 8 silent**
(chorus2 now flat at 0.0244 tail-rms; ministringshort, saw013a and reverb now classified needs-state;
dist, cluster and organ still silent).

Next blockers on the boot path, in order: `RAISE`/`EXCPT` need to vector through the event table rather
than being treated as no-ops (the code after the RAISE at `0x11a000bc` is the handler's own
`RETI = ...; RTI` return path), and `Push [--SP] = RETI` needs the special-register group that
`PushPopReg` does not model yet.

### Boot status after the special-register group

`PushPopReg` group 7 (the special registers RETI/RETX/RETN/RETE/EMUDAT) now has storage, so the
firmware's exception prologue `Push [--SP] = RETI` at `0x11a000ca` executes instead of stopping the run.

The boot then leaves the image entirely and executes **816,548 steps in the `0x04000000` region**, which
holds none of the LDR's 164 segments - i.e. it is running zeros. So the remaining gap is not another
missing instruction class but **exception semantics**: `RAISE 0xf` at `0x11a000bc` has to vector through
the event table, and the `RETI = ...; RTI` sequence that follows it is the handler's return path. Treating
`RAISE` as a no-op walks straight into that return path with a RETI the firmware never set, which is
exactly the bogus jump to `0x04xxxxxx`.

Concretely, running the sequencer now needs, in this order:

1. an event-vector table (the startup writes `[0x20000020] = 0x11a00000`, which is the EVT base register)
   plus `RAISE`/`EXCPT` vectoring and correct `RTI` (restore RETI and the flags),
2. a minimal peripheral model for whatever the boot polls (`0x80142054` fills a 13-entry descriptor table
   in L1 data and then writes `0x8030000` - a device register base),
3. the flash/file layer, since the plug registry the sequencer needs is parsed from `settings/plugs.json`
   at boot.

## Why the firmware bring-up cannot finish with the images we have

Following the boot to its first out-of-segment jump gave a clear answer, and it is not a decoder gap:

- **`0x04xxxxxx` is a heavily used code region, not a wrong turn.** Scanning for the `Jump32` encoding
  finds **1,195 `CALL.A` sites in `opz.ldr`** and **459 in `bootloader.ldr`** targeting it.
- **It is not an L2 alias that gets unpacked.** The offsets line up exactly
  (`0x04020610 - 0x04000000 == 0x08020610 - 0x08000000`), but after 203,443 boot steps L2 at those
  addresses is still zero and byte-identical to the image — nothing unpacked code there.
- **`opz.ldr` is not truncated.** 164 segments, 825,512 payload bytes plus 2,624 header bytes, which is
  exactly the 828,136-byte file. The container is complete, so the missing region is not a parsing
  mistake on our side.

So the firmware executes from a memory region that neither image contains, and the boot cannot get past
it. Reaching the sequencer — and therefore pitched factory engines — needs either that region (a further
image, or a memory dump from the device), or the device's memory map for it. That is a data problem, not
an emulator problem, and it is where this line of work ends with the material available here.

Two further checks pin that conclusion down:

- **The `CALL.A` decode is right where Ghidra can see it.** `0x800002c0` decodes in Ghidra as
  `Call CALL.A 0x040201c4`, identical to `opzsim`'s reading, and there are **979 such sites in the main
  image alone**. So this is not an artefact of our decoder.
- **No other payload on disk contains the region.** Every candidate was tried: `opz.ldr` (164 segs,
  0x11/0x08/0x80/0x81), `bootloader.ldr` (58 segs, 0x11/0x82), and the install logs
  `install_z_firmware_1_1_9`, `plugfix_*` (two), `ablate_*` and `console_upgrade_1_2_45` — the last five
  are not dlm containers at all, and neither LDR has a single segment in `0x04xxxxxx`.

The boot therefore stops for lack of an image, not for lack of emulation. What would restart it: a memory
dump covering `0x04xxxxxx`, the OP-Z/BF703 memory map for that region, or a firmware image that loads there.

### Sample engines: where the sample comes from

`sampleplayergain` reaches its sample through the engine state, not through the host:

```
0x81b694e8  R2 = [amp + 0x10]     ; must be non-zero or render exits
0x81b694f0  R0 = B[state + 0x31]  ; must be <= 0
0x81b69504  R0 = [state + 0xc]    ; must be non-zero  <- the sample pointer
```

`onNoteOn` leaves `state+0x14 = 0x81b59048`, and render reads `0x81b59040`, `0x81b59054`, `0x81b59078`.
Setting `state+0xc` to a PCM buffer makes render **loop forever** unless `state+0x8` is also given a
plausible length; with both set it returns, but still outputs silence.

So the two fields are now identified - `state+0xc` is the sample pointer and `state+0x8` its length - and
the remaining unknown is the sample *header* the engine expects around that pointer. That is a much
smaller question than the sequencer, and it does not depend on the missing `0x04xxxxxx` firmware region,
which makes the two sample engines the most tractable remaining route to audible factory output.

Measured and disproved: putting PCM at the pointer is **not** sufficient. Six byte gates on top of the
pointer and length were tried - `state+0x5b`, `state+0x31`, `state+0x48`, `state+0x5a` - with both 16-bit
and 32-bit sine buffers and the pointer in `state+0xc`, `state+0x14` and `state+0x10`. Every combination
returns cleanly and outputs **zero**. The render also consults its own note-to-sample table at
`0x81b6a454` / `0x81b6a570`, so the sample path has at least one further condition that pointing it at PCM
does not satisfy.

## A family of working instruments, built with our own toolchain

Everything above is about playing the *factory* binaries, which still need state the sequencer computes.
For an app that must ship working, correctly-pitched instruments today, `toolkit/build_family.py` drives
the same verified builder (`build_struck.py`) once per preset, changing only the modal ratios, the
per-mode damping and the strike position - the builder reads `opzstruck.MARIMBA`,
`opzstruck.MARIMBA_T60` and `build_struck.STRIKE_POS` when it runs, so a family is a driver rather than a
rewrite.

Measured with `opzenginetool.py --selfcheck` (cache cleared between runs) and a harmonic-centroid check:

| engine | pitch @ 440 Hz request | harmonic centroid |
|---|---|---|
| bar | 440.1 Hz | 5.68 |
| bell | 440.1 Hz | 1.19 |
| glass | 440.1 Hz | 3.68 |
| organ | 440.1 Hz | 1.29 |
| pluck | 440.1 Hz | 2.61 |

All render audible signal at the requested pitch and are spectrally distinct, so the app can play a
complete instrument set today.

`build_family.py` also emits **one voice per factory instrument slot** (`analoga`, `chord`, `cluster`,
`digital`, `electric`, `ep`, `fm003b`, `ministringshort`, `organ`, `sampleplayergain`, `saw013a`,
`synthsampler`, `volt`), so the app has a working, correctly-pitched engine wherever a factory name is
used. Verified: every one renders at **440.1 Hz** for a 440 Hz request, and the thirteen are spectrally
**distinct** (harmonic centroids 1.27 to 7.08), so they are genuinely different voices rather than the
same engine renamed.

**These are our engines, not the OP-Z factory engines, and must not be presented as the latter.** They
exist because the factory binaries need per-voice state that only the sequencer computes; this route
delivers audible, correctly-pitched instruments without depending on the missing `0x04xxxxxx` region.

Usage: `python3 toolkit/build_family.py engines-family` (the `.engine` files are gitignored; the generator
is the artifact).

### Two call conventions live side by side, and the sweep only knows one

The family is verified through the **app's own path**:

```
opzenginetool.py --selfcheck   ->  peak 0.112, measured pitch 440.1 Hz  (cache cleared per run)
opzplay.py --engine ... --selftest -> realtime and audible, 62-69 us per 64-frame block
```

But `opzenginesweep.py`, the standing factory measurement, reports every family engine as **silent** -
and it is right to, for the convention it uses. The two ABIs differ:

| engine | `render` arguments |
|---|---|
| factory | `stack=(out, freq_q16, 0, ctx, params, amp)` - six words, ctx at `[FP+0x14]` |
| ours (`build_struck.py`) | 7 saved-register words then `ctx`, `params` - i.e. `stack=(ctx, params)` |

`build_struck.py`'s render walks its own saved registers (`for _ in range(7)`) before reading arg4, so the
six-word factory layout puts `out` where it expects `ctx` and it renders zeros. Consequently **the sweep
cannot judge our engines and opzenginetool cannot judge the factory ones** - each tool is correct for its
own convention, and neither verdict should be quoted across the boundary. "Audible in the app" means the
`opzplay` / `opzenginetool` path; the factory sweeps in this document use the factory convention.

### Effects, and a real `UNLINK` bug in the assembler

Effects export `renderFX(ctx, freq_q16, state, in, out)` with `in` and `out` as stack arguments.
`toolkit/build_effects.py` builds one - `dist`, which is gain-then-wrap, a distortion the name actually
describes. Measured: **output = 4.0x input** on 63 of 64 frames, so the effect path works end to end.

Getting there exposed a genuine assembler defect. `opzasm.unlink()` emitted only the first halfword
(`01 e8`) while `UNLINK` is a 32-bit class whose second halfword is the frame word - the factory bytes at
`volt` render `0x81bf06f6` are `01 e8 00 00`. The short form put the following instruction one halfword
early, so an `UNLINK` followed by `RTS` executed the RTS' halfword as data and fell into the module's name
strings. `opzasm.unlink()` now emits four bytes and its self-test expectation was corrected to the factory
form; `struck.engine` and the whole family were rebuilt.

Two more traps recorded from the same session, both of which produced false readings:

- `Z.call(m, entry, args)` puts only `args[:3]` in registers and pushes `stack=` - passing a five-argument
  list and no `stack` silently drops arguments four and five, which made an effect look like it wrote
  nothing.
- Argument reads must happen **before** borrowing registers: `LINK` leaves the first stack argument at
  `FP+8`, but pushing seven registers first shifts `SP`, so the loads after a borrow land on the saved
  registers instead of the arguments.

Two effects are built and measured:

| engine | rule | measured |
|---|---|---|
| `dist` | `out = in << 2`, left to wrap | in `0x005e501a` -> out `0x01794068` (exactly 4x), 63/64 frames |
| `crush` | keep the top 12 bits (`>> 20` then `<< 20`) | in `0x005e501a` -> out `0x00500000`, 63/64 frames |

Both names describe what the code does. The remaining six effect slots (`chorus`, `chorus2`, `delay`,
`fdnreverb`, `reverb`, `tapetwo`) need delay lines and modulated feedback; they are **not** built, because
shipping a gain stage under the name "reverb" would be false.

### A real delay line, and two more assembler gaps it exposed

`delay` is now built and measured. It is a circular buffer of 4096 words in module data, wrapped by
masking the byte offset (`& 0x3fff`, valid because the size is a power of two), reading 1024 words behind
the write pointer:

```
buf[idx] = in; delayed = buf[(idx - 4096) & 0x3fff]; out[i] = in + delayed; idx = (idx + 4) & 0x3fff
```

Verified with an impulse: a single `0x40000000` at frame 0 produces **exactly one** echo, at frame
**1024** (21.3 ms), and nothing else. The write index persists across blocks in module data word 0, so
successive blocks form one continuous delay line.

Building it required two additions to `opzasm.py`, both already implemented and verified in the
interpreter:

- **`comp_eq`** - `CC = Rdst == Rsrc` (`instr16/08-CCFlag.sinc`): `CC = R0 == R3` encodes as `0x0818`,
  matching the factory bytes.
- **`logic32`** - `Rdst = Rsrc0 op Rsrc1` (`instr16/15-Comp3op.sinc`), opcode 2 = AND.

And it exposed a third **pointer-group defect, this time in the assembler**: `ldimm32` could only emit
the data-register form, so every `Preg = imm32` in a built engine silently wrote a data register - the
exact bug the interpreter had two rounds ago. `ldimm32` now emits `0xda08|reg` for pointer destinations
and `0xda00|reg` for data ones. Every module was rebuilt afterwards and all gates pass: 34/34 encodings,
`struck` selftest, `opzplay` realtime and audible, 440.1 Hz, 21/21 containers round-trip clean.

`tapetwo` is the same circular buffer with two taps (`TAP1` 1024 bytes = 256 samples, `TAP2` 3072 bytes =
768 samples). Verified with an impulse: one `0x40000000` at frame 0, echoes at exactly frame **256** and
frame **768**, nothing else. Constant reloads happen per frame into a scratch register, which keeps the
register allocation at eight without spilling.

Effect status: `dist`, `crush`, `delay`, `tapetwo` built and measured. `chorus`, `chorus2`, `reverb` and
`fdnreverb` remain - they need an LFO and a feedback network respectively, both of which build on this
same buffer.

`chorus` modulates the same buffer with a sawtooth LFO held in module data word 1: the tap delay is
`CHORUS_BASE + (phase & 0x3ff) * 4` bytes, so the delay time sweeps between 512 and 1535 samples.
Verified with impulses at frames 0, 100 and 200: they return at frames **512, 644 and 776**, i.e. delays
of 512, 544 and 576 samples. A fixed delay would have returned them 100 frames apart; the swept tap moves
them 132 frames apart, which is what makes it a chorus rather than a delay.

One trap worth recording: the two module-data words (write index, LFO phase) are loaded through the same
pointer, so the first load must post-increment (`aop=0`). Using `aop=2` for both read word 0 twice, which
made the phase equal the write index and produced no echo at all - the effect looked broken when it was
only reading the wrong word.

`reverb` and `fdnreverb` feed the taps back into the buffer, so energy recirculates and each pass decays
by the feedback gain. Measured with an impulse:

| engine | taps | response |
|---|---|---|
| `reverb` | one, 512 samples | echoes at 512/1024/1536/2048/2560 with amplitudes 0.25, 0.062, 0.016, 0.004, 0.001 - exactly 0.25 per pass |
| `fdnreverb` | two, 256 and 768 samples | 15 nonzero frames, denser and audibly longer (0.25, 0.062, 0.266, 0.129 ... down to 0.005 at frame 3584) |

`chorus2` is the same modulated delay with a deeper, slower sweep (depth 0x7ff, step 3). Measured against
`chorus` with impulses at frames 0/100/200: `chorus` returns them at 512, 644, 776 while `chorus2` returns
a different, denser set (718, 768, 1692, 1742, 1792), so the two are distinguishable by measurement rather
than by name.

**All eight effect slots now carry effects that do what their names say**: `dist`, `crush`, `delay`,
`tapetwo`, `chorus`, `chorus2`, `reverb`, `fdnreverb`. Together with the thirteen instrument voices, the
app has a working engine for **every one of the twenty-one factory slots** - built by us, not the OP-Z
binaries, which still need state only the sequencer can supply.

### Measuring "plays the requested note" without being fooled by harmonics

A plain frequency reading cannot answer the question. An engine whose loudest partial is the 2nd or 3rd
harmonic reads 2x or 3x the requested pitch while being perfectly in tune - which is why an earlier
version of this check reported 33 false failures and was deleted rather than trusted.

`toolkit/opzfamilycheck.py` now uses two tests that a harmonic cannot fake:

- **octave tracking** - the reading must double when the note rises an octave, whatever partial it locked
  onto. A detuned engine fails this; a bright one passes it.
- **energy at f0** - a fallback for engines that switch which partial dominates (`fm003b` does, between
  notes 57 and 69), asking whether the requested fundamental is present at all.

Two measurement traps are baked into it: use the **whole clip** for the spectral test (a fast-decaying
note leaves the tail near silent, so the last 8192 samples measure noise, not the engine), and never
compare absolute readings between presets - `analoga`, `bell`, `organ`, `saw013a` and `volt` legitimately
read exactly 2x while `bar`, `ep`, `glass`, `pluck` and `synthsampler` read 1x.

Current verdicts:

| set | result |
|---|---|
| `engines-family` (ours, 17 modules) | **17/17 PASS** - every engine tracks the requested note with exact octave steps |
| `engines-official` (OP-Z binaries, 21 modules) | **21/21 FAIL** - silent, or a null function pointer that wants OS-populated state |

### The host memory no longer needs Ghidra, or a cache, or the network

`opzhost.load()` used to read `~/.cache/opzenginetool/hostmem.json`, generated by driving headless Ghidra
over the OS image. That cache is easy to lose - deleting it silently makes every factory engine read zeros,
which is exactly the failure that looks like an engine bug.

The two regions can be built straight from the image instead: `opz.ldr` is a dlm container whose segments
carry their own load addresses, so `opzhost.regions_from_image()` walks `opzengine.parse()`'s segments and
assembles `0x0800b000..+0x3000` (the shared sine table) and `0x81003850..+0x40` (the host-services table)
directly. `load()` now falls back to that whenever the cache is missing, so the toolchain is self-sufficient
and nothing derived from the firmware is written to disk.

Why this matters beyond convenience: hooking external reads showed **digital touching 68 distinct addresses
and chord 131, all in `0x0800bb44..0x0800cfff`, all reading zero** when the tables were absent. Engines are
not self-contained; they render through that shared table. Restoring it brings digital to peak 0.1123 and
chord to 0.0751.

It is necessary but **not sufficient**: with the tables present neither engine tracks the octave
(chord's steps are 0.38/4.57, digital's readings 19.6/784.5/1275.2 across notes 45/57/69), and the 21-engine
sweep is unchanged at 2 detuned / 3 flat / 3 loops / 5 needs-state / 8 silent.

### The factory patches were in the app, not the firmware

The OS image's `settings/plugs.json` holds engine ids and paths with **no parameter values**, which made
it look as though the factory patches were unavailable. They are in the OP-Z app package:
`assets/factory-plug-cache/<id>/metadata.json` carries, per factory plug, the engine it drives, its
parameter names and every factory preset with its values:

```
digital.engine  params=['offset', 'space']  3 presets
  dust        [0, 255, 14, 84, 30, 17, 2, 0, 156, 163, 127, 123, 0, 210, 125, 203, 255, 0]
chord.engine    params=['phase', 'shape']   8 presets
```

`toolkit/opzplugs.py` reads them straight out of the APK (16 engines, 58 presets), and the preset names match
`plugPresets.dat` in the OS image, which is the same data in packed form.

Two limits found while checking whether this closes the gap:

- **Engines do read `params`** - hooking the params region during a render counts 8 accesses for `digital`,
  `chord` and `electric` and none for `organ`.
- **It does not change their output.** Feeding every `digital` preset, as plain bytes and as bytes shifted
  into the top of each word, gives byte-identical output (peak 0.1240 in all six cases), so the parameter
  values are consumed but do not carry the voice coefficient that is keeping these engines silent.

So the factory patch data was genuinely missing and is now available; it is simply not the missing piece.

### chord's oscillator works; its tuning does not

Two corrections worth keeping, both found by tracing stores into the output buffer rather than trusting an
address from an older note:

- The real output stores are at `0x81be28ba` and `0x81be28ce`, and the multiply feeding them
  (`0x81be2858`) **does** run every sample: `R1` carries real sine samples (`0xff294b95`, `0x0207e398`)
  and `R2` a gain (`0xe0000000`). chord's oscillator path terminates correctly, so "the multiply is never
  reached" was wrong. The mistake was arithmetic: `Machine.mem_base` is `0x81ba2000`, not the module base
  `0x81be2400`, so offsetting from the module base produced addresses in the stack region.
- chord still does not play the requested note. Rendering 48 blocks at notes 45/57/69 and taking spectral
  peaks from 30 to 3000 Hz gives 329.4 Hz (2.99x), 164.7 Hz (0.75x) and 1317.5 Hz (2.99x) for requests of
  110/220/440 Hz. The ratios are inconsistent, so this is not a note at the requested pitch. Autocorrelation
  cannot judge chord at all - it is a multi-oscillator engine, so its waveform is deliberately non-periodic
  and only a spectrum is meaningful.

### A control probe settles whether the engines track pitch

Measuring energy at the requested fundamental is not enough on its own: if the output is broadband, some of
it always lands on f0 and looks like tracking. The control is to request frequencies that are not octaves of
each other and see whether the peak moves with the request.

| request | chord peaks at | digital peaks at |
|---|---|---|
| 220 Hz | 220 Hz | 220 Hz |
| 300 Hz | **220 Hz** | **440 Hz** |
| 600 Hz | **300 Hz** | **220 Hz** |

Neither engine's peak follows the request, so the factory engines are not playing the requested note. The
readable part of chord's render explains why the earlier "1.5x and 3x" readings looked musical: its phase
increment is computed from the pitch argument through a divider against a band base, with `params[5]` as an
offset, so pitch does reach an increment - but the resulting oscillator does not land on the requested
frequency in this harness.

### The engines read real sine data, and still emit a ramp

Two harness-level faults were fixed before ruling this out, so the conclusion is not an artefact:

- **The note was hardcoded to 69.** The render helper called `onNoteOn(0, 69, ctx)` while varying only the
  pitch argument, and chord selects its octave band from the note, using the argument only for the in-band
  offset. Passing the real note changes nothing measurable: digital still peaks at 753.1/745.7/753.1/753.1 Hz
  for requests of 110/220/440/880 Hz, i.e. a fixed 48 kHz / 64 = 750 Hz block rate.
- **The sine table is present and read.** With host memory loaded, 107 of 328 external reads return real
  sine data (`0x0096ca93`, `0x012d9456`, ... from `0x0800bb5c`). The number of table reads varies with pitch
  (98 at 110 Hz, 50 at 220, 26 at 440 and 880), so pitch does reach the engine's control flow.

What the engine writes is nevertheless a monotone ramp: 49 to 61 distinct sample values per block, each
larger than the last, which is an envelope with a zero oscillator term rather than a waveform.

chord's band table was also located while checking the octave logic - `0x81be2de0` holds a twelve-entry
octave ladder in Q16 Hz (12.1, 24.3, 48.6, 97.2, ... 24,882.9), doubling each entry, and the render indexes
it by comparing the pitch argument against those edges.

### The oscillator does track pitch; its output does not reach the buffer

Reading the table-read addresses inside digital's render settles a question that black-box measurement could
not. The stride between successive sine-table reads **is the requested frequency in bytes per sample**:

| request | read offsets (first samples) | per-sample stride |
|---|---|---|
| 110 Hz | 0, 0, 108, 108, 220, 220, 328, 328, 440, 440 | 108 / 112 alternating |
| 440 Hz | 0, 0, 440, 440, 880, 880, 1320, 1320 | 440 |

So the oscillator's phase index advances proportionally to the pitch argument - the engines are not ignoring
pitch after all, and the two read sites (`0x81be641e`, `0x81be6434`, two interpolating taps) fire once per
sample. Whatever is wrong, it is not the pitch input.

What is wrong is downstream. Energy at the frequency that stride implies (f x 48000 / 0x8000) is only 0.02 to
0.33 of the peak, because every render is dominated by a 753 Hz staircase (64-sample blocks, 48 kHz / 64).
In the steady-state tail - the last 1280 samples of a 200-block render - digital peaks at 53.5 Hz whatever the
pitch, so the oscillator's contribution never surfaces at audible level.

### Where the stored sample comes from, and why it is a ramp

Watching both of digital's output stores (`0x81be64a2` left, `0x81be64b6` right) with the registers and the
two most recent sine-table taps gives a precise picture:

- the stored sample **is R4** on the left and **R6** on the right - nothing else is combined at the store;
- **no sine-table read happens in that block at all.** The table reads observed earlier (the ones whose count
  varies with pitch) all come from the early blocks;
- R7 carries a large accumulator-like value (`0xe328dbba`, `0xc499b774`) that is never turned into a sample.

So the oscillator phase is being advanced (its stride tracks pitch exactly) and then simply not converted: the
sine lookup stops firing, and the buffer receives a ramp through R4/R6. That is the precise defect - not the
pitch input, which demonstrably works.

### Correction: the sine lookup never stops

An earlier note in this document said the lookup fires only in the early blocks. That was wrong, and the cause
was my own instrumentation: I counted reads inside a window ending at `0x0800d400`, and the table pointer
walks past it. With the window widened to `0x0800a000`-`0x08020000`, every block performs **130 reads** -
about two per output sample, matching the two interpolating taps - and the pointer advances **440 bytes per
read** at a 440 Hz request, marching from `0x0800bb44` to `0x08013xxx` over ten blocks.

So the oscillator runs continuously and its stride is the requested frequency. What defeats measurement is the
output itself: each block is a ramp whose intra-block slope steps repeat at the 64-sample block rate, and that
751 Hz component dominates the spectrum (1.4e-2) whether or not per-block DC is removed.

### The pitch unit is off by 48000/32768, and that is measurable

The shared L2 table at `0x0800bb48` is not a full waveform: all 8191 words are positive and monotone from
1,647,049 to 2,145,962,988 (0.999 of full scale) with **zero sign changes** - a quarter-sine. The engine walks
it at a byte stride equal to the pitch argument, so the output frequency is

    f_out = f_in * 48000 / 32768 = f_in * 1.4648

which predicts that passing `q` produces a tone at `1.4648 q`. Measured, with energy probes at fixed
frequencies:

| pitch passed | predicted tone | energy @440 | @644.5 | @880 |
|---|---|---|---|---|
| 300 Hz | 440 Hz | **2.21e-3** | 3.73e-4 | 3.82e-5 |
| 440 Hz | 644 Hz | 3.39e-4 | **1.26e-3** | 1.00e-4 |
| 600 Hz | 880 Hz | **3.35e-4** | 2.99e-4 | 9.59e-5 |

Two of three probes land exactly where the model says. The third (600 to 880) does not, so the scaling is
confirmed for some bands but not all - and the tone still sits well below a 751 Hz block-rate component
(1.4e-2), which is why a plain spectral peak never revealed it.

### One factory engine now plays correct notes

Applying the measured factor 32768/48000 to the pitch argument makes **digital** play the requested note.
Energy probes at the target frequency against its 0.75x and 1.5x neighbours:

| request | energy at f0 | neighbour max | verdict |
|---|---|---|---|
| 110 Hz | 1.13e-2 | 2.94e-3 | **plays** |
| 220 Hz | 6.18e-3 | 2.72e-3 | **plays** |
| 330 Hz | 4.44e-3 | 1.68e-3 | **plays** |
| 440 Hz | 4.99e-3 | 9.90e-4 | **plays** |
| 550 Hz | 4.51e-3 | 1.53e-3 | **plays** |
| 660 Hz | 3.43e-3 | 9.51e-4 | **plays** |
| 880 Hz | 2.57e-3 | 8.65e-4 | **plays** |

Seven of eight probed pitches land on their own frequency. `opzenginetool.render_clip` now takes a factory
path that loads the host memory, fills the amp object, pushes all six arguments and scales the pitch; with it
digital renders a 440 Hz note through the app path (1.0e+5 against a 9.0e+4 neighbour, marginal) while our own
engines are unaffected (`opzfamilycheck` 17/17, `opzplay` realtime and audible, 440.1 Hz).

The other twenty engines do not benefit: `chord`'s energy is flat across the sweep, eight are silent, and five
raise errors. **1 of 21 factory engines now plays a correct note** - for the first time in this work the number
is not zero.

### Three factory engines play correct notes (verified through the app path)

With the scaled pitch argument and the app's own render path, three factory instrument modules play the
requested note at both 220 and 440 Hz. `toolkit/opzfactorycheck.py` is the reproducible check:

| engine | 220 Hz | 440 Hz |
|---|---|---|
| chord | 2.6e5 vs 1.1e5 | 8.8e4 vs 5.2e4 |
| digital | 5.0e5 vs 3.2e5 | 4.7e5 vs 1.8e5 |
| ep | 3.6e6 vs 1.7e6 | 1.6e6 vs 9.1e5 |

(each figure is energy at the requested frequency versus the stronger of its 0.75x and 1.5x neighbours)

**3 of 13 instrument modules.** The remaining ten: `volt` is DC, six are silent, four raise errors.

Two measurement traps had to be fixed to see this, and both had produced false failures:

- **interleaving** - `render_clip` returns interleaved L,R, so a DFT at f over that array reads it as f/2.
  Each channel must be measured separately. This is why an earlier audit reported digital failing at 440 Hz
  while the direct harness had it passing.
- **single-channel engines** - `ep` writes the right channel and nothing on the left, so any left-only reader
  (including this project's earlier sweeps) reports it as silent.

### The silent engines fail an early gate, and the gate is not the whole story

`organ` exits after 19 steps and `cluster` after 21, and in both cases the only state read before the exit is
**`state+0x10 == 0`** - so that read is what stops them. But it is necessary, not sufficient: seeding
`state+0x10` with 1, 2, 3, 4, 5, 6, 0xff or 0x100 changes nothing measurable. `organ` stays at peak 0.0000 and
`cluster` emits a constant 2e-4 with no response to the seed, so a second condition downstream is also unmet.

`electric` is different: it runs 15,430 steps, reads `amp+0x10`, `state+0x2c`, `params[0]`, `params[5]` and
`params[+0x14]`, and still writes zeros.

### organ's early exit, read from its decompiled render

`FUN_81b7d1a0` (organ's render) opens with two gates that explain the 19-step exit:

```
if (*(int *)(param_4 + 0x10) == 0) return;              // param_4 is the state block
if (*(char *)(param_4 + 0x89) != 0) { --*(char*)(param_4 + 0x89); return; }
```

and later, guarded by `state+0x8c == 0`, it writes the pitch argument into four consecutive words:

```
*(uint *)(param_4 + 0x10) = param_2;
*(uint *)(param_4 + 0x14) = param_2;   // and +0x18, +0x1c
```

So `state+0x10` is meant to hold the pitch argument and the engine only self-initialises it *after* the gate
that reads it - which is why an unseeded harness gets a one-line return. Seeding it with the pitch argument
does get past the gate, but is not enough: organ stays at peak 0.0000 and emits only 1e-12, cluster stays at a
constant 2e-4, and electric becomes audible (peak 0.0315 with 0x40000000) without tracking pitch at 220 or
440 Hz. A further condition downstream of the gate is still unmet in all three.

### The erroring engines really do want the OS to service them

Mapping the OS image alongside the engine (the arrangement `opzos.build` uses) changes the failure of the four
erroring modules. `analoga`, `saw013a` and `ministringshort` no longer report *"keeps calling outside its
window"* - their out-of-window calls now land in real firmware code - and instead raise **"call did not
return"**. `fm003b` never returns at all (it had not finished after 1,400 s).

So these engines are not misreading a boundary; they issue a call that expects the OS to answer it, and no
amount of seeding the module's own state supplies that answer. That is the same wall as the sequencer-state
problem, now reached by a different route, and it also makes the OS-mapped route impractical for auditioning
(one engine does not return at all).

`electric` is separately ruled out: it responds to `state+0x10` only weakly (energy at 440 Hz moves between
2.6e-4 and 4.3e-4) and never beats its 330/660 Hz neighbours, while its pitch argument has no effect whatever.

### The remaining silent engines need the OS, not more seeding

Seeding the amp object's byte fields (`amp+0x14`, which `FUN_8012e0a4` writes at note start) with 0x01, 0x02 and
0xff changes nothing on `organ`, `cluster`, `sampleplayergain` or `synthsampler`: organ and the two sample
engines stay at peak 0.0000 and cluster at a constant 2e-4.

One detail explains the rest: `organ` with its `params` set to 0x7fffffff does make progress - and immediately
raises *"keeps calling outside its window"*. So these engines are not blocked by a missing seed; they are
blocked because their rendering path issues a call the OS must answer. That is the same conclusion the four
erroring engines reached from the other direction.

### Why an out-of-window call cannot simply be stubbed

`opzsim.call` already emulates an out-of-window call as a callee that returns 0 through RETS - it was never a
hard failure. It only raised after 64 *consecutive* such calls. What that reveals is that these engines **spin**
on a host call: each return is zero, so the caller's loop never converges.

Stubbing the whole host-services table (all 13 dwords pointed at a bare `RTS` inside the window) changes nothing
for `organ`, `analoga`, `saw013a` or `ministringshort` - they still raise, which also shows the offending calls
do not go through those table entries. Raising the consecutive-call ceiling to 200,000 (now the `HOST_CALL_LIMIT`
constant in `opzsim.py`) does not let any of them finish either.

So the requirement is not "answer the call" but "answer it with the value the engine is waiting for" - a real
OS service, not a stub.

### A real decoder gap found by following the OS call: ProgCtrl STI

Logging the out-of-window calls showed `organ` repeatedly calling the OS routine at **`0x800314c0`** (host
table slot 7). Running that routine with the OS image mapped failed on `ProgCtrl opc=0xe`. The ProgCtrl table is
`0xC` IDLE, **`0xD` CLI**, **`0xE` STI**; `opzsim` handled only `0xC`, so real OS code enabling interrupts
stopped the run. With `0xD`/`0xE` handled as no-ops the routine executes and **returns in 38 steps with R0 = 0**.

That fix does not unlock the engines, and the reason is instructive: `organ` then proceeds to `0x80000003` and
executes garbage (`0x7980`) - a call through OS data that is zero in an unbooted image. `analoga`, `saw013a` and
`ministringshort` still raise "call did not return".

So the engines are waiting on OS *state*, not merely OS code: the routines exist and can be executed, but the
data they consult is uninitialised without a real boot.

### The host call's return value is not what the looping engines wait on

`opzsim` now exposes `Machine.host_return` (default 0, so behaviour is unchanged) to control what an
out-of-window call hands back, in case an engine uses it as a buffer pointer and calls through it. Running
`organ`, `analoga`, `saw013a` and `ministringshort` with 0, `0x81b00000` and `0x81500000` gives twelve identical
outcomes: every one still raises "keeps calling outside its window".

So the loops are not waiting on a return value that a harness can supply. Combined with the previous section -
the OS routines themselves now execute after the ProgCtrl STI fix - the conclusion is that these engines wait on
**OS state created by a real boot**, and no single knob substitutes for it.

### What organ's "loop" actually is: an out-of-range table index

The out-of-window reads are not a host wait. Disassembling the loop explains them:

```
81b7d5bc  LSETUP(0x81b7d5c0, 0x81b7d5c0) LC0 = P1
81b7d5c2  R1 = 0x64                              // divisor 100
81b7d5c6  CALL 0x81b7ed08                        // organ's own routine, returns an index in R0
81b7d5ce  P2 = 0x81b7f698                        // organ's table
81b7d5da  P1 = P2 + (P1 << 2)                    // index * 4
81b7d5dc  R0 = [P1]                              // <-- the "outside window" read
```

So the "keeps calling outside its window" failure is a **negative table index**: the routine at `0x81b7ed08`
returns a value that runs off the front of organ's own table, and the read lands outside the module. It is a
data-dependent fault inside organ's arithmetic, not a missing host service - which also explains why no
`host_return` value or table stub changed anything.

### Factory engines can only be auditioned on the interpreter path

Bringing the JIT player up to factory engines needed two things, both now in place: `opzjit` passes **six**
stack arguments (factory engines read context, params and amp from the stack) and treats `sop=3` as the
logical shift the interpreter already implements. Our own engines still play at 29 us per block.

That is not enough for the factory modules. They then stop on instruction classes the JIT does not emit:
**Dsp32Shf** (shift by a register, `sigd=0xC`) and a form that decodes as **Dsp32Mac** (`sig2=0`), which the
interpreter does not implement either. `opzplay` therefore raises `Unsupported` for every factory engine - an
honest failure, rather than the wrong pitch it would otherwise produce.

Consequence: the three working factory engines (`chord`, `digital`, `ep`) are playable through
`opzenginetool` (the interpreter path), not through the realtime JIT player. Closing that needs register-shift
emission in `opzjit` plus a Mac implementation in both engines.

### The realtime player is further behind than the interpreter

After adding the NOP32 test and register-shift (`Dsp32Shf`) to `opzjit`, the factory modules advance one more
instruction and stop on **`0xe0a2`** - `LSETUP` in its register-count form. `opzjit` implements no `LSETUP` at
all, and never needed to: our own engines are loop-free, so nothing exercised it.

That makes live factory playback a substantially larger job than a gap or two (loop frames with LC/LT/LB,
begin/end addresses and the back-edge), and it would not change the engine count either - the ten non-playing
engines are blocked on state, not on the JIT. So the three working factory engines stay on the interpreter path
(`opzenginetool`), where they are verified at 220 and 440 Hz, and the JIT keeps its NOP32 and shift fixes, which
are correct regardless (our engines still measure 440.1 Hz and play in realtime).
