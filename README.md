# OP-Z Firmware Notes

This repo records analysis of `z_firmware_1_2_45.zfw`. Its AES-256 key remains unknown; a console oracle recovers
selected decrypted archive bytes without the key. The current target is the separate compressed `bootloader.ldr`
member, whose plaintext prefix has not yet revealed the key (details below).

See `FIRMWARE_ANALYSIS.md` for the full detail.
Original factory-audio investigation: [FACTORY_SAMPLES_RESEARCH.md](FACTORY_SAMPLES_RESEARCH.md).

## Current oracle status

The active target is the separate ZIP member `firmware/blackfin/bin/bootloader.ldr`, not the much larger OS image.
Its compressed stream is 156,306 bytes; 811 contiguous bytes have been recovered and inflate to a 1,211-byte
incomplete prefix. A scan of all 1,180 sliding 32-byte windows in that prefix found no AES key candidate; this
negative result applies only to the recovered prefix. The bounded collector is `toolkit/opzbootprobe.py`.

The user reports an Arduino-controlled relay power cut turns the OP-Z fully off even with USB connected. Automatic
power restoration, return to update mode, and remount have not yet been tested, and the collector has no relay
integration. A 20-second full cycle is an assumption: at the measured yield it would take about 20.25 hours for the
remaining ~3,645 probes. See [HANDOVER.md](HANDOVER.md), §§66.91–66.93 in `FIRMWARE_ANALYSIS.md`, and the
[automation checklist](PLAN_OPZ_BOOTLOADER_ORACLE_AUTOCYCLE.md).

