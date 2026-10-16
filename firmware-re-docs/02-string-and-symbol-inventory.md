# 02 — String, symbol and structure inventory

A survey of the decrypted images' rodata. Both `opz.ldr` (OS) and `bootloader.ldr` were scanned for
printable NUL-terminated runs: **1,269 strings in the OS**, **628 in the bootloader**. This document
records what the inventory reveals about the system's architecture, on-disk layout and internals.

## 2.1 OS boot-sequence stages

The OS logs its startup in named phases, which read as a map of the boot:

```
[communication handlers]
[usb initialization]
[file system init]
[file system mount]
Entering main loop. build date: %s, %s
Event: Jack inserted
```

`Entering main loop. build date: %s, %s` is notable: the OS prints its own build date at the point the
main loop starts, which is why the device's log can be dated without the upgrade log.

## 2.2 On-disk layout visible to the OS

```
/yaffs2                          mount root
/yaffs2/opz.dev                  <-- see 2.3
/yaffs2/contentmode.plz          content-mode marker (also written by restart-into-content)
/yaffs2/time.txt                 RTC persistence
/yaffs2/logs/                    log directory with four channels:
/yaffs2/logs/system    /yaffs2/logs/upgrade
/yaffs2/logs/import    /yaffs2/logs/battery
/yaffs2/tmp/                     working directory
/yaffs2/user/tmp/
/yaffs2/user/projects/           project storage
/yaffs2/system/content/          factory content tree
/yaffs2/server/                  <- see 2.4
/yaffs2/system/firmware.version
```

## 2.3 `/yaffs2/opz.dev`

This path appears **immediately adjacent to `/yaffs2/contentmode.plz`** in the string pool, in the
middle of the boot-stage block. `contentmode.plz` is the marker that selects content mode (confirmed: the
hidden `restart-into-content` command creates it, `04-hidden-features-and-easter-eggs.md` §4.1).

So `/yaffs2/opz.dev` sits in exactly the position a **second mode-selector marker** would occupy. The
inference is that `.dev` selects a developer/engineering mode analogous to content mode, but this is
**not confirmed** — I could not find code referencing the string (neither via the reference manager nor
as a signed-immediate scalar), which suggests the path is assembled at runtime by concatenation. The
name, its position next to the other marker, and the existence of `enable-debug` in the MIDI command
table all point the same way. Treat as a strong lead, not a finding.

## 2.4 `/yaffs2/server/`

Appears in the `FileManager.cpp` region alongside the content and project paths:

```
/yaffs2/system/content/
/yaffs2/user/tmp/
/yaffs2/server/
/yaffs2/user/projects/
samplepacks/UserSampler.aif
samplepacks/CuckooC_keypawn.aif
files
```

A `/yaffs2/server/` directory managed by the file manager is consistent with the device acting as a file
**server** over USB MIDI (`FileServer.cpp` / `FileClient.cpp` / `FileSync.cpp` are all real source files,
see `01-ldr-format-and-image-layout.md`). Most likely this is where hosted/served files are staged.

## 2.5 Plug and engine architecture vocabulary

The OS's `PlugManager.cpp` string pool exposes the plug/settings schema directly. The **complete,
verbatim** key and path list, in address order:

```
engine       samples      Unknown      presets      plugId
id           version      flags
index        values       defaultOctave
tracks       packs        engines      plugs        memoryslot
/yaffs2/user/             auto_import

settings/slotConfiguration.dat     settings/slotConfiguration.json
settings/plugs.dat                 settings/plugs.json
settings/plugs_patch.json          settings/plugPresets.dat
settings/plugPresets.json          config/userPresets.dat

rendertone.preset                  %sengines/fmedit.preset
```

Things this settles:

- **`trackmask` does not appear anywhere in either image.** The `trackmask` field seen on device-side
  plug records is therefore a *key the app writes*, not one this firmware's string table names — so its
  name comes from the app's own serializer. Any documentation that presents `trackmask` as a firmware
  key should say so.
- Both a `.json` **and** a `.dat` form exist for **each** of the four settings files
  (`slotConfiguration`, `plugs`, `plugPresets`, and the `config/userPresets.dat` variant). The `.dat`
  form is the binary form the app pulls as `plugPresets.dat`; the `.json` form is what the app syncs.
  This dual representation is worth remembering — earlier recovery work hit precisely this ambiguity.
- **`settings/plugs_patch.json` is a real firmware path**, and `auto_import` sits in the same block. So
  the patch/auto-import mechanism observed in `system/content/settings/plugs_patch.json` is implemented
  in `PlugManager.cpp` and is a *designed* feature rather than something bolted on.
