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
