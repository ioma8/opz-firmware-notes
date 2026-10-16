# 01 — The `.ldr` container format and image layout

The decrypted Blackfin images ship as ADI **boot-load streams** (`.ldr`). The format was reverse
engineered from the two files themselves; the layout below is verified to walk each file end-to-end
with **zero bytes left over**, which is the strongest available check that the parse is correct.

## Block header (16 bytes)

Both files use the same header. All fields little-endian.

| offset | size | field | meaning |
|---|---|---|---|
| `+0x00` | u16 | `tag` | `0x5004` for a top-level stream block; `0x0004` for a nested block |
| `+0x02` | u16 | `type` | payload/load type discriminator |
| `+0x04` | u32 | `dest` | destination address (see the caveat below) |
| `+0x08` | u32 | — | always `0` in both files |
| `+0x0c` | u32 | `count` | payload length in bytes; payload begins at `+0x10` |

Advancing by `16 + count` walks the stream exactly:

```
opz.ldr        1 block,  count=0xca2d8 -> 0x10 + 0xca2d8 = 0xca2e8 = file size  ✓
bootloader.ldr 2 blocks, 0x10 + 0x109c  = 0x10ac (next header)
                        0x10ac + 0x10 + 0x3ddb0 = 0x3ee6c = file size        ✓
```

**Two tags, and the reason it matters.** The top-level tag is `0x5004`; a *nested* block inside a
top-level payload uses `0x0004`. The tag low/high halves are `04 50` and `04 00` on the wire, which is
why a naive `u32` read of the first four bytes gives `0xad3e5004` and hides the structure. Reading the
first field as a `u32` (instead of `u16` tag + `u16` type) is the main way to mis-parse these files.

## The `dest` field is not the load address for the payload

`dest` reads `0x11a00000` in **every** top-level block of both files, including the bootloader's second
block which is clearly a different body of data. So `dest` describes the *stream*, not where the bytes
end up.

The real addresses are found from the **content**. Anchoring on strings whose addresses were
independently established from the device:

| string | file offset | virtual address | implied base |
|---|---|---|---|
| `Too long source filename` | `0x03ca38` | `0x8283708C` | `0x827fb710` |
| `Too long target filename` | `0x03ca54` | `0x828370A8` | `0x827fb710` |
| `The command is not recognized` | later re-located | `0x82837DDC` | consistent |

Two independent anchors agree on base `0x827fb710`, and with that base the whole rodata region resolves
into a coherent `0x827fb710`–`0x828394c0` block containing yaffs2, zlib, the bootloader sources and the
serial command strings. The mapping is:

```
file offset  = 0x10bc + (virtual - 0x827fb710)     # bootloader second block
```

Because Ghidra's Blackfin+ loader reads the block structure itself, **none of this relocation has to be
done by hand** — importing the `.ldr` directly produces the correct addresses, which is how the
addresses above were confirmed.

## Resulting memory maps

### `opz.ldr` (the OS, 828,136 B → 1,993 functions)

Ghidra maps the image into the chip's real Blackfin+ memory banks:

| region | address range | contents |
|---|---|---|
| L2 SRAM | `0x08002000`–`0x0803ffff` | OS code + the image's own vector/lookup tables |
| L1 data A | `0x11802000`–`0x11803fff` | initialised data |
| L1 data B | `0x11900000`–`0x11904xxx` | the **vtable / callback tables** (see the 0x34-byte pattern below) |
| L1 instruction | `0x11a00000`–`0x11a0bfff` | hot code |
| DDR2 / LPDDR | `0x80000000`+ | main heap and larger buffers |

**A caution on reading Ghidra's block map:** the L1 data B region is reported by Ghidra as a long run of
small blocks alternating `0x34` then `0x04` bytes. That is the **loader's segment granularity, not a data
structure** — inspecting the bytes shows mostly zeros with sparse 4-byte values (e.g. `0x224` at
`0x119046c4`, `0x125` at `0x119046fc`). Do not mistake Ghidra block boundaries for records. What the
sparse values mean is unexplored.

### `bootloader.ldr` (257,644 B)

| region | address range | contents |
|---|---|---|
| L1 instruction | `0x11a00000`–`0x11a04f5b` | bootloader code (`block7`, `block8`) |
| L1 data A | `0x11800000`–`0x11803fff` | bootloader data / init tables |
| rodata | `0x827fb710`–`0x828394c0` | strings, source paths, log formats |

## An important correction to earlier notes