- **`rendertone.preset`** and **`engines/fmedit.preset`** are new: preset files for tone rendering and an
  FM-editor preset living under `engines/`. The latter implies the FM engine has an editable patch
  format the firmware knows how to load.

## 2.6 Sample-import validation vocabulary

From `ContentManager.cpp` (see also `04-hidden-features-and-easter-eggs.md` §4.4):

```
wav|aif|aiff|engine             the accepted extension filter
/one_sample_pack_per_slot.plz   the one-pack-per-slot enforcement marker
userPresets.dat
  importing %s...
unsupported file type
invalid meta data
invalid drum sample pack
invalid synth sample
unsupported sample rate
op1 synth patches are not supported
```

The distinction between **`invalid drum sample pack`** and **`invalid synth sample`** confirms the
importer has two separate validation paths, matching the device's drum-vs-synth track split.

## 2.7 DMX subsystem

```
DmxController.cpp     config/dmx.json
profiles              profile       fixture      channels      config
d2ddd2ddd2dd
```

`d2ddd2ddd2dd` is a repeating hex pattern — likely a fixture definition or a test constant.

The subsystem is now decompiled: **DMX is track 14**, played as **nine scale-spaced notes** that each select a
lighting slot, with a fixture/profile engine loaded from `config/dmx.json` and a controller singleton at
`0x81015e9c`. See doc `05` §5.8. The same tree also ships the vendor's own `readme/how_to_dmx.txt` (6,671 B),
which documents the channel types, the `profiles`/`config` blocks and the **up to 16 fixtures** — that file is
the authoritative source for the config model, and doc `05` §5.8 reproduces its table.

## 2.8 MIDI subsystem

```
Midi.cpp    SequencerMidi.cpp    UsbMidi.cpp
MidiEntity list full!
xcx0312p1.0.8
config/midi.json
incoming_midi  outgoing_midi  midi_echo  track_channels  track_enable
channel_one_to_active  timing_clock_in  timing_clock_out
alt_program_change  enable_program_change  parameter_cc_out
```

`MidiEntity list full!` shows a **fixed-size entity list** for MIDI connections — a hard cap on
simultaneous MIDI endpoints worth knowing when attaching gear.

The diagnostics the MIDI *input* path can emit, added after the pipeline in doc `05` §5.2b/§5.2c was read —
these name the two layers and are the strings to grep for in a device log when MIDI misbehaves:

| string | layer | meaning |
|---|---|---|
| `USB MIDI message size not multiple of 4: %d!` | `UsbMidi.cpp` packet pump | a USB-MIDI packet run is not a multiple of the 4-byte packet size |
| `USB MIDI SysEx message too large!` | `UsbMidi.cpp` | the SysEx reassembly would exceed the 4 KB staging buffer |
| `sysex without first packet` | `UsbMidi.cpp` | a SysEx continuation packet arrived with no start packet |
| `unhandled usb midi packet %02x` | `UsbMidi.cpp` | CIN value outside the handled set |
| `Sysex message interupted. Read %d` | `Midi.cpp` stream parser | a status byte arrived inside a SysEx (`%d` = bytes staged so far) |
| `Midi message too big. Ignoring.` | `Midi.cpp` | the 4 KB staging buffer filled |
| `unhandled common message 0x%02x` | `Midi.cpp` | status byte outside the length table |
| `unhandled real_time message 0x%02x` | `Midi.cpp` | real-time byte outside `0xF8/0xFA/0xFB/0xFC/0xFE` |

Note the asymmetry that matters when probing: an unrecognised **status byte** is logged, while an
unrecognised **SysEx opcode** is silent (doc `05` §5.3).

## 2.8b What the shipped import readme states

The image carries a second vendor document next to `how_to_dmx.txt`: **`system/content/readme/how_to_import.txt`**
(8,447 B). It is the authoritative statement of the content-import rules, and several of its claims are
confirmed by the firmware's own strings:

| readme statement | firmware evidence |
|---|---|
| rejected content "will end up in a folder named **`rejected`** on this disk the next time content mode is entered" | strings `rejected` (`0x81005120`) and `rejected/` (`0x81005210`) |
| OP-Z "can hold up to **5 bounces**" | `bounces` (`0x810050f4`, `0x81113660`), `bounce.wav`, `%sbounces/bounce0%d/` |
| "ten OP-Z projects … files are named **`project01.opz` to `project10.opz`**, anything else will be rejected"; removing one "will be replaced by a default empty project" | `project%02d%s.opz` (`0x8110e42c`), `projects/project%02d.opz` (`0x81127b6c`), `%02d.opz`, `project.opz` |
| "only **one sample pack per slot** folder will be imported, any additional ones will be rejected" | the `/one_sample_pack_per_slot.plz` gate in §2.6 |
| duplicates "will be prefixed with **`~` and have 0 size**" | this explains an observation made on a real OP-Z content disk [DEV]: the sample slots contained **0-byte `~name.aif` files** (e.g. `1-kick/03/~redmountKicks.aif`, `2-snare/03/~redmountSnares.aif`), which look like corruption but are the vendor's own de-duplication markers for a pack that is stored once in another slot |

