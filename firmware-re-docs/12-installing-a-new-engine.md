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

**Practical note on runs:** the toolkit now installs a two-minute watchdog (`toolkit/opztime.py`) on every
tool, because an unmodelled engine loop otherwise hangs a run silently. Override with
`OPZ_TIME_LIMIT=<seconds>`.
