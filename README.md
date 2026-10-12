# OP-Z Firmware Notes

This repo captures a short write-up of what we learned while poking at
`z_firmware_1_2_45.zfw`. The decrypted archive is still locked behind the
device’s secret AES-256 key, so the notes focus on the file structure, known
offsets, and next steps once the key becomes available.

See `FIRMWARE_ANALYSIS.md` for the full detail.
Original factory-audio investigation: [FACTORY_SAMPLES_RESEARCH.md](FACTORY_SAMPLES_RESEARCH.md).

**TL;DR:** yes — the `.zfw` payload is AES-CBC (PKCS#7) with a global key that lives in an
on-die BF703 key slot, not in the file, so the raw key is not recoverable from the files. The
software-only read path is the **console readout oracle** (place payload ciphertext in the
`0x300` slot and set the IV to the preceding ciphertext block — see `oracle_decrypt.py`),
which returns plaintext without ever needing the key.

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

**Where to go next:** `FIRMWARE_ANALYSIS.md` → §64 *“Better ways than brute force: the route map”*.
Brute force is closed by measurement (one candidate is already one AES block, 96 ns; optimisation buys
`log(X)/log(95)` characters, so a 1000-GPU farm buys under 3), and §64.2–§64.6 lays out the five routes that
were open at the time.

**BREAKTHROUGH (2026-10-10, §66.12):** the first read through the corrected decoder proved the archive is an
**ordinary Deflate zip** — `PK\x03\x04 | ver 20 | flags 0x0000 | method 8 | 2022-03-31 14:03:04` — and that the
long-standing "seed" (`… c0 1e 04 …`) was a **hand-pasted constant**, not an observation (it contains NULs, which no
leak can). Every conclusion derived from it — flags `0x1ec0`, method 4, nameless entries, "no central directory" —
was fiction. That makes §64.3 (read the central directory) the live cheap route: a named CD at the tail gives the
component map in dozens of windows instead of ~23,000.

**Three of those five are now closed by measurement, and one replacement was found** — see
`FIRMWARE_ANALYSIS.md` → **§65 “Autonomy, the read trigger, and what actually closes the loop”**:

| route | verdict |
|---|---|
| capture the plaintext archive (§64.2) | **dead** — the update volume is volatile and is rebuilt at every boot (§65.1) |
| root SCSI media-load (§64.4) | **dead** — run with real root, every SCSI command accepted, `TEST UNIT READY` still reports no medium (§65.8) |
| several windows per boot (§64.5) | **dead** — one firmware read per boot is firmware policy, with a control run where the directory was provably healthy (§65.3) |
| leak **and** reboot in one probe (§64.3) | **dead** — the leaked bytes become the FAT filename, which FAT rejects, and the name is truncated at 37 bytes (§65.6) |
| **a successful upgrade reboots the device** | **works** — the only host-drivable reboot; proven end to end with no user action (§65.5) |

The practical consequence is a **cost model**: one power cycle per leak window, and the window is hard-capped at
**~65 bytes** by the device's 128-byte log buffer, so the full 1.49 MB decode is **~23,000 power cycles**. Before
any of that, see **§66 “Second review: what the decoder got wrong, and the log-buffer cap”** — the oracle generator
spliced ciphertext at unaligned offsets, so every tail read was pseudorandom, 94% of the saved map is garbage, and
the "no central directory at the tail" conclusion is void. The corrected codec is
`~/.opz-decode/toolkit/opzframe.py` (self-tested against the surviving captures).

## Status (2026-10-10 21:45)

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