An earlier session recorded bootloader strings at `0x82835c20`, `0x8283822c`, `0x82838799` and
`0x82836c68`. Importing the `.ldr` with the proper Blackfin+ loader places the same strings
consistently; the `0x82836c68` value for `..\src\serial_command_handler.cpp` reproduced exactly, while
the others drift by up to `0x420` bytes. The difference is that those earlier addresses came from a
manual byte-search in a file whose offsets were being treated as addresses. **Treat the Ghidra-loaded
addresses as authoritative** and re-derive any address from the older notes before relying on it.

## Source tree and build environment (from rodata)

The firmware retains its original source paths. Extracting them from `opz.ldr` yields **75 unique source
files**, which is effectively a map of the whole OS — this is the single most useful artefact in the image
for further work.

**`snake-software` is the project root** — "snake" is the OP-Z's internal codename. The keyboard PSoC
firmware is literally named `SnakeKeyboardModule_*.cyacd`.

### Blackfin platform layer (`src/bf/`)

```
main.cpp              Codec.cpp             callstack.cpp
ModuleControl.cpp     UsbControl.cpp        smx_usb.cpp
command_handler_module.cpp                  dlm.cpp
Nand.cpp              fs.cpp                mass_storage.cpp
bf_crc.cpp            gpio.cpp              i2c.cpp
metadata.cpp          otp.cpp               rtc.cpp
spi_flash.cpp
```

### Sequencer / application (`src/sequencer/`)

```
SnakeSystem.cpp       Sequencer.cpp         SequencerMidi.cpp
Pattern.cpp           Arpeggio.cpp          NoteUtils.cpp
ParameterSweep.cpp    Synth.cpp             PlugManager.cpp
SampleLoader.cpp      Midi.cpp              UsbMidi.cpp
StateSync.cpp         Serialize.cpp         ContentManager.cpp
DmxController.cpp     DataCompressor.cpp
```

### Contexts (the UI/input state machine) — `src/sequencer/contexts/`

```
DefaultContext.cpp    PatternContext.cpp    RenderSongContext.cpp
SamplerContext.cpp    ScoreContext.cpp      TempoContext.cpp
TrackContext.cpp
```

### File service and synth internals

```
src/sequencer/filemanager/FileClient.cpp
src/sequencer/filemanager/FileManager.cpp
src/sequencer/filemanager/FileServer.cpp
src/sequencer/filemanager/FileSync.cpp
src/sequencer/synth/FxManager.cpp
src/sequencer/synth/InstrumentManager.cpp
src/sequencer/synth/Voice.cpp
src/shared/KeyHandler.cpp
src/shared/SerialMessageHandler.cpp
src/shared/command_handler.cpp
src/shared/command_handler_ble.cpp
src/shared/command_handler_kb.cpp
src/sequencer/task.cpp
```

### Third-party (`ext/`)

```
ext/yaffs2/        yaffs_guts.c, yaffs_nand.c, yaffs_checkptrw.c, yaffs_allocator.c,
                  yaffs_bitmap.c, yaffs_verify.c, yaffs_tagscompat.c,
                  yaffs_tagsmarshall.c, yaffs_packedtags2.c, yaffs_endian.c,
                  yaffs_yaffs1.c, yaffs_yaffs2.c, direct/yaffsfs.c, yaffs_getblockinfo.h
ext/libaiff-5.0/  libaiff.c, aifx.c
ext/smx_usb/       XBASE/bos.c, XUSBH/USBD/udriver.c
```

Read that carefully and several things fall out:

1. **`command_handler*.cpp` is split three ways** — `command_handler.cpp`, `command_handler_ble.cpp`,
   `command_handler_kb.cpp`, plus `command_handler_module.cpp` in the platform layer. So the serial,
   BLE, keyboard and module channels each have their own handler implementation. This is the map for
   the serial-command work in `03-serial-commands.md`.
2. **`dlm.cpp` is the dynamic module loader** that opens `*.engine` files — confirming the earlier
   finding that `dlm: Unsupported fill value` comes from the loader in this file.
3. **The OS and the bootloader share one source tree.** The bootloader's `..\src\disk/disk_io.h` and
   `..\src\shared/Queue.h` resolve into the same `src/` the OS names, with
   `C:\snake-software\snake-synth-bf\..\src\...` for the OS link and
   `\snake-software\bootloader\..\src\...` for the bootloader link. A separate link of shared
   components, **not** a separate codebase.
4. **`ext/smx_usb/` is a third-party USB stack** (SMX is a commercial RTOS/USB vendor), so the USB
   device and host stacks are licensed rather than written in-house.
5. Built on **Windows with a `C:\`-rooted tree**, i.e. the ADI VisualDSP++ / CCES toolchain, not a
   Linux cross-compiler.