Its **per-type operation chart** is worth reproducing, because it defines which edits the device honours at all:

| type | add | modify | remove |
|---|---|---|---|
| `bounces` | no | no | **yes** |
| `DMX` | no | **yes** | no |
| `MIDI` | no | **yes** | no |
| `projects` | yes | yes | yes |
| `sample packs` | yes | yes | yes |

and its five-step procedure is the behaviour to expect from the device: edit content → **eject** → wait for the
unit to synchronise → when the import completes the synth enters normal mode → anything rejected appears in
`rejected` the next time content mode is entered.

Two further specifics worth recording:

- **Sample packs are OP-1 `.aif`**, either drum or synth format ("export samples from OP-1, build your own
  using the OP-1 drum utility, or download from op1.fun"), placed in **one of ten slot subfolders per track**.
  The readme states a **24 MB total sample-data ceiling**; I could **not** confirm that constant statically
  (no `0x1800000`-style operand found near the import code), so it is recorded as readme-stated rather than
  firmware-verified.
- **The `midi.json` keys get their vendor descriptions here** — `channel_one_to_active` is "any incoming midi
  on channel one is sent to the currently active track", `alt_program_change` is an "alternative PC format",
  `midi_echo` "echo incoming midi back on same port", `track_channels` sets the outgoing channel per track,
  `parameter_cc_out` sets the outgoing CC per parameter. Doc `05` §5.5 lists those keys from the binary; this is
  what they mean.

## 2.9 Assorted internals worth recording
| string | file | significance |
|---|---|---|
| `Not found`, `Errno`, `Bad file`, `Internal error`, `CRC error`, `Unknown error` | bootloader | the yaffs/fs error-name table |
| `[factory reset]` | bootloader | a factory-reset log tag |
| `0123456789abcdefghijklmnopqrstuvwxyz` | both images | base-36 alphabet — serial-number format |
| `systeminfo/version.txt`, `systeminfo/serial.txt` | bootloader | the files written into `systeminfo/` on the update-mode volume |
| `/yaffs2/tmp/crash01.log`…`crash05.log` | bootloader | a **rolling 5-entry crash log ring** |
| `requesting psoc error log` | OS | the keyboard PSoC keeps its own error log that the OS pulls |
| `index`, `values`, `defaultOctave` | OS | per-preset schema (18 integer values per preset, per earlier findings) |
| `use ASSERT_LOG instead` | OS | developer assertion macro guidance left in the binary |
| `NOPE! %d != %d` | OS | the checksum-failure log for the hidden config command channel |

The **rolling crash log ring** (`crash01`–`crash05`, in `/yaffs2/tmp/`, copied to `systeminfo/`) explains
the `crashlogs/` directory seen on the update-mode volume in earlier device work, and means the *five*
most recent crashes are always retained — useful for anyone diagnosing a unit in the field.

## 2.10 The debug/verbose build-date literal

`Jan 26 2021` appears in the **bootloader** as a standalone string, and the `0x35` version reply
interleaves it into the version block (`03-serial-commands.md` §3.3). That means the bootloader has a
hard-coded build date — consistent with `bootloader.version` reading `1.1.35` and the earlier finding
that the bootloader reported "Already installed" during the stock reflash.

## 2.11 USB identity strings and project filenames

The OS carries the USB mass-storage and MIDI endpoint names it presents to a host:

```
OP-Z       FAT32                     <- volume label, FAT32 variant
OP-Z       FAT                       <- volume label, FAT variant
OP-Z Disk                            <- mass-storage device name
OP-Z Out 0        OP-Z Out 1         <- MIDI output port names
OP-Z Midi                            <- MIDI port name
OP-Z (Composite)                     <- composite USB device name
OP-Z Serial Emulator                 <- CDC console port name
```

So the device's USB enumeration is **explicitly configured for two different filesystem variants**
(FAT and FAT32) and exposes a *composite* device with mass storage, MIDI and a CDC serial console. The
`OP-Z Serial Emulator` name is what macOS surfaces as the `/dev/cu.usbmodem…` node.

Project files follow a fixed two-digit numbering scheme:

```
projects/project%02d.opz        <- the canonical path
project%02d%s.opz               <- with a variant suffix
project.opz      %02d.opz       <- single-project and bare-number forms
```

That matches the `project01.opz`…`project10.opz` files observed on the content-disk dump, and the
`%s` variant slot implies projects can carry a suffix (likely a backup or export marker).