**TL;DR:** the `.zfw` payload uses AES-256-CBC (PKCS#7). The key is unresolved. The console readout oracle can
recover selected archive plaintext without the key; a scan of the first 1,211 bytes of the separate bootloader
plaintext found no raw 32-byte key window, which does not rule out later bytes. See §§66.92–66.93.

> ⚠️ **BRICK WARNING.** The upgrade-mode console is a **root shell, not a log sink**. Sending
> command **`0x15`** to it formats the internal NAND; the unit then **only ever boots into update
> mode**, and reflashing (1.1.12 and 1.2.45), factory reset and power-drain do **not** recover it.
> Never enumerate unknown console command types. Full postmortem, evidence and hard cautions:
> `FIRMWARE_ANALYSIS.md` → *“POSTMORTEM: how the normal-boot path was bricked”*.

`decrypt_zfw.sh` is ready for the moment a key is available; `HYPOTHESES.csv` records what has
been tested — including the bricking tests and their verdicts.

**Recovery effort:** the official companion app's APK (`OP-Z_1.3.0_APKPure.apk`, analysed offline)
yielded the complete factory plug table (**35 plugs, 58 presets, 16 engines**) now saved as
`opz-factory-plugs.json`, plus the exact internal file paths and binary formats of
`settings/plugDefinitions.dat`, `settings/plugPresets.dat` and `settings/slotConfiguration.dat`, and
the source-level rule that the content disk can only overwrite *existing* internal files. See
`FIRMWARE_ANALYSIS.md` → §11.

The cloud DLC catalogue turned out to be **public**: all **21 official engine binaries**
(`engines/`, ~103 kB) and the full 44-plug catalogue are downloadable without authentication. Host
repair through the **content disk** is exhausted — it is a four-folder interface (`config/`,
`projects/`, `bounces/`, `rejected/`) that cannot write `/yaffs2/user/{settings,engines}/`, and
`samplepacks/` is a read-only re-export. See §16–18.

**But the updater itself is a general write primitive.** §24: a *plain* zip named
`firmware_bin_only_with_bootloader.zip` in the volume root is extracted into `/yaffs2/`, with `..`
resolved unsanitised and missing parents created, **before** the `ble` gate — no key, no crafted
`.zfw`. That is the channel that changed everything: **the unit now boots the application** (startup
animation, track-selection UI, full sequencer/audio/MIDI init) instead of dying during init. See
§66.25–§66.27 for the payload, the proof and the recipe.

**Where to go next:** validate the Arduino-controlled power-cycle/remount path, then implement the opt-in relay
loop and recover the rest of `bootloader.ldr`. The current execution checklist is
[PLAN_OPZ_BOOTLOADER_ORACLE_AUTOCYCLE.md](PLAN_OPZ_BOOTLOADER_ORACLE_AUTOCYCLE.md); §64 is a historical route map.

**HISTORICAL BREAKTHROUGH (2026-10-10, §66.12):** the first read through the corrected decoder proved the archive is an
**ordinary Deflate zip** — `PK\x03\x04 | ver 20 | flags 0x0000 | method 8 | 2022-03-31 14:03:04` — and that the
long-standing "seed" (`… c0 1e 04 …`) was a **hand-pasted constant**, not an observation (it contains NULs, which no
leak can). Every conclusion derived from it — flags `0x1ec0`, method 4, nameless entries, "no central directory" —
was fiction. That makes §64.3 (read the central directory) the live cheap route: a named CD at the tail gives the
component map in dozens of windows instead of ~23,000. Later probes identified the bootloader member directly;
recovering its compressed stream is now the active key-search path (§§66.87–66.93).

**Three of those five are now closed by measurement, and one replacement was found** — see
`FIRMWARE_ANALYSIS.md` → **§65 “Autonomy, the read trigger, and what actually closes the loop”**:

| route | verdict |
|---|---|
| capture the plaintext archive (§64.2) | **dead** — the update volume is volatile and is rebuilt at every boot (§65.1) |
| root SCSI media-load (§64.4) | **dead** — run with real root, every SCSI command accepted, `TEST UNIT READY` still reports no medium (§65.8) |
| several windows per boot (§64.5) | **dead** — one firmware read per boot is firmware policy, with a control run where the directory was provably healthy (§65.3) |
| leak **and** reboot in one probe (§64.3) | **dead** — the leaked bytes become the FAT filename, which FAT rejects, and the name is truncated at 37 bytes (§65.6) |
| **a successful upgrade reboots the device** | **works** — proven end to end (§65.5); relay power-off is also reported, but its full reboot/remount cycle is untested (§66.93) |

The historical full-archive cost model remains about **23,000 power cycles** at the measured ~65-byte leak cap.
The current key-recovery target is smaller: recover the 156,306-byte compressed `bootloader.ldr` member, currently
estimated at ~3,645 further probes. That estimate assumes the recent 42.7-byte/probe yield; a 20-second complete
cycle would imply ~20.25 hours, but no full relay cycle has been measured. Before that work, see **§66 “Second review:
what the decoder got wrong, and the log-buffer cap”** — the oracle generator
spliced ciphertext at unaligned offsets, so every tail read was pseudorandom, 94% of the saved map is garbage, and
the "no central directory at the tail" conclusion is void. The corrected codec is
`~/.opz-decode/toolkit/opzframe.py` (self-tested against the surviving captures).

## Historical device status (2026-10-10 21:45; superseded by Current oracle status above)

**The unit is largely repaired: it boots, the interface responds, sequencing works, it plays audio, and
content mode is back.**

| | |
|---|---|
| boot to the application (animation, track UI, TRACK button) | works (§66.26) |
| **sound on key presses** | **works** (§66.28) — except track 1 |
| DMX config, `fxmanager: Couldn't find plug` errors | **fixed** (§66.28) |
| **content mode (the disk mounts)** | **fixed** (§66.38) |
| track 1 (kick) | silent — its sample pack is missing |
| PLAY button | **still crashes** — `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`, `DCPLB_FAULT_ADDR 0x000002c0`, `RETX 0x80117baa` (§66.29) |

### Four rules that are now paid for

1. **A plug's `samples` field must never name a pack that cannot be loaded.** Doing so makes content
   mode unreachable (`mass_storage: create and mount FAT` → `DCPLB_FAULT_ADDR 0x00000001`,
   `RETX 0x80033fd6`). Verified both ways: setting it broke content mode, reverting it to `samples: ""`
   fixed it immediately. Set `samples` only once the pack is genuinely installed.
2. **Never write inside the eight factory pack directories** (`samplepacks/<track>-<name>/…`). The
   updater can only write, never delete, so such an entry can never be removed from the host again — a
   0-byte file reclaims the space but the name stays forever.
3. **The content disk is a curated export, not a mirror.** It carries `config/`, `projects/`,
   `samplepacks/`, `bounces/`, `rejected/` and the `how_to_*.txt` files — **not** `settings/` or
   `engines/`. It is 33 MiB with 1.9 MiB used and 31 MiB free, so space was never a factor anywhere.
4. **The updater write channel is confirmed by independent read-back**: `config/dmx.json` (782 B, host
   timestamp) appears in the exported `config/` next to the device's own files.

### Where the sample pack currently is

On the **live content disk**, at both paths the import function tries:
`/samplepacks/redmountKicks.aif` and `/samplepacks/user/redmountKicks.aif` (891,612 B each, with the
macOS `._*` AppleDouble files removed since the device scans that FAT). **Ejecting the disk makes the
unit import it** (`how_to_import.txt`); only after that should plug 13 be given
`samples: "redmountKicks.aif"` (rule 1).

### Toolkit

The research toolkit is included: scripts and tests live at the root and in `toolkit/`, with the
clean-room SysEx reference implementation under `refs/op-z-sysex/`. Recent USB/BLE pull tools are
`toolkit/opzpull.py` and `toolkit/opzble.py`; run their device-free self-check with
`python toolkit/test_pull_paths.py` (`mido` is needed for USB, `bleak` for BLE).

For bounded update-mode oracle reads, use `uv run --script toolkit/opzbootprobe.py --start 467296
--length 64 --max-probes 4`. It preserves existing disk files, stages one probe per cycle, saves raw
captures and recovered bytes under `~/.opz-decode/bootloader-probes/`, and automatically polls for the
update volume before each next cycle. It logs elapsed time from volume detection to the first complete
decrypted leak frame, resumes saved ranges on rerun, and changes the first-block mask when a NUL would
stall progress. It refuses to run alongside the automatic decode farm. Polling only waits: after each probe, the
OP-Z still needs a power cycle before the update volume returns. The collector does **not** operate the relay; that
integration remains unimplemented and is tracked in `PLAN_OPZ_BOOTLOADER_ORACLE_AUTOCYCLE.md`.

The bulky local artifacts are omitted: firmware/app binaries, device dumps and backups, most logs,
samples, wordlists, and the virtual environment. Older experiment scripts may still expect those files
and the original `~/.opz-decode/` paths; provide suitable input files before running them.
`opz-sudo-install.sh` installs a passwordless sudo rule—review it and the associated scripts before use.
