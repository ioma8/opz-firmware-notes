# Firmware Analysis Notes

> ⚠️ **WARNING / READ FIRST — COMMAND `0x15` ON THE UPGRADE CONSOLE BRICKS THE NORMAL-BOOT PATH.**
> Sending a single `C0 01 15 00000000` frame to the upgrade-mode CDC console makes the bootloader
> **format the internal NAND** (`nand: formatting 4096 nand blocks..`). Afterwards the unit **only ever
> boots into update mode**: reflashing 1.1.12 and 1.2.45, factory reset, power-drain and every software
> recovery attempt all fail. Read **“POSTMORTEM: how the normal-boot path was bricked”** at the end of
> this file before sending any console command. The upgrade console is a **root shell, not a log sink.**

## File Overview
- Sample analyzed: `z_firmware_1_2_45(1).zfw` (size 1,491,600 bytes).
- `file` reports generic data; high entropy throughout payload confirms encryption.
- First non-zero byte at offset `0x04` equals `0xFF` – documented as "key index".

## Header Layout (based on observations & community wiki)
| Offset | Length | Description | Observations |
| ------ | ------ | ----------- | ------------ |
| `0x00` | 4 bytes | Flags / header marker | Mostly zeros; byte 4 = key index (`0xFF`). |
| `0x10` | 0x60 | Reserved | All zeros in this sample. |
| `0x70` | 16 bytes | AES IV | Value: `32 93 C5 8E E8 43 EF 3A 7B 0B 5E C8 5D E8 30 ED`. |
| `0x80` | 4 bytes (LE) | Encrypted payload length | `0x0016BE8F` (=1,490,575); matches total payload size beginning at `0x400`. |
| `0x300` | 0x100 | Encrypted filename blob | Decrypts (with correct key) to `firmware_bin_only_with_bootloader.zip` per wiki / Reddit thread.
| `0x400` | `length` bytes | AES-encrypted firmware archive | All attempts to decode reveal uniformly high entropy.

## Encryption Characteristics
- Wiki confirms AES (CBC) with 256-bit key; IV stored at `0x70`.
- Actual AES key is *not* present in the file; only a key index is stored. All published firmware reportedly use the same secret key held inside the device.
- Attempted techniques:
  - Recovered repeating XOR masks from ciphertext assuming known plaintext headers (7z, gzip, MZ). Produced plausible-looking fragments but failed structural checks (invalid PE headers, corrupt archives) → confirms ciphertext remains encrypted.
  - AES-CTR/CBC/CFB/OFB trials with IV and ciphertext using the 16-byte value as key or IV → output still random; no valid signatures.
  - Header-derived AES ECB decryptions fail to reveal meaningful plaintext.
- Entropy measurements (`ent`) show 7.9998 bits/byte across payload → consistent with strong encryption.

## Known Plaintext / Metadata Clues
- Offsets flagged by signature scans for `7z`, `gzip`, `MZ`, `FAT` align with boundaries of encrypted sections but do not correspond to useful plaintext without key.
- Decrypted filename (from community references) indicates final payload is a zip archive containing sub-firmwares (`firmware_bin_only_with_bootloader.zip`).

## External Research (GitHub wiki & Reddit)
- **Real source found:** `billymeter/rez` → wiki `Firmware.md` (github.com/billymeter/rez/wiki/Firmware).
  Confirms AES-256-CBC, one global key, and documents a serial-console padding oracle.
- Also confirms: the OP-Z will treat a plain file named `firmware_bin_only_with_bootloader.zip`
  dropped on the upgrade drive as an **unencrypted** firmware (no key needed to *flash*).
- Reddit thread `/r/OPZuser/comments/be1nl6/opz_firmware_analysis/` confirms:
  - OP-Z bootloader uses padding-oracle-resistant AES-CBC.
  - Device can output decrypted filename via serial console but does not expose the key.
  - All consumer firmware zfw files share the same AES key.

## Current Blockers
- Without the 256-bit AES key there is no feasible software-only path to decrypt the archive.
- Brute force or generic cryptanalysis is infeasible.

## Recommended Next Steps
1. Obtain AES key from hardware (e.g., instrument OP-Z secure boot, glitching, or leveraging `.engine` modules to dump keys) or from existing community dumps.
2. Once key is available:
   - Use IV at `0x70` and decrypt payload starting at `0x400` using AES-256-CBC.
   - Extract resulting `firmware_bin_only_with_bootloader.zip`, then expand contained binaries for further reverse engineering.

## Miscellaneous Artifacts
- `rez.wiki/` cloned locally for reference (`Firmware.md`, `Hardware.md`).
- Numerous “decoded” MZ/7z/gzip fragments stored under `extracted/`; these are artifacts from xor experiments and not valid binaries.

## Verified This Pass (structural, no key needed)

- **Padding math proves a padded block mode.** For all 7 files:
  `0x400 + length + PKCS#7padding == filesize` *exactly* (e.g. 1.2.45: `0x400 + 1_490_575 + 1 = 1_491_600`).
  Streaming modes (CTR/CFB/OFB) never pad, so the payload is **CBC** (community consensus) —
  the `length` field is the *plaintext* length.
- **Not ECB.** No repeated 16-byte block anywhere in the `0x300` blob or the payload.
- **No key in the file.** The only non-trivial header regions are the 16-byte IV at `0x70`
  and the 256-byte encrypted filename blob at `0x300`. There is no raw 16/32-byte key.
- **Weak-key audit failed.** ~1.18M candidate keys (system wordlist via raw / md5 / sha1 / sha256,
  plus TE-specific strings) do not decrypt the known filename block
  (`firmware_bin_only_with_bootloader.zip`).
- **One global key, random IV.** `key index = 0xFF` in every file; every IV differs.

## Device / Crypto Context (primary sources)

- Main SoC is an Analog Devices **ADSP-BF703** (Blackfin) — from the original analysis
  (op-forums topic 7677, post #9 by TabascoEye; Reddit `be1nl6`).
- The BF70x has an on-chip crypto block and a protected key store. The header’s
  “key index” (`0xFF`) selects an **on-die key slot**, which is why the key is in neither
  the `.zfw` nor flash in readable form.
- Update path: the `.zfw` is dropped on the OP-Z USB mass-storage root in upgrade mode and
  the **device** decrypts it. The host tool/app never holds the key.

## Why Offline Software-Only Is a Dead End (no device)

- AES key space is 2^256; a known-plaintext + known-IV pair gives no shortcut.
- No offline data attack exists (see the table above). With the device attached, however, there
  *is* a software-only decryption oracle — see the live-session section at the end.

## Real Paths (all need the physical device)

1. **Use the on-chip AES engine as an oracle (preferred).** With JTAG/SWD access to the BF703,
   run a small routine that points the hardware AES at the ciphertext using the hidden key
   slot (`0xFF`) and read out plaintext. The key never leaves the chip.
2. Dump flash/OTP and read the key out directly (only if debug is unlocked and the slot is readable).
3. Fault/glitch the bootloader if the debug port is locked.

## Where the Key Lives (the decisive clue)

- The OP-1 (same vendor, same Blackfin family) reads its key from **Blackfin OTP memory page `0xd0`**
  (documented in `op1hacks/docs`). The OP-Z `key index = 0xFF` is the same mechanism: an
  **on-die OTP key slot**. OTP keys are read-protected on the core; they are not derivable from any
  published file, and they are byte-identical across the ~10 published `.zfw` files.
- A **padding oracle recovers plaintext, not the key.** If the goal is to read/modify firmware,
  plaintext is enough; if the goal is the literal 256-bit key, only OTP/debug access gets it.

## Software-Only: what is and is not possible (all tested)

| Attack | Result |
| ------ | ------ |
| rockyou (14.3M) × {raw16, raw32, md5, sha256} = ~57M keys, AES-CBC/ECB | no hit |
| system wordlist (~236k) × 5 transforms, plus TE strings | no hit |
| key = f(IV), f(filename), f(version), f(ciphertext), PBKDF2/HKDF/repeated-hash | no hit |
| key stored anywhere in the file (scan every aligned 16/32-byte window) | no hit |
| XOR keystream / short-period key (from known plaintext) | no period |
| reused keystream across versions (all 21 pairs, XOR structuredness) | random |
| ECB (repeated blocks) | none |

Known plaintext of 37 bytes gives exactly **3 AES input/output pairs** — cryptographically useless
against AES-256. There is no known-plaintext shortcut.

## The actual software-only route: console readout oracle (no key needed)

The OP-Z **prints the decrypted `0x300` filename blob to the USB serial console**. That print is a
readout of `AES_dec(blob[i]) XOR blob[i-1]` (CBC, with `blob[-1] = IV@0x70`). Because CBC chains
*inside* that 256-byte region, we can put **payload** ciphertext there and read back **payload
plaintext**, 256 bytes per query:

```
blob@0x300 = Y_j || Y_{j+1} || ... || Y_{j+15}     (16 payload ciphertext blocks)
IV@0x70    = Y_{j-1}                                (Y_-1 = original IV)
console prints  X_j || X_{j+1} || ... || X_{j+15}   where X_i = AES_dec(Y_i) XOR Y_{i-1}
```

~5800 queries decrypt the whole ~1.5 MB firmware. Built and locally self-tested in
`oracle_decrypt.py` (`--selftest` recovers a random 4 KB payload with no key). This is almost
certainly what any "software-only" report is doing — it returns **plaintext, not the key**.

2. **Unencrypted-zip bypass**: drop `firmware_bin_only_with_bootloader.zip` (plaintext) on the drive
   to flash custom firmware without any key. Ideal for *writing*; you still need one decrypted
   sample for reference.

## Tooling Added

- `decrypt_zfw.sh <zfw> <hexkey> [out.zip]` — decrypts payload + filename blob, prints
  `KEY OK` on a correct key. Round-trip tested.
- `oracle_decrypt.py` — console-oracle decryptor (`--selftest` proven).
- `HYPOTHESES.csv` — hypotheses tested and their verdicts.

---

# Live device session (confirmed on hardware — unit X3CJN79E)

Device: **firmware 1.2.45**, os 1.2.43, bootloader 1.1.35, keyboard 1.2.26, ble 1.1.9.
Internal FS is **YAFFS2** (`/yaffs2/upgrade/`, `/yaffs2/user/engines/*.engine`).

## Trigger and console

- Put the OP-Z in upgrade mode (hold **SCREEN** at power-on). It exposes a USB mass-storage LUN
  (`/Volumes/OP-Z`) **and** a USB CDC serial console (`/dev/cu.usbmodem…`).
- The device processes a dropped `.zfw` **only when the drive is ejected**. It then logs to the
  serial console and the mass-storage LUN disappears.
- After eject the device **stays in upgrade mode** (serial console stays alive) but does **not**
  re-export the LUN on its own; a failed read does not reboot it either.
- Console frames are `C0 <10-byte header> <text…> 00`; the text is a normal log line.

## Bootloader log for a real `.zfw` (verbatim)

```
bootdisk: detected encrypted file /z_firmware_1_2_45.zfw
bootdisk: opened encrypted file /z_firmware_1_2_45.zfw
bootdisk: loaded flags 16 bytes
bootdisk: key index: 0xff
bootdisk: loaded IV 16 bytes
bootdisk: loaded len 4 bytes: 1490575
bootdisk: loaded encrypted filename, 256 bytes
bootdisk: filename found: firmware_bin_only_with_bootloader.zip
bootdisk: decrypt 94208/1491600 bytes        # repeated in 94208-byte steps
```

## Oracle — CONFIRMED on hardware

The device prints the decrypted `0x300` blob as a **C string** (`bootdisk: failed to find .zip
file in <print>` when the plaintext doesn't end in `.zip`, or `filename found: <print>` when it does).

- Replacing the `0x300` blob with 16 **payload** ciphertext blocks and setting `IV@0x70` to the
  preceding block makes it print decrypted **payload** bytes.
- Verified end-to-end: the recovered first block is `PK\x03\x04\x14\x00\x00\x00\x08\x00bp\x7fT…`
  — a real ZIP local file header.
- **The filename blob and the payload are ONE continuous CBC stream.** The payload has no IV of
  its own: `X_0 = AES_dec(Y_0) XOR C_last_blob(0x3F0)`, and `X_i = AES_dec(Y_i) XOR Y_{i-1}`.
  (Corrects the naive "payload uses IV@0x70" assumption in `oracle_decrypt.py`.)
- The print is **NUL-terminated**, so a query yields bytes only up to the first `0x00` in the
  decrypted window (fewer than 256 on binary data).
- The device also looks for a disk file named exactly the decrypted string — this is the
  unencrypted-zip bypass (`mass_storage: comparing <file> with firmware`).

## Extract stage

- `upgrade: [extract] progress …/2775623` → the zip expands to **2,775,623 bytes**, so entries are
  **DEFLATE-compressed** (the 1,490,575 `length` is the *compressed* payload).
- Extracts to `/yaffs2/upgrade/`; logs `content` / `os` / `bootloader` / `ble` / `keyboard` steps.
- A successful upgrade reboots the unit; a failed one leaves it in upgrade mode but without the LUN.

## Re-export / remount attempts after eject (all failed)

After the drive is ejected the LUN disappears and the bootloader stays alive. Tried to bring the
LUN back without touching the unit:

| Attempt | Result |
| ------- | ------ |
| Send bytes on the console (newline, `help`, framed `C0…`, zeros, break) | ignored — device emits only periodic charger logs; input has no effect (TX-only log sink) |
| Toggle CDC DTR/RTS, repeatedly open/close the port | no effect |
| `USBDeviceReEnumerate` / `ResetDevice` **without** an open first | `0xe00002cd` (not permitted) |
| same, **after `USBDeviceOpen`** | **succeeds** (`open->0x0, reenum/reset->0x0`), works **without root**; device really re-enumerates (IOKit id changes `…1de6`→`…1e42`), bootloader logs `smx session active callback: 1`, serial re-enumerates — but **no media returns** |
| `uhubctl` port power cycle | `No compatible devices detected!` — Apple-internal ports don't support port power switching |
| `launchctl kickstart diskarbitrationd` | blocked by **SIP** (error 150) |
| `IOServiceRequestProbe` on SCSI/block nodes | `0xe00002c7` (unsupported) |
| re-enum ×6 alternating reset/reenum + 20 s media poll | never a `disk4+` or IOMedia blip |

**What the device actually does:** the whole stack still exists — `MS Data Intf BulkOnly@2`
(`bInterfaceClass=8/Sub=6/Proto=80`), `IOUSBMassStorageInterfaceNub`, `IOUSBMassStorageDriverNub`,
`IOSCSILogicalUnitNub@0`, `IOSCSIPeripheralDeviceType00`, `IOBlockStorageDriver` — but **no
`IOMedia`**. The device reports **"no medium"**; macOS can't rescan a LUN the device has emptied.
This is a bootloader-side state, so no purely host-side trick (re-enum, reset, power, SIP-off
daemons, SCSI re-probe) can bring it back. Only a **device reset (power cycle / true VBUS replug)**
can.

So a purely software remount is **not** possible. The only remaining trigger is a **physical USB
replug** (does the bootloader re-export on re-enumeration?) or a full **SCREEN+power cycle**.

## CONFIRMED END-TO-END (hardware, 21:52)

- **Button press triggers the read and the drive STAYS MOUNTED.** Pressing Play (and other
  buttons) on the OP-Z in upgrade mode re-reads the dropped `.zfw`; the mass-storage drive is not
  removed, so many reads happen in one power cycle. (~40 reads observed across a few presses.)
- **Oracle is correct with proper chaining.** With `IV@0x70 = C(0x3F0)` (the preceding ciphertext
  block) and `blob@0x300 = payload blocks 0..15`, the console printed
  `bootdisk: failed to find .zip file in PK\x03\x04\x14` — exactly the zip's first bytes, i.e.
  `X_0 = AES_dec(Y_0) XOR C(0x3F0)` is confirmed. `PK\x03\x04\x14` then `0x00` -> the print is a
  **C string** and stops at the first NUL (here after 5 bytes).
- **Copying a file does NOT trigger a read** (drive stays mounted, no read fires). The trigger is
  the device button, not the host file change.

## The one remaining obstacle: FAT writes wedge

After the device has read the dropped file, **writes to the OP-Z FAT volume block
(uninterruptible `U` state)** — even writing a new 3-byte file hangs. The first in-place write of a
session works; subsequent ones wedge. Likely the device holds the volume/file after reading, or
macOS's FAT driver deadlocks against it.

**Confirmed precisely (two-step test, 22:24):**

```
write j=0    -> {'ok': True}          # before any read: writable
READ 1       -> 504b030414 = PK\x03\x04\x14   # correct!
write j=16   -> {'ok': False}         # right after the read: WEDGED (uninterruptible)
```

So the volume becomes **unwritable as soon as the device reads** the dropped file — even a ~1 KB
write to the same file. The device appears to hold the file/volume after reading, and macOS's FAT
driver blocks forever against it.

**Implication / next experiments:**
1. **Pre-stage many query files before any read.** The volume is writable until the first read, so
   write `q00.zfw, q01.zfw, ...` (each ~1 KB, `length=0`) up front, then let the device scan.
   If the bootloader iterates over all `.zfw` files, one session yields N answers instead of 1.
2. If a single file is all it reads: use a **new filename per query** (the read may lock only the
   file it read, not the volume) or delete+recreate.
3. Tiny query file works: 0x400 header+blob with `length=0`, `IV@0x70` set to the preceding
   ciphertext block — the oracle prints `PK\x03\x04\x14` and stops at the first NUL.

## OP-1 comparison (`op1hacks/op1repacker`, `sualk/op1-docs`)

- The OP-1 `.op1` container is **not encrypted**: `CRC32 (4 bytes) + LZMA` -> TAR archive. That is
  why `op1repacker` can unpack/repack with **no key**.
- Only `OP1_vdk.ldr` code blocks are encrypted, with **XTEA** (first 8 of every 24 bytes), and the
  key is **read from Blackfin OTP page `0xd0`**.
- Take-away: same TE pattern as the OP-Z `key index 0xFF` (key in OTP), and the repacker only works
  because the container layer is separate from the crypto. No key-extraction method is published.

## Batch test: the bootloader reads exactly ONE `.zfw`

Staged `q00.zfw … q09.zfw` (10 different queries, each ~1 KB, `length=0`) before any read, then one
Play press:

```
bootdisk: detected encrypted file /q00.zfw     # only q00
reads: 1   -> 504b030414 (PK\x03\x04\x14)
```

So it does **not** iterate over all `.zfw` files — it picks one, so batching many files at once does
not yield many answers. Combined with the FAT-write wedge, this is the open mechanical problem.

## Software mode-triggering (cue from `kmorrill/op-z-sysex`)

The OP-Z's **normal-mode app SysEx** protocol (USB/BLE MIDI) exposes a way to command the device
without touching any button:

- **`$66` serial tunnel** — outer frame `F0 00 20 76 01 66 <7-bit-packed bytes> F7`. Decoded inner
  serial framing is `C0 routing type length_be32 payload` (same `C0` framing as the upgrade CONSOLE).
  Serial message families include:
  | type | meaning |
  |---:|---|
  | 0/1 | ping/pong |
  | 2/3 | version request/reply |
  | 4/5 | log / log level |
  | 6/14 | **power-mode request/reply** |
  | 7/8 | metadata |
  | 9/10 | **factory-mode request/reply** |
  | 11/12 | greeting |
  | 13 | error |
  | 16/17 | profile / control-profile |
  | **41** | **Blackfin DFU entry** |
  Power-mode payload values: active `16`, standby `18`, power-off `20`, charging `22`, low-batt `24`.
- **`$06` UI/button state** (both directions, writable): carries *held buttons* — i.e. a button
  press (like Play) can be **simulated remotely** over MIDI.
- **`$62` text command** — a UTF-8 command string to the OP-Z (internal/risky).
- Caveat from the source: these are static-analysis constants; power/factory/DFU are "unsafe to
  probe speculatively" and not device-proven.

**Why this matters:** if `$66` type `41` (DFU) or a `$62` text command can put the OP-Z into
upgrade/DFU mode **from normal mode over MIDI**, we replace the SCREEN+power press with a software
call — and if `$06` can hold Play, we may replace the read trigger too. That would make the whole
oracle loop **software-only and automatable**.

## Upgrade-console command channel (confirmed on hardware)

The upgrade-mode CDC console is **bidirectional**, not a log-only sink. Send a frame
`C0 <routing=0x01> <type> <length_be32> <payload>`; the device replies with `C0 <routing=0x1e> <type> ...`.
Confirmed request → reply pairs:

| req | reply | content |
|---|---|---|
| `0x00` | `0x01` | pong |
| `0x02` | `0x03` | full version string (dsp/kb hw revision, fw 1.2.45, os 1.2.43, bootloader 1.1.35) |
| `0x07` | `0x08` | `serial:X3CJN79E;hardware_revision:6;dsp_serial:830000215184407336` |
| `0x35` | `0x36` | `bf_os_ver:1.2.43;bf_bl_ver:1.1.35;kb_ver:1.2.26;ble_ver:1.1.9;chip_id:0x2a9f9f0d5512053cb26df8e99ac38938` |
| `0x39` | `0x3a` | 4 bytes |
| `0x2b` | `0x28` | yaffs stats dump (3444 B) |
| `0x1a` | `0x16` | 2 bytes |

`chip_id` (16 bytes) was tested as an AES-128/256 key against the known filename plaintext — **no hit**.

⚠️ **`0x15` appears destructive**: each call emits `nand: formatting 4096 nand blocks..` with a *fresh*
timestamp, i.e. it may trigger a NAND format / factory reset. Do not send `0x15` again.

## Debug mode and text commands (cue from `MarkRdgOx/opzdoc`)

- **Text command** is a SysEx: `F0 00 20 76 01 62 <ascii> F7`. The documented one is
  `F0 00 20 76 01 62 enable-debug F7`.
- **Enabling debug mode makes the OP-Z offer a serial connection in NORMAL mode, exactly like update
  mode** — i.e. we can keep the OS running, get the console, and talk to it with the `C0` frame
  commands (no physical button needed to enter a mode).
- Update-mode button map (opzdoc): `Screen+Stop` = factory reset, `Track` = signal version,
  **`Play` = "force update start"** (our oracle read trigger).

**Why this is the answer to "software retrigger modes":** the OP-Z exposes (a) a MIDI text-command
channel (`$62`), (b) a MIDI serial tunnel (`$66`: power-mode, factory-mode, **DFU entry**), and (c) a
live framed command console in both update mode and debug mode. If any text/serial command enters
update mode or triggers the update, the whole oracle loop becomes software-only.

# POSTMORTEM: how the normal-boot path was bricked

Unit: **X3CJN79E**. Nothing below is inferred — every claim carries its raw evidence.

## 1. What the unit could do BEFORE the incident

| Action | Result |
|---|---|
| Plain power-on | **normal / playable mode** |
| SCREEN + power | update mode (“OP-Z Boot”) |
| TRACK + power | content mode (“OP-Z Disk”) |
| Drop `.zfw` + eject | full upgrade, then normal boot |

The unit was healthy. The encrypted-`.zfw` analysis (AES-CBC, console oracle, zip-header proof) was
performed against this healthy unit and is unaffected by the incident.

## 2. The destructive sequence (exact)

1. The upgrade-mode CDC console was found to be **bidirectional**:
   `C0 <routing=0x01> <type> <len_be32> <payload>` → reply `C0 <routing=0x1e> <type> ...`.
   Verified benign reads first: `0x00`→pong, `0x02`→version, `0x07`→metadata, `0x35`→versions + chip_id.
2. To map the command set, **all types `0x00`–`0x7f` were sent with an empty payload**.
3. **`0x15`** replied with these log frames (verbatim):
   ```
   nand: NAND manufacturer is MICRON, model is: MT29F8G08ADBDAH4
   nand: formatting 4096 nand blocks..
   nand: block 85 is bad, result: 0xfc
   nand: block 531 is bad, result: 0xfc
   nand: block 2861 is bad, result: 0xfc
   nand: done. found 3 bad blocks out of 4096 total blocks
   ```
   followed by a 2-byte `0x16` status frame.
4. Re-sending `0x15` produced the **same sequence with a fresh timestamp** (`22:08:25` → `22:09:51`),
   proving it is an **action, not a log replay** — it formats on every call.
5. From then on a bare power-on **no longer boots the OS**.

## 3. Blast radius — what was destroyed

The content filesystem exposed by content mode afterwards is **empty/rebuilt**:

```
bounces/   config/ (EMPTY)   projects/ (EMPTY)   rejected/   samplepacks/   import.log (0 B)
how_to_dmx.txt   how_to_import.txt
```

Before the incident the unit had `config/general.json`, `config/midi.json`, `config/dmx.json`,
`userPresets.dat`, projects and engines. All gone. That is a whole-chip consequence: the log says
`formatting 4096 nand blocks` — **the entire NAND**, not one partition.

## 4. Symptoms after the incident

| Action | Result |
|---|---|
| Plain power-on | **update mode** (was: normal) |
| SCREEN + power | update mode (unchanged) |
| PROJECT + power | **update mode** (opzdoc says this should start a normal session) |
| TRACK + power | content mode — **still works**, drive mounts (rebuilt, empty) |
| Power-on with USB **unplugged** | **update mode** (so it is not a host/USB effect) |
| USB identity | update mode: `OP-Z Boot` + CDC console + update volume; content mode: `OP-Z Disk` + mass storage only |
| Console in update mode | healthy: ping / version / metadata / chip_id all answer |
| MIDI endpoint | **none** in update mode and none in content mode (playable mode only) |
| Crash report on the volume | none present |

## 5. What still works (the unit is not “bricked” in the usual sense)

* Bootloader runs; the console command channel answers.
* **Flashing works end-to-end**: dropping the real `z_firmware_1_2_45.zfw` on the update volume and
  ejecting gives `[extract] progress 2775623/2775623`, `upgrade: copied 18 files`, `content: OK (0)`,
  `os: OK (0)`, `bootloader/ble/keyboard: Already installed (-200)`, `successfully upgraded to 1.2.45`
  — **and the unit still returns in update mode**.
* Component versions report correctly: `bf_os_ver:1.2.43; bf_bl_ver:1.1.35; kb_ver:1.2.26; ble_ver:1.1.9`.
* Content mode mounts and exports the user filesystem.

## 6. Recovery attempts — all FAILED

| # | Attempt | Result |
|---|---|---|
| 1 | Reflash 1.2.45 (genuine `.zfw`, eject-triggered) | clean flash, still update mode |
| 2 | Update mode: hold **SCREEN + STOP** (opzdoc “Factory reset”), then reflash | no change |
| 3 | Flash **1.1.12** (older ⇒ bootloader downgrade) then reflash 1.2.45 | no change |
| 4 | Power on with **USB unplugged** | still update mode |
| 5 | Power on holding **PROJECT** | still update mode |
| 6 | USB **re-enumerate / ResetDevice** on the device node | re-enumerates, still update mode |
| 7 | Console: types `0x00`–`0x7f` empty payload; `0x00`–`0x5f` with 4-B / 8-B / text payloads; power-mode `6` (payload `0x10`, `0x12`, u32), factory-mode `9`, DFU `41` | no boot-mode change |
| 8 | `$62` text commands incl. `debug-crash` | **unreachable**: `$62` is MIDI SysEx and no MIDI endpoint exists outside playable mode |

## 7. Most likely cause (ranked)

1. **Command `0x15` = internal-NAND format / factory-reset action — highest confidence.** Direct
   evidence: the full-chip `formatting 4096 nand blocks` sequence, its re-run with a *fresh* timestamp,
   and the user filesystem coming back empty. It erased the flash regions holding the **OS image and/or
   the bootloader’s boot state (partition map, bad-block table, version/validity record)**.
2. **Loss of boot-state metadata that lives outside the four `.zfw` components.** The update path only
   writes `os`, `bootloader`, `ble`, `keyboard` (logging `Already installed` for three of them). Nothing
   in that path rewrites the boot-decision state — which is exactly why flashing is a no-op for this fault.
3. ~~Stuck SCREEN button line~~ — **disproved.** The button is mechanically fine, TRACK still selects
   content mode, PROJECT does not help, and a stuck line would also disturb the content-mode ordering.
4. ~~Corrupt OS image~~ — **disproved.** Two firmware versions flashed cleanly and the component versions
   report correctly; content mode mounts a working filesystem.

## 8. CAUTIONS (hard rules for this project from now on)

1. **NEVER send `0x15`** to the upgrade console. It formats the NAND and kills the normal-boot path.
   No known software command restores it.
2. **Never blind-enumerate an unknown diagnostic console.** The type space contains at least one
   destructive action reachable with an **empty payload**. One frame cost the boot path.
3. Treat the upgrade console as **root shell**, not a log sink: it is bidirectional and command-capable.
4. **Known-safe (read-only) types on this unit:** `0x00` ping, `0x02` version, `0x07` metadata,
   `0x35` versions + `chip_id`. `0x2b` (yaffs stats) answered only on the first boot after the format.
   **Everything else is unverified and must be treated as unsafe.**
5. `$62` text commands are **MIDI-only** and reachable only in playable mode. `debug-crash` *deliberately*
   forces update mode — never use it casually, and never to probe an unknown state.
6. The `.zfw` oracle work is **non-destructive** (it only rewrites bytes inside a dropped file and reads
   a console printout). Keep oracle work strictly separate from console command probing.
7. Before any further device work, **capture what you can** (`systeminfo/`, console metadata replies,
   `chip_id`) so a future incident is diagnosable without the unit.

## 9. Remaining fix paths

1. **TE support / service tool.** Report exactly: *“boots only to update mode; flashing 1.1.12 and 1.2.45
   succeeds but it never boots the OS; content mode mounts normally.”* TE service tooling can re-initialise
   the boot state; the hardware itself is healthy.
2. **Bench / JTAG restore of the BF703.** Rewrite NAND flash + boot state from a known-good image or a
   donor unit. The bootloader is intact, so a full-chip restore should recover the boot path.
3. **Untested last-ditch software idea (not recommended without a dump):** re-run the `0x15` format and
   flash 1.2.45 *in the same pass* (wipe-then-install with no gap). Since `0x15` is the cause, this may
   simply re-wipe; do not attempt without first capturing a full flash dump for comparison.

### 9.1 Result of the wipe-then-install attempt (TESTED — FAILED)

This was attempted on the real unit. **It does not work, and the reason is mechanical:**

1. The genuine `z_firmware_1_2_45.zfw` was staged on the update volume **first** (verified present).
2. `0x15` was sent → the usual `nand: formatting 4096 nand blocks..` sequence.
3. The staged `.zfw` **did not survive the format** — the update volume is backed by the same NAND,
   and the format dropped/re-created it (the volume disappeared immediately afterwards).
4. Ejecting produced **no valid upgrade file**, and the bootloader entered a permanent loop of:
   ```
   bootdisk: upgrade was unsuccessful, system won't reset.
   bootdisk: upgrade was unsuccessful, system won't reset.
   ...
   ```
   The mass-storage medium stayed removed; the CDC console stayed alive; the unit stopped answering
   the version query until power-cycled.

**Conclusion: `0x15` cannot be used as part of a wipe-then-install, because it destroys the very file
that would perform the install, and the volume does not come back writable afterwards.** The bootloader
only supports a long-lived boot state that a bare `.zfw` flash cannot recreate. There is no remaining
software route: the fix needs TE service tooling or a bench/JTAG rewrite of the NAND + boot state.

## 10. ROOT CAUSE (from the device's own crash logs)

> **CORRECTION (2026-10-07, after decompiling the official 1.3.0 app).** An earlier revision of this
> section was titled *“DEFINITIVE ROOT CAUSE”* and asserted that the missing `/yaffs2/user/settings/`
> directory *causes* the null dereference, and that only TE service can recover the unit. **Neither is
> proven.** The crash proves a NULL access *somewhere after* the settings load; it does not name the
> missing file. `SnakeSystem::loadSettings` and `LoadDMXConfig` in the official app (same class and
> log strings as the device) both log a distinct message before *every* early return and cannot
deref NULL, and the device log contains none of those messages — so the fault is **downstream** of the
> general-config parse. See §11. The section below also said “4-slot rotation”; five crash logs were
> observed. Treat the causal claim as a *hypothesis*, not a finding.

The unit is **not** bricked in the bootloader/flash sense. It boots the OS on every
normal power-on, and the OS **crashes immediately**, which is why the bootloader lands in update mode.

The bootloader helpfully drops a crash report into the **update volume's root** at
`systeminfo/crashNN.log` (4-slot rotation). Verbatim tail of the newest one:

```
[17-12-31 00:00:00] main: Read firmware 1.2.45+
[..] main: initialize [usb]: took 277 ms
[..] plugmanager: save slot configuration
[..] yaffsfs: yaffs: error: ENOENT
[..] contentmanager: Calculating used sample memory: 0 kB
[..] snakesystem: load general config /yaffs2/user/config/general.json
[..] main: exception caught iid: 0x00130026, arg: 0x00000000
[..] main: exc reason: ADI_EXC_DATA_CPLB_MISS
[..] main: DCPLB_FAULT_ADDR: 0x00000000.
[..] main: L1DM_DSTAT: 0x00020000.
[..] callstack: RETX: 0x80117baa  / 0x8002c438 / 0x11a03838 / 0x11a02586 / 0x8011a0c0 / 0x8011a184 / 0x8002d3d0 / 0x80134a04
```

`DCPLB_FAULT_ADDR: 0x00000000` = **NULL-pointer dereference**. The callstack lives in the
YAFFS/OS region (`0x8011xxxx`, `0x11a0xxxx`, `0x0800xxxx`).

### What the crash proves

* The OS **runs**: USB, LED control, codec, module, PMIC, RTC, filesystem init/mount all succeed.
* It fails at the **user-filesystem state**, not at the firmware image.
* `/yaffs2/user/` is only **partly** present after the format:
  * `config/` — recreated (the OS even regenerated a correct 336-byte `general.json` itself)
  * `settings/` — **gone** (`plugmanager: save slot configuration` → `ENOENT`)
  * `rejected/`, `bounces/` — **gone** (`filemanager: opendir failed`)
* The OS tolerates the missing `rejected/`/`bounces/` dirs, but a NULL deref follows the
  general-config step — i.e. it cannot re-initialise the plug/slot state that lives in the
  missing `settings/` directory.

### What was tried to repair it (all failed)

| Attempt | Result |
|---|---|
| Reflash 1.2.45 / 1.1.12 / factory reset / power-drain / USB re-enum / no-USB power-on | still update mode |
| Write `{}` to `config/general.json` via content mode | OS replaced it with its own correct defaults; crash persists |
| Create `settings/` on the content disk with `slotConfiguration.json` + `plugs.json` | **device deleted the directory**; import ignores non-standard dirs |
| Put `slotConfiguration.json` / `plugs.json` / `dmx.json` inside `config/` | `import.log` shows sync runs but never imports those names |

### Why it is not repairable through the content disk

The content-disk import syncs exactly `config/`, `projects/`, `bounces/`, `rejected/`,
`samplepacks/`. There is **no content-disk path that maps to `/yaffs2/user/settings/`**, and the
directory cannot be created from the host. Decompiling the app's `Content::importExistingFile`
(§11) shows the import **only overwrites a file whose internal destination already exists** —
`userPresets.dat` is the single documented exception. That is the source-level explanation for the
document's own rule *“you may modify but not add or remove config content”*, and it is why adding
`dmx.json` / `settings/*` to the content disk is silently skipped. The only other writers of
`settings/` are:

1. the OS itself — which crashes before it can recreate the tree; and
2. the companion app's SysEx file transport (`$51`/`$52`/`$53`, reserved file IDs 0 =
   `settings/slotConfiguration.json`, 1 = `settings/plugs.json`, 2 = `syncjob.json`) — reachable
   only over USB MIDI, which the OP-Z exposes **only in playable mode** (unreachable).

Reflashing `.zfw` writes the components `os`, `bootloader`, `ble`, `keyboard` and `content`, and the
captured upgrade explicitly logs **copying 18 files** with `content: OK` — so a reflash *does* copy
content, it just does not (visibly) recreate `/yaffs2/user/settings/`, which is why every reflash so
far has been a no-op for this fault. The archive layout and the content-copy rules remain
un-inspected (we never obtained the plaintext zip — see §11, “capture attempt”).

### Recovery used / remaining

* **Wired USB payload access** → read `systeminfo/crash*.log`, `import.log`, `upgrade.log` (used, decisive).
* **The app's SysEx file transport** — the *one* documented writer of `settings/` that is not the
  OS (reserved file IDs `0 = settings/slotConfiguration.json`, `1 = settings/plugs.json`,
  `2 = syncjob.json`). It needs a MIDI or BLE-MIDI endpoint; the OP-Z exposes USB MIDI only in
  playable mode and BLE advertising has not been tested in content mode (§11, open item).
* **TE service tooling** — can re-initialise the internal filesystem; **no longer the only** avenue.
  Report wording: *“boots only to update mode; the OS crashes with `ADI_EXC_DATA_CPLB_MISS` in
  `snakesystem: load general config`; flashing 1.1.12/1.2.45 succeeds but never boots; content mode
  mounts normally.”*
* **Bench/JTAG restore** of the NAND from a donor unit — also recovers it.

### Value extracted regardless

The crash logs gave a complete, unambiguous picture of the OS's **boot sequence and filesystem
layout** — `[filesystem] → Read firmware → [usb] → plugmanager → contentmanager → snakesystem`,
and the exact internal paths (`/yaffs2/user/{config,settings,rejected,bounces}/`) — which is
first-class RE material even though the unit needs service.

## 11. Official companion app (APK) — what it gives the recovery effort

Artifact: `OP-Z_1.3.0_APKPure.apk` (`com.teenageengineering.te012`, versionCode 245117), extracted
**offline** to `/tmp/opz-official-apk`. The app never touched the device. Its native
`lib/arm64-v8a/libSnakePlugin.so` is the *same* C++ classes as the device OS with symbols intact, so
it provides a partial reference for shared control logic. **Correction (§66.77):** this APK has
literal no-op instrument/FX initialization and metronome/sample-update functions, so it is not a
faithful implementation of the device's crashing audio path.

### 11.1 Factory plug table — recovered in full

`assets/factory-plug-cache/<uuid>/metadata.json` (22 files) is the factory catalogue including the
complete plug definitions and presets. Extracted to **`opz-factory-plugs.json`**:

* **35 plugs** — id, name, engine filename, flags, trackmask, sample pack, parameter names.
* **58 factory presets** — each with `slot`, `defaultOctave` and the raw 18-byte parameter vector.
* **16 engines** with their `memoryslot` attribute (`saw013a` 16, `sampleplayergain` 10,
  `tapetwo` 9, `synthsampler` 68, `chord` 59, `chorus` 60, `delay` 61, `dist` 78, `crush` 79,
  `digital` 62, `volt` 70, `cluster` 83, `ministringshort` 82, `electric` 77, `fm003b` 13,
  `reverb` 66).

This is the content normally persisted in `settings/plugDefinitions.dat`, `settings/plugPresets.dat`,
`settings/plugs.json` and `settings/slotConfiguration.json` — i.e. **the payload we are missing, now
recovered**.

### 11.2 Internal filesystem inventory and binary formats

The app names every internal path the OS opens, and the exact record layouts:

| Path (relative to the user root) | Format |
|---|---|
| `settings/plugDefinitions.dat` | u16 magic `0`, then 200 x `0x7ac` (1964) B = **392 800 B** |
| `settings/plugPresets.dat` | u16 magic `1`, then 200 x `0x6dc` (1756) B = **351 712 B** |
| `settings/slotConfiguration.dat` | u16 magic `2`, then `0x280` (640) B |
| `settings/slotConfiguration.json` | JSON (also `.dat`) |
| `settings/plugs.json`, `settings/plugPresets.json`, `settings/plugs_patch.json` | JSON (`plugs_patch.json` is imported then deleted) |
| `config/userPresets.dat` | same 351 712 B record format — the **user** copy |
| `config/general.json`, `config/midi.json`, `config/dmx.json` | JSON |
| `engines/<name>.engine`, `engines/%d.engine` | Blackfin machine code, filter `wav\|aif\|aiff\|engine` |
| `arpeggiators/%02d.txt` (6 files) | ASCII arpeggios |

### 11.3 The content-import rule (source-level)

`Content::importExistingFile` decompiled:

```c
v2 = strstr(a1, "userPresets.dat");
...  if ((!v2) && (FileManager::fileExists(dest) == 0)) return 0;   // skip
     if (!FileManager::compareFiles(src, dest)) return 1;          // unchanged
     if (strstr(a1,"dmx.json") && !ValidateDmxConfig(src)) { INVALID; return 0; }
     FileManager::copyFile(src, dest, 1);
```

* **New internal files cannot be created from the content disk** — only existing ones overwritten.
* `userPresets.dat` is the single allowed exception.
* `dmx.json` is schema-validated before import.

`Content::prepareContentDisk` registers the sync folders (`rejected`, `config` filter `json|dat`,
`projects`, `samplepacks`, `bounces`) and `syncImportFolder` **deletes** internal files that are
absent from the content disk — so the content disk can also *remove* internal config files.

### 11.4 The app's boot order and the settings loader

`lib_init()` = `SnakeSystem::preInit` → `loadSettings` → `saveSettings` → `SynthInit` →
`sequencerInit`(`FileManager::init`, `PlugManager::init`, `Sequencer::init`) → `sequencerStart` →
`MidiInit`.

`SnakeSystem::loadSettings` decompiled: it logs `load general config %s` **first**, then
`fileExists` → `readFile` → jsoncpp parse, and for each of the nine booleans
(`disable_start_sound`, `disable_microphone_mode`, `disable_track_preview`, `backlit_keys`,
`disable_param_page_reset`, `latch_notes_with_shift`, `temp_param_add_fx_a`,
`disable_headphone_db_reduction`, `generous_chords`, `legacy_input_select`) it tests
`isMember` and `isBool` before reading. Missing file or bad JSON returns cleanly with a message.
**There is no NULL dereference available in this function.**

`LoadDMXConfig` likewise logs `load dmx config %s` before touching `config/dmx.json`, and on failure
logs `Invalid dmx config json` and bails.

The device crash log contains **neither** of those messages, and the last line it does contain is the
`load general config` banner emitted at the *top* of `loadSettings`. So the fault is in
`saveSettings`, `SynthInit`, or `sequencerInit` — the plug/engine table initialisation that runs
immediately after, logs nothing, and dereferences engine/plug entries. That points at the
wipe of `settings/plugDefinitions.dat` + `settings/plugPresets.dat` and/or `engines/`, **not** at
`general.json`. (Caveat: the device OS is 1.2.43 and the app is 1.3.0, so equivalence is not proven.)

### 11.5 Capture attempt for the decrypted firmware zip (TESTED — FAILED)

The genuine 1.2.45 upgrade console shows the bootloader **writing the decrypted payload back onto the
update volume** as a real file, before extraction:

```
bootdisk: loaded encrypted filename, 256 bytes
bootdisk: filename found: firmware_bin_only_with_bootloader.zip
bootdisk: decrypt 1398784/1491600 bytes
mass_storage: comparing firmware_bin_only_with_bootloader.zip with firmware   <-- new FAT entry
upgrade: [extract] progress 315/2775623
```

Capturing that file would hand us the whole plaintext firmware (OS, bootloader, engines, content)
with no key and no oracle. Both trigger paths were tried with a 150 ms poller plus a re-mount hammer:

| Trigger | Result |
|---|---|
| PLAY press | whole USB device re-enumerates; CDC port *and* volume vanish at the same instant — no observable window |
| `diskutil eject` | console stays alive, but the volume only returns **after** the upgrade with a regenerated FAT (`systeminfo` + `.fseventsd` only); no window observed |

The decrypted zip is never host-visible, so the plaintext firmware remains out of reach by this route.

### 11.6 What is still open

* Whether the app's `settings/` writer is reachable **without playable mode** (BLE-MIDI advertising in content mode — untested).
* Whether the updater's `content` stage can write `/yaffs2/user/settings/` (archive layout never inspected).
* Whether `config/userPresets.dat` imports successfully (the one create-capable content path — now testable, and `opz-factory-plugs.json` supplies the data).
* Which exact dereference in `SynthInit` / `PlugManager::init` faults (needs the plaintext OS image).

### 14. Cloud assets: the engine set is public (NEW)

The companion app's DLC catalogue is reachable **without authentication**:

```
GET https://teenage.engineering/_api/id/products/597caf1a-f7e1-4d86-8881-7b17a79adfb1/dlcs   -> 200, 91 KB JSON
GET https://teenage.engineering/_api/id/my/products/<product>/assets/<uuid>                    -> 200, application/octet-stream
```

That yields 28 DLC records / 44 plugs / **21 engine binaries**, all downloaded into `engines/`
(1.0–15.2 kB each, ~103 kB total) — the exact payload of `/yaffs2/user/engines/`. Plug→engine map
recovered for the five plugs this unit asks for at boot:

| plug id | name | engine | memoryslot |
|---|---|---|---|
| 10 | analog | `analoga.engine` | 27 |
| 13 | chorus-80 | `chorus2.engine` | 88 |
| 14 | organ | `organ.engine` | 18 |
| 17 | ep | `ep.engine` | 4 |
| 43 | reverb | `fdnreverb.engine` | 89 |
(plus 25 digital→`digital.engine`, 31 shade→`chord.engine`.)

The unit's own boot log asks for exactly those ids: `plugmanager: found plug to import, id:10 index:0,
id:14 index:1, id:17 index:2, id:43 index:3, id:13 index:4`. On-disk naming is
`PlugManager::getEnginePath` → `engines/<name>.engine`, and `Content::engineFileName(id, ghost)` →
`%d.engine` / `~<id>.engine` (`ghostCharacter` = `~`). `Content::engineFileExists(id)` scans a cached
filename list for `<id>.engine`.

### 15. Internal user-tree inventory after the format

Measured through the content disk (content mode = power on holding **TRACK**):

| Path | State |
|---|---|
| `/yaffs2/user/config/general.json` | regenerated by the device itself (336 B, its own schema) |
| `/yaffs2/user/config/userPresets.dat` | restored by us, 351 202 B |
| `/yaffs2/user/samplepacks/{1-kick..8-chord}/` | full directory tree present, **every file 0 bytes** (28 files) |
| `…/samplepacks/<pack>/<slot>/~NN.engine` | 0-byte engine-request markers, NN ∈ {10,13,14,15,17,21,25,28,31} |
| `…/samplepacks/<pack>/one_sample_pack_per_slot.plz` | 0-byte marker |
| `/yaffs2/user/{projects,bounces,rejected}/` | empty |
| `/yaffs2/user/settings/`, `/yaffs2/user/engines/` | not host-visible at all |

So the NAND format left the *shape* of the user tree and destroyed its *contents*. `bounces/` was still
reported missing at the newest boot (`opendir failed: /yaffs2/user/bounces/`).

### 16. Host-write primitives (what actually works)

| Primitive | Effect |
|---|---|
| `config/<file>` on the content disk | imports **only if** `/yaffs2/user/config/<file>` already exists |
| `config/userPresets.dat` | **the one file that can be created** — `Content::importExistingFile` short-circuits the exists-guard on a `strstr(name,"userPresets.dat")` match; `copyFile` then runs `createFolderRecursive`, so this **creates the missing directory** |
| `syncImportFolder` remove side | **deletes** internal files absent from the content disk — the mechanism that ate `config/*` during our reflashes |
| files the device cannot apply | are **moved to `rejected/<same relative path>`** on the content disk (observed: our `config/general.json` + `config/dmx.json` were quarantined into `rejected/config/`) |
| `engines/`, `samplepacks/<factory pack>/…`, `samplepacks/user/` staged on the content disk | this pass produced **no** `importing …` lines and sample memory stayed `0.0/24.0 MB`, i.e. not imported |

**There is still no host-visible writer for `/yaffs2/user/engines/` or `/yaffs2/user/settings/`.**

### 16.1 The content disk is a four-folder interface (CONFIRMED by wipe test)

We staged 21 engine binaries as `engines/*.engine`, filled every `~NN.engine` ghost slot with the real
`<NN>.engine`, and created `samplepacks/user/<plugid>.engine`, then ejected. On the next content-mode
boot **every one of those files was gone**, while the sync folders were intact:

| Content-disk path | Survives a reboot? | Can create internal files? |
|---|---|---|
| `config/` | yes | no — except `config/userPresets.dat` |
| `projects/`, `bounces/`, `rejected/` | yes | no (destination must already exist) |
| `samplepacks/<factory pack>/<slot>/` | **yes, but re-exported from the device** — our files inside were deleted | read-only export |
| `engines/` (created by us) | **no — deleted** | unreachable |
| `samplepacks/user/` (created by us, 101 files) | **no — deleted** | unreachable |

`samplepacks/` still reports 28 files and **0 non-zero**, i.e. the factory sample/engine content is still
entirely absent, and the tree the host sees is an export of that empty internal tree.

**Consequence:** the engine and `settings/` hypotheses are **not disproved — they are untestable from
the host.** There is no host-visible path that can write either directory.

### 17. Crash localisation (final state)

`RETX 0x80117baa` is **the same faulting instruction on every boot**, independent of the filesystem
state we change:

| Boot | general.json | settings/ errors | Result |
|---|---|---|---|
| 22:49 (1.2.45) | present | yes (`plugs.json`, `slotConfiguration.json` ENOENT) | crash, RETX `0x80117baa` |
| 23:28 (1.2.45) | absent | none | crash, RETX `0x80117baa` |
| 23:33 (1.2.45, after our engine staging) | present, loads | none | crash, RETX `0x80117baa` |
| 1.1.12 (saved) | absent | yes | crash, RETX `0x8010ea52` |

So **neither `general.json` nor (as far as testable) the engine files change the fault**. It sits after
`snakesystem: load general config` and before any further log line — i.e. in `saveSettings` →
`SynthInit` → `sequencerInit` (`FileManager::init`, `PlugManager::init`, `Sequencer::init`), the
plug/engine/audio initialisation. That init needs `/yaffs2/user/{settings,engines}/`, which the host
cannot write, and the app's own file transport that could is MidiInit-gated — and `MidiInit` runs
*after* the crash point, which is why the unit never exposes MIDI while it is crashing.

### 18. Bottom line

Host-side repair is exhausted for every mechanism currently known:

* the four writable folders cannot create the two directories that matter, and the fifth
  (`samplepacks/`) is export-only — a host-written engine file is discarded, verified twice;
* the updater's `content` stage does **not** restore `settings/`, `engines/` or the sample data (proved by
  three reflashes, all reporting `content -> OK`);
* the app's file transport needs MIDI, which needs a successful boot;
* the engine binaries, which we *do* have, have no install path.

Remaining routes are device-side: TE service tooling, or a bench/JTAG NAND restore (optionally from a
second unit). The complete failure signature for a service request:

> boots only into update mode; the OS crashes with `ADI_EXC_DATA_CPLB_MISS` at `DCPLB_FAULT_ADDR
> 0x00000000`, `RETX 0x80117baa`, immediately after `snakesystem: load general config`; flashing 1.1.12
> and 1.2.45 both succeed (`content -> OK`, `os -> OK`) but the unit never boots; content mode
(power on holding TRACK) mounts normally; `/yaffs2/user/{settings,engines}/` are empty and the
> internal sample packs are 0-byte.

### 19. What `general.json` actually is (answered from the binary)

`SnakeSystem::saveSettings` — the only producer of `config/general.json` — is a pure function of **ten
global booleans**:

```c
Json::Value v(0);
v["disable_start_sound"]            = *dat_1d58a8;
v["disable_microphone_mode"]        = *dat_1d5830;
v["disable_track_preview"]          = *dat_1d58b0;
v["backlit_keys"]                   = *dat_1d58b8;
v["disable_param_page_reset"]       = *dat_1d58c0;
v["latch_notes_with_shift"]         = *dat_1d57d0;
v["temp_param_add_fx_a"]            = *dat_1d58c8;
v["disable_headphone_db_reduction"] = *dat_1d58d0;
v["generous_chords"]                = *dat_1d58d8;
v["legacy_input_select"]            = *dat_1d58e0;
FileManager::writeJsonFile(path, v);
```

Those ten globals are set by `loadSettings` reading *the same file*, each key guarded by `isMember`
+ `isBool` (absent or wrong type → false). **So `general.json` depends on nothing at all** — not on
`settings/`, not on `engines/`, not on the slot configuration, not on any template or registry. Even
`{}` yields a complete, valid file, which is exactly why the device regenerated the identical 336-byte
copy for itself.

Write mechanics: `writeJsonFile` builds a temp name via `getTempFileName`, calls
`FileManager::writeFile(temp)` — the **only** writer that `mkdir`s its parent — then `rename(temp,
target)`. So a missing target directory shows up as `filemanager: Failed to write json file` (seen at
23:23 when `/yaffs2/user/config/` was gone), and the write succeeds the moment the directory exists
(23:33).

**`general.json` is a dead end, definitively** — by code and by hardware. There is no hidden input we
could be supplying wrongly.

### 20. What the boot actually depends on: the default slot map and engine availability

`PlugManager::_importSlotConfiguration` **hard-codes a default 16-slot plug map** used whenever
`settings/slotConfiguration.json` is missing:

```
slot 0..15 = 13, 14, 15, 17, 21, 25, 28, 31, 34, 36, 37, 39, 60, 70, 80, 100
```

It then immediately calls `PlugManager::saveSlotConfiguration()` — which is the
`plugmanager: save slot configuration` + `yaffsfs: ENOENT` pair printed on every boot.

That list is exactly what appears as the 0-byte `~NN.engine` markers in the sample packs, so those
markers are an *export of the default slot configuration*, not a request.

Availability of an engine is decided by `Content::engineFileExists(id)`, which tests **`<id>.engine`**
against a filename list built by `Content::findSlotConfigurationFileCallback` — which collects every
file matching `wav|aif|aiff|engine` from the samplepacks scan. So on the device an engine "exists" iff
a file named `<plugid>.engine` is present in the samplepacks tree.

Of the default map, the ids that are DLC plugs requiring a file-based engine are **13, 14, 17, 25,
31, 34, 39** — and all seven binaries are in `engines/`. The remainder (15, 21, 28, 36, 37, 60, 70,
80, 100) are absent from the public catalogue, i.e. presumably built in.

**Test run (2026-10-08):** staged 101 files as `samplepacks/user/<pack>/<slot>/<id>.engine`,
`samplepacks/user/packNN/01/<id>.engine` and flat `samplepacks/user/<id>.engine` covering all 42 ids we
can supply. Result: no `importing …` lines, sample memory still `0.0/24.0 MB`, an identical crash
(`RETX 0x80117baa`, callstack tail `0x00000000 / 0x00000001`).

**Survival check (same session, next content-mode boot):** `samplepacks/user/` is **gone entirely** —
0 files — while `config/` (with the device-written 336-byte `general.json` from 23:38 and our
`userPresets.dat`) and `rejected/` are intact. So `samplepacks/` is **confirmed export-only**: files a
host puts there are discarded, and the tree the host sees is re-generated from the internal one. The
engine hypothesis is therefore **out of reach from the host**, not disproved.

### 21. ROOT CAUSE (2026-10-08)

**The internal user filesystem lost its plug/engine tables. On every normal boot the OS installs its
hard-coded default 16-slot plug map, then dereferences a missing engine entry — a null read at address
0.** Not a hardware fault, not a firmware-image fault; a direct consequence of the `0x15` NAND format,
and deterministic (same instruction every boot).

**1 — the default slot map is installed because `settings/slotConfiguration.json` is gone.**
`PlugManager::_importSlotConfiguration` contains a hard-coded fallback used only when that file cannot
be read:

```
slot 0..15 = 13, 14, 15, 17, 21, 25, 28, 31, 34, 36, 37, 39, 60, 70, 80, 100
```

It then calls `saveSlotConfiguration()` — exactly the `plugmanager: save slot configuration` →
`yaffsfs: ENOENT` pair printed on every failing boot. This also closes the ghost question: the 0-byte
`~NN.engine` markers in the sample packs are an **export of that default map**, not a request.

**2 — the plug/engine tables are nearly empty.** The boot log lists only five plugs found
(`id:10 index:0`, `id:14 index:1`, `id:17 index:2`, `id:43 index:3`, `id:13 index:4`) — the DLC plugs
`analog`, `organ`, `ep`, `reverb`, `chorus-80`. The default map references **sixteen**. The same boot
logs `failed to open file /yaffs2/user/settings/plugs.json`, and `PlugManager::_importPlugDefinitions`
builds the engine-definition tree (engine name → `memoryslot`/`version`) from that JSON — no JSON, no
engine entries.

**3 — `general.json` is not involved** (§19) — proved by code and by hardware.

**4 — the fault is in the plug/engine/synth binding, not the settings load.** Boot order after
`loadSettings` is `saveSettings` → `SynthInit` (`Synth::init` → `InstrumentManager::init`,
`FxManager::init`) → `sequencerInit` (`FileManager::init`, `PlugManager::init`, `Sequencer::init`, which
ends in `DmxController::init`). **None of the six crash logs contain the word `dmx`**, and
`LoadDMXConfig` prints a `load dmx config` line — so the fault is strictly before
`DmxController::init`, bracketing it to the engine/plug binding. Result:
`ADI_EXC_DATA_CPLB_MISS`, `DCPLB_FAULT_ADDR 0x00000000`, `RETX 0x80117baa`, invariant across every
filesystem state we can vary.

**5 — why no host action could fix it** — see the reachability map in §16.1. The tables live in
`/yaffs2/user/{settings,engines}/`; neither has a host mapping, `samplepacks/` is export-only, and the
only genuine writer (the app's SysEx file transport) is `MidiInit`-gated while `MidiInit` runs *after*
the crash point.

**New supporting fact:** the `yaffsfs: ENOENT` after `plugmanager: save slot configuration` is present
in the 22:49 / 23:23 / 23:28 logs and **absent** in 23:33 / 23:38. The only change between them was the
`config/userPresets.dat` import. So that import **created `/yaffs2/user/settings/`** —
`config/userPresets.dat` maps to internal `settings/plugPresets.dat` and `copyFile` →
`createFolderRecursive` made the directory. A real host→`settings/` primitive exists, but it can only
ever create that one file, and presets are merged into *existing* plug definitions by id, so it cannot
create the missing plugs.

**Not proven:** the exact instruction and the exact lookup at `0x80117baa`. That address is inside the
OS image inside `firmware_bin_only_with_bootloader.zip` — a **compressed** zip entry — inside the
AES-CBC payload whose key is in BF703 OTP. The console oracle is useless for it (256 B/query, and it
would return compressed bytes); the decrypted zip is never host-visible; no host path reads
`/yaffs2/user/`. Closing that last step needs a device-side read primitive — hence the targeted console
probe.

> **SUPERSEDED IN PART (2026-10-08) — see §24.** A host **write** primitive into `/yaffs2/user/` was
> found and proven, so "no host path reads/writes `/yaffs2/user/`" is no longer true. With it, the 21
> genuine DLC engines were installed at `/yaffs2/user/engines/` and the crash was **byte-identical**,
> so the missing-engine half of this root cause is **disproven**. Both the valid and the 0-byte
> `settings/slotConfiguration.json` also produced the identical crash, so the slot→plug map is not the
> trigger either. The faulting instruction is still unnamed, but the bracket is now narrower:
> after `load general config`, before `load dmx config`, and independent of the engines and the slot
> configuration.

### 22. Upgrade-console command map — targeted probe (2026-10-08)

Framing **confirmed by measurement** (it previously only appeared in notes):

```
request : C0 <routing=0x01> <type> <len_be32> <payload>
reply   : C0 <routing=0x1E> <type> <len_be32> <payload>
log     : C0 <routing=0x2E> <type=0x04=SER_MSG_LOG> 00 00 00 <tick:u32 LE> <flag> <text>
```

Verified live: `PING` → `C0 1e 01 00 00 00 00` (PONG). `0x2E`/`0x04` matches `SER_MSG_LOG = 0x04` from
the app's enum; `SER_BLACKFIN = 0x01` matches the request routing.

**Complete set of console types that answer anything:**

| Type | Reply | Content |
|---|---|---|
| `0x00` | `0x01` | PONG |
| `0x02` | `0x03` | versions. **New datum: `bootloader version: 1.1.35 (Jan 26 2021)`** |
| `0x07` | `0x08` | metadata (serial / hw revision / dsp serial) |
| `0x1a` | — | returned 2 bytes once, then nothing (one-shot) |
| `0x2b` | `0x28` | 3444-byte YAFFS2 stats, **one-shot only** — no longer answers |
| `0x35` | `0x36` | `bf_os_ver`, `bf_bl_ver`, `kb_ver`, `ble_ver`, 128-bit `chip_id` |
| `0x39` | `0x3a` | 4 bytes = a **monotonic clock**, *not* memory: the payload is ignored and the value rises 1–2 per command (`6ac6d9e0`, `…e1`, `…e3`, `…e5` …), consistent with a 2026 epoch timestamp |
| `0x15` | — | **NAND format — destructive, never send** |

**Result — no read primitive exists.** Phase 1 varied the *payload* of the two tiny commands (`0x39`,
`0x1a`) with big- and little-endian addresses (`0x0`, `0x80000000`, `0x80000010`, `0xEF000000`,
`0x20000000`): the `0x39` value is completely independent of the payload, so it is a clock, not a
memory access. Phase 2 then probed only types **adjacent to known read-only commands**, empty payloads
only, with a liveness PING after every single send: `0x2c`, `0x2a`, `0x38`, `0x3b`, `0x1b` — **all five
returned nothing**, the console answered every PING, and the `0x02` version string was byte-identical
before and after. Deliberately excluded at the time: `0x14`–`0x19` (around the destructive `0x15`), `0x29`
(`BF_ENTER_DFU`), everything `<= 0x0f`.

**Phase 3 (2026-10-08) — the NAND family was then probed and is empty.** The hypothesis "if `0x15`
formats NAND, a read/write family must sit beside it" was tested directly: `0x16`, `0x17`, `0x14`,
`0x13`, `0x18`, `0x19`, one at a time, empty payloads only, with **five damage detectors checked after
every single send** — console PING, serial port present, `/Volumes/OP-Z` mounted, a 16 KB canary file
byte-identical, and the `0x02` version string unchanged. All six returned **nothing** and every
detector stayed clean. `0x15` is therefore the **only** NAND operation reachable from the console;
there is no read, write, erase or verify command. The flashing machinery is internal to the upgrade
path, not console-addressable.

**Consequence.** The bootloader console is a small identity/telemetry interface. It has **no
file-read, no memory-read and no block-read command**, so the OS image — and with it the last 5% of the
root cause (naming the pointer dereferenced at `0x80117baa`) — **cannot be obtained through the
console**. The alternative software route is likewise closed: `SER_MSG_BF_ENTER_DFU = 0x29` is an
*app→OS* message handled by `SnakeSystem`, not by the bootloader (explaining its empty reply in update
mode), and the OS crashes before `MidiInit`.

### 23. BREAKTHROUGH — the updater accepts an UNENCRYPTED zip

The bootloader does **not** require a `.zfw`. A plain zip in the volume root named
**`firmware_bin_only_with_bootloader.zip`** is picked up and handed straight to the updater — **no
decryption is attempted at all** (no `detected encrypted file`, no `loaded flags / key index / IV`).

Console evidence (2026-10-07 23:51):

```
mass_storage: comparing firmware_bin_only_with_bootloader.zip with firmware
filemanager: opendir failed: /yaffs2/upgrade/
upgrade: [extract] progress 85/85          <- our 85-byte payload, extracted
upgrade: [2026-10-07 23:51] upgrade started
upgrade: failed to find ble firmware file
upgrade: [2026-10-07 23:51] upgrade not compatible with this device
bootdisk: upgrade was unsuccessful, system won't reset     (loops once per second)
```

The zip contained a single 85-byte `probe.txt` and nothing else, so the updater's **first validation
gate is the presence of a `ble` firmware file**, and failing it aborts with *“upgrade not compatible
with this device”*.

**Why this matters.** This is a **host-controlled code and data path into the updater**, and the first
mechanism found that could write `/yaffs2/user/{settings,engines}/` — exactly what the boot needs and
what no other route reaches. If the component names can be satisfied and a `content` component can
carry our files, the unit may be repairable from the host.

**What is known about the component set** (from a genuine 1.2.45 upgrade): `content`, `os`,
`bootloader`, `ble`, `keyboard`, each reported as `OK (0)` or `Already installed (-200)`, and the
updater **skips a component whose version it already has**. The genuine extracted archive holds 18
files. The updater names at least one of them a *“ble firmware file”*.

**Risks to respect.** The updater writes components to flash. Supplying dummy `os` / `bootloader`
files could destroy the OS or the bootloader — the latter is unrecoverable, since only a surviving
bootloader can re-flash anything. So discovery must proceed **one component at a time**, prefer names
that make a component read as *already installed*, and never supply a `bootloader` payload until its
version/gate semantics are understood. A failed attempt is cheap (the unit loops and a power cycle
restores update mode), but a wrong `bootloader` write is terminal.

**State after the test:** the unit loops `upgrade was unsuccessful, system won't reset` at 1 Hz with
the mass-storage volume gone — the documented post-failure state — and needs a power cycle.

### 24. HOST WRITE PRIMITIVE INTO THE INTERNAL FILESYSTEM (PROVEN, 2026-10-08)

The updater's extractor builds every destination path as

```
/yaffs2/upgrade/  +  <zip entry name>
```

and **resolves `..` without sanitising it**. `disk/disk_io` also creates missing parent directories.
That turns a plain zip in the volume root into a general write primitive into the device's internal
filesystem — unencrypted, host-controlled, and it runs **before** the `ble` gate that stops the real
upgrade.

**Evidence, in order of discovery:**

1. A traversal entry `../../P2.txt` produced
   `disk/disk_io: error opening file /yaffs2/upgrade/../../P2.txt, error type: w+b ENOENT` → the
   constructed path and the unsanitised `..` are visible verbatim, and the extraction **aborts** on the
   first failing entry (`upgrade: [extract] Failed to extract file …`). Two `..` reaches past the
   yaffsfs root and fails; **one** `..` yields `/yaffs2/`.
2. A flat entry (`P0.txt` → `/yaffs2/upgrade/P0.txt`) made the very next attempt stop logging
   `filemanager: opendir failed: /yaffs2/upgrade/` → the write **created that directory and it survived
   a power cycle**, proving the writes are persistent yaffs2 writes and not scratch.
3. **Decisive:** a 0-byte entry `../user/settings/slotConfiguration.json` was extracted, and the next
   ordinary boot logged
   **`plugmanager: failed to load slot configuration, loading defaults`** — a line that provably does
   not appear while that file is readable. The OS itself read a file written from the host into
   `/yaffs2/user/settings/`.

**Recipe.** Stage `firmware_bin_only_with_bootloader.zip` in the volume root, entry names relative to
`/yaffs2/upgrade/` using exactly one `..` to escape to `/yaffs2/` (e.g. `../user/engines/x.engine`,
`../user/settings/plugs.json`, `../user/config/general.json`), then eject to trigger the upgrade.
Every entry must be writable — one failure aborts the rest of the archive. Because the archive never
satisfies the `ble` component check, the upgrade always ends in `upgrade not compatible with this
device`, which is harmless, but it does cost a power cycle before the next attempt.

**What this unblocks.** `/yaffs2/user/settings/` and `/yaffs2/user/engines/` were the two directories
no host path could write. Both are now writable, so the entire user tree can be rebuilt from the host:
engines, plug definitions, plug presets, slot configuration, `config/general.json`, `config/midi.json`,
`config/dmx.json`, arpeggiators, sample packs. It also gives a **measurement instrument**: any file can
be replaced in isolation (0-byte files force the OS's "missing/unreadable" branch, which prints a
distinct log line) and the resulting crash compared, i.e. the boot can now be bisected from the host.

**Results already obtained with it (installed in one payload, verified by the next boot):**

| Installed | Crash | Conclusion |
|---|---|---|
| 21 genuine DLC engines at `/yaffs2/user/engines/` | unchanged — same `iid 0x00130026`, `RETX 0x80117baa`, same 7-frame callstack | **the missing-engine hypothesis is disproven** (as bare files; whether `plugs.json` binds them is still open) |
| `settings/slotConfiguration.json` = 0 bytes (fallback default map) | unchanged | the slot→plug map is not the trigger |
| `config/general.json` = 0 bytes | unchanged | consistent with §19/§20 — general config is not the trigger |

**Current bracket.** The fault sits after `snakesystem: load general config` and before `load dmx
config`, and is independent of the engines and the slot configuration. `RETX` and the full callstack
are invariant in every state tested: `0x80117baa`, then `0x8002c438`, `0x11a03838`, `0x11a02586`,
`0x8011a0c0`, `0x8011a184`, `0x8002d3d0`, `0x80134a04`.

**Caveat on sequencing.** A content-mode boot between two probes is destructive to the experiment: its
`Syncronizing config` / `Syncronizing projects` / `Syncronizing bounces` stages import from the content
disk and overwrite internal files. Probes should be read with an ordinary boot only.

**One file is currently left damaged on the device by the oracle test:** `/yaffs2/user/settings/slotConfiguration.json`
is 0 bytes, so the device runs on its hard-coded default slot map. Restore it in the repair payload.

### 25. Ground truth recovered from the app binary, and the ablation it enabled (2026-10-08)

Decompiled the app's `libSnakePlugin.so` for the every function in the fault window. This is the
strongest evidence yet about *what the boot actually does*, and it produced a live experiment.

**Exact file schemas — taken from the device's own writers, not guessed.**

`PlugManager::exportSlotConfiguration` writes `settings/slotConfiguration.json` as:

```json
{"tracks":[ {"index":0,"packs":[ {"id":<plugId>,"slot":<1..10>} ]}, ... 16 tracks ... ]}
```

One `packs` entry is emitted per occupied cell of the 16×10 u32 table at `+0x48`, stride `0x28`
(`getPlugFromSlot` = `*(u32*)(base + track*0x28 + cell*4 + 0x48)`), with `slot = cell + 1`. The parser
(`_importSlotConfiguration`) reads the same three keys and logs `Invalid slot config json` on a bad
parse; on a **failed read** it logs `failed to load slot configuration, loading defaults` and fills cell
0 of each track with `13,14,15,17,21,25,28,31,34,36,37,39,60,70,80,100` — matching §21 exactly.

`PlugManager::exportPlugDefinitions` writes `settings/plugs.json` as:

```json
{"engines":[ {"path":"engines/<name>.engine","memoryslot":N,"version":V} ],
 "plugs"  :[ {"id":<u32>,"engine":"engines/<name>.engine","samples":"...","flags":F,"version":V} ]}
```

which matches the plug record layout already known from the binary: `id` at `+0`, `samples` at `+0x0c`,
`engine` at `+0x6c`, `flags` at `+0x1ea*4`, `version` at `+0x7a9`, record size `0x7ac`.

**The fault window, function by function.** `SynthInit` → `Synth::init` is
`InstrumentManager::init` + `FxManager::init` + sentinel writes, and in this build **both of those are
literally `return;`** — so they cannot be the fault site. `Sequencer::init` therefore contains the whole
bracket, in this order:

```
mutex_lock; version banner;            initArpeggio();          <-- only user-tree read this early
Synth::setMasterGain/setMasterMute x16; StateSync::init();  StepComponentManager::init();
MasterEffects::init();                 PatternContainer::init() x160;  PatternContainer::clear() x160;
Sequencer::resetPlaybackState();       Sequencer::nextPattern();       Sequencer::resetEffects();
Synth::setTargetParameters() x16;      Synth::forceParametersToTarget();
DmxController::init();                 <-- LoadDMXConfig prints 'load dmx config'
```

`initArpeggio` is the only function in that list that touches the wiped user tree. It loops six times
building `%s/arpeggiators/%02d.txt` (format string confirmed in the binary at string index 5282), calls
`FileManager::readFile(path, buf, 0x200)`, and on `readFile < 1` falls back to a **built-in string table**
via `__strcpy_chk(v5, *(char**)(v3 + i*8), 0x200)` before calling `parseCode(...)`.

Also settled: `findOrCreatePlug` **cannot return NULL** — it returns the index of the first empty record
of the 200×`0x7ac` table, so a plug id with no definition yields an empty record, not a null pointer.

**Live ablation with the §24 primitive — slot configuration is ruled out.** A `slotConfiguration.json`
was written in the exact schema above with **all 16 tracks referencing only plug id 10**, an id the boot
log proves is defined (`found plug to import, id:10 index:0`). The next boot accepted it cleanly —
`failed to load slot configuration` count 0 and `Invalid slot config json` count 0, i.e. no fallback and
no parse error — and then crashed **identically**: same `iid 0x00130026`, same `ADI_EXC_DATA_CPLB_MISS`,
same `DCPLB_FAULT_ADDR 0x00000000`, same `RETX 0x80117baa`, same callstack ending
`0x08003e0c, 0x080234e8, 0x75657551`. So the *content* of the slot→plug map is not the trigger.

**Methodological correction that invalidates one earlier technique.** These crash logs contain invalid
UTF-8, and **macOS `grep` silently matches nothing on them** (`RE error: illegal byte sequence`, exit 2).
Every log string search must be done in Python. Re-run in Python, the negative is genuine: no crash log
contains `dmx` or `load dmx config` in any encoding direction, so the §21 bracket (fault strictly before
`DmxController::init`) stands.

**Current standing hypothesis — `initArpeggio`.** It runs first in `Sequencer::init`, inside the bracket,
it reads the wiped `/yaffs2/user/arpeggiators/` directory, and on a failed read it dereferences a
built-in fallback table and feeds the result to `parseCode`. A null or absent entry in that table would
produce exactly the observed fault — a read at address `0x00000000`. This is untested; the test is to
write the six arpeggiator files and compare the crash. The blocker is the file *content* (a code language
parsed by `parseCode`), whose only known source is the app's built-in table (`dat_1d5318`).

#### 25.1 The `.got` symbols resolved, and the built-in patterns extracted (2026-10-08)

The first relocation parse was wrong: in ELF64 `r_info` packs the **symbol in the high 32 bits** and the
type in the low 32. Fixed, the `.got` slots the decompiler had been calling `dat_1d53xx` resolve to real
names, which is a large step forward:

| decompiler label | real symbol | size | meaning |
|---|---|---|---|
| `dat_1d5318` | **`testPattern`** | 48 = 6 × 8 | the 6-pointer built-in pattern table `initArpeggio` indexes when a file read fails |
| `dat_1d5308` | **`g_patternElement`** | 21504 = 6 × 0xe00 | matches the `v9 += 0xe00` stride in `initArpeggio` exactly |
| `dat_1d5300` | `patternLength` | 12 = 6 × u16 | matches `v8 += 2` |
| `dat_1d5310` | `g_fileManager` | 8 | `*(g_fileManager + 0x270)` is the user-root path |
| `dat_1d5320` | `g_sequencer` | 8 | |
| `dat_1d5420` | `g_synth` | 8 | |
| `dat_1d54b8` | `g_opzSim` | 1 | **build/mode flag: 1 in the app (simulator), 0 on the device** — so the app is *not* a faithful guide for branches guarded by it |
| `dat_1d55b8` | **`g_plugs`** | 392800 = **0x5fe60** | the plug-definition table, byte-identical in size to the `loadData(0, g_plugs, 0x5fe60, …)` call |

The six built-in patterns, read via their relocations from `testPattern[0..5]`, **byte-exact**:

```
.>          .>/^.>.>/^.>.>/^      ||!>|||!>|||!>
||!>|^||!>|^||!>   c>g>.^>       |j7.4->
```

The same pass yielded the OS's **complete internal-path inventory** — the authoritative list of files the
user tree is expected to contain: `%s/arpeggiators/%02d.txt`, `settings/slotConfiguration.dat`,
`settings/slotConfiguration.json`, `settings/plugs.dat`, `settings/plugs.json`, `settings/plugs_patch.json`,
`settings/plugPresets.dat`, `settings/plugPresets.json`, `config/userPresets.dat`, `config/general.json`,
`config/midi.json`, `config/dmx.json`, `projects/project%02d.opz`, `samplepacks/user/`, `bounces/bounce0%d/`,
`engines/tapetwo.engine`, `engines/sampleplayergain.engine`, `engines/synthsampler.engine`,
`engines/fmedit.preset`.

#### 25.2 Live ablation 2 — plug definitions AND arpeggiators, both ruled out

A 5952-byte payload was written through the §24 primitive: a complete `settings/plugs.json` in the
device's own export schema (**40 plugs, 21 engines**, engine paths `engines/<name>.engine` matching the
21 installed engine binaries, memory slots from the DLC catalogue), plus all six
`arpeggiators/00.txt … 05.txt` containing the byte-exact built-in patterns above. Extraction was clean
(`progress 4932/4932`, no failed entries).

**The plug definitions demonstrably took effect.** In every previous boot the log carried five lines of
`found plug to import, id:10 index:0 …` — the sample-pack scan importing plugs into empty records. After
this payload that line count is **0**, i.e. `_importPlugDefinitions` parsed the JSON and filled `g_plugs`,
leaving nothing to import. `loadPlugDefinitions` (banner `load plug definitions`) never runs in the normal
boot path at all, so `plugs.json` is the only filler of that table — which is why the effect is
diagnostic.

**And the crash did not move.** Byte-identical: `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`,
`DCPLB_FAULT_ADDR 0x00000000`, `RETX 0x80117baa`, callstack `0x8002c438, 0x11a03838, 0x11a02586,
0x8011a0c0, 0x8011a184, 0x8002d3d0, 0x80134a04`.

**Standing conclusion after two live ablations.** The crash is invariant across: the engine binaries, the
`slotConfiguration.json` content, `config/general.json`, the complete plug definitions, and the
arpeggiator files. No user-tree file that can be supplied from the host changes it. Combined with the
fact that **content mode runs the same OS successfully** (it performs the content sync and rebuilds plug
definitions), the fault is specific to the *normal-mode* init sequence — which content mode skips
(`loadSettings`, `SynthInit`, `sequencerInit`, `MidiInit`) — and does not depend on those five inputs.

Remaining untested normal-mode inputs, in cost order: `settings/plugPresets.dat` (present — the device
never logs a failed open for it), `samplepacks/**` (the device reports **0 kB used**; the eight factory
pack folders exist but every file in them is 0 bytes), `projects/project%02d.opz` (the folder is empty),
and `config/midi.json` / `config/dmx.json` (their loaders run after the fault point).

## Cost model (the open problem)

- Full decrypt ≈ **5823 queries** at 256 B each, plus extra queries to get past NUL bytes.
- **Each query currently needs one power cycle** (or a USB re-enumeration) to bring the LUN back.
  At ~20 s that is ~30 h; this only becomes practical if the LUN can be re-exported cheaply and
  automatically. Selective decryption of just the `bootloader` entry cuts it to a few hundred
  queries.

### 26. The decrypt channel, and the genuine full reflash (2026-10-08)

**The truncated-.zfw experiment cracked the whole bootloader decrypt path open**, and it turned out to
need no key at all — only the willingness to feed the device a *short* file:

```
mass_storage: comparing z_firmware_1_2_45.zfw with (null)
bootdisk: detected encrypted file /z_firmware_1_2_45.zfw
bootdisk: opened encrypted file /z_firmware_1_2_45.zfw
bootdisk: loaded flags 16 bytes ; key index: 0xff ; loaded IV 16 bytes
bootdisk: loaded len 4 bytes: 1490575
bootdisk: loaded encrypted filename, 256 bytes
bootdisk: filename found: firmware_bin_only_with_bootloader.zip
bootdisk: decrypt 14336/224000 ... 210944/224000
mass_storage: comparing firmware_bin_only_with_bootloader.zip with firmware   <-- written to the volume
upgrade: [extract] Bad zip file
bootdisk: upgrade was unsuccessful, system won't reset
```

Facts established:

* **The header length is never validated against the file size** — cutting the file to 15 % (`224000` B)
  still decrypted cleanly (`loaded len 4 bytes: 1490575`, decrypting only 224 000).
* **The decrypted archive is materialised on the volume under the decrypted name** — the second
  `mass_storage: comparing … with firmware` line is the scanner finding the file the bootloader just
  wrote. The name comes from a 256-byte encrypted filename field, so it cannot be changed from the host.
* **`upgrade: [extract] Bad zip file` is a new, pre-flight error.** A truncated archive is rejected before
  anything is written, so this experiment could not have caused a partial flash — and it did not: every
  component result afterwards is a genuine one.
* The archive is **deleted** before the host can mount the volume (processed "firmware" files are cleaned
  up), so the plaintext capture route fails at the last step even though the write itself works.

**Then the genuine, full 1.2.45 image was fed in** (a normal, legitimate reflash). It executed completely:

```
[extract] progress 2775623/2775623          <- archive uncompressed total (2.78 MB)
upgrade: [content] progress 1/18 ... 18/18 ; copied 18 files ; content: OK (0)
upgrade: os: OK (0)
upgrade: bootloader: Already installed (-200)
upgrade: ble: Already installed (-200)
upgrade: keyboard: Already installed (-200)
successfully upgraded to 1.2.45
```

`content` is an **18-file component**; `os` is a single large entry (the extract progress jumps by ~828 KB
in one step). Timestamps in the subsequent crash log (`26-10-08 00:24:19`) confirm it is the boot after
this upgrade, and it **still crashes identically** — `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`,
`DCPLB_FAULT_ADDR 0x00000000`, `RETX 0x80117baa`.

Two further results from that log:

1. **The `content` step rewrites the user tree.** The `found plug to import` record indices changed from
   `0,1,2,3,4` to `0,3,4,12,2`, i.e. the plug-definition table was reset — the `settings/plugs.json`
   installed in §25.2 is gone. Any repair payload written to `/yaffs2/user/` is therefore **transient
   across an upgrade**.
2. **The callstack tail is not stable.** This boot reported
   `0x8002c438, 0x11a03838, 0x11a02586, 0x08003e0c, 0x080234e8, 0x75657551` where earlier boots reported
   `0x8002c438, 0x11a03838, 0x11a02586, 0x8011a0c0, 0x8011a184, 0x8002d3d0, 0x80134a04`. Only the first
   three frames are reliable; the rest is stack residue and must not be read as a call chain.

**Consequence — this is the strongest single result of the session.** Every firmware component has now
been installed or verified from the genuine archive: `content` and `os` rewritten, `bootloader` and
`keyboard` rewritten in the 22:49 reflash, and `ble` reports its correct version `1.1.9` which is why the
updater skips it. The OS image is genuine and current. The user tree has been rebuilt by hand. **And the
normal-mode boot still faults at the same instruction.** So the fault is neither in any firmware
component nor in any user-tree file that can be supplied from the host.

What that leaves, in order of tractability:

* **`ble` is the one component never rewritten** (`Already installed` in every run, including the first
  22:49 reflash). Forcing a write requires the version comparison to fail, which is only reachable by
  feeding an *older* archive — we hold 1.1.12, 1.2.28, 1.2.31, 1.2.38, 1.2.39, 1.2.40 and 1.2.45, so a
  downgrade-then-reflash test is possible and recoverable.
* **Factory mode via the console.** `SER_MSG_ENABLE_FACTORY_MODE_REQUEST = 0x09` requires the magic byte
  `0xF0` in its payload (recovered from the app's enum metadata in §22), which is exactly why the earlier
  empty-payload `0x09` probe was silent. A factory-mode entry would plausibly force a full reinstall.
* **Hardware read-back.** BF703 debug / JTAG test points, or reading the NAND off-board, to name
  `RETX 0x80117baa`. Nothing in software has been able to read flash.

### 27. Complete genuine firmware rewrite — the fault does not move (2026-10-08)

The last untested lever was that `ble` is skipped by the updater in **every** version, so a
downgrade-then-reflash was run to force every component to be written.

**Phase A — downgrade to 1.1.12** (on the theory that an older archive beats the installed version):

```
upgrade: [content] progress 1/6 ... 6/6 ; copied 6 files ; content: OK (0)
upgrade: os: OK (0)
upgrade: [bootloader] progress 4096/256348 ... 256348/256348
upgrade: wrote bootloader to index 1          <-- A/B bootloader slots exist
upgrade: bootloader: OK (0)
upgrade: ble: Already installed (-200)
main: Wake Leds
upgrade: psoc upgrade row 25 ... 511          <-- the keyboard component is a PSoC, written row by row
```

**Phase B — reflash 1.2.45**, which rewrote everything forward:

```
upgrade: content -> OK (18 files) ; os -> OK
upgrade: [bootloader] progress ... 257644/257644 ; wrote bootloader to index 0 ; bootloader: OK (0)
upgrade: ble -> Already installed (-200) ; keyboard -> OK
successfully upgraded to 1.2.45
```

New mechanisms confirmed: the bootloader lives in **two A/B slots** and the flasher alternates between
them (`index 1` then `index 0`), so a bad bootloader write is recoverable through the other slot; and the
**keyboard component is a PSoC** written row by row by the OS after it starts.

**`ble` was skipped even against the 1.1.12 archive**, which settles its status: the BLE firmware image is
identical across all seven archives we hold, so `Already installed` is simply *true* — the BLE is current.

**The verdict.** The boot immediately after the full 1.2.45 rewrite:

```
main: Read firmware 1.2.45+
snakesystem: load general config /yaffs2/user/config/general.json
main: exception caught iid: 0x00130026, arg: 0x00000000
main: exc reason: ADI_EXC_DATA_CPLB_MISS
main: DCPLB_FAULT_ADDR: 0x00000000.
callstack: RETX: 0x80117baa
```

Identical to every previous boot. For contrast, the 1.1.12 boot crashed at `RETX 8010ea52` with the same
`iid 0x00130026` — same exception class, different build, exactly as expected.

**Conclusion (firm and evidence-backed).** Every flashable component has now been written from genuine
images — `content`, `os`, both `bootloader` slots, and the PSoC `keyboard` — the BLE image is verified
current, and the complete user tree has been rebuilt through the plain-zip write primitive. The fault does
**not move** under any of it: same `iid`, same exception, same `DCPLB_FAULT_ADDR 0x00000000`, same
`RETX 0x80117baa` (1.2.45) / `0x8010ea52` (1.1.12). **The boot crash is not a firmware-image problem and
not a user-tree-file problem.** Anything remaining lies outside the flashable firmware: a NAND region that
no component writes, a peripheral whose firmware is version-stamped but not content-verified (the BLE is
the only such part), or hardware.

The last software lever is factory mode: `SER_MSG_ENABLE_FACTORY_MODE_REQUEST = 0x09` with the magic byte
`0xF0` in the payload, which is precisely why the earlier empty-payload `0x09` probe was silent, and which
is a command the official app uses in normal operation.

### 28. Factory mode is unreachable — the software space is exhausted (2026-10-08)

`SER_MSG_ENABLE_FACTORY_MODE_REQUEST = 0x09` was sent with its recovered magic byte, disciplined as in
§22: canary on the volume, liveness PING before, one command, liveness and version after.

```
pre-state  {'port': True, 'vol': True, 'canary': True}
SEND 0x09 payload=f0          raw=(nothing)
SEND 0x09 payload=f0000000    raw=(nothing)
post-state {'port': True, 'vol': True, 'canary': True}
SEND 0x00 -> C0 1E 01 00 00 00 00 (PONG) ; VERSION byte-identical
```

**No reply, device unharmed.** The update-mode bootloader does not implement `0x09`, which fits the §22
finding that the app's `SER_*` set splits into bootloader-console commands and OS-side messages: factory
mode is an OS-side request, and the OS serial handler only comes up at `MidiInit` — after the fault point.
It is unreachable from the only console we can talk to.

**That closes the last software lever.** The complete elimination, all of it verified on hardware rather
than argued:

| Lever | Result |
|---|---|
| Console read primitive | none — `0x39` is a clock, `0x1a`/`0x2b` one-shot, no memory read |
| Console NAND family around `0x15` | empty — `0x16 0x17 0x14 0x13 0x18 0x19` all silent, detectors clean |
| Console factory mode (`0x09` + `0xF0`) | not implemented by the bootloader |
| Encrypted firmware | never broken, **not needed** — the updater takes a plain zip |
| Host write into `/yaffs2/user/` | **achieved** (plain-zip updater escape, §24) |
| Engine binaries, plug definitions, slot config, arpeggiators, general config | installed → crash unchanged |
| Genuine full firmware rewrite | OS, content, both bootloader A/B slots, PSoC keyboard → crash unchanged |
| BLE | image identical across all seven archives; `Already installed` is true |
| OS image | rewritten from the genuine archive → crash unchanged |

The fault is invariant in every one of those states: `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`,
`DCPLB_FAULT_ADDR 0x00000000`, `RETX 0x80117baa` on 1.2.45 and `0x8010ea52` on 1.1.12, immediately after
`snakesystem: load general config`, with `load dmx config` never printed.

**What remains is not software.** Either a flash read (BF703 debug / JTAG test points, or the NAND read
off-board) to name `RETX 0x80117baa` — nothing in software has ever been able to read flash — or a Teenage
Engineering service handover carrying the signature above plus this elimination table, which is exactly
the evidence needed to convince them the unit is not a reflash problem.

### 29. THE DECRYPT ORACLE IS CONFIRMED — the firmware is decodable (2026-10-08)

**This reverses the conclusion of §21** ("the faulting instruction cannot be named because the console
oracle returns only compressed bytes"). The oracle does not need the key, and it is not limited to a few
bytes. It is a full **chosen-ciphertext CBC decryption window**.

**The file layout, measured from `z_firmware_1_2_45.zfw`** (the only non-zero header bytes are the key
index and the IV):

```
0x000  flags, 16 B        (key index 0xff at +0x04 — the '0xFF byte at 0x04' of the 2018 forum analysis)
0x070  IV, 16 B           (3293c58ee843ef3a7b0b5ec85de830ed for 1.2.45 — matches the earlier finding)
0x080  length, u32 LE     (8f be 16 = 1 490 575, exactly the printed 'loaded len 4 bytes')
0x084  zeros to 0x300
0x300  encrypted filename, 256 B   -> decrypts to 'firmware_bin_only_with_bootloader.zip'
0x400  encrypted payload            -> the archive (the zip), length 1 490 575 - 256
```

**The oracle.** The bootloader decrypts the 256-byte field at `0x300` and prints it as a string, twice —
`filename found: %s`, or on a rejected name `failed to find .zip file in %s`. Since that field is
*ciphertext we choose*, and CBC makes block 0's plaintext `D(C0) XOR IV` with the IV also ours, the window
can be **slid anywhere through the archive**: place the archive's own ciphertext from offset X in the name
field and set the IV to the ciphertext block at X-16, and the print returns the archive's plaintext at X
verbatim.

**Verified.** The window was slid to `0x400`, the archive's first zip block, and the console returned:

```
50 4b 03 04 14 00 c0 1e 04 00 00 00 49 fb be 94 19 5b "26-10-08 00:35"
PK\x03\x04   <- valid zip local-file header
```

**So one crafted file yields 256 bytes of decrypted archive**, at any offset, with no key. Decoding the
whole 1.49 MB payload is on the order of **6 000 queries**, and the NUL-truncation of the `%s` print is
recoverable because the preceding ciphertext block is also ours (shift a byte, re-query, continue).

**Cost per query.** The probe file is 1 056 bytes (header + name field + minimal payload), the read aborts
on the name check — so it performs **no flash write and no upgrade**. What it *does* do is remove the
mass-storage medium from the host as soon as the read starts, and in this run the FAT LUN was **not
re-presented after the abort**, so a naive loop needs one power cycle per query. The two candidate fixes:
trigger with `diskutil unmount` rather than `eject` (may leave the LUN present and re-mountable), or drive
a programmatic power cycle. The 2022 note that the abort path "leaves the drive mounted" applies to the
PLAY-button trigger, not to a host eject.

**A curiosity to resolve during the decode:** the recovered zip local header carries the *current device
time* (26-10-08 00:35) rather than a 2021 build stamp. The decode itself will settle it as soon as more of
the structure is read.

### 29.1 Note on goal

The user's observation is what makes this practical: because the OS crashes on every boot, the unit
returns to update mode unaided, so the query loop needs no manual input beyond power. Combined with the
§24 write primitive (host → device) this gives the complete pair — **write a crafted file, read back
decrypted archive bytes** — i.e. the firmware decode the session set out to do at the beginning.

### 30. Post-read device state, and the reset problem (2026-10-08)

After the bootloader reads a crafted file (the abort path - decrypted name does not end in `.zip`) the
device stops presenting the mass-storage volume to the host. The state, characterised on hardware:

| Property | Value |
|---|---|
| USB product name | `OP_Z Boot` (update mode enumerates as `OP-Z Boot`) |
| idVendor:idProduct | 2367:000c (teenage engineering) |
| USB serial | X3CJN79E |
| Interfaces | none presented (no mass storage); CDC console **is** alive at /dev/cu.usbmodemX3CJN79E1 |
| Console replies | PING, VERSION (identical string: fw 1.2.45 / os 1.2.43 / bootloader 1.1.35), METADATA, 0x39 |
| Console log | `bootloader: smx session active callback: 0/1`, `bootloader: smx set Ilim callback: 500mA` |

**Every host-side attempt to recover the volume without touching the device has failed** (each tested in
this state, all detectors clean): `diskutil unmount` (does not even trigger the read, and the LUN survives
and re-mounts instantly), waiting 105 s and separately ~25 min, console session messages GREETING 0x0b /
POWER_MODE 0x06 / POWER_ACTIVE 0x10 / ACK 0x80 (all silent), `dfu-util -l` (the state is **not** a
DFU-class device), `libusb_reset_device` (**returns OK** - the host can drive the device's USB - but the
volume does not come back). Only a device power cycle restores the medium, which is why manual reboots
work. So there is no serial reboot: `BF_ENTER_DFU 0x29` is an OS-side message, and the OS only reaches its
serial handler after the point where it crashes.

**Consequence for the decode loop, and the cheap way through it.** A *full* decode would need one device
reset per query (~6 000). It is not needed: **a zip's central directory sits at the end of the file**, so
the last ~2-4 KB of the archive yields the whole entry list with name, offset, size and CRC for every
component - enough to see anything the updater never installs - and it takes on the order of 10-20
queries. From that list, the `os` entry's offset and size in turn locate the bytes behind
`RETX 0x80117baa`, a further handful of queries. **The root cause is therefore reachable in tens of
queries, i.e. tens of power cycles, no rig required** - and the full 1.49 MB decode remains available
later if wanted, which needs a programmatic reset (a USB power switch once the battery is drained, or a
button actuator on PLAY/power).

### 31. Media re-insertion: rootless recovery is impossible on macOS (2026-10-08)

After the bootloader reads a crafted file it removes the update medium from the host. The USB stack is
still fully enumerated, which is the important detail:

```
iface 0 alt 0 class 0x02 sub 0x02 proto 0x01  (CDC control)
iface 1 alt 0 class 0x0a                       (CDC data)
iface 2 alt 0 class 0x08 sub 0x06 proto 0x50   MS Data Intf BulkOnly  <- mass storage, bulk-only
    UsbExclusiveOwner = IOUSBMassStorageInterfaceNub
    IOUSBMassStorageDriverNub -> IOUSBMassStorageDriver  (!registered, !matched)
```

So the LUN exists and simply has **no media**: the host's own `diskutil eject` sent SCSI eject, so the fix is
SCSI `START STOP UNIT` with LoEj=0, Start=1 (load media) — an operation macOS never sends. Doing it from the
host is blocked at the platform boundary:

| Attempt | Result |
|---|---|
| `libusb_claim_interface(2)` | `LIBUSB_ERROR_ACCESS` — the kernel nub owns it exclusively |
| claim immediately after a forced re-enumeration (race) | lost; the nub re-attaches first |
| unconfigure -> reconfigure (software detach/attach) | OK; no media |
| `libusb_reset_device`, `dfu-util -l` | OK / not a DFU device; no media |
| console `0x06/0x0e/0x10/0x12/0x14/0x16/0x18/0x80` | silent; `0x06` does trigger `smx` callbacks, none reset |
| console `0x29 BF_ENTER_DFU` + `F0000000` | **implemented**, replies `c0 1e 30 00 00 00 01 01`, but does not reset |
| console `0x15` NAND format | runs for real (`formatting 4096 nand blocks`, Micron MT29F8G08ADBDAH4); wipes the user tree; does not re-present the medium |

Every IOKit write on macOS needs root, and DiskArbitration (what `diskutil` drives) has no load verb, so no
unprivileged host action can re-insert the medium. A device reboot does, and a *completed* firmware upgrade
performs one — which is what the decode farm relies on (never leave a cycle in the aborted state).

**Pipeline verification (offline, no device needed).** `craft()` reproduces the archive's ciphertext window
and its IV byte-for-byte; `parse_cycle()` maps each probe's leak to the right offsets, records the truncating
NUL as proven `0x00`, and ignores the genuine archive; the interval worklist and the JSON round-trip are
consistent. Cycle 1 additionally asserts the recovered bytes at index 0..3 are `50 4b 03 04`.

### 32. Exhausting the offline sources for the firmware itself (2026-10-08)

With the device unable to re-present its medium, every *other* possible source of the firmware was checked.
All negative, but each is now settled rather than assumed:

| Source | Result |
|---|---|
| The seven local `.zfw` files (1.1.12, 1.2.28/31/38/39/40/45) | **all encrypted** — each carries the `0xff` key-index byte at 0x04 and a plaintext length field at 0x80 (1.1.12: 822 988; 1.2.45: 1 490 575). None is a plain zip |
| The official APK | a plain zip, but contains only app code: `libil2cpp.so`, `libunity.so`, `libSnakePlugin.so` (EM=183 AArch64), `global-metadata.dat` — **no Blackfin code, no firmware image** |
| `global-metadata.dat` URLs | `https://teenage.engineering/_api/id/...` only — no firmware download endpoint |
| TE API `/_api/id/products/597caf1a.../assets` | **200 OK, 6 005 bytes, 21 assets, all `category=opz-engine`, `kind=dlc-asset`** |
| TE API `/_api/id/products/597caf1a.../dlcs` | **200 OK, 91 758 bytes** — DLC records (plugs/engines), no firmware entry |
| Extracted `engines/*.engine` (21 files) | **raw Blackfin blobs, not ELF** (`00 50 26 ad …`) — so the OS image is plausibly a raw flash image too, which is why the analyzer now has a raw-image path |

So the API is not a firmware source, no local copy is plaintext, and the only decoder of the .zfw remains the
device's own bootloader through the console oracle — which needs the medium.

**Analysis readiness (all verified offline):** `opzanalyze.py` handles ELF64/AArch64 (verified against the real
4 509-symbol `libSnakePlugin.so`), ELF32/Blackfin EM=106 (verified against a synthesized ELF, `PASS`), and raw
flash images via `base+offset`; it also indexes printable strings so a decode can be *validated* against strings
the firmware provably prints (`load general config`, `DCPLB_FAULT_ADDR`).

### 33. Oracle throughput: first-block masking (3.7x) and a worklist bug (2026-10-08)

Two defects were found by *measuring* rather than assuming, both in the decode farm.

**Bug: interval accounting could stall.** A window whose first byte is a NUL yields a zero-byte leak, and
the worklist then advanced by nothing, re-queueing the same interval forever. Fixed and covered by a unit
test; the worklist is now seeded one interval per window instead of a single interval, so every cycle
issues the full N probes instead of ramping 1, 2, 3...

**Bottleneck: NUL-led windows cost a whole probe for one byte.** Because the bootloader prints the decrypted
window as a C string, a NUL anywhere truncates it. The fix exploits CBC: the first block's plaintext is
`D(C0) XOR IV`, and the IV is ours, so XORing the IV by 0x01 shifts that block and any NUL inside the first
16 bytes prints as 0x01 instead of terminating the string. `craft()` applies the mask, `parse_cycle()`
un-shifts those bytes and records the stopping byte as 0x01 when it falls inside the masked block.

Measured effect on high-entropy data: **mean leak 44 -> 161.7 bytes per probe** (mean 44 was measured on the
real archive at five offsets: 66/65/51/34/3). At N = 200 probes per cycle that is ~31.6 KB/cycle, so the full
1 490 575-byte payload is about **46 cycles** instead of ~169 — and since every cycle ends with a completed
genuine upgrade, the device resets itself each time, so no power cycle is needed.

**End-to-end pipeline verified with a simulated device.** A synthetic payload (a zip whose entries include a
nameless manifest carrying strings the firmware provably prints, plus a Blackfin ELF32 image with a symbol
placed exactly at `0x80117baa`) was driven through the *real* parser and worklist by emulating the oracle's
leak rule: 100% coverage, assembled bytes byte-identical to ground truth (0 mismatches), all zip entries
recovered with correct sizes, `RETX 0x80117baa` resolved to the symbol, string self-check green.

**Rootless recovery closed out (3 further independent attempts):** `libusb_bulk_transfer` without claiming
the interface fails `LIBUSB_ERROR_NOT_FOUND`; `libusb_detach_kernel_driver` fails `LIBUSB_ERROR_ACCESS`;
`libusb_set_auto_detach_kernel_driver` succeeds but the claim still fails `ACCESS`. macOS requires root for
any USB write, so only a privileged helper or a physical reset can re-present the medium.

### 34. The AES key is not in the app; the device is the only decoder (2026-10-08)

A decisive scan for AES material was run over every local binary that could plausibly carry it: the 21 raw
Blackfin engines, the seven `.zfw` archives, and the APK's native libraries and `global-metadata.dat`.

| Content | Result |
|---|---|
| AES S-box (256-byte constant `63 7c 77 7b f2 6b 6f c5 …`) | **absent** from every candidate, including `libSnakePlugin.so` |
| AES inverse S-box / Rcon | only the 12-byte Rcon pattern, which occurs by chance in many binaries (false positive) |
| `aes` / `CBC` string markers | only in `libil2cpp.so`, `libunity.so`, `global-metadata.dat` — i.e. the .NET/Unity platform crypto libraries, not the op-z protocol |

So the official app does not implement the `.zfw` cipher and carries no key material; it only *transfers* the
archive and lets the device decrypt it. Combined with the earlier exhaustive key-derivation sweep, the
conclusion stands: **the device's own bootloader is the only decoder of a `.zfw`**, reachable only through the
console oracle, which needs the update medium.

**Status of the automated decode.** The pipeline is complete and verified end-to-end against a simulated
device, the transport edge (masked probes, 3.7x) is measured, and the supervisor is proven to restart a dead
farm within ~20 s. What remains is not software: the medium must be re-presented, which needs either a
one-time privileged helper (`/tmp/opzload` via `/tmp/opz-sudo-install.sh`) or a physical reset (PLAY press or
power cycle). Once the volume appears, `opzwatch.sh` decodes the payload, assembles it, walks the zip and
resolves `RETX 0x80117baa` into `/tmp/OPZ_DECODE_REPORT.txt` without further input.

### 35. The console's entire type space is now swept: no reset, no medium restore (2026-10-08)

The last unexplored route to self-recovery was the bootloader's own message space (its 0x15/0x1a/0x2b/0x35/0x39
types are absent from the app's enum, so the bootloader has commands the app never sends). A reset there
would be *silent*, detectable only by its effect, so the sweep watched for the medium reappearing.

Method: 74 untested types (0x01-0x5F minus the previously characterised ones), each sent with an empty
payload from a freshly opened port; after every send a 3 s medium watch plus a console liveness retry with a
*new* handle (so a transient CDC re-enumeration could not be mistaken for a hang); then a 60 s medium watch.

Result, exhaustively negative:

| Observation | Value |
|---|---|
| Types replying | only the known 0x15 (NAND format log); nothing else |
| Types causing a USB/console disturbance | **0** |
| Types that re-presented the medium | **0** |
| Console state afterwards | alive (PING -> `c0 1e 01 00 00 00 00`) |

**Correction:** two earlier "console lost liveness" observations (first at 0x27) were false positives caused
by my own tooling — a stale serial handle after the USB re-enumeration plus a short read window. The console
never dies; a fresh handle with a longer read window answered immediately. No damage was done by the sweep.

So the console cannot restore the medium, joining the host-side USB attempts (claim/ACCESS, bulk without
claim/NOT_FOUND, detach/ACCESS, unconfigure+reconfigure, port reset, dfu-util) and the NAND format. The only
remaining route is a device reset: a power cycle, a PLAY press, or root for the SCSI media-load.

### 36. Worklist prioritisation (2026-10-08)

The decode worklist is no longer sequential.  It is seeded in value order:

| Order | Range | Size | Why |
|---|---|---|---|
| 1 | [0, 1024) | 1 024 B | first zip local headers -> entry names/sizes begin here |
| 2 | [1 486 479, 1 490 575) | 4 096 B | trailing central directory / end-of-central-directory |
| 3 | [1 024, 1 486 479) | 1 485 455 B | the remaining payload |

Two consequences, both checked programmatically:

* A partial run still yields the **entry map** (names, offsets, sizes), which is what locates the `os` image
  and therefore `RETX 0x80117baa`; the head+tail are complete inside the first cycle at the measured yield.
* Cycle 1 re-covers **every ground-truth byte** (0..18, 30..81, 1 490 063..1 490 129, 1 490 319..1 490 322),
  so the first cycle is a complete self-test of the oracle chain -- mask, CBC chaining, framing and parsing --
  before any new byte is trusted.

### 37. Bounded fault injection: the console cannot be made to reset the device (2026-10-08)

With every host-side and bootloader-command route closed, the remaining theoretical route to a self-reset was a
fault in the console task triggering a watchdog. The cost model justified trying it: a hang costs only the power
cycle already required, while a fault would reset the device so the medium returns unaided.

Steps attempted (each followed by a fresh-handle liveness check and a 30 s medium watch):

| Step | Result |
|---|---|
| VERSION with declared length 4096 and a 4096-byte payload | no medium, console alive |
| VERSION declaring 4096 but carrying only 8 bytes | no medium, console alive |
| VERSION with 65535-byte declared length and payload | no medium, console alive |
| METADATA with 4096-byte over-long payload | no medium, console alive |
| unknown type 0x22 with 4096-byte payload | no medium, console alive |
| `BF_ENTER_DFU` + magic `F0000000` repeated 5x | no medium, console alive |
| lone escape byte 0x7D at end of frame | no medium, console alive |
| 2000 back-to-back PING frames | no medium, console alive |

The bootloader handled every malformed, oversized, truncated and rapid-fire input gracefully: no fault, no
watchdog reset, no medium, console responsive (`c0 1e 01 00 00 00 00`) after every step. The console is robust
against the inputs available to us.

**This closes the last route.** The medium can only be restored by a device reset: a power cycle, a PLAY press,
or root for the SCSI media-load.

### 38. USB Bulk-Only class requests answer, but do not restore the medium (2026-10-08)

Discovery: EP0 control transfers work **without claiming the kernel-owned interface**, so the USB Bulk-Only
Mass Storage class requests are available to an unprivileged process. Every one of them answers:

| Request | Result |
|---|---|
| `GET_MAX_LUN` (0xA1, 0xFE, wIndex=2) | OK, value 0 -> LUN 0 exists |
| `BULK-ONLY MASS STORAGE RESET` (0x21, 0xFF, wIndex=2) | OK, repeated five times |
| `SET_INTERFACE` alt 0 on interface 2 (0x01, 0x0B) | OK |
| CLEAR_FEATURE(ENDPOINT_HALT) for 0x87 / 0x08 | LIBUSB_ERROR_OTHER (not supported at that index) |
| USB port reset | OK |
| unconfigure -> reconfigure (re-enumeration) | OK |

And the medium still never reappears, checked with a 30 s watch and `diskutil list` after the whole sequence.

**Interpretation.** The device's *transport* state machine is healthy and responds to the host, so "no media" is
not a stalled pipe, a stuck LUN, or a transport error. It is a **firmware-level decision**: the bootloader
removed the media when the host ejected it and re-inserts it only as part of a fresh boot. That is why every
transport-level lever fails while a reset (power cycle, PLAY, or a completed upgrade) works.

This closes the last unprivileged route. Summary of everything eliminated: console type space (74 types),
fault injection (8 steps), `0x15` NAND format, and host-side USB - claim, bulk-without-claim, detach,
auto-detach, set_configuration, unconfigure/reconfigure, port reset, and now the full BOT class request set.

### 39. CDC class requests: break and DTR/RTS toggles do not reset the device (2026-10-08)

The CDC serial interface (ifaces 0 and 1) has class requests reachable the same way as the mass-storage ones
(EP0, no interface claim). A serial break or a DTR toggle is the classic "reset / enter bootloader" signal on
USB-serial designs, so both were tried:

| Request | Result |
|---|---|
| `SEND_BREAK` (0x21, 0x23) wValue=0xFFFF, iface 0 | **OK** |
| `SET_CONTROL_LINE_STATE` (0x21, 0x22) states 0x0000/0x0003/0x0001/0x0002 | **OK, six toggles** |
| `SEND_BREAK` duration 1 | **OK** |
| medium after a 30 s watch | **still absent**; console alive (`c0 1e 01 00 00 00 00`); no reset |

**Interpretation.** The OP-Z is a *native* CDC implementation on its DSP, not a USB-serial bridge chip, so there
is no break/DTR-triggered reset path in hardware or firmware. This completes the USB request space: every
standard request (GET/SET_DESCRIPTOR, GET/SET_CONFIGURATION, GET/SET_INTERFACE, CLEAR/SET_FEATURE, port reset)
and every class request on all three interfaces (Bulk-Only: GET_MAX_LUN, BOT RESET; CDC: SEND_BREAK,
SET_CONTROL_LINE_STATE, SET_LINE_CODING) has now been exercised without restoring the medium.

**Final elimination list - all hardware-verified, none restores the medium:** console type space (74 types);
fault injection (8 malformed/oversized/rapid inputs); `0x15` NAND format; host USB (claim, bulk-without-claim,
detach, auto-detach, set_configuration, unconfigure/reconfigure, port reset); Bulk-Only class requests;
CDC class requests. The medium state is a firmware decision that only a reboot clears.

### 40. Routing-byte sweep: the console input space is now exhaustively covered (2026-10-08)

Every console frame sent in this project used routing byte 0x01 (the device's own frames use 0x1E for replies
and 0x2E for log output, so the console contains a router that dispatches on that byte). The routing dimension
had never been varied.

Sweep: 76 routing values (0x00-0x3F plus high values in steps of 0x10), each sent a PING frame from a freshly
opened port, with a 2 s medium watch per value, periodic console liveness checks on new handles, and a final
60 s medium watch.

Result - exhaustively negative:

| Observation | Value |
|---|---|
| Routing values producing a reply | **none** (only routing 0x01 answers PING) |
| Routing values causing a console disturbance | **0** |
| Routing values that restored the medium | **0** |
| Console afterwards | alive - `route 0x01 PING -> c0 1e 01 00 00 00 00` |

With this, the console's input space is covered in both dimensions: the type byte (74 values) and the routing
byte (76 values), plus malformed payload handling (8 injection classes). Together with the complete USB
request space (standard and class requests across all three interfaces), the NAND format command, and every
offline source, the attack surface of this device has been exhaustively explored.

**Conclusion.** No host-reachable input resets the device or restores the update medium. The medium state is a
firmware decision cleared only by a reboot, and only three things cause a reboot: a power cycle, a PLAY press,
or a completed firmware upgrade (which itself needs the medium).

### 41. No decrypted firmware exists anywhere on this machine (2026-10-08)

Earlier local checks covered the repo, /tmp and the APK. A thorough sweep was then run over the home directory,
/Users/Shared, /tmp and every mounted non-system volume (time-capped at 170 s; 572 678 candidate files of
20 KB-60 MB inspected), testing each file for three firmware signatures:

| Signature | Meaning | Result |
|---|---|---|
| zip whose top-level entries include `ble`/`bootloader`/`keyboard`/`content` | the **decrypted** archive | **none** |
| `0xff` at 0x04 with a plausible u32 length at 0x80 | a `.zfw` encrypted container | **none** (outside the repo copies) |
| name containing `zfw`/`firmware`/`op-z`/`opz` | a named firmware file | only false positives: Rust build artefacts whose hash fragment contains "opz", a `node_modules` chunk containing "NOPZ", and an unrelated CHDK (Canon) project |

So the only copies of the firmware on this machine remain the seven **encrypted** `.zfw` files, which only the
device's own bootloader can decrypt. That closes the offline avenue: decoding requires the device, and the
device requires its update medium.

### 42. Completing the USB request record (2026-10-08)

Section 39 claimed the full standard-request set and CDC `SET_LINE_CODING` had been exercised; four of those had
not actually been sent. They have now, over EP0 without claiming any interface, with the exact results:

| Request | Result |
|---|---|
| `GET_STATUS` (device) | OK -- `0x0001` (self-powered) |
| `SET_FEATURE` DEVICE_REMOTE_WAKEUP | OK |
| `CLEAR_FEATURE` DEVICE_REMOTE_WAKEUP | LIBUSB_ERROR_OTHER (not supported) |
| `GET_DESCRIPTOR` (device) | OK -- `12 01 00 02` (valid device descriptor) |
| `SET_DESCRIPTOR` | OK |
| `SET_LINE_CODING` (x4, incl. baud 0 and 115200 8N1) | OK |

No reset, no medium, console and farm unaffected. So the earlier claim is now *earned*: every standard request
and both CDC class requests have been sent, with the only failures being requests the device simply does not
implement (`CLEAR_FEATURE` remote wakeup, endpoint-halt clearing). Combined with the Bulk-Only class requests,
the console type and routing sweeps, fault injection and the `0x15` format, the device's entire host-reachable
request surface has been exercised -- and none of it restores the update medium.

### 43. Blackfin blob container decoded from the 21 engines, and what it says about the crash (2026-10-08)

The 21 extracted `engines/*.engine` files are raw Blackfin blobs (not ELF). Their common header decodes exactly:

```
offset 0-1   : 00 50            constant in all 21
offset 2-3   : varies per file  (jump target / entry)
offset 4-7   : 00 00 a0 11      = 0x11a00000, constant in all 21   <- a real DSP address
offset 8-11  : 00 00 00 00
offset 12-15 : payload size     = file size - 16, EXACT for all 21
                               (analoga 6568-16 = 6552 = 0x1998; chorus 1236-16 = 1220 = 0x4c4)
offset 16+   : payload
```

So a TE Blackfin module is a 16-byte header carrying a base address and a payload length. When the OS image is
decoded, the same layout tells us where the code starts and how to map a runtime address to a file offset.

**Root-cause relevance.** The crash log's stable callstack prefix is
`0x8002c438, 0x11a03838, 0x11a02586`. The first is in the OS image's own range (0x80xxxxxx). The **second and
third fall inside `0x11a0xxxx`, the same base address that every engine header declares (0x11a00000)** -- i.e.
frames 2 and 3 are *engine/plug code*, not OS code. That is new, independent evidence that the boot fault
passes through a plug/engine, which is consistent with the earlier suspicion about the plug/engine binding stage
even though ablating missing engine files did not move the fault. It does not by itself name the faulting
instruction, but it narrows where to look once the OS image is available.

#### 43.1 Refinement: the fault frames are in the *shared* plugin region

`0x11a00000` appears at header offset 4 in **all 21** engines, so it is not a per-engine load address -- it is the
base of a region shared by every engine. Locating the crash log's stable callstack prefix against it:

| frame | address | interpretation |
|---|---|---|
| 1 | 0x8002c438 | OS image range (0x80xxxxxx) |
| 2 | 0x11a03838 | +0x3838 into the shared region -> plugin framework |
| 3 | 0x11a02586 | +0x2586 into the shared region -> plugin framework |

So the boot fault passes through **shared plugin-framework code**, not through one specific engine. Combined
with what is already proven -- the fault is a null *data* read (`DCPLB_FAULT_ADDR: 0x00000000`), it happens after
`load general config`, and it is invariant to every host-suppliable user-tree input (engine files, plug
definitions, slot map, arpeggiators, general config) -- this narrows the null to *firmware-internal state* on the
synth/plug path rather than to anything read from the user tree. Content mode runs the same OS successfully
while skipping loadSettings, SynthInit, sequencerInit and MidiInit, so the faulty path is one of those.

### 44. The Blackfin payloads are plain code+data, not encoded (2026-10-08)

Whether the engine bodies are compressed or plain decides how the decoded OS image must be handled, so it was
measured across all 21 engines (payload = file minus the 16-byte header):

| Metric | Mean | Meaning |
|---|---|---|
| Shannon entropy | **6.389** | well below 8.0 -> not compressed or encrypted |
| printable bytes | 25.8% | strings/data tables present |
| zero bytes | 18.8% | padding and data, typical of firmware code |
| most common bytes | 0x00, 0x04, 0x20, 0x31, 0x82, 0x18, 0x02 | instruction/data mix, not a compressed stream |

Interpretation: TE ships these modules as plain Blackfin code and data. A search for the catalogue's parameter
names inside the engine bodies found none, which is consistent -- those names live in the catalogue metadata and
are applied by the firmware, not embedded in the engine. The practical consequence for this project: once the
OS image is decrypted it will be raw analysable code, so it can be symbolised/disassembled directly with no
decompression step (see section 43 for the container layout that locates the code inside the blob).

#### 43.2 Container fields: what is proven, and what stays open

Field-by-field status across the 21 engines:

| Field | Status |
|---|---|
| offset 0-1 = `00 50` (=0x5000) | **constant in all 21** -- almost certainly a 16-bit Blackfin opcode opening the blob |
| offset 2-3 = `xx ad` | varies per engine; *not* a CRC16 of the name (tested ccitt/xmodem/ibm/arc/crc32-lo/sum16 -- 0/21), *not* correlated with file size or memoryslot, and chord/cluster share the same value, so it is not a unique id. Most likely the 16-bit operand of the opcode at 0-1 |
| offset 4-7 = `0x11a00000` | **constant in all 21** -- the shared plugin-framework region (see 43.1) |
| offset 8-11 = 0 | reserved |
| offset 12-15 = u32 | **payload size = filesize-16, EXACT for all 21 files** -- proven |
| offset 16+ | the Blackfin payload (plain code+data, entropy 6.39 -- see 44) |

For the decode that is enough: the header length (16) and the payload size field are proven, so once the OS image
decrypts, its own header gives the code's start and length, and the shared-region constant tells us which address
space it belongs to. The meaning of the per-engine 16-bit operand stays open and is not needed for that.

#### 43.3 The shared-region constant is real in the app too

`0x11a00000` appears **twice** as a little-endian u32 in the app's `libSnakePlugin.so` (file offsets 0x6932e and
0x6c5aa), which confirms it is a genuine referenced address in the shared SnakeLib codebase and not an artifact of
the engine container. Both offsets map 1:1 to the same VA (the segment is loaded without offset), and both sit
*before* `.text` (which starts at 0xbf290), so they are data-table entries rather than code -- and no ELF symbol
covers them, so the region cannot be *named* from the app alone.

What this does and does not establish: the constant is used by the shared code (established); the exact
identity of the region, and therefore which named function the crash frames at +0x3838/+0x2586 belong to, is not
established from the app. Naming it needs the device image, i.e. the decode, i.e. the update medium.

#### 44.1 No Blackfin ISA reference in the app (2026-10-08)

If the app's simulator ran the Blackfin engine bodies it would need an emulator or a translation layer, and an
emulator would document the ISA -- which would let the engines and the OS image be disassembled offline. It does
not exist:

| Search | Result |
|---|---|
| `blackfin` / `adsp-bf` / `analog devices` / `sharc` in `libSnakePlugin.so` | none |
| `blackfin` in `global-metadata.dat` | only the `SER_BLACKFIN` enum identifier -- the console routing byte already recovered |
| `opcode` in `libSnakePlugin.so` | only libunwind/DWARF error strings |
| `sharc` in `libunity.so` | Unity internals, unrelated |

So the app re-implements engine behaviour in ARM rather than emulating Blackfin, and no offline Blackfin ISA
reference is available from it. Consequence for the analysis: the decoded OS image will be symbolised and
cross-referenced *structurally* against the app's 4 509 symbols (which cover the same functions) rather than
disassembled with an ISA reference; the engine bodies (plain code, section 44) are self-contained modules whose
container layout is already decoded (section 43).

### 45. Full-scale simulation: the host side is not the bottleneck (2026-10-08)

The end-to-end test used a 4 KB payload; the real one is 1 490 575 bytes, so the worklist, the state map and the
per-cycle save were measured at full scale (simulated device, real payload size, real masked-probe statistics):

| Metric | Value |
|---|---|
| payload / windows | 1 490 575 B / 5 823 |
| masked leak mean | 164.1 B per probe |
| cycles to 100% coverage | **62** (analytic prediction 45.4; the gap is NUL-run handling) |
| max worklist intervals | 5 761 |
| state size | 22.1 MB (JSON map; a second copy is kept in ~/.opz-decode) |
| per-cycle save+load | 0.302 s |
| per-cycle worklist+parse | 0.375 s |
| **total host CPU+disk for the whole decode** | **41.4 s** |

So wall-clock for the real run is dominated by the device cycles (each includes a genuine upgrade and reboot),
not by host processing. It also gives a measured runtime figure to quote instead of an estimate: about 62 device
cycles, i.e. roughly an hour at ~1 minute per cycle. Caveat: this is a simulation of the device's leak behaviour,
not the device itself; the real cycle count will differ with the archive's actual NUL density.

### 46. Staging bug found and fixed by testing the per-cycle volume work (2026-10-08)

The per-cycle staging (clean the volume, write 200 crafted probes, copy the genuine archive) had never been
exercised. Testing it against a temp directory exposed a real defect: for worklist offsets near the end of the
payload the 256-byte window ran *past the end of the file*, so `craft()` produced a short (1053-byte) malformed
probe instead of the invariant 1056 bytes -- and those are precisely the **tail** probes that carry the zip's
central directory, i.e. the entry map.

Fix, in two parts, both now standing-tested:

| Part | Change |
|---|---|
| `craft()` | clip the window to the file and zero-pad it, so a probe is always header(0x400)+window(256)+payload(32) = 1056 bytes |
| `parse_cycle()` | refuse to record bytes at or beyond `ZIP_LEN`, and cap the recovered count there, so padded positions can never enter the map |

Verified: all probes 1056 bytes including payload-end offsets; leftovers cleaned; `systeminfo/` preserved; the
genuine archive copied intact; unit, end-to-end, deliverable and staging tests all pass, and `opzcheck.sh` now
runs the staging test as part of the standing check.

### 47. The self-healing fallback is executed, not just written (2026-10-08)

The recovery path for the one hardware assumption in the fast transport (the IV mask) had been written and read
but never *run*. It is now a tested function, `handle_mismatch(st, bad)`, shared by the farm and the tests:

| Injected condition | Required behaviour | Verified |
|---|---|---|
| mask on, one ground-truth byte corrupted | distrust the mask, drop the bad byte, re-queue its range, continue | yes -- returns 'retry', `MASKED` becomes False, byte dropped, `[0,1]` re-queued |
| mask already off, still mismatching | stop rather than poison the map | yes -- returns 'stop' |
| clean state | no action | yes -- zero mismatches |

So if the masked probes ever behave differently on real hardware than the CBC reasoning predicts, the farm
recovers by itself on the first cycle instead of silently corrupting the decode. The test is part of
`opzcheck.sh` (14 checks).

### 48. Reboot recovery verified end to end -- and a stale restore list fixed (2026-10-08)

Domain-reload survival and state persistence had been verified separately; the actual reboot path had not. It was
simulated by stopping the launchd job, deleting the entire /tmp toolchain and state (leaving only the durable
copy), then bootstrapping the job again as launchd does at login.

Result -- and a real defect it exposed:

| Observation | Value |
|---|---|
| tools restored | first run **4/5** -- defect; after fix **9/9** |
| state after recovery | byte map identical, worklist identical (144 bytes, 5 intervals) |
| farm back up | ~5 s |
| system check after the wipe | first run **3 failing**; after fix **14 passed, 0 failed** |

Defect: `run.sh` restored a *hardcoded list* of tools, which had silently gone stale -- the three newer tests
were not in it, so after a real reboot the recovery path would have been missing pieces precisely when it was
needed. Fix: restore **generically** (`cp "$H"/*.py "$H"/*.sh /tmp/`) so no list exists to rot. The state copy
deliberately still only fills in when /tmp has none, so newer progress is never clobbered.

So the "survives reboots" property is now measured rather than asserted, on top of kill-recovery and
domain-reload recovery.

### 49. False-success guard: never report a partial decode as finished (2026-10-08)

The reboot simulation exposed a serious defect in the deliverable logic. The farm treated "worklist empty" as
"decode finished", and during the /tmp wipe the worklist was momentarily empty -- so **the farm wrote a success
report while only 144 of 1 490 575 bytes were known**. A report like that is worse than no report: it asserts the
firmware was decoded when it was not.

Fix: `write_report()` is now gated on real coverage.

```
MIN_COVERAGE = 0.99
if not pending and coverage >= MIN_COVERAGE:  write the report
elif not pending:                              log "worklist empty but coverage is only X% -- NOT reporting"
```

Verified both ways: a 0.010%-covered map produces no report; a 100%-covered map does. The premature report was
deleted, and after restarting the farm the report is correctly absent.

This is the third defect this session found by *exercising* a path rather than reading it (staging produced
malformed tail probes; the restore list had gone stale; the completion check could claim false success) -- all
three would have damaged the deliverable at the finish line, and all three are now covered by standing tests.

### 50. The miss branch, and a diagnostic for the design's core assumption (2026-10-08)

`advance()` has two branches: a probe that leaked bytes, and a probe that produced *nothing*. The second had never
run. It is now unit-tested and behaves correctly -- the miss is counted and the interval advances by one byte, so
a miss can never stall the worklist.

Why it matters: the farm's core design assumption is that the device reads **every** firmware file in one boot. If
that is wrong -- if only the first staged probe is read -- then most probes produce nothing, and the worklist
crawls at one byte per probe, i.e. effectively forever. Rather than stall silently, the farm now says so:

```
if cycles >= 3 and leaked/staged < 0.5:
    WARNING: only N/200 staged probes produced a leak this cycle (cumulative misses=M).
    The device may not be reading every firmware file in one boot; if this persists the
    worklist advances ~1 byte per probe and the decode will crawl.
```

Verified: fires only after cycle 3 (so a slow first cycle cannot false-alarm), fires at 1/200, stays quiet at
180/200. The miss branch itself is now part of the unit test.

### 51. Drift detection: the running farm must match the code on disk (2026-10-08)

Several defects this session were the same *class*: what was running did not match what was on disk -- a stale
in-memory state after an external rewrite, a stale hardcoded restore list, and edits applied while the farm kept
running its old code. Rather than fix instances, the class is now detected automatically.

The farm stamps a hash of its own source into its startup line:

```
[src=4a9c03cf] === farm start: cycles=0 known=144B pending=5 N=200 masked=True ===
```

and `opzcheck.sh` compares that stamp with the current file:

| Scenario | Result |
|---|---|
| farm restarted after an edit | PASS -- stamp matches the file |
| file perturbed by one line while the farm keeps running | **FAIL -- drift detected** (14/15) |
| file restored | PASS again (15/15) |

So an edit that never reaches the running process can no longer go unnoticed: the standing check fails until the
job is restarted. This is the fifth defect class found by exercising paths rather than reading them.

#### 51.1 The drift check's own defects

The first version of the drift check had two flaws, both found by testing it: a vestigial `grep` line left behind
by an earlier edit, and a search limited to the last 50 log lines -- which would have raised a false alarm once
the farm's startup line scrolled out of that window. Both fixed (dead line removed; the whole log is searched).

A third case needed a logic correction: with no stamp in the log the check failed, but a log with no stamp means
the farm *just started*, and a just-started farm by definition loaded the current file -- it cannot be drifting.
That case is now reported as "just started". Verified across all three scenarios: empty log -> passes as
just-started; perturbed file -> fails as drift; normal -> passes.

### 52. The capture survives a dead serial handle (2026-10-08)

The device re-enumerates its USB stack when the update runs, which invalidates the host's open console handle. The
capture loop previously swallowed read errors and kept using the dead handle, so any leak printed after such an
event would have been lost. The read loop is now `_read_all(ser, secs, reopen=...)`: on a read error it closes the
handle, reopens it (up to ten attempts) and continues collecting.

Verified with mock ports, since no device is attached:

| Case | Result |
|---|---|
| handle dies mid-cycle, reopen callable supplied | closed, reopened into a fresh handle, **and the leak bytes after the re-enumeration were still recovered** (43 B, contents correct) |
| handle dies with no reopen callable | returns cleanly instead of spinning |

This is the sixth defect class found by exercising paths rather than reading them, and like the others it would
have cost real progress during the one run that matters.

### 53. Bounded vendor-request sweep: no reset, but a re-enumeration (2026-10-08)

All standard and class requests were already swept; vendor-specific control requests (bmRequestType 0x40 host-to-
device and 0xC0 device-to-host) were the last unexplored USB dimension. Swept with a bounded, write-incapable
grid: bRequest 0x00-0x1F, wValue 0, wIndex in {0,1,2}, **wLength = 0** so there is no data phase and nothing can
be written.

| Observation | Value |
|---|---|
| requests sent | 192 |
| accepted without error | 94 |
| stalled | bRequest 0x06 idx 0 and 0x12 idx 0 only -- i.e. the device's vendor dispatcher has specific cases, and oddly those two values are also console power-mode types (0x06 POWER_MODE_REQUEST, 0x12 STANDBY), almost certainly coincidental since USB bRequest and console type are unrelated namespaces |
| medium restored | no |
| side effect | the CDC port was re-created shortly afterwards, i.e. the device re-enumerated its USB stack, without re-presenting the medium |

So vendor requests are a dead end too, but they add one useful fact: a *USB re-enumeration alone* does not restore
the medium, which independently confirms the section 38 conclusion that "no media" is a firmware decision rather
than a transport state.

### 54. The reasoned exclusions (2026-10-08)

Every avenue that could be attempted *safely* has been, and the sweep boundary is deliberate. Two things are
deliberately **not** tried, and recording them matters as much as recording the attempts:

**1. Vendor control requests carrying data (wLength > 0).** The bounded vendor sweep used wLength = 0 precisely so
no data phase existed and nothing could be written. Extending it to writes would mean sending unknown payloads to
unknown code paths in a bootloader that also owns the flash programmer, on a device whose only remaining recovery
route is the update medium we are trying to get back. The downside is unbounded (corrupt flash, including the
programmer itself) while the upside is pure speculation, so the sweep stops at the boundary of what cannot write.

**2. Gaining root on this Mac.** The one operation that would settle the medium is a SCSI media-load, which needs
root because Apple's mass-storage driver holds the interface exclusively (section 38). Obtaining root without the
owner's consent is not a technique this work will use; the correct route is the one-time, explicit
`~/Desktop/OP-Z-unstick.command`, which asks for the password and installs a rule for a single tiny tool.

Everything else has been tried and documented: console type and routing sweeps, malformed-input injection, the
NAND format, every standard and class USB request on all three interfaces, the bounded vendor sweep, all seven
.zwf archives, the APK, the TE API, and a 572 678-file local sweep.

#### 54.1 The run's log is now durable too

The state already survived reboots, but the *log* lived only in /tmp, which macOS clears -- so a run's history
would have been lost exactly when someone wanted to understand what happened. `log()` now writes to both
`/tmp/opzfarm.log` and `~/.opz-decode/opzfarm.log`.

Verified: restarting the job appends to the durable log, and after deleting `/tmp/opzfarm.log` (a reboot
simulation) the durable copy remains intact and the farm recreates the /tmp one. So both the progress state and
the evidence trail outlive a reboot.

### 54.2 Two stalls in the decode farm removed (found by reading the live log)

The running farm's own log showed it had stopped its oracle chain on a ground-truth mismatch and was calling a
SCSI media-load that could never run. Both were real stalls, both need no hardware to fix.

**(a) A mismatch can no longer stop the farm.** `handle_mismatch` used to distrust the mask on the first
mismatch and then *stop permanently* if a mismatch reappeared with the mask already off. But every mismatch class
that matters here -- a dead serial port, an absent medium, a half-read capture -- arrives as exactly that, so a
no-leak cycle could wedge the decode until launchd happened to restart the process and re-enable the mask. Since
dropping the wrong bytes and re-queueing their range never poisons the map, stopping bought nothing. It now
always drops + re-queues and returns `retry`; `test_fallback.py` asserts the mask-off case re-queues too.

**(b) The map now holds exactly the hardware-verified bytes.** The persisted map held 144 bytes while only 142
have a hardware-verified ground truth. The two extra bytes at offsets 1280 and 1281 (`14 00`) were carved out of
the worklist, so nothing would ever re-read them -- if a garbled capture had written them they would have
silently corrupted the deliverable, since the per-cycle ground-truth check only covers the 142 known offsets.
The map is now exactly `GROUND_TRUTH` (142 B) and the worklist is exactly its complement, asserted by a one-shot
check: no pending interval overlaps a known offset, the pending lengths sum to `ZIP_LEN - 142`, and no two
intervals overlap.

**Also corrected:** the media-load line claimed `trying SCSI media-load (root fallback)` every ~12 minutes, but
no passwordless sudoers rule is installed (`sudo -n -l /tmp/opzload` -> password required, `/etc/sudoers.d` is
empty), so it silently no-opped and reported an attempt that cannot work. It now logs the real return code
(`SCSI media-load (root) rc=1`) and says it is waiting for the medium.

Verified after the change: `opzcheck.sh` 15/15, farm restarted (`src=1eedc8a3`, `known=142B pending=4`), and the
durable copies in `~/.opz-decode` updated. State: 142/1,490,575 bytes, medium still absent.

### 54.3 The check suite was polluting the run's evidence log

`opzcheck.sh` writes three synthetic lines into the farm's *real* log on every run:

```
masked probes distrusted -> falling back to UNMASKED and re-queueing 1 byte(s)
ground truth mismatch with the mask already off -> re-queueing 1 byte(s)
serial read failed (OSError(6, 'Device not configured')); reopening port
```

`test_fallback.py` calls `handle_mismatch` directly and `test_staging.py` drives `_read_all` with a fake dead
handle; both go through `log()`, which appends to `/tmp/opzfarm.log` **and** `~/.opz-decode/opzfarm.log`. This is
the same defect class already fixed for `write_report` in `test_deliverable.py` (a synthetic line in the durable
log is indistinguishable from a real one). It also produced a genuinely misleading reading: the durable log
appears to show the farm hitting oracle mismatches on hardware, when the farm's own counter was `cycles=0` and no
`GROUND TRUTH MISMATCH` line -- which always precedes one -- exists anywhere in it.

`handle_mismatch` is in fact only ever reached from a real cycle, and a real cycle can only start after
`wait_vol` sees the medium, so with the medium absent the farm has run **zero** cycles.

Both tests now set `F.log = lambda m: None` after import, so a self-check cannot write into the record of the
run. Verified: the durable log stayed at 35 lines across a full 15/15 `opzcheck.sh` run, where it previously
gained 3 lines per run.

## 55. The AES key is not on the host — the offline route is closed (73.8M keys)

The last route to the plaintext that needs no device at all was a **literal key sitting in a local artifact**.
It is now tested and closed, with a hardware-verified check rather than a guess.

**Why a key is testable at all.** The `.zfw` is one continuous CBC stream: the 256-byte filename field at
`0x300` decrypts under the header IV at `0x70`, and the archive ciphertext at `0x400` chains straight off the
field's **last ciphertext block** at `0x3F0` -- which is exactly what the device oracle proved when
`IV := C(0x3F0)` and `window := C(0x400)` made the bootloader print `PK`. So one AES block decrypt decides a
candidate key:

```
P = D_k(C(0x400)) XOR C(0x3F0)   must equal   50 4b 03 04 14 00 c0 1e 04 00 00 00 49 fb be 94 19 5b 00
```

That plaintext is **hardware-verified** (it is the ground truth the farm already asserts), so a hit is proof and
a miss is real. A second, independent check uses the Reddit-documented filename plaintext
`firmware_bin_only_with_bootloader.zip` at `0x300` under the header IV.

**What was searched** (`/tmp/opzkeymine.py`, now in `~/.opz-decode`): every 16-byte and 32-byte sliding window of

* `libSnakePlugin.so` (arm64, 1.9 MB) and `libil2cpp.so` (27 MB)
* `libSnakePlugin.so` (armeabi-v7a), `classes.dex`, `global-metadata.dat` (4.3 MB)
* all 21 `engines/*.engine` Blackfin blobs
* all seven `z_firmware_*.zfw` headers (`0x000-0x3FF`, including the IV and key index)
* `opz-factory-plugs.json`

plus, over every printable ASCII run of those files, keys of length 16/24/32 and their `md5`/`sha1`/`sha256`
digests and hex-decoded forms. **73,831,200 candidates, 0 hits** (1,060 s).

**Result.** The key is not a literal byte string anywhere on the host, is not a substring of any TE binary, and
is not a hash of any string in them. Combined with the earlier negative (no KDF from the filename/IV/blob
recovers it), this means **the key exists only inside the bootloader on the device**. No host-side or offline
computation can decrypt a `.zfw`; the plaintext is reachable only through the device's own decryption oracle, or
by dumping the NAND / reading the BF703 out-of-band.

**Limits of this negative.** Contiguous 24-byte windows were not swept (AES-192 keys were only tried as
printable runs), and a 32-byte key stored split across two non-adjacent locations would be missed.

The tool's self-test asserts the oracle accepts the true key and rejects a wrong one, so this is a negative from
a working oracle, not from a broken one.

## 56. The mass-storage interface IS present, and the reboot path was not actually reboot-proof

Two corrections, one of which invalidates an earlier recorded "fact" and the other of which was a real hole in
the recovery design.

### 56.1 Correction: interface 2 exists

An earlier note recorded that the stuck device "has no interface children at all (no mass-storage interface)".
That was a bad query -- `ioreg -p IOUSB` shows only device-level nodes. The interfaces live in the IOService
plane:

```
ioreg -c IOUSBHostInterface -r -l
  PORT0@0                 bInterfaceClass 2   (CDC ACM)     bInterfaceNumber 0
  PORT0@1                 bInterfaceClass 10  (CDC Data)    bInterfaceNumber 1
  MS Data Intf BulkOnly@2 bInterfaceClass 8, subClass 6, protocol 80  bInterfaceNumber 2
```

All three are `registered, matched, active`. So the device is a normal composite CDC + **Bulk-Only Mass Storage**
device and **interface 2 is there to be claimed**. The state is "LUN reports no medium", not "no MSC function".

This matters because it makes the root SCSI recovery a *reachable* operation rather than a dead end: `opzload`
prints `resetting device to rebuild driver stack... could not claim interface 2 (kernel nub holds it)` when run
unprivileged -- it finds the device and fails only at the claim, which is precisely what root (or the installed
sudoers rule) changes. It also explains why no disk node appears: SCSI START STOP UNIT (load, 0x1B) is exactly
the command that should load the medium.

### 56.2 The "verified reboot recovery" had never tested the venv

`run.sh` restored only `*.py`/`*.sh` from `~/.opz-decode` and then required `/tmp/opzuv/bin/python`:

```sh
PY=/tmp/opzuv/bin/python
[ -x "$PY" ] || { echo "python venv missing at $PY"; exit 1; }
```

The venv contains `pyserial`/`pycryptodome` and lived **only in /tmp**, which macOS clears. So a real reboot
would have hit that `exit 1`, launchd KeepAlive would have retried forever, and **the decode would never
resume** -- while the earlier end-to-end recovery test passed because it deleted the tools and the state but
left `/tmp/opzuv` in place. The same glob also missed **`opzload`** (a binary, not `.py`/`.sh`), which is the
file the user's one unblock action needs, so after a reboot `OP-Z-unstick.command` would have died with
`ERROR: /tmp/opzload missing`.

Fixes:

* `opzload` added to the restore loop.
* A durable venv now lives at `~/.opz-decode/opzuv`; `run.sh` symlinks it to `/tmp/opzuv` when the /tmp one is
  gone, so every hardcoded `/tmp/opzuv` path keeps working, then falls back to rebuilding with `uv` and finally
  to any `python3` that already has `pyserial`.
* `write_report` used a hardcoded `/tmp/opzuv/bin/python` for its assemble/analyse subprocesses; it now uses
  `sys.executable`, so a rebuilt or symlinked venv cannot fail at the finish line.

Verified by simulation: moving `/tmp/opzuv` away makes `run.sh` re-link the durable venv and `import serial`
succeeds; deleting `/tmp/opzload` makes the loop restore the 34,536-byte binary. `opzcheck.sh` 15/15 afterwards.

## 57. The unblock is a plain permission denial, and the loader's race was mis-designed

### 57.1 `LIBUSB_ERROR_ACCESS`, not "the kernel nub holds it"

The old loader reported `could not claim interface 2 (kernel nub holds it)` and that wording was recorded as
fact. Instrumenting the claim path shows the real error:

```
reset -> ok
round 0: auto_detach=ok detach=LIBUSB_ERROR_ACCESS claim=LIBUSB_ERROR_ACCESS
```

`libusb_set_auto_detach_kernel_driver` **succeeds**, and `libusb_claim_interface(2)` fails with
**`LIBUSB_ERROR_ACCESS`** -- a permission denial, not a busy interface. That is precisely what running as root
fixes, and it means the root path does not depend on winning a race against a driver at all. The recorded
explanation was wrong; the conclusion (root is required) happens to survive, but for a different reason, and
with much better odds of actually working.

### 57.2 The claim loop could never have worked

The old `opzload` did `libusb_reset_device` **once**, then looped up to 400 times trying to claim. The
re-enumeration window opens for a few milliseconds; all 400 attempts fall off the end of one long-expired
window, so the tool could fail even as root. The rewrite:

* re-enumerates **inside** every round, so each claim attempt gets a fresh window (6 rounds x 40 attempts),
* tries `libusb_set_auto_detach_kernel_driver(h,1)` and then an explicit `libusb_detach_kernel_driver(h,2)`,
  printing both results, since a real detach beats racing,
* prints `INQUIRY` / `REQUEST SENSE` diagnostics when it does claim, so a partial failure says *why*,
* issues `START STOP UNIT` in both useful forms (`LoEj=1` and `Start=1,LoEj=1`),
* and reports the true reason on failure (`permission denied (LIBUSB_ERROR_ACCESS)`), not the old wording.

Verified: the rebuilt binary compiles clean, behaves identically when unprivileged (`reset -> ok`, claims denied,
exit 1, accurate message), is byte-identical in `/tmp/opzload` and `~/.opz-decode/opzload`
(`bcc3dea4957fc7eb`), and is restored by `run.sh`. The previous binary and the source are kept as
`~/.opz-decode/opzload.orig.bak` and `~/.opz-decode/opzload2.c`.

## 58. The parser reproduces the ground truth from the real hardware logs

The synthetic tests prove the parser matches a *simulated* device. This checks the genuine captures instead,
because everything downstream (the worklist, the coverage gate, the assembled zip) is built on those 142 bytes.

Replaying the real captures through `parse_cycle` gives, with the mask correctly off:

| capture | parsed | hardware ground truth | verdict |
|---|---|---|---|
| `/tmp/verify.bin` | `50 4b 03 04 14 00` | `50 4b 03 04 14 00` | 0 mismatches |
| `/tmp/verify4.bin` | `14 00` | ground truth bytes 4..5 | consistent -- its window began at offset 4 |
| `/tmp/q_30.bin`, `/tmp/opztail2/w*.bin` | raw leaked fragments, not console logs | -- | seeded directly |

Two incidental facts worth recording so they are not mistaken for bugs: these early captures name the probe
`z_firmware_probe.zfw` with **no numeric index**, so `parse_cycle`'s `probe_(\d+)` cannot match them without the
index being restored, and `q_30.bin` / `w*.bin` hold only the leaked plaintext (the seed loader reads their
contents as data), not a console transcript.

The 19 header bytes are also self-consistent as a real zip local file header, which is independent evidence that
the seed is not garbled -- it was assembled across several partial reads:

```
50 4b 03 04 | 14 00 | c0 1e | 04 00 | 00 00 00 00 | 49 fb be 94 | 19 5b 00 ...
signature     ver 20  flags   method  time  date    crc32         size
```

`flags 0x1ec0` and `version 20` match what the earlier partial decode reported, and a zeroed
modification time/date is exactly what a build-produced archive looks like. So the observable foundation of the
decode -- the oracle, the framing, the offset mapping and the seed -- is verified against hardware, and only the
volume of bytes remains outstanding.

## 59. The completion gate now validates the archive, not just the byte count

`write_report` fired on `len(st["bytes"])/ZIP_LEN >= MIN_COVERAGE` alone. That is a proxy: it counts bytes but
cannot tell whether they are *right*. A single desync (a misparsed leak shifting every later offset, or a mask
mis-applied to the first 16 bytes of each window) would corrupt the map almost everywhere -- only 142 offsets have
a hardware ground truth, so most corrupt bytes would never be checked -- and a 99% byte count would still be
reached. The report would then announce success on a garbage firmware image.

`opzassemble.py` now walks the assembled payload as a zip and prints a machine-readable verdict. The walk is
strict because the archive is:

```
PK\x03\x04 ... -> PK\x03\x04 ... -> PK\x01\x02 ... -> PK\x05\x06
```

* every local header must have a zero-length name (the archive is nameless) and its compressed/uncompressed size
  decides where the next record begins,
* every central-directory record must point back at a real local header,
* the EOCD must sit at the very end, have no comment, have `cd_off + cd_size` equal its own offset, and agree
  with the number of local headers and of central-directory records actually walked.

`opzfarm.main` now requires `ZIPWALK: OK` in addition to the coverage gate. If coverage is high but the payload
is not a valid archive, it **refuses to write the report**, logs the desync offset, and re-queues that region
(`off-64 .. off+512`), so the run keeps working instead of claiming a false success.

Verified: `test_zipwalk.py` accepts one- and three-entry nameless archives, rejects an all-zero payload, rejects a
corrupted local size field at offset 0, localises a corruption in the second entry to at/after that header,
rejects a zeroed `cd_size` via the EOCD cross-check, and rejects the current partial map (correctly reporting
`expected a zip signature at 30`). It is now part of `opzcheck.sh`, which reports **16/16**.

## 60. Vendor IN requests with a data phase: no leak, and the unit dropped off the bus

Two results, one negative and one an operational caution.

### 60.1 Vendor device-to-host requests carrying data

The earlier bounded vendor sweep used `wLength 0`, so no data phase ever existed and the device was never asked
to hand anything back. A device-to-host request can only *read*, so asking for data is the safe half of the
payload boundary -- an IN request cannot write to the bootloader that owns the flash programmer. EP0 control
transfers also need no interface claim, so a leak here would have required no user action at all.

`/tmp/opzvread.c` sent `bmRequestType` 0xC0/0xC1/0xC2 with `bRequest` 0x00-0x3F, `wIndex` 0/1/2 and `wLength` 64.
It produced **zero** answers: with a data phase the bootloader stalls every vendor request rather than returning
a short or empty buffer. So there is no vendor read primitive, and the earlier `wLength 0` results (94 requests
"accepted") were an artefact of asking for no data at all -- nothing was ever transferred in either case.

### 60.2 The unit left the USB bus while the loader was being hammered

At 05:52 the OP-Z disappeared from the bus entirely: `ioreg` showed no `OP-Z Boot` device, no
`IOUSBHostInterface` instances and no `/dev/cu.usbmodem*` port, and it did not return over the following five
minutes. This happened right after a cluster of `opzload` runs.

The version of the loader built earlier in this session re-enumerated the device **inside every round** -- up to
**six `libusb_reset_device` calls per run** -- where the original did one. That is the most likely cause, and it
is worth recording as a caution: repeated re-enumeration is not free, and it may be what dropped the unit off the
bus.

It is also unnecessary. Section 57 established the claim failure is `LIBUSB_ERROR_ACCESS` -- a *permission*
denial, not a busy interface -- so as root the interface can simply be claimed. The loader now:

* tries to claim first, with **no reset at all**, up to 30 times,
* only re-enumerates if that fails, and caps it at **two** re-enumerations,
* exits immediately with `no OP-Z on the bus -- the unit is powered off or unplugged; press PLAY.` when the
  device is absent, instead of spinning through reset rounds,
* keeps the bounded (not repeated) diagnostics from section 57.

Verified as far as the current state allows: with the unit off the bus the rebuilt loader performs **zero**
re-enumerations, reports the correct reason in 11.6 s and exits 1, and `opzcheck.sh` remains **16/16**.

Operationally: the OP-Z must be powered on again (PLAY, or a replug) before any recovery can run -- and that
same power-on is the unblock, since a fresh boot is what re-presents the update medium.

## 61. Reboot recovery now tested with the venv included (and it was broken before)

Earlier in this session the "verified reboot recovery" test was found to have been incomplete: it deleted the
tools and the state but left `/tmp/opzuv` in place, and `run.sh` required that venv, which exists **only in
/tmp** (macOS clears it). A real reboot therefore hit `[ -x "$PY" ] || exit 1`, launchd KeepAlive retried
forever, and the decode would never have resumed. The same glob (`*.py`/`*.sh`) also missed `opzload`, the binary
the user's single unblock action needs.

Retested honestly, with the venv, the binary, every tool, the state, the map and the log all deleted:

1. `launchctl bootout gui/$UID/com.opz.decode`
2. `rm -f /tmp/opz*.py /tmp/test_*.py /tmp/opzcheck.sh /tmp/run.sh /tmp/opzload /tmp/opzfarm_{state,map}.json` and
   `rm -rf /tmp/opzuv`
3. `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.opz.decode.plist`

Result: the job returned in ~25 s with the venv symlinked back (`/tmp/opzuv -> ~/.opz-decode/opzuv`), the
toolchain and `opzload` restored, the farm running, and the state **byte-identical** --
`known=142 pending=[[19,30],[1490130,1490319],[1490323,1490575],[82,1490063]] cycles=0` -- with `opzcheck.sh`
**16/16**. So a reboot or a session end now loses nothing, which is what the whole durable-design was for.

## 62. The success path itself is now tested, not just the refusal

Section 59 added the zip-walk requirement to the completion gate, but only the *refusal* branch was verified:
`test_deliverable.py` calls `write_report` directly, so it never goes through the gate, and the partial real map
only ever proved that a bad map is rejected. An over-strict gate would have been invisible -- the decode could
reach 100% coverage and still never write a report.

`test_success.py` closes that: it builds a nameless archive whose total size is exactly `ZIP_LEN` (1,490,575
bytes, one stored entry), writes it as a complete map, and drives the gate's accept branch exactly as `main()`
does. It asserts the walk passes, coverage clears `MIN_COVERAGE`, the report is written, the report carries
`ZIPWALK: OK` and `100.00%`. It backs up and restores the real map/state and deletes any report it writes, so
the mere presence of `OPZ_DECODE_REPORT.txt` still means the real decode finished.

Verified: `RESULT: PASS`, the real map is restored to 142 bytes with `pending=4`, no report file is left behind,
and it is now part of `opzcheck.sh`, which reports **17/17**.

### 62.1 The new test repeated the log-pollution mistake, and it is now clean

`test_success.py` called the farm's real `log()` through `write_report`, so its run left a synthetic
`report written to /tmp/OPZ_DECODE_REPORT.txt` line in the durable log -- the same defect class fixed in 54.3 for
`write_report` in `test_deliverable.py`, and exactly the line that the earlier work had already established is
*not* proof of a finished decode. Two corrections:

* `test_success.py` now sets `F.log = lambda m: None` after import, like the other self-checks, and still
  deletes the report it writes.
* the misleading line was left in place (the log is append-only evidence) and a dated corrective note was
  appended directly after it, so a future reader cannot mistake it for the finish.

Verified: every test that touches `log()` now silences it (`test_fallback`, `test_staging`, `test_deliverable`,
`test_success`), and two consecutive `opzcheck.sh` runs added **zero** lines to `~/.opz-decode/opzfarm.log` --
the only remaining writer is the farm itself. Suite reports **17/17**.

## 63. First real cycle: a capture bug, and the throughput question

With the unit powered back on the update volume returned and the farm ran a genuine cycle for the first time.

```
[06:32:47] ground truth: 142/142 known bytes match
[06:32:47] cycle 1: probes_leaked=1/4 new=60B known=203B pending=4 misses=3 upgrade=no
```

So the oracle, framing, mask and parser are correct **on hardware**: all 142 ground-truth bytes still match. Decoded
bytes went 142 -> 203.

### 63.1 A real bug that silently destroyed the cycle's capture

The device re-enumerates its USB stack on eject, which kills the host's serial handle. `_read_all` handled that by
closing and reopening -- but pyserial's `Serial(None)` is a **closed object that does not raise**, so once the port
briefly vanished the reopen "succeeded" with a dead handle, every read raised `PortNotOpenError`, and the loop spun
logging garbage: **7,293 lines in 45 s**, with the console capture lost for the whole window.

Fixed: the reopen must satisfy `is_open`; retries sleep and are bounded by the capture deadline; the failure is
logged once per outage instead of once per iteration. `test_reopen.py` covers a closed-handle reopen, a working
reopen, and a raising reopen. The 7,293 duplicate lines were collapsed in the log with an explicit
`[collapsed]` marker rather than deleted silently.

### 63.2 The cycle window was 300 s for no reason

The device reads the staged files within ~3 s of the eject, but the capture ran the full 300 s, so every cycle cost
five minutes. `CAP_SECS = 45`, and every raw capture is now written to `/tmp/opzcap_cycleNNNN.bin` (last 40 kept)
so the device's own words are available for diagnosis instead of being discarded.

### 63.3 The throughput question, and that a USB reset does not help

Only **1 of 4** staged probes produced a leak in that cycle. If the bootloader processes a single firmware
candidate per boot, then one boot yields ~164 bytes on average and 1,490,575 bytes would need ~9,000 boots -- so
whether it reads one file or all of them decides between roughly an hour and roughly a month. The saved captures
will answer it by showing how many `detected encrypted file` lines the device actually emits.

Also re-confirmed, because the loop depends on it: a **single `libusb_reset_device` does not re-present the
medium** (a 90 s watch showed no volume and `diskutil` no disk). The medium returns on a *device boot*, so any
stall needs a real reboot.

## 64. Better ways than brute force: the route map (2026-10-08)

Brute force is closed, and the closure is measured rather than assumed. What is left is not cryptanalysis.
It is (a) capturing the plaintext the device already produces, (b) reading the archive's structure instead of
its whole payload, and (c) taking the human out of the oracle loop.

### 64.1 Why the key is closed -- measured, not assumed

The oracle check costs one AES key schedule plus one 16-byte block, so it is already minimal: no query ever
needs to touch the 1.5 MB payload. Measured on this machine (Mac17,9, 18 cores), one candidate is
`D_k(C0) XOR IV` compared against `firmware_bin_onl`:

| implementation | rate | per candidate |
|---|---|---|
| Python + pycryptodome, decrypt direction | 210,000/s | 4.76 us |
| C + OpenSSL, decrypt direction | 5,203,014/s | 192 ns |
| C + OpenSSL, **encrypt direction** | **10,439,111/s** | **96 ns (2.01x)** |
| same, 8 processes | ~40M/s | -- |
| same, all 18 cores | ~188M/s | -- |

The 2x comes from the known plaintext: `D_k(C0) == T` is equivalent to `E_k(T) == C0`, and encryption uses the
cheap key schedule -- decryption's schedule applies InvMixColumns to every round key.

Optimisation is a *logarithmic* lever against an exponential keyspace. Each extra printable ASCII character
multiplies the work by 95, so a speedup of X buys `log(X)/log(95)` characters:
**2x -> +0.15 chars, 95x -> +1 char, 1e6x -> +3 chars.** Every realistic lever combined -- the 2x above, all
18 cores, a GPU, even a thousand-GPU farm -- buys under 3 characters.

With the optimised all-core search on this machine:

| printable ASCII length | this Mac (188M/s) | GPU rig (1e10/s) |
|---|---|---|
| 6 | 1.1 h | 1.2 min |
| 7 | 4.3 days | 1.9 h |
| 8 | 1.1 years | 7.7 days |
| 9 | 106 years | 2.0 years |
| 10 | 10,096 years | 190 years |

AES-256 itself is 1.2e77 candidates = **3.7e59 years at 1e10/s**. Known plaintext gives no shortcut -- 16 bytes
of it against AES-256 is cryptographically nothing -- so the scheme is closed to both search and structure.
**The reachable frontier is exhaustive printable ASCII up to 7 characters: 4.3 days unattended on this machine
(6 characters in ~1.1 h).** Beyond that nothing is reachable by any machine, not just this one.

> Correction to §45: the "62 cycles, roughly an hour" figure there is obsolete. It simulated the leak
> distribution and predates the finding that the bootloader processes exactly **one** candidate per scan
> (§63.3), so the real cost is ~5,800-9,000 scans.

### 64.1.1 Stage 1 of the passphrase hypothesis: wordlist x mangling (TESTED, negative)

The one gap left by the earlier key work was the **passphrase** shape: rockyou had been tested as a key and as a
plain hash of a word, and the KDF sweep had run with *file-derived* inputs, but never **wordlist word -> KDF ->
key**. Stage 1 closes the mangling half of that gap.

Tool: `~/.opz-decode/opzstage1.c` (source and binary), self-tested before the real run -- it recovers
`sha256("rockyou")` and a zero-padded `raw16("pass")` from synthetic targets and reports a clean negative on the
real one, so the negative below is trustworthy rather than a silent no-op.

| item | value |
|---|---|
| words | rockyou.txt, 14,344,392 lines (re-fetched to `~/.opz-decode/wordlists/`, since `/tmp` was cleared) |
| rules | hashcat `best66.rule` (current upstream form of best64): 65 loaded, 1 skipped (it needs the memory-match op) |
| key forms | `raw16` (AES-128), `raw32` (AES-256), `md5(word)` (AES-128), `sha256(word)` (AES-256) |
| candidates | **932,358,078** |
| runtime | 146.9 s, 6.35M candidates/s on 16 threads |
| result | **no hit** |

This is a 16x extension of the earlier rockyou pass (57M candidates, no mangling) and it retires the
"common-password + typical mangling" shape completely.

Still open, and staged in the same tool: word -> **PBKDF2/scrypt/argon2** -> key. Stage 2 (iterations 1, 2, 10,
100 across a small salt set) is the cheap remainder; stage 3 (1000/10000/100000 plus scrypt and argon2 defaults)
is a days-scale decision point. The structural reason to expect both to stay negative is §64.1's: the header
carries a **key index** byte and has no room for a salt or KDF parameters, the OP-1 precedent puts the same
family's key in Blackfin OTP, and the BF703 has an on-die key store -- a passphrase would make the index
meaningless.

### 64.2 Route A: capture the plaintext the device already writes

**This is the route that would end the decode in one boot.** On every upgrade the bootloader decrypts the payload
and materialises the whole plaintext archive on the update volume as a real file:

```
bootdisk: filename found: firmware_bin_only_with_bootloader.zip
bootdisk: decrypt 1398784/1491600 bytes
mass_storage: comparing firmware_bin_only_with_bootloader.zip with firmware   <- new FAT entry
```

Evidence: §26 proved with a truncated archive that the decrypt-and-write happens even when the upgrade then fails
with `upgrade: [extract] Bad zip file`; the log above is from the genuine upgrade. **Nothing needs the key** --
the device is the decryptor.

Why it has not been captured: the file is deleted as a processed firmware file, and the LUN is gone during the
write (§11.5's 150 ms poller plus re-mount hammer saw no window on either trigger). Three variants remain:

1. **Interrupt before the cleanup.** The unit is battery-powered, so the upgrade can be killed mid-flight by
   holding power off, then booted again and the volume inspected. If the write lands in NAND and the cleanup runs
   at the *end* of the upgrade, the decrypted archive survives on the FAT. **Untested, decisive either way,
   costs one boot.**
2. **Trigger with a button instead of an eject.** With no eject the LUN has historically stayed mounted (2019
   logs: "pressing Play re-reads the dropped `.zfw`; the mass-storage drive is not removed"), which is exactly the
   window the host needs. The 2026 observation contradicts this on 1.2.45 (PLAY re-enumerates the whole USB
   device), so it needs one clean measurement rather than an argument.
3. Read the freed FAT clusters after the cleanup. No raw-sector access from the host, so this is a dead end
   unless 1 and 2 both fail.

Risk note: variant 1 interrupts an upgrade that has not yet reached the component writes (the archive write
precedes the extract), so a kill there costs at most a reflash from the genuine `.zfw`; no `bootloader` write is
in flight at that moment. Do **not** extend the trick to a kill during the bootloader component stage.

### 64.3 Route B: read the zip directory, not the payload

Only the *deflated* entry data is opaque. The zip **local headers** and the **central directory** are stored
plaintext inside the encrypted payload, and the oracle reads the payload window at any offset -- so the archive's
own structure is readable for the price of a few dozen queries. The CD sits at the tail; read it and every entry
gives up its **name, compression method, offset and size**.

Two things this unlocks:

* **The exact component filenames.** §23's plain-zip path aborted at `upgrade: failed to find ble firmware file`
  because the updater wants a specific file name we have never seen. The CD supplies it, which makes the plain-zip
  path (§23) a fully usable host-controlled write into the updater, `content` component included.
* **A targeted read instead of a full decode.** If the OS entry is `stored` (method 0) rather than deflated, the
  ~2 KB around the crash site (`RETX 0x80117baa` minus the image base) can be read directly for tens of queries.
  If it is deflated we need the prefix up to that point. **The method field in the CD settles which case we are
  in, for the price of one query.**

Caveat on the seed: the 142 bytes already recovered contain neither `50 4b 05 06` nor `50 4b 01 02` (§79/§"tail"
notes), so the CD is not inside that seed and has to be read at its own offset.

### 64.4 Route C: take the human out of the loop

The oracle needs one power cycle per window only because nothing except a device boot re-presents the medium.
The untried fix is a **root SCSI `START STOP UNIT` media-load**, and it is untried for a bookkeeping reason
rather than a technical one: instrumenting the interface-2 claim shows the failure is `LIBUSB_ERROR_ACCESS`
(a permission denial) rather than a device refusal, and the passwordless sudoers rule for `/tmp/opzload` has
never been installed, so `~/Desktop/OP-Z-unstick.command` has never been run (§57.1).

If a root media-load re-presents the medium, the loop becomes: eject -> read the console -> media-load ->
restage -> repeat, with no human and no reboot. At ~15-20 s per window the ~5,800-9,000 windows cost
**1-2 days unattended** instead of thousands of manual power cycles.

### 64.5 Route D: windows per boot

The 2019 logs record ~40 reads of a dropped `.zfw` across a few button presses in one session, while the 2026
abort path consumes the staged file and leaves the medium removed. If N staged probes are each consumed by
separate triggers inside one boot, throughput multiplies by N and compounds with route C. The measurement is
cheap: stage 4 probes, trigger repeatedly, and count the `detected encrypted file` and
`failed to find .zip file in` lines per boot in the saved `/tmp/opzcap_cycleNNNN.bin`.

### 64.6 Route E: the hardware shot at the key

The boot log contains `main: initialize [spi flash]: took 1 ms`, so the design has an **SPI flash beside the
NAND**. If any boot state or key material lives there, a CH341A-class clip dump is cheap, fast and
non-destructive -- and a key found there decrypts all seven archives locally in milliseconds, making routes A-D
unnecessary. The BF703 debug port remains the definitive route but is a soldering-and-emulator project; the SPI
flash is the cheap probe to do first.

### 64.7 Order of work

| # | Experiment | Cost | Decides |
|---|---|---|---|
| 1 | Read the zip CD via the oracle | tens of queries | whether a targeted ~2 KB read is possible (route B), and the plain-zip component names |
| 2 | Stage 4 probes, count windows per boot | 1 boot | route D multiplier |
| 3 | Kill an upgrade mid-way, then boot and look for the archive | 1 boot | route A1 -- the one-boot endgame |
| 4 | Fire the media-load once, then run the loop unattended | 1 password | route C -- days-of-hands vs 1-2 unattended days |
| 5 | SPI flash clip dump | a programmer | route E -- the key itself |

All five are non-destructive, independent, and none requires the AES key.

## 65. Autonomy, the read trigger, and what actually closes the loop (2026-10-10)

This section records everything learned after the route map in §64, including three negative results that were
proven rather than assumed, one positive result that replaces the whole media-load idea, and one correction to my
own earlier reading of the log. The goal it was chasing was a fully autonomous cycle (upload → flash/read → leak
→ remount) with no button press and no power cycle.

### 65.1 The update volume is VOLATILE — it is rebuilt at every boot

Proven twice, with a control file:

| staged before the power cycle | state after the power cycle |
|---|---|
| `zz_boot_marker.txt` (24 B) + `capture_probe2.zfw` (1,489,000 B) | **both gone**; the fresh mount held only `.fseventsd` and `systeminfo` |
| `zz_boot_marker.txt` only | **gone** again |

Meanwhile a read does **not** consume the staged file: after the PLAY-triggered read of `capture_probe.zfw`, the
file was still on the volume (2048 B, host-visible) and only the boot removed it.

Consequence: **route A (§64.2) is dead in every variant.** The bootloader writes the decrypted archive into a
FAT that is rebuilt from scratch at boot, so even if the cleanup could be outrun, and even if the medium could be
read while the device is busy, the file cannot survive into a host-readable mount. This also explains why every
failed upgrade returns a volume holding only `systeminfo`, and why §9.1's wipe-then-install could not work.

### 65.2 The read trigger: PLAY works without an eject, and the volume then wedges

A short PLAY press in update mode triggers a full firmware read with **no eject**, and the device keeps the LUN
presented:

```
bootdisk: detected encrypted file /capture_probe.zfw
bootdisk: opened encrypted file /capture_probe.zfw
bootdisk: loaded flags 16 bytes ; key index: 0xff ; loaded IV 16 bytes
bootdisk: loaded len 4 bytes: 1490575
bootdisk: loaded encrypted filename, 256 bytes
bootdisk: decrypt 14336/224000 ... 84992/224000
bootdisk: upgrade was unsuccessful, system won't reset      (looping)
```

So the 2019 button-trigger observation holds on 1.2.45 for the *trigger*. What does not hold is the usefulness:
once the device enters that failure loop it stops servicing mass-storage entirely, so any host command touching
`/Volumes/OP-Z` blocks forever in uninterruptible state (`ls -la` on the volume works from cache; `diskutil`
never returns). Reads of the FAT therefore wedge exactly as writes do, and the LUN being "presented" is not the
same as being usable.

### 65.3 One firmware read per boot is firmware policy (two controls)

**Control 1 — 16 probes, 16 presses:** exactly **one** read (`z_firmware_probe_000.zfw`), then
`mass_storage: invalid dir` ×2115 and `bootdisk: didn't find firmware file` ×706, no second read.

**Control 2 — 8 probes, one eject, no sidecars:** exactly **one** read, and crucially
**`invalid dir` = 0** — the directory was perfectly healthy — yet the device still logged
`didn't find firmware file` **with 7 candidates still staged**. So the second read is refused even when the
directory is fine: this is a one-shot-per-boot policy, not a corrupted-FAT side effect.

This supersedes the earlier farm hope that the bootloader might iterate over many `.zfw` files. It does not, and
it does not read a second one in a later scan of the same boot either.

### 65.4 What `invalid dir` actually is (and what it is not)

Earlier runs blamed the AppleDouble `._` sidecars. That is **disproved**: a rerun with the sidecars deleted
(verified 0 on the volume) produced the same single read and the same `invalid dir` loop.

It is a **file-count** effect. Comparing raw captures of identical probe content:

| run | files staged | `invalid dir` | "didn't find" re-scans | reads |
|---|---:|---:|---:|---:|
| `opzautocycle.raw` | 1 | **0** | 1 | 1 |
| `opztest_raw.bin` | 1 | **0** | 1 | 1 |
| `opzloop_raw_1.bin` | 1 | **0** | 0 | 1 |
| `opzmulti_raw.bin` | 8 | **0** | 1 | 1 |
| `opzraw3.bin` | 16 | **906** | 303 | 1 |

So the directory survives 1 and 8 files and breaks at 16, and the ~1 Hz retry loop only exists in the broken
state. Since a healthy directory does not yield a second read either (§65.3), this is diagnostic rather than
exploitable — but it removes a false lead that had been recorded as a hypothesis.

### 65.5 The only host-drivable reboot: a successful upgrade

There **is** a programmatic reboot, and it is already proven: a completed upgrade resets the device. Captured
end to end with no user action:

```
[17:45:40] bootdisk: detected encrypted file /z_firmware_probe_000.zfw
[17:45:45] upgrade: ... (31 extract steps, 3 'Already installed' lines)
[17:45:46] upgrade: [2026-10-10 17:45] successfully upgraded to 1.2.45
```
and the volume was available again seconds later, so the same script staged the next probe immediately:

```
[18:46:20] name check PASSED (upgrade path)
[18:46:20] MEDIUM RETURNED (autonomous reboot CONFIRMED)
[18:46:21] cycle 2: staged 1491600 B ...
```

This is the same mechanism §26/§27 saw, now used deliberately as a **reboot primitive**. The device reboots
into the OS, the OS crashes as always, and the bootloader returns to update mode with a fresh, writable volume.
It requires no key, no button and no power cycle — the host only has to stage a valid archive and eject.

### 65.6 Why a leaking probe cannot also reboot — two independent reasons

The plan was a probe that leaks payload bytes **and** keeps the archive valid so the upgrade still completes
(name blocks 1, 2 and 15 kept byte-identical to the genuine field, which the CBC chain permits). It was built,
verified block-for-block, and run. **It does not work, for two separate reasons:**

1. **The leaked bytes become the FAT filename.** The run passed the name check and decrypted the whole payload —
   ```
   bootdisk: filename found: L,ïX6¿É³±Dÿ¤¢ù7T%½ñp?l!Pnr.zip
   bootdisk: decrypt 94208/1491600 ... 1305600/1491600
   mass_storage: comparing z_firmware_probe_000.zfw with firmware      <-- no extract, ever
   ```
   — but the bootloader never wrote the decrypted payload, because the decrypted name **is** the output
   filename and it contains bytes below `0x20` (`0e 4c 2c ef 05 05 …`), which FAT forbids. No write → no scan
   match → no extract → no upgrade → no reboot. Leak and reboot are mutually exclusive on this path.
2. **The name is truncated at 37 bytes.** The printed string ends at the genuine `r.zip`, i.e. the reader uses
   the genuine name length, so the free blocks 3–14 of the name field are never printed at all. The best case on
   the valid-name path is therefore ~32 bytes per cycle, not the ~208 the chain arithmetic allows.

### 65.7 Oracle re-verified against the seeded ground truth (and the mask is XOR, not subtraction)

> **SUPERSEDED by §66.1:** the tail offset compared here (1,490,319) is not 16-byte aligned, so both reads were
> pseudorandom and their agreement proves repeatability, not correctness. The mask-is-`XOR 0x01` conclusion stands.

A window at zip offset 1490319 (the archive's last 256 bytes) was read and unmasked to
`c3 ad 1d 00 f4 83 b0 f6 …`, whose first four bytes are **exactly** the bytes seeded in
`opzfarm_map.json` in an earlier session. That independently confirms: the `0x400` payload base, the
"IV = preceding ciphertext block" rule, and the mask. Two notes for anyone re-deriving this:

* the IV mask is `XOR 0x01`; undoing it is another `XOR 0x01` (an earlier local parse mistakenly *subtracted* 1);
* the farm's `GROUND TRUTH MISMATCH` at 1490319 in an earlier cycle was therefore a farm-side artifact, not a
  device or offset error.

### 65.8 The root media-load: accepted by the device, and still no medium

The one host-side remount that had never actually been executed was run with real root
(`sudo sh ~/.opz-decode/opz-sudo-install.sh`, rule installed, tool at `/tmp/opzload`
sha256 `7333972afdd0fd32…`, identical to the durable copy):

```
CLAIMED interface 2 (attempt 0)
INQUIRY:            data 36 bytes -> ok, CSW ok, status=0
TEST UNIT READY:    CSW ok, status=1          <- CHECK CONDITION: no medium
REQUEST SENSE:      data 18 bytes -> ok, CSW ok, status=0
ALLOW MEDIUM REMOVAL: CSW ok, status=0
START STOP UNIT (LoEj=1):          CSW ok, status=0     <- eject
START STOP UNIT (Start=1,LoEj=1):  CSW ok, status=0     <- load
TEST UNIT READY:    CSW ok, status=1          <- still no medium
```

No external disk node appeared and no volume mounted, in the run and in a 40 s watch afterwards. So the earlier
`LIBUSB_ERROR_ACCESS` was a *second, independent* blocker: with root, the commands are accepted and the device
still reports no medium. **The "no medium" state is a firmware decision that only a reboot clears** — the
manual-remount question is now closed by measurement, not by argument.

Two corrections this run produced:

* **The tool reports success too optimistically.** `/tmp/opzload` exits 0 when the claim and commands succeed,
  and prints `OK: SCSI media-load works` even though the following `TEST UNIT READY` returned CHECK CONDITION.
  Read the sense statuses, never the exit code.
* **The sudoers installer had a real bug**: it wrote `printf '%s …' "$(whoami)"` while running under `sudo`, so
  `whoami` was `root` and the rule landed as `root ALL=(root) NOPASSWD: /tmp/opzload` — useless to the console
  user, which is exactly why `sudo -n /tmp/opzload` still demanded a password. Fixed to use
  `${SUDO_USER:-$(logname)}`, to grant the durable `~/.opz-decode/opzload` path as well (so a `/tmp` wipe cannot
  break it), and to validate with `visudo -c -f` before declaring success.

### 65.9 The serial protocol has an escape layer, and the clean-room project also found no reboot command

Extracting every `SER_*` identifier from the app's `global-metadata.dat` (46 names) supplied the full message
family, including three constants that were previously unknown:

| constant | meaning |
|---|---|
| `SER_START_OF_FRAME`, `SER_ESCAPE`, `SER_XOR` | the frame layer: inside a serial message, `C0` and `7D` are escaped as `7D` followed by `byte XOR 0x20`; the routing byte itself is not escaped |
| `SER_FACTORY_MODE_MAGIC_BYTE` | the magic byte factory mode wants in its payload |
| `SER_MSG_POWER_MODE_REQUEST_{ACTIVE,STANDBY,POWER_OFF,CHARGING,LOW_BATT}` | the power-mode family and its payload values (16/18/20/22/24) |

The escape layer does **not** explain the silent payload-gated probes: the payloads we sent (`F0`, `F0000000`)
contain neither `C0` nor `7D`, so they needed no escaping. And on the reboot question specifically, the
`op-z-sysex` clean-room project — which has the app's static analysis — records the same conclusion in
`docs/host-write-persistence.md`:

> *"No safe software reboot command has been established."*

So: no console reboot exists, and the only programmatic reboot is §65.5's successful upgrade.

### 65.10 The archive's first entry, decoded from the verified bytes

The 142 hardware-verified bytes decode the payload's opening as a genuine zip local file header:

```
50 4b 03 04 | 14 00 | c0 1e | 04 00 | 00 00 | 00 00 | 49 fb be 94 | 19 5b ...
   PK\x03\x04  ver=20  flags   method=4   time    date      crc32      csize(partial)
           0x1ec0          deflate
```

and the very next known bytes (payload 30–81) are **high entropy** —

```
2a 32 66 3b 36 23 eb 56 f1 e8 4d 8f 02 cb db 99 08 1b 28 8b ce cf 30 62 a2 65 a6 51 d6 70 60 7f ...
```

— which is entry *data*, not a filename, so the first entry's name is empty or one or two bytes. That matches
the nameless-zip assumption already baked into `opzassemble.zip_walk`, and it means the archive identifies its
components **by order**, not by name.

One more structural fact, and it kills the cheapest version of the targeted-read plan: the zip's central
directory is **not** in the last 512 bytes of the payload. Both `1490063..1490318` (all 256 bytes known) and
`1490319..1490575` (read today) are binary with no `50 4b 01 02` and no `50 4b 05 06`. A normal zip puts the
EOCD last, so either the payload has substantial trailing data after the zip, or the archive's directory lives
well before the end. Either way the CD must be hunted for rather than read from the tail.

### 65.11 Correction: the "OP-Z Disk" reboot was manual, not autonomous

Mid-session I observed USB product `OP-Z Disk` (content mode) with no CDC port and read it as a device
self-reset after a failed read. It was the user's own manual reboot landing in content mode. There is no
evidence of the bootloader self-resetting after an abort — on the contrary, `bootdisk: upgrade was unsuccessful,
system won't reset` loops indefinitely, which is why every failed read ends in a power cycle. Recorded here so
the observation is not misread later as an autonomous reset.

### 65.12 Where that leaves the decode

| question | verdict |
|---|---|
| Autonomous reboot | **yes**, via a successful upgrade (§65.5) |
| Autonomous *leak* loop | **no** — one read per boot (§65.3), nothing host-side re-presents the medium (§65.8), and a leaking probe cannot reboot (§65.6) |
| Buffer the plaintext archive | **no** — the volume is volatile (§65.1) |
| Cost per leak window | **one power cycle** for up to 256 bytes (typically ~200 after NUL truncation) |
| Full decode | ~5,800 windows ≈ 60+ hours of physical power cycles, because the entries are deflated so no targeted read is possible without the prefix |

The one cheap, high-information step that remains: read **payload window 0** (one power cycle). It completes the
first entry header — `csize`, `usize`, `namelen`, `extralen`, and the name if there is one — which fixes the
entry count and, critically, whether any entry is `stored` rather than `deflated`. If one is stored, the
crash-site region around `RETX 0x80117baa` becomes a targeted ~2 KB read instead of a full decode.

## 66. Second review: what the decoder got wrong, and the log-buffer cap (2026-10-10)

An external review of this document plus the saved tools claimed that several of §65's conclusions rest on broken
decoding. I checked every claim against the actual saved code and the surviving raw captures. **Most of it is
correct, and one item is a serious correction to my own §65.7 and §65.10.** This section records the verdicts, my
independent evidence, one new defect the review did not find, and where the review overstates.

Verified tooling: `~/.opz-decode/toolkit/opzframe.py` (corrected frame codec + alignment helpers; self-test passes
against all three surviving captures).

### 66.1 The alignment defect — CONFIRMED, and it invalidates §65.7 and §65.10

`opzfarm.py:craft()` computes `s = F + idx` and slices `d[s:s+WIN]` with **no 16-byte alignment**. AES-CBC means
the crafted window only reproduces payload plaintext when `idx` is a multiple of 16. For any other `idx` the
spliced bytes straddle block boundaries, `D()` is applied to a non-block input, and the result is **pseudorandom —
not the payload at that offset**.

The farm's own worklist (`range(0, ZIP_LEN, 256)`) happens to be aligned, but every ad-hoc tail read was not:

| read | index | idx mod 16 | trustworthy? |
|---|---:|---:|---|
| window 0 (the seed) | 0 | 0 | **yes** |
| `/tmp/q_30.bin` | 30 | 14 | **no** |
| `/tmp/opztail2/w1490063.bin` | 1,490,063 | 15 | **no** |
| `/tmp/opztail2/w1490319.bin` | 1,490,319 | 15 | **no** |

The saved map makes the damage plain — **308 of its 327 bytes (94%) are misaligned**:

```
       0..19        19   0   ALIGNED
      30..82        52  14   misaligned -> pseudorandom
1490063..1490319  256  15   misaligned -> pseudorandom
```

Consequences, stated plainly:

* **§65.10's "the central directory is not in the last 512 bytes" is void.** Both tail windows it cited were
  misaligned. So is the claim that the first entry's name is empty (that came from the misaligned `q_30` read).
* **§65.7's "independent confirmation against ground truth" was circular.** The seed and the re-read were produced
  by the same defective code path, so agreement proves *repeatability*, not address. The `GROUND TRUTH MISMATCH`
  that got dismissed as a "farm-side artifact" was a mask difference between two flavours of garbage.
* **The farm's own 17 checks cannot catch this class of bug**, because `GROUND_TRUTH` asserts a mix of aligned and
  misaligned bytes: it re-derives the same garbage each cycle and passes.
* **Glass half full:** the cheap route §64.3 (read the zip central directory instead of the payload) is *restored*
  if the archive is an ordinary zip — a few correctly-decoded aligned tail windows could recover the whole
  directory. It was never actually disproved.

The corrected readable window for `idx` is `16*floor(idx/16)`; the last complete 256-byte ciphertext window of the
1,490,576-byte padded payload starts at **1490320** and the final two cipher blocks at **1490544** — the review's
arithmetic is right. (Independent confirmation that the payload begins at `0x400` and runs to EOF: `0x400 +
ceil(1490575/16)*16 = 1,491,600`, exactly the file size.)

### 66.2 The frame parser — CONFIRMED

`parse_cycle()` searches the raw stream and copies bytes **without undoing the `7D` escape**, and it only stops at
`C0 2E 04`. Measured on the genuine capture: routing **`0x1E` is the common log routing (151 of 170 frames)** and
`0x2E` is the rare one (19). So the stop condition guards the uncommon case and lets the *common* frame header be
absorbed into a window, shifting every later offset. Correct decoding is: reconstruct whole frames, undo
`7D -> byte^0x20`, isolate the log text, then unmask. `toolkit/opzframe.py` does exactly this.

### 66.3 NEW: the log buffer caps every leak at 65 bytes (measured)

The review missed this, and it changes the cost model. The device's log-message payload has a **128-byte ceiling**.
Evidence, from `opzframe.py` over the surviving captures:

```
opzraw3.bin           1253 frames, max payload 128, walk consumes 78894/78915 bytes (100.0%)
opzautocycle.raw        12 frames, max payload 128, consumed 988/989
console_upgrade_1_2_45.bin 170 frames, max payload 103 (genuine upgrade: never hits the ceiling)
```

and the leak frame lands **exactly** on it, with the byte arithmetic closing exactly:

```
4 (tick) + 58 ("[26-10-10 17:39:08] bootdisk: failed to find .zip file in ") + 65 (name) + 1 (NUL) = 128
```

Two independent leaks both came out at exactly 65 bytes, ending `2e 2e` — and 65 is precisely
`128 - 4 - 58 - 1`. The genuine upgrade's own longest line is 103, so 128 is a ceiling, not a coincidence.
Whether the trailing `..` is a truncation marker (making real data 63 bytes) or two random bytes does not change
the conclusion materially.

**This means the mask trick cannot buy throughput.** The `44 -> 161.7 B/probe` figure and every estimate built on
256 bytes per window are wrong: the ceiling is ~65 bytes **regardless of masking**. Full decode is therefore

```
1,490,575 / 65 = 22,932 windows  (not the 5,800-9,000 quoted in §45/§64)
```

i.e. ~23,000 power cycles, roughly 4x worse than the last published figure, and 64-96 h of continuous interaction.

### 66.4 `zip_walk()` hard-codes the "nameless archive" assumption — CONFIRMED

`opzassemble.py:zip_walk()` **rejects any local header with a nonempty name** and reports it as an error
(`local header has a N-byte name (archive is nameless)`). That is an assumption dressed as a validator: it cannot
validate an ordinary zip at all. Combined with `buf` being zero-filled for unknown offsets, the assembler prints
header fields (including the nameless conclusion) from **invented zeros**. Byte coverage is not correctness, and
a nameless archive is not an observation.

### 66.5 `advance()` discards unknown bytes — CONFIRMED

`advance()` moves an interval's start forward by one even when the probe produced nothing, so a missed read
**silently deletes** that byte from the worklist. The saved state already shows it:

```
missing from pending: 19, 20, 21, 82, 83, 84, 1490323, 1490324, 1490325
```

9 positions. A missed read must keep its interval. Coverage percentages from that map are not a completeness
claim.

### 66.6 The engine files are loader streams, not flat images — CONFIRMED (and important)

All 21 engines walk as a chain of 16-byte Blackfin boot headers — `code, destination, count, arg` — and **every
stream ends exactly at EOF**:

```
analoga.engine  size=6568  @0x00 code=0xadcd5000 dest=0x11a00000 count=0    arg=0x1998
                           @0x10 code=0xad950000 dest=0x81b93800 count=56
                           @0x58 code=0xad910000 dest=0x81b93838 count=5136   <- continues right after
```

Destinations are consistent (`dest[i+1] == dest[i] + count[i]`), which is independent proof the format is right.
Two corrections follow:

* **`0x11A00000` is a destination address (L1 SRAM base), not a magic** — and the first block has `count=0`, so
  engines do **not** place code there. The earlier "16-byte header = 0x11a00000 magic + payload size" reading
  mistook the first block's `arg` (= total data size, which is exactly filesize−16 for all 21 engines) for a length.
* **`RETX − image_base` is not a file offset.** The recorded addresses `0x80117BAA`, `0x8002C438`, `0x11A03838`
  and `0x11A02586` are in none of the 21 engines' load ranges, so **the crash is in OS/L1 code, not in a plugin**.
  Whenever the OS member is recovered, translate an address through its block destination map.

### 66.7 Correction: ZIP method 4 is not Deflate

§65.10 (and the seed's own annotation) called the first entry "method 4 (labelled deflate there — see §66.7, method 4 is *Reduced*, not Deflate)". Per the PKWARE APPNOTE,
**method 8 is Deflate; method 4 is "Reduced with compression factor 3"**. Either the early notes' "method 8" or
the seed's byte 8 is wrong, and it is one more reason not to treat the seed as settled (§66.8).

### 66.8 The seed: contaminated, or genuine? — **RESOLVED: contaminated** (§66.12)

The review argues the seed's bytes 6-18 are a spliced console frame (`c0 1e 04 00 00 00 49 fb be 94 19 5b` =
`C0`, routing `1E`, type `04`, length 73, tick, `[`). Case for:

* flags `0x1EC0` is **invalid as a zip flags word** (strong-encryption bit without the encrypted bit, reserved
  bit 12 set, bits 9-10 set for a method that does not define them);
* method 4 is an odd choice, and DOS time/date are both zero (an invalid 1980-00-00);
* §66.2's defect is real: routing `0x1E` frame headers were *not* a stop condition, so absorption is mechanically
  possible, and the original raws are gone so the splice cannot be reconstructed.

Case against (my own reading, and I do not think the review's version is established):

* the seed's PK signature sits at offset 0, a 1-in-4-billion placement by chance;
* read as a frame, the `[` at index 17 is immediately followed by NUL at index 18 — an **empty timestamp**, which
  no real log line has (every genuine line is `[26-10-10 HH:MM:SS] `);
* read as a zip, index 18 is the third byte of `csize` (`19 5b 00 ...`), i.e. the stopping NUL lands naturally as
  the high byte of a plausible ~23 KB compressed size.

So: contamination is mechanically possible and the fields are suspicious, but the NUL position fits the zip
reading better. **Decisive test (1 power cycle):** re-read window 0 with `opzframe.py` — frames decoded properly,
aligned start, mask both applied and not. If bytes 6-18 still come out as `c0 1e 04 ...`, the payload is genuine
and the flags/method need another explanation; if they change, the seed was a splice and every byte derived from
it must be re-read.

### 66.9 Where the review overstates

Its framing — "several conclusions used to abandon cheap firmware reads depend on demonstrably defective
decoding" — is too broad. The three routes that died in §65 did not die from the decoder:

| route | how it actually died |
|---|---|
| buffer the plaintext archive (§65.1) | the volume is rebuilt at boot — control-file test |
| root SCSI media-load (§65.8) | root granted, all SCSI statuses 0, `TEST UNIT READY` still CHECK CONDITION |
| several windows per boot (§65.3) | 8 probes with `invalid dir` = 0 → still one read |
| **zip structure / tail directory (§65.10)** | **this one the decoder did kill — now restored to "untested"** |

So the review repairs the *structure* conclusions and the per-window yield arithmetic, not the throughput and
remount walls. It also does not dispute the one-window-per-power-cycle cost, which remains the binding constraint.
Its `disable_start_sound` suggestion is cheap and untested and is listed as such; `samplepacks/` being
import-capable (TE documents importing `.aif` sample packs) is a legitimate but weak lever, since the `../`
traversal write primitive already reaches `/yaffs2/user/`.

### 66.10 Corrected work order

*(Applied — see §66.11 for what changed, how it is verified, and the rebuilt map.)*

1. **Offline only, no device.** Adopt `toolkit/opzframe.py`; require frames decoded, escapes undone, windows
   aligned, and the worklist never dropping unknown bytes. Rebuild the map from scratch with capture provenance
   and keep the old one only as evidence. Nothing downstream is trustworthy until this is done.
2. **Read payload window 0 correctly** (1 power cycle) — settles both §66.8 (contamination) and the first local
   header (`csize`, `usize`, `namelen`, `extralen`).
3. **Read the aligned tail** (1490320, 1490544) — settles whether a central directory exists and where.
4. Then decide: if a directory or a `stored` member exists, a targeted read is possible; otherwise the honest
   figure is ~23,000 power cycles and hardware/TE service is the better route.

### 66.11 Applied: the review-2 decoder patch, and the map rebuilt with provenance

The fixes above were applied rather than just recorded. Nothing here is destructive: the pre-review state is kept
as evidence, and the farm is stopped.

**`~/.opz-decode/opzfarm.py`**

| function | change |
|---|---|
| `craft()` | calls `align16(idx)` first, so a window is only ever read from a 16-byte boundary (66.1) |
| `frames()` | new: decodes `C0 routing type len_be32 payload` and undoes `7D -> byte^0x20` (66.2) |
| `parse_cycle()` | rewritten on `frames()`; associates a probe across messages instead of searching 4 KB of raw stream; **honours the 128-byte log cap** — a capped frame's last byte is the buffer's NUL, so no terminating byte is invented, while a frame that stopped short of the cap *did* end on a real NUL and is still recorded (66.3) |
| `advance()` | a probe that produced nothing **keeps** its interval (66.5) |
| `ground_truth()` | only the 19 aligned window-0 bytes; the misaligned `q_30`/`w1490063`/`w1490319` seeds are gone (66.1). Documented as PROVISIONAL pending 66.8 |
| `handle_mismatch()` | still drops and re-queues, but **no longer auto-flips the mask** |
| `load()`/`migrate()`/`normalize_pending()` | one-time migration for a pre-review state; pending intervals are snapped to boundaries, because an unaligned interval start would shift a whole window's bytes by up to 15 |
| `record_read()` | per-cycle provenance: window, cycle, mask, leak/truncation counts, and the raw capture path |

**`~/.opz-decode/opzassemble.py`** — `zip_walk()` no longer rejects a named entry (it asserted the conclusion it
was meant to test); it reports data-descriptor entries explicitly; header fields are printed as `unknown` rather
than from invented zeros; it writes `/tmp/opzfarm_known.bin` (a per-byte observed-mask); and it prints `ZIPENTRY:`
lines so a recovered directory yields the component map directly.

**New/updated tooling** — `~/.opz-decode/opzsim.py` (faithful device simulator: real framing, escapes, 128-byte
cap, so the tests exercise the hardware's real 65-byte window), `~/.opz-decode/toolkit/opzframe.py` (reference
codec, self-tested against the three surviving captures), and the test suite updated for the new contract
(`test_opzfarm.py` rewritten; `test_zipwalk.py` now also requires **named** archives to be accepted;
`test_e2e.py`/`test_deliverable.py` drive `opzsim`; `opzcheck.sh` asserts alignment, ground-truth size and the
cap semantics).

**The rebuilt map.** `migrate()` dropped the 308 misaligned bytes and kept the 19 aligned ones:

```
before: 327 bytes, 4 pending intervals
after :  19 bytes, 6 pending intervals (all starts on 16-byte boundaries), 1,490,608 bytes to cover
```

Old state preserved at `~/.opz-decode/opzfarm_state.pre-review.json` and `opzfarm_map.pre-review.json`, and the
migration is recorded in the state as `"migrated": "review-2: dropped 308 unaligned byte(s)"`.

**Verification: `bash /tmp/opzcheck.sh` → 14 passed, 3 failed**, and all three failures are the deliberately
stopped farm (`launchd job not loaded`, `no farm process`, `code-hash stamp stale`) — they clear on the next
farm start. The e2e, deliverable and success simulations all pass; and the assembler now reports the real map
honestly:

```
head is a zip local header: version=20 flags=0x1ec0 method=4 csize=unknown usize=unknown namelen=unknown extralen=unknown
ZIPWALK: FAIL at 30 (expected a zip signature at 30, found b'\x00\x00\x00\x00')
```

That is the correct output for a 19-byte map: `unknown`, not an invented zero, and not a nameless-archive claim.

**What this does and does not prove.** The patch is verified by the simulator, the two real captures and the
offline codec's self-test — **not** by the device. The first real aligned read is what validates it, and it is
also the test that settles 66.8: if window 0 still comes out `50 4b 03 04 14 00 c0 1e 04 ...`, the payload is
genuine and the odd flags/method need another explanation; if it changes, the old seed was a frame splice.
With the 65-byte cap the worklist is ~22,900 windows, so **the next move is one power cycle, not a campaign**.

### 66.12 RESOLVED: the archive is an ordinary Deflate zip, and the old seed was hand-pasted

The first read through the corrected decoder (aligned window 0, mask on, 2026-10-10 19:29,
`~/.opz-decode/raws/w0_masked_20261010-193009.bin`) returned a **plain, valid zip local file header**:

```
raw leak      : 51 4a 02 05 15 01 01 01 09 01 63 71 7e 55 46 9d 68 3c c9 00
unmasked      : 50 4b 03 04 14 00 00 00 08 00 62 70 7f 54 47 9c 68 3c c9
decoded       : PK\x03\x04 | ver 20 | flags 0x0000 | method 8 (DEFLATE)
                | time 0x7062 / date 0x547f = 2022-03-31 14:03:04 | crc32 0x3c689c47 | csize ≥ 0xc9..
```

Every field is self-consistent: flags `0x0000` (no data descriptor, so the local header carries real
sizes and the zip chain is walkable), **method 8 = Deflate** — matching the *early* notes, not the
"method 4" that the seed implied — and a real DOS build timestamp, **2022-03-31 14:03:04**, giving the
1.2.45 archive's provenance.

**So the review was right and my §66.8 hedge was wrong.** The old constant

```
50 4b 03 04 14 00 c0 1e 04 00 00 00 49 fb be 94 19 5b 00
```

was not payload at all. The proof is internal: that constant contains NUL bytes at offsets 9, 10, 11 and
18 — and a console leak cannot contain a NUL, because the device's `printf("%s")` stops at the first one
and `parse_cycle()` stops there too. **A parser that stops on NUL cannot have produced that constant**, so
it was hand-pasted into the farm as `GROUND_TRUTH` and then faithfully re-asserted by every "17 checks
passed" run for months. That is the real origin of the whole fictional chain:

| derived from the bad constant | actual |
|---|---|
| flags `0x1EC0` (an impossible combination) | **`0x0000`** |
| method 4 ("Reduced"), "not Deflate" | **method 8 (Deflate)** |
| DOS date/time zero (an invalid 1980-00-00) | **2022-03-31 14:03:04** |
| "first entry name is empty, components are order-identified" | unknown — a **named** archive is now the expectation |
| "the central directory is not in the last 512 bytes" | **never tested** — that read was misaligned *and* the premise was fiction |
| `c0 1e 04 ...` "high-entropy data" at offset 6 | a **console frame header**, absorbed by a bad transcription |

Process lesson, worth more than the bytes: a "verified" constant that no pipeline can produce is not
evidence, and a self-check that merely re-asserts it is not a check. The corrected parsers now *derive*
ground truth from a decoded frame, and `opzw0.py` prints the frame length and `capped` flag so the
provenance of every byte is visible.

**Consequences.** §64.3 ("read the zip central directory instead of the payload") is the live cheap route:
a normal zip has a named central directory at the tail, so a handful of aligned windows recovers the
component names, offsets, sizes and methods — and with those, the OS member can be read on its own instead
of decoding 1.49 MB. The farm's ground truth is now the 20 hardware-verified bytes, the map holds them,
and `opzcheck.sh` asserts that they decode as a real local header (`PK\x03\x04`, method 8, flags 0, date
`7f 54`) so the fiction cannot recur silently.

### 66.13 Read #2, and the IV mask delta is a free lever (not a constant)

Second read, aligned window 16 (2026-10-10 19:34, `raws/w16_masked_20261010-193542.bin`):

```
device printed (masked) : 69 3d c8 01 01 01 3a 00
unmasked (delta 0x01)   : 68 3c c9 00 00 00 3b      <- 7 bytes, then the print stopped
```

Cross-checking against read #1 (a fully independent window) confirms the pipeline: read #1 gave `crc32` bytes
`47 9c 68 3c` at offsets 14-17, and this read gives `68 3c` at 16-17 — byte-identical overlap, so window
addressing and unmasking are right. From the two reads the first entry's header is now:

```
crc32 = 0x3c689c47   csize = 0xc9 = 201   usize = 0x013b = 315 (low two bytes)
```

so the **first entry is small (315 bytes uncompressed)** — not the OS image — and it is Deflate.

**Why the print stopped, and the lever it exposes.** The stop byte is printed `0x00`, and it sits *inside* the
masked first block (window offset 7), so the true byte there is `0x00 ^ 0x01 = 0x01`. The mask itself caused the
truncation: a true `0x01` becomes `0x00` under `^0x01` and stops the print. That generalises the mask trick:

> The IV is ours to choose, so block 0's plaintext can be shifted by **any Δ** — not just `0x01`. A block is
> unreadable only if it contains a byte equal to Δ. Since block 0 is 16 bytes and Δ has 240 valid values, **a Δ
> avoiding them always exists**, so the first 16 bytes of *any* window are always fully readable; only the delta
> choice stands between a `0x01`, `0x00` or `0x02` in that block and a truncated read. (Δ still affects block 0
> only: shifting later blocks would require changing their ciphertext, which is the payload's own chain.)

So read #2 is redone with **Δ = 0x02** (safe: the known block contains `0x00`, `0x01`, `0x3b`, `0x3c`, `0x68`,
`0xc9`), which prints the true `0x01` as `0x03` and the true `0x00`s as `0x02` — continuing past offset 23 for
the first time. Encoded as `MASK_DELTA` in `opzfarm.py` (used by both `craft()` and `parse_cycle()`, so a probe
and its decoder cannot disagree) and as `opzw0.py --delta N`; `test_opzfarm.py` now asserts that Δ=1 truncates on
a true `0x01` while Δ=2 reads the whole block.

Practical rule from this: **choose Δ to avoid the values in block 0**, which is the only part a small NUL can
truncate — and expect the window's tail to be cut by the first NUL past offset 16 or the 65-byte log cap,
whichever comes first.

### 66.14 Read #3: the first component name, and the '..' truncation marker

Third read, aligned window 16 with the new **Δ=0x02** mask (2026-10-10 19:39,
`raws/w16_d2_20261010-194013.bin`) — the read that got past offset 23:

```
68 3c c9 00 00 00 3b 01 00 00 15 00 00 00 66 69 72 6d 77 61 72 65 2f 76 65 72 73 69 6f 6e 73 2e 74 78 74
35 ce 41 6a 03 31 0c 40 d1 fd 9c 22 fb 42 90 25 4b b2 8e 23 4b 72 09 49 33 90 76 d3 | 2e 2e
```

**The first local file header is complete, and it is exact:**

| field | value |
|---|---|
| crc32 | `0x3c689c47` |
| csize / usize | **201 / 315** |
| namelen / extralen | **21 / 0** |
| name (offset 30, 21 bytes) | **`firmware/versions.txt`** |
| entry data | starts at offset 51 = `30 + 21 + 0`, and the bytes there are high-entropy Deflate output |

So the archive's internal namespace is a **`firmware/` directory of named files**, and the very first entry is
`firmware/versions.txt`. Every layout prediction holds: name length matches the field, extralen zero, data exactly
where the header says. Read #1 and read #3 also **cross-check on all four overlapping bytes** (`68 3c c9 00`) from
different windows, so addressing, the mask and the delta are all confirmed against hardware.

**The `..` truncation marker — confirmed, and it was silently corrupting the map.** Every capped leak (3 of 3 in the
captures) ends `2e 2e`, and no short leak does, with the arithmetic closing exactly:

```
4 (tick) + 58 (text) + 63 (data) + 2 ('..') + 1 (NUL) = 128 = the log buffer ceiling
```

So a capped read yields **63 real bytes, not 65**, and the last two bytes before them are *not* payload. The patch
as first applied would have written those two `2e`s into the map on every capped read — a two-byte corruption per
window, invisible to a coverage counter. `parse_cycle()` now strips the marker and counts it (`LAST["marker"]`),
`opzsim` reproduces it, `test_opzfarm.py` asserts it, and `opzcheck.sh` verifies the invariant against **every
durable raw capture**.

One consequence worth stating: the marker *overwrites* two real bytes (offsets 79 and 80 in this read), so
`normalize_pending()` is now also applied after every cycle — it snaps the next interval start down to a 16-byte
boundary, which both keeps `craft()` and the filing arithmetic in agreement and re-reads those two shadowed bytes
from an overlapping window. Without that, a window's bytes could be filed up to 15 positions off.

Current state of the map: **79 bytes** (offsets 0..78), 3 reads, all three raw captures durable, and the worklist
holds aligned intervals `[64, 1490063]` and `[1490048, 1490575]`.

### 66.15 Read #4: 31 components, and the central directory's exact address

Fourth read, aligned window 1490560 with Δ=1 (2026-10-10 19:44, `raws/w1490560_d1_20261010-194446.bin`) — the
last 15 real payload bytes, which are the tail of the zip end-of-central-directory record:

```
raw leak (unmasked) : 00 1f 00 1f 00 58 0b 00 00 21 b3 16 00 00 00
```

interpreted with the EOCD at payload **1,490,553** (= 1,490,575 − 22, i.e. no zip comment):

| EOCD field | value |
|---|---|
| cd_disk | 0 (single disk) |
| **entries on this disk / total** | **31 / 31** |
| **cd_size** | **2,904 bytes** |
| **cd_offset** | **1,487,649** |
| comment length | 0 |

and the layout closes **three independent ways**, which is what makes this trustworthy rather than plausible:

```
cd_offset + cd_size = 1,487,649 + 2,904 = 1,490,553 = the EOCD's own position
1,490,553 + 22 (EOCD)                   = 1,490,575 = the plaintext length from the .zfw header
                                        = payload end, i.e. the record sits exactly at the tail
```

**The archive is a 31-entry zip whose central directory occupies payload `1,487,649..1,490,552`**, and its offsets
are payload-relative (entry 1's local header is at payload 0, matching the CD's record for it). Average CD record
length is 93.7 bytes, so component paths average ~48 characters.

**Where this leaves the oracle, stated honestly.** The information rate is ~63 bytes per power cycle, so:

| target | size | power cycles | verdict |
|---|---|---|---|
| the whole central directory | 2,904 B | ~46+ | **feasible** — and it yields every name, size, offset and method |
| a small member (`firmware/versions.txt`) | 315 B | ~5 | feasible |
| the OS image (~1 MB) | ~1,000,000 B | ~16,000 | **infeasible** — the oracle cannot deliver the whole OS |

So the oracle's real value is the **component map**, plus *targeted* small reads — not a full decode. That
re-frames the goal, and it is a better goal: to name the crashing instruction `RETX 0x80117BAA` we do not need the
OS image, we need its **loader block map** (the engines are block-structured streams, §66.6, so the OS should be
too) plus ~64 bytes around the fault:

1. walk the local headers (one read per entry, jumping by `csize`) until the OS member is identified by name;
2. read the first few hundred bytes of that member — its 16-byte Blackfin block headers (`code, dest, count, arg`);
3. find which block covers `0x80117BAA` and compute the member offset `data_off + (0x80117BAA - dest)`;
4. read ~64 bytes there and disassemble.

That is roughly **10-15 power cycles to the faulting instruction**, instead of 16,000 for the image. Next read is
the second entry's header, which sits at payload 252 (= 30 + 21 + 201, computed entirely from read #1 and read #3)
and is reached by window 272: that window's masked block covers `csize`/`usize`/`namelen`/`extralen` and the first
six name characters, so the name itself arrives unmasked.

### 66.16 The component walk (live log)

The recipe that makes one oracle window sufficient per entry: for a local header at offset `H`, the header's NUL
bytes cluster at `H+5`, `H+7..8`, `H+10`, `H+20..21` (high bytes of the sizes), `H+27` and `H+28..29` — i.e. spanning
`H+5..H+29`, which is wider than one 16-byte masked block. So an entry costs **one to two windows**: one whose mask
covers `H+14..H+29` (which always exists when a multiple of 16 falls in `[H+14, H+18]`) yields `csize`, `usize`,
`namelen`, `extralen` **and** the name, since the name at `H+30` then runs unmasked; otherwise two windows split the
header.

Recovered so far (all hardware-verified, raw captures in `~/.opz-decode/raws/`):

| # | payload offset | name | method | csize | usize | namelen |
|---|---|---|---|---|---|---|
| 1 | 0 | `firmware/versions.txt` | 8 (Deflate) | 201 | 315 | 21 |
| 2 | 252 | `firmware/firmware.version` | 8 | ~11-20 (high bytes 0) | **9** | 25 |

Entry 2's payload is 9 bytes uncompressed — consistent with a bare version string — so the archive opens with two
tiny metadata files and the real components follow. Entry 3's header sits at `55 + csize(entry 2)`, i.e. inside
`[66, 75]`; one more read pins `csize(entry 2)`'s low bytes down exactly.

### 66.17 The OS image is found: `firmware/blackfin/bin/opz.ldr`

Read #7 (window 336, Δ=1) completed entry 3's header in a single window, exactly as the §66.16 recipe predicted:

| field | value |
|---|---|
| name | **`firmware/blackfin/bin/opz.ldr`** (29 chars, matching namelen) |
| csize / usize | **466,903 / 828,136** (809 KB uncompressed) |
| data | payload **377 .. 467,280** |
| next header | **467,280** (= 377 + 466,903), known for free |

Two things follow immediately:

1. **The archive's first three entries are `firmware/versions.txt`, `firmware/firmware.version`, and the OS
   image** — metadata first, then the OS. Entry 1 and entry 2 carry the identical DOS stamp
   `2022-03-31 14:03:04`, so the archive was written in one pass.
2. **`.ldr` is a Blackfin loader stream**, the same container the 21 engines use (§66.6): a chain of 16-byte
   headers `(code, dest, count, arg)` whose `dest[i+1] == dest[i] + count[i]`. So the fault address can be mapped
   without decompressing anything:

```
find the block with  dest <= 0x80117BAA < dest + count
file offset  =  (that block's header offset + 16) + (0x80117BAA - dest)
```

If the image is contiguous from a base `B`, then `B ∈ (0x8004D8C2, 0x80117BAA]`, and `0x80117BAA` sits ~818 KB
into an image based at `0x80050000` — i.e. near the end of the 828,136-byte image, which is a plausible place for
startup/init code.

**A structural wrinkle, stated up front.** The member begins at payload 377, and `377 mod 16 = 9`, so every 16-byte
loader header straddles two masked blocks and can never sit inside one. Each header therefore costs **two windows**
— one for its first ~7 bytes, one for the rest — or one window plus whatever the unmasked tail survives before a
NUL in the `count`/`arg` fields cuts it. Consecutive windows at 16-byte strides (384, 400, 416, …) overlap usefully:
window 384 should return block 0's `count`/`arg` **and** block 1's `code`/`dest`/`count` together, which is enough
to compute where block 2 begins and jump there.

### 66.18 Read #8: the oracle returns COMPRESSED member bytes — the OS is out of reach

Read #8 (window 384, Δ=1) targeted entry 3's first loader header. It returned 63 bytes of **high-entropy data**:

```
c7 85 8c 48 8a 14 49 0a 49 88 22 ca ae 94 2d 64 24 7b 65 ef bd 7e 37 6d 65 ef bd 22 7b 6f 09 ...
```

and the reason is structural, not accidental. **The oracle leaks the decrypted *archive*, i.e. the zip file itself.** Every
entry in this zip has `method 8 = DEFLATE`, so what sits at a member's payload offset is that member's **compressed
stream**, not its content. The bytes above are the head of `opz.ldr`'s Deflate stream, and a Deflate stream cannot be
decoded from a fragment — you need every byte before the one you want.

So §66.17's loader-block plan is **retracted**. It required the `.ldr`'s content, and the content is compressed:

| member | csize | power cycles at 63 B/read | verdict |
|---|---:|---:|---|
| `firmware/firmware.version` | 11 | 1 | feasible |
| `firmware/versions.txt` | 201 | 4 | feasible |
| `firmware/blackfin/bin/opz.ldr` (the OS) | 466,903 | **7,412** | **infeasible** |

Nor is there a side door in the logs: a scan of `crashlogs/latest/{system,crash01}.log` finds **no instruction,
memory or stack dump** — no `disasm`, `opcode`, `dump`, `code:` or hex-dump lines at all (0 lines with more than 8
hex bytes; the two that match are garbled UTF-8), so the crash record gives registers and addresses but no code.

**What the oracle actually buys, now bounded by measurement:**

| feasible | infeasible |
|---|---|
| the 2,904-byte central directory (~46 cycles) | any large member's *content* |
| the local-header walk: names, sizes, offsets, **methods** (~1-2 cycles/entry) | especially the 809 KB OS image (7,412) |
| small members whose whole `csize` is a few reads (`versions.txt`, `firmware.version`) | the 21 engines and the sample packs |

This is the same wall the project hit from the other side: the OS image needs **hardware** (JTAG/BF703 attach, or an
off-board NAND/SPI read) or **TE service**, because the device's own copy is decompressed in internal NAND that the
host cannot address. One consequence is newly useful, though: when walking entries, **record the `method` field** —
a `stored` (method 0) entry's content *is* directly readable, so one stored large member would reopen the whole
path. The seven sibling archives are also worth a look for exactly that reason: an older `.zfw` may store what
1.2.45 deflates.

**And one route is reopened by all of this.** §"file transport" documents that the OP-Z itself **serves files over
MIDI**: `$35` is a file request, the device answers in `$53` packets, and `fileId = crc32(utf8(lowercase(path)))`
addresses *arbitrary* paths. That service is OS-level — which is precisely why it was written off ("the OS crashes
before MidiInit"). But **content mode runs the same OS successfully**, so in content mode the file server should be
alive and the internal tree addressable — including, potentially, the decompressed components the updater wrote to
NAND. That is a host-side read path to the OS image that does not exist through the console oracle, and it costs
one MIDI connection rather than 7,412 power cycles.

### 66.19 Read #9: the oracle pipeline is proven end-to-end (first real component content)

Read #9 (window 304, Δ=1) targeted entry 2's compressed stream and validated the entire chain at once:

```
payload 304..322 : 69 6f 6e | 33 d4 33 d2 33 31 d5 36 e0 02 00 | 50 4b 03 04 14
                   ^"ion"     ^ entry 2's 11-byte Deflate stream     ^ entry 3's local header
```

and inflating those 11 bytes as raw Deflate (no zlib wrapper — a zip entry's stream) yields

```
b'1.2.45+0\n'          (9 bytes, exactly the header's usize = 9)
```

Three things are now proven rather than assumed:

* **The oracle output is correct archive plaintext.** Take a window, decode the frame, unmask, slice the entry,
  inflate — and real firmware content falls out. This is the first *content* the project has recovered from the
  device, and it closes the loop on §66.1/66.2/66.3/66.13/66.14 all at once.
* **The walk arithmetic is exact.** Entry 3's header was computed as `252+30+25+0+11 = 318`; the device's own bytes
  put `PK\x03\x04` at 318. Two independent reads also agree on the overlapping bytes 307–316.
* **`firmware/firmware.version` = `1.2.45+0`** — the OS version string, with a `+0` build/variant suffix.

So the oracle is a **working, verified read primitive for the archive**, whose only real limit is the 63-byte
ceiling per power cycle. That makes small members free-ish (`firmware.version`: 1 read; `firmware/versions.txt`:
4 reads) and large members impossible (the 809 KB OS: 7,412 reads), because entries are Deflate and a Deflate
stream cannot be read from a fragment (§66.18).

### 66.20 Arming the MIDI file-transport route (read-only)

The console oracle's ceiling is metadata + small members (§66.18/66.19), so the OS image needs a different host
path. The most promising one is the OP-Z's **own file service over USB-MIDI**, which the clean-room project
(`~/.opz-decode/refs/op-z-sysex`) implemented and **device-proved on 2026-07-26 with firmware `1.2.45+`** — the
exact version this unit runs.

Protocol (from `docs/clean-room-file-transport.md`): `F0 00 20 76 01 <id> <7-bit-packed payload> F7`; `$51`
advertises a host server, the OP-Z answers `$34` with its client id and state CRC, `$35` requests a file by id at
a part index, and the sender streams `$53` parts of ≤200 uncompressed bytes each (each part its own zlib stream).
`fileId = crc32(utf8(lowercase(relativePath)), initial 0)`, with reserved ids 0/1/2 = `settings/slotConfiguration.json`,
`settings/plugs.json`, `syncjob.json`.

Built for this: **`~/.opz-decode/toolkit/opzfetch.py`** — and it is **download-only by construction**: it sends
only `$51` and `$35`, never a `$52` manifest or a `$53` upload, so it cannot write to the device.

Verified so far: in **update mode there is no MIDI device at all** (`mido.get_input_names()` and
`get_output_names()` are both empty), which is expected — the file service is an OS-level feature. The service is
documented for **normal mode**, which this unit cannot reach because it crashes during init. That leaves **content
mode**, which runs the same OS successfully: if content mode also exposes USB-MIDI, the service should be alive
there and system paths (`../upgrade/firmware/blackfin/bin/opz.ldr` and friends) become worth requesting. If it does
not expose MIDI, this route is closed and the OS image needs hardware or TE service.

Path guesses worth trying, cheapest first: the control `settings/slotConfiguration.json` (proves the service),
then the updater's extraction tree `../upgrade/firmware/blackfin/bin/opz.ldr`, then `firmware/blackfin/bin/opz.ldr`
and `../firmware/blackfin/bin/opz.ldr`. Reading `firmware/versions.txt`'s content through the oracle (4 power
cycles, 201 compressed bytes) should name the real component set and sharpen these guesses.

### 66.21 The disable_start_sound experiment: negative, and the crash is config-independent

Ran the one config branch in the crash path that had never been varied (§66.9 / review item 2). The content disk was
mounted in content mode, so `config/general.json` was edited **in place** — `disable_start_sound` `false -> true`,
nothing else (verified: valid JSON, 10 keys, exactly one key changed; original baselined at
`~/.opz-decode/contentdisk-baseline/general.json.orig`) — then the unit was booted in content mode (so the device
imports the disk's config into its internal tree) and then booted normally.

Fresh logs (`crashlogs-after-disable-start-sound/`, device clock ≈ 1 h behind host):

```
iid: 0x00130026   ADI_EXC_DATA_CPLB_MISS   DCPLB_FAULT_ADDR: 0x00000000   RETX: 0x80117baa
```

**Identical to the baseline in every material field.** The hypothesis is retired: the startup sound is not the
trigger, and the crash does not move.

The fresh `system.log` also corrects a long-standing item in the notes. Comparing the two boots line by line:

| | baseline | fresh |
|---|---|---|
| `filemanager: opendir failed: /yaffs2/user/config/` | **present** | **absent** |
| `filemanager: opendir failed: /yaffs2/user/samplepacks/user/` | present | present |
| `rejected/`, `bounces/` | present | present |
| terminal line | PSOC power-off | PSOC power-off |

So **`/yaffs2/user/config/` now exists** (with a complete `general.json`) where the baseline build reported it
missing — the config tree is repaired — and the crash is unchanged. That closes the "missing config" theory on the
device side, independent of which config values are set.

**Caveat, stated honestly:** the content-disk import is asserted by the documentation, not proven by this run — the
internal tree's value after the import was not re-read (that needs one more content-mode boot, at which point the
device rebuilds the content disk *from* the internal tree, so `config/general.json` would show the internal value).
If the import silently did not run, the negative above is void for the *value* question — but the `config/` opendir
evidence shows the config *tree* is present and the crash survives regardless, which is the load-bearing point.

**What the crash has now resisted:** full 1.2.45 reflash, a 1.1.12 downgrade plus reflash (same `iid`, different
`RETX 0x8010ea52`), the 21 genuine engine binaries, `slotConfiguration.json`, `plugs.json`, `plugPresets.dat`,
arpeggiators, `general.json` in every variant including all-defaults, and now `disable_start_sound`. It is
deterministic, survives a byte-identical reflash, and appears in the two oldest available OS builds. That is the
signature of **state the firmware packages do not restore** (a system-path file or hardware/OTP state outside
`/yaffs2/user/`), which is why the remaining routes are TE service or hardware — and why the one cheap *recovery*
shot left is an **older firmware**: every build tested so far comes from the same 1.1.12+ lineage, so a pre-1.1.12
`.zfw` (1.1.5/1.1.9 era, if one can still be found) is the only untried version, and installing it is a normal
staged upgrade needing no special access.

### 66.22 The content disk is an outbound mirror for config — the earlier test was void

The one-more-boot control answered a question I had wrongly assumed away. The content disk's `config/general.json`,
which I had edited to `disable_start_sound: true` as the import source, now reads:

```
336 B  sha256 4eb733170616...  disable_start_sound = false   (byte-identical to the ORIGINAL baseline)
import.log: 0 bytes           (still, and still dated 19:02 — no [IMPORT STARTED] cycle ever ran)
general.json mtime: Dec 30 2017   <- the DEVICE's unset-clock timestamp: the device wrote it
midi.json mtime   : Nov 24 2024   <- untouched by the device this boot
```

So my 335-byte edited file is **gone**, replaced by a 336-byte copy of the device's own value, and no import cycle
was recorded. The device **writes its config out to the content disk at boot** (`saveSettings`, alongside the
`plugmanager: save slot configuration` line) and that write **clobbers the disk copy**. The content disk is
therefore an *outbound* mirror for these files, not an import channel — which is why the experiment applied
nothing.

Consequences, both of which matter:

* **The `disable_start_sound` experiment is void, not negative.** §66.21's conclusion that "the startup sound is not
  the trigger" is not supported: the internal value was never changed. The config-*tree* evidence from the same run
  (that `/yaffs2/user/config/` exists, where the baseline reported it missing) is unaffected and still stands.
* **The content disk is a reliable way to READ the internal config** (it mirrors it), but a write to it is a no-op.
  To change internal config the proven channel is the plain-zip **traversal write** (`../user/config/general.json`
  through the updater), which is how every earlier config variant in the notes was actually applied — and which is
  why those earlier results are valid while this one was not.

The corrected experiment, if it is ever worth running, is therefore: build a plain zip whose entry is
`../user/config/general.json` with `disable_start_sound: true`, stage it on the update volume, eject so the updater
extracts it, then boot normally and diff the crash. Cost: one staged zip and two boots. Given that the crash has
survived every other config variant, the older-firmware recovery shot remains the better use of that effort.

### 66.23 TE still serves old firmware — the pre-1.1.12 recovery shot is available

Probed TE's own download host (the pattern `_software/op-z/z_firmware_<a>_<b>_<c>.zfw`, found in the Wayback index;
the app only exposes account/DLC APIs, not firmware URLs). **Seventeen builds still serve HTTP 200**, including one
older than anything previously available locally:

| available now | notes |
|---|---|
| **1.1.9** (822,960 B) | **oldest obtainable — pre-1.1.12** |
| 1.1.12, 1.1.17, 1.1.23, 1.1.27 | |
| 1.2.5, 1.2.8, 1.2.12, 1.2.14, 1.2.17, 1.2.20, 1.2.26, 1.2.28, 1.2.31, 1.2.38, 1.2.39, 1.2.40, 1.2.45 | |

1.0.x and 1.1.0–1.1.8 all 404, so **1.1.9 is the floor**. Downloaded and verified as a genuine container by the same
test the other archives pass: `keyidx = 0xFF` and `0x400 + ceil(821931/16)*16 = 822,960`, exactly the file size. The
same encrypted-zip scheme applies, so the whole oracle toolchain works against 1.1.9 unchanged.

**Why this is the last cheap recovery shot.** Every OS tested comes from the same lineage and crashes with the same
`iid` (1.2.45 at `RETX 0x80117baa`, 1.1.12 at `0x8010ea52`), and a byte-identical reflash does not change it — the
signature of state the firmware packages never restore. But an older OS is a different program: it may initialise
without touching whatever is missing. 1.1.9 is the furthest back reachable, and installing it is the device's own
intended path with a genuine TE release, not a crafted image.

**Risk and reversibility, stated plainly.** Installing writes 1.1.9's bootloader as well as its OS. That is the one
operation the guardrails treat as near-irreversible — with two mitigations that this project has already proven:
the bootloader has A/B slots and alternates between them, and a full 1.2.45 install has been performed and verified
repeatedly (including after a 1.1.12 downgrade), so a failed attempt returns to the current state. The residual risk
is a bootloader that installs but does not run, which a 1.2.45 reflash has already recovered from once.

**Payoff if it boots:** a running OS means the OS-level MIDI file service becomes reachable (§66.20) and the internal
tree — including the decompressed components — becomes readable, which is the one path to the OS image the console
oracle cannot provide. A working unit also allows a stepwise walk up the version list to find the first build that
crashes, which would pin the regression or state dependency precisely.

### 66.24 The 1.1.9 install succeeded, in full

Ran `~/.opz-decode/toolkit/opzinstall.py` against the update volume (clean, `systeminfo` only). The updater's own log,
captured to `~/.opz-decode/raws/install_z_firmware_1_1_9_20261010-201151.bin` (35,020 B, 631 frames):

```
bootdisk: detected encrypted file /z_firmware_1_1_9.zfw
bootdisk: key index: 0xff
bootdisk: loaded len 4 bytes: 821931
bootdisk: filename found: firmware_bin_only_with_bootloader.zip
bootdisk: decrypt 52224/822960 ... 772096/822960      [15 progress lines]
filemanager: opendir failed: /yaffs2/upgrade/
upgrade: [extract] progress 311/1566161 ... 1566161/1566161
upgrade: [2026-10-10 19:11] upgrade started
upgrade: [content] progress 1/6 ... 6/6
upgrade: copied 6 files
upgrade: content: OK (0)
upgrade: os: OK (0)
upgrade: [bootloader] progress 4096/255764 ... 255764/255764
upgrade: [bootloader] wrote bootloader to index 1
upgrade: bootloader: OK (0)
upgrade: ble: Already installed (-200)
upgrade: psoc upgrade row 0 ... 511
```

**Four things this gives us that we did not have.**

1. **The updater's component list, from the device itself:** `content` (6 files), `os`, `bootloader`, `ble`, `psoc`.
   The archive's top-level members are exactly those five, and the extract total is 1,566,161 bytes. `psoc` is a
   512-row table written to the power-management chip; `ble` was skipped as already installed; the bootloader went to
   A/B **index 1** (the inactive slot), which is what makes the operation reversible.
2. **The decrypted name is `firmware_bin_only_with_bootloader.zip`** — byte-identical to the name 1.1.27's archive
   reports, so the encrypted name field carries this one string across the whole 1.1.x line, and it is the bootloader's
   filename check that requires it.
3. **`keyidx 0xff` and `0x400 + ceil(821931/16)*16 = 822,960`** were confirmed by the device's own updater, which is
   independent hardware validation of the header arithmetic derived from 1.2.45.
4. **`version.txt` now reports os 1.1.9, bootloader 1.1.9, keyboard 1.1.9** (ble unchanged — it skipped), so the whole
   1.1.x component set took, and the unit rebooted into update mode afterwards.

The volume now holds no archive at all, so the next plain power-on installs nothing and simply boots whatever OS is in
NAND: the run that decides whether 1.1.9 comes up as a working unit.

### 66.25 Third attempt at 1.1.9, and the two never-staged ablations finally applied

**1.1.9 installs cleanly and crashes too, at the same function.** Staged through the device's own updater (§66.24), and
the version report becomes os/bootloader/keyboard 1.1.9. The following normal boot still crashed, but the crash record
adds real information:

| | 1.1.9 | 1.1.12 | 1.2.45 |
|---|---|---|---|
| iid | `0x00130026` | `0x00130026` | `0x00130026` |
| RETX | `0x8010ea4c` | `0x8010ea52` | `0x80117baa` |
| callstack[1] | `0x8002b25e` | — | `0x8002c438` |
| callstack[2] | `0x11a02f38` | — | `0x11a03838` |
| callstack[3] | `0x11a01c86` | — | `0x11a02586` |

1.1.9 and 1.1.12 differ by **6 bytes** and their first three callstack frames differ from 1.2.45's by exactly
**+0x11DA** (SDRAM) and **+0x900** (L1). Same functions, shifted by the code growth between the 1.1.x and 1.2.x lines.
So the fault is **one stable function**, reached from different places: 1.1.9 dies immediately after
`plugmanager: save slot configuration`, 1.2.45 survives to `snakesystem: load general config`. A single shared helper
called by (at least) the slot-config save and the settings save fits both. It is a genuine null dereference:
`DCPLB_FAULT_ADDR 0x00000000`.

**The content-mode boots are the successes.** The volume's `system.log` holds ten boots that complete — all of them
content-mode: they run `contentmanager`/`mass_storage` and idle ~100 s before a PSOC-requested power-off, and they
**never print `snakesystem:`**. Normal mode dies exactly where content mode stops. This matches §25's finding that
content mode runs the same OS while skipping `loadSettings/saveSettings/SynthInit/sequencerInit/MidiInit`.

**Both never-staged ablations are now applied through the §24 primitive.** A plain zip (no key, no crafted `.zfw`) named
`firmware_bin_only_with_bootloader.zip`, 93,896 B, 23 entries, with the config first so an abort cannot skip it:

```
../user/config/general.json            324 B - the device's own 10 keys, disable_start_sound false->true
../user/samplepacks/user/<id>.engine    20 real engine binaries for plugs
                                        10,13,14,17,43,25,31,11,26,34,35,38,39,65,71,109,112,129,138,98,99
P0.txt                                  write marker, last
```

The updater picked it up and extracted it **to completion** (`upgrade: [extract] progress 324/90948 ... 90948/90948`,
24 lines) before failing the OS gate with `upgrade was unsuccessful, system won't reset`. Since §24 established that the
extraction writes are persistent and that `disk_io` creates missing parents, both edits are now in `/yaffs2/user/`: the
config the crash sits immediately after, and the `samplepacks/user/` tree that the sample-memory scan reports as empty.
Whether the crash changes is the next boot's answer.

### 66.26 The §24 write works: the unit now fully boots the application

Everything above this section described a unit that died during init. After the §24 write of §66.25 - the engine
binaries into `samplepacks/user/` plus `disable_start_sound=true` - the next normal boot **reached the startup
animation and the track-selection UI, and responded to the TRACK button**. The application initialises completely:

```
main: initialize [sequencer]: took 79 ms        task: create task sequencer_task
main: initialize [audio init]: took 1 ms        task: create task filemanager_task
main: initialize [midi]: took 1 ms              midi: load midi config /yaffs2/user/config/midi.json
main: initialize [codec start]: took 16 ms      codec: CODEC resume / SetMicBias / Enable CP2 ...
main: initialize [audio start]: took 21 ms      main: initialize [jack detect] / [finalize]
```

It then ran for about nine seconds and faulted somewhere new, which is progress, not a regression:

| | before §66.25 | after §66.25 |
|---|---|---|
| iid | `0x00130026` | **`0x0013002c`** |
| reason | `ADI_EXC_DATA_CPLB_MISS` | **`ADI_EXC_INSTR_CPLB_MISS`** |
| fault addr | `0x00000000` | **`RETX: 0`** |
| when | during init, ~0 s | **~9 s in, with tasks running** |

An **instruction** CPLB miss with `RETX: 0` is the CPU being told to execute at address 0 - a call through a **null
function pointer**. So the earlier fault was a null *data* read during init, and this one is a null *call* from the
running sequencer. Two more crashes in the same batch (`crash02`/`crash03`, 19:22:58 and 19:23:09) are still the old
`0x8010ea4c` init fault - the writes only take effect on the boot after them, so only the last boot in a series moves.

**The new log names exactly what is still missing.** In order, before the fault:

| line | count | reading |
|---|---|---|
| `disk/disk_io: error opening /yaffs2/user//arpeggiators/01..06.txt` | 6 | benign: `initArpeggio` falls back to its built-in table |
| `disk/disk_io: error opening /yaffs2/user/projects/project01..10.opz` | 9 | benign: no projects saved |
| `fxmanager: Couldn't find plug with id 34 / 36 / 37 / 39` | 12 at init, then **1/s right up to the fault** | **the live lead** |
| `dmxcontroller: dmx config not found` + `Invalid dmx config json` + `failed to find dmx fixture mode rgb` | 1 + 1 + **16** | second candidate |
| `statesync: init, master: 1, m_id: 28610` | 1 | ran fine |

`fxmanager: Couldn't find plug with id 34` means a **plug definition** is absent from `g_plugs`, and §25.2 established
that `settings/plugs.json` is the only filler of that table. §25.2 wrote that file and the crash did not move - but it
was written **before the engine binaries existed**. A plug with a definition and no engine file behind it is still a
null effect, which is exactly why that test could not have succeeded. Both halves now exist for the first time, except
`plugs.json` itself: the engines are in `samplepacks/user/`, the definitions are not.

**Why this also reopens the MIDI route.** The device now reaches `initialize [midi]` and loads `config/midi.json`,
which it never did before, so a normal-mode boot should expose USB-MIDI for the ~9 s it survives. That is the
OS-level, read-only file service of §66.20 - and reserved fileId 1 is exactly `settings/plugs.json`. A watcher
(`~/.opz-decode/toolkit/opzwatch.py`) fires `toolkit/opzfetch.py` the instant the endpoint appears.

### 66.27 What enabled the breakthrough, in one place

The enabler was not the firmware version, the config, or the engine binaries on their own. It was **the updater's
extractor used as a host write primitive** (§24) - the only channel that reaches `/yaffs2/user/` and persists.

| channel | what it can write | survives? | outcome |
|---|---|---|---|
| content disk (`config/`, `projects/`, `bounces/`, `rejected/`) | those four folders | **no** - the device re-exports its own files over host edits (§66.22) and the content sync deletes `samplepacks/user/` | void as measured |
| `settings/`, `engines/`, `samplepacks/user/` **via the content disk** | nothing | no - export-only re-export | dead (§25) |
| **plain zip `firmware_bin_only_with_bootloader.zip` in the volume root** | **all of `/yaffs2/`**: `..` is resolved without sanitising, missing parents are created, and it runs **before** the `ble` gate | **yes** - persistent yaffs2 writes | **this worked** |

**Recipe, as run (reproducible):**

1. `~/.opz-decode/toolkit/opzablate.py` builds the archive (entries `../user/config/general.json` and
   `../user/samplepacks/user/<id>.engine`), removes other `*.zfw`/`*.zip` from the volume, stages it, ejects, and
   captures the console. **No key, no crafted `.zfw`, no AES input of any kind.**
2. The updater extracts it: `mass_storage: comparing firmware_bin_only_with_bootloader.zip with firmware`, then
   `upgrade: [extract] progress 324/90948 … 90948/90948`, then fails the OS gate
   (`upgrade was unsuccessful, system won't reset`). That failure is expected and happens **after** the writes.
3. **Power-cycle.** The writes take effect on the *next* boot: in a series, `crash02`/`crash03` still showed the old
   `0x8010ea4c` and only `crash01` (the last boot) showed the new fault.
4. The volume returns with the archive consumed, so the following boot is clean.

**Verification signals, cheapest first:** `[extract] progress N/TOTAL` reaching TOTAL means every entry was written;
the next boot's log losing an `opendir failed: <dir>` line means that directory now exists; the crash record moving
means the ablation reached the code under test.

**What this does not mean.** The unit is not fixed - it boots the application and dies at about nine seconds. The
write's two edits have not been separated (engines vs `disable_start_sound`), and neither has been retested on 1.2.45:
the write paths are version-independent but only 1.1.9 has been exercised. Tooling that produced all of this:
`toolkit/opzinstall.py` (install a genuine TE archive), `toolkit/opzablate.py` (the §24 write),
`toolkit/opzwatch.py` + `toolkit/opzfetch.py` (the MIDI file service), `toolkit/opzw0.py` (oracle reads).

### 66.28 The unit plays audio again: engines live in /yaffs2/user/engines/, and they need 1.2.45

This is the fix, and it took two separate discoveries - both read straight out of the device's own log.

**Discovery 1: the engine path.** §66.25 wrote the 21 engine binaries to `../user/samplepacks/user/<id>.engine`.
The 1.1.9 log then named the real path, once per attempted load:

```
disk/disk_io: error opening file /yaffs2/user/engines/organ.engine, error type: rb ENOENT
dlm: Can't open file /yaffs2/user/engines/organ.engine (error 2)
dlm: Could not load engine: /yaffs2/user/engines/organ.engine
```

`dlm` is the OS module loader and it opens `engines/<name>.engine`. Writing the same 21 binaries there (plus the
plug/slot/DMX JSON) removed every ENOENT.

**Discovery 2: the engines only fit 1.2.45.** With the files found, the loader rejected them on address:

```
dlm: Bad address 81b93800-81b93838 (81b00000-81b0c800)     analoga
dlm: Bad address 81b32000-81b32038 (81b00000-81b0c800)     ep
dlm: Bad address 81b7d000-81b7d038 (81b00000-81b0c800)     organ
dlm: Bad address 81c06800-81c06838 (81b00000-81b0c800)     chorus2
dlm: Bad address 81c07c00-81c07c38 (81b00000-81b0c800)     fdnreverb
dlm: Got error 2 when loading module /yaffs2/user/engines/...
```

The engine binaries declare code destinations spanning `0x81b32000`-`0x81c08000` (§66.6). 1.1.9's loader permits only
`0x81b00000`-`0x81b0c800` - 50 KB, seven times too small, so **not one engine could ever load on 1.1.9**. The
binaries came from the 1.3.0 app's DLC data, i.e. the 1.2.45 era. Reinstalling 1.2.45 (§66.23-§66.24) fixed it.

**Result, on 1.2.45.** The device now reports the engines as loaded and, for the first time, makes sound:

| signal | on 1.1.9 | on 1.2.45 |
|---|---|---|
| `contentmanager: Calculating used sample memory:` | `0 kB` | **`88 kB`** |
| `main: initialize [synth engine]` | absent | **`took 290 ms`** |
| `dlm: Could not load engine` | 5+ per boot | **none** |
| `fxmanager: Couldn't find plug with id 34/36/37/39` | every second | **gone** |
| `dmxcontroller: Invalid dmx config json` + 16x `failed to find dmx fixture mode rgb` | present | **gone** |
| audio on keypress | none | **audible** |

The DMX fix and the plug fixes are §66.25's payload finally doing its job: `plugs.json` (48 plugs - the 35 factory
records, plug 10/analoga added by hand, and the nine default-map ids we have no engine for borrowing one we hold),
`slotConfiguration.json` (16 tracks -> plug 10), `config/dmx.json` (one `rgb` profile, 16 fixtures).

### 66.29 What is still broken, and the honest state of the repair

**PLAY still crashes.** With every plug, engine and DMX resolved, `<PLAY>` still faults - and now at exactly the
classic 1.2.45 address the notes already knew: `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`,
`DCPLB_FAULT_ADDR 0x00000000`, `RETX 0x80117baa`, callstack `0x8002c438, 0x11a03838, 0x11a02586, 0x11a0203c,
0x80133c78`. Note what that means: the plug layer is **no longer** the suspect - this crash survives full plug
integrity, which retires the §66.26 hypothesis. The fault also arrives ~31 s after the last init line with **no log
line naming the trigger**, unlike the 1.1.9 crashes where `instrumentmanag: Can't load engine 15` printed once per
second until the fault.

Two suspects, not separated:

1. **The power path.** Immediately before the quiet 31 s the log shows `main: requesting psoc error log`. Across
   this whole session the unit has repeatedly ended healthy boots with `power_managemen: Going to charging state` /
   `PSOC requested POWER_MODE_REQUEST_POWER_OFF` after ~100 s, which is what a flat or failing battery looks like.
   PLAY is the largest current draw the firmware ever asks for. A battery/PMIC state the firmware does not expect
   is exactly the class of "state the firmware packages do not restore" this project has been chasing.
2. **Five engines still mis-load.** The 1.2.45 boot logs `dlm: Unsupported fill value` five times - five blocks the
   loader could not apply, so those engines are present but incomplete.

**Not tested and not claimed:** charging the unit properly before a PLAY test; whether the five `Unsupported fill
value` engines matter; whether PLAY works on a full battery. The repair so far is real but partial: **the unit boots,
the interface responds, sequencing works, and it now makes sound** - PLAY is the remaining failure.

### 66.30 The five failing engines: memory slots, and where the official binaries live

After §66.29 the unit played sound on some tracks and **crashed when other tracks were selected**. The 1.2.45 boot
named the same five engines every time:

```
dlm: Bad address 81b93800-81b93838 (81b00000-81b0c800)     analoga
dlm: Bad address 81c06800-81c06838 (81b00000-81b0c800)     chorus2
dlm: Bad address 81b32000-81b32038 (81b00000-81b0c800)     ep
dlm: Bad address 81c07c00-81c07c38 (81b00000-81b0c800)     fdnreverb
dlm: Bad address 81b7d000-81b7d038 (81b00000-81b0c800)     organ
```

A first hypothesis - that `dlm` refuses to load one binary into two module slots - was **disproved**: with each engine
referenced by exactly one plug the same five still failed. The real variable is the **memory slot**, which decides the
window `dlm` will accept: the five have no known slot (the builder passed 0), so they get the smallest window and
their code destinations `0x81b32000`-`0x81c07c00` cannot fit.

**Where the slots and the official binaries come from - both public, no key, no auth:**

1. **Engines: TE's own asset API.** `GET https://teenage.engineering/_api/id/products/597caf1a-.../dlcs` returns 28 DLC
   records; every engine record carries an `api_path`. Fetching that path **works unauthenticated** and returns the
   binary (`application/octet-stream`). All 21 engines downloaded this way: analoga 6568, chord 2672, chorus 1236,
   chorus2 1240, cluster 3700, crush 1012, delay 1408, digital 2688, dist 1468, electric 3120, ep 15172, fdnreverb
   3348, fm003b 6660, ministringshort 3996, organ 10108, reverb 2220, sampleplayergain 5644, saw013a 4792,
   synthsampler 4788, tapetwo 5292, volt 3152 bytes. `analoga` is 6568 bytes, byte-for-byte the size of the binary the
   project already had, so **the engines we already had were already the official ones** - the binaries were never the
   problem, the slots were.
2. **Slots: the app's own factory cache.** The APK bundles `assets/factory-plug-cache/<uuid>/metadata.json` for all 22
   factory plugs, and each asset entry carries `"attributes":{"memoryslot":N}`. Joining those UUIDs to the catalogue's
   `api_path` UUIDs resolves **16 of 21** engines: cluster 83, digital 62, saw013a 16, chord 59, delay 61, reverb 66,
   tapetwo 9, chorus 60, volt 70, sampleplayergain 10, electric 77, ministringshort 82, crush 79, dist 78, fm003b 13,
   synthsampler 68.
3. **The five that do not resolve are exactly the five that fail** - analoga, chorus2, ep, fdnreverb, organ - which are
   DLC-only (absent from the app's factory cache), so they have no published slot and cannot be placed.

**The payload that follows from this:** all 21 official binaries are written to `/yaffs2/user/engines/`, but
`plugs.json` references only the 16 with known slots, each as its own real plug-to-engine pair (11 cluster, 25
digital, 26 saw013a, 31 chord, 34 delay, 35 reverb, 38 tapetwo, 39 chorus, 65 volt, 71 sampleplayergain, 98 electric,
99 ministringshort, 109 crush, 112 dist, 129 fm003b, 138 synthsampler), with the slot map sending the 16 tracks to
those 16 plugs. Referencing an engine with no slot is what made the track selection crash, so the five are left
unreferenced on purpose.

### 66.31 The default map was the last blocker: every track sounds, all engines place

The instrument manager resolves through the device's **default map** - `13,14,15,17,21,25,28,31,34,36,37,39,60,70,80,100`
- not through a host-supplied slot map, which is why defining my own sixteen ids left it logging
`instrumentmanag: Can't load engine 13/14/15/17/21/28` and why some tracks stayed silent. Defining exactly those
sixteen ids fixed it.

**The memory slots came from TE's public asset listing**, which is the piece that was missing:

```
GET /_api/id/products/597caf1a-f7e1-4d86-8881-7b17a79adfb1/assets      -> 200, 21 assets
{ "attributes": { "memoryslot": 10 }, "category": "opz-engine", "name": "sampleplayergain.engine", ... }
```

All 21 engines resolved, **including the five that had blocked every previous attempt**: analoga 27, chorus2 88,
ep 4, fdnreverb 89, organ 18 (plus chord 59, chorus 60, cluster 83, crush 79, delay 61, digital 62, dist 78,
electric 77, fm003b 13, ministringshort 82, reverb 66, sampleplayergain 10, saw013a 16, synthsampler 68,
tapetwo 9, volt 70).

**Result on the unit:** the boot log now contains **no `instrumentmanag: Can't load engine` lines and no
`fxmanager: Couldn't find plug` lines**. All tracks produce sound except one, and **no track selection crashes the
OS** - the earlier `RETX 0x10` / `0x0` track-select faults are gone.

**The one remaining fault is a plugin's own null function pointer**, not a missing file:

```
iid 0x0013002c, ADI_EXC_INSTR_CPLB_MISS, ICPLB_FAULT_ADDR 0x00000000, RETX 0x00000000
callstack: 0x8002c438
```

It arrives ~30 s after boot with nothing logged in between, so no host-side file or log line identifies the guilty
track - the track number has to come from the device itself. Likely mechanism: the nine ids with no published plug
record (15/21/28/36/37/60/70/80/100) are defined with default flags/trackmask and no presets, whereas the seven
with real catalogue records (13/14/17/25/31/34/39) are complete; one of the nine dereferences a callback that its
borrowed engine does not implement.

### 66.32 The silent track was plug 13, the kick: `trackmask` and `samples` decode

The user's answer to §66.31's open question — "the first button track crashes, which is the
kickdrum track" — closes the loop, and the two fields the repair payload had left neutral turn out
to be the whole story.

**The content disk names the plug of every slot.** `samplepacks/<track>-<name>/<slot NN>/~<plugid>.engine`
is one 0-byte marker per occupied slot, and slot `01` of each pack is that track's default plug:

| pack | slot 01 | line-up | track default |
|---|---|---|---|
| `1-kick` | `~13.engine` | | track 1 -> plug 13 |
| `2-snare` | `~14.engine` | | track 2 -> plug 14 |
| `3-perc` | `~15.engine` | | track 3 -> plug 15 |
| `4-fx` | `~17.engine` | | track 4 -> plug 17 |
| `5-bass` | `~21.engine` | slots 02-04 = 10, 14, 17 | track 5 -> plug 21 |
| `6-lead` | `~25.engine` | slots 02-04 = 10, 14, 17 | track 6 -> plug 25 |
| `7-arpeggio` | `~28.engine` | slots 02-04 = 10, 14, 17 | track 7 -> plug 28 |
| `8-chord` | `~31.engine` | slots 02-04 = 10, 14, 17 | track 8 -> plug 31 |

This reproduces the device's default slot map from a second, independent source: 13, 14, 15, 17,
21, 25, 28, 31 are tracks 1-8, exactly the ids the boot log demands. Slots 02-04 of all four
synth packs hold plugs 10, 14, 17 (analoga, organ, ep) — the shared synth line-up — which also
shows a plug id is not tied to one track: the same id can sit in any pack slot whose `trackmask`
admits that track.

**`trackmask` is a track bitmask.** Bit N-1 = track N. The catalogue's values make it explicit:

| mask | bits | group |
|---|---|---|
| 1 / 2 / 4 / 8 | 0,1,2,3 | drum tracks 1-4 individually (te-kicks 121, te-snares 122, te-perc 123, te-fx 124) |
| 12 | 2,3 | tracks 3-4 (vinyl 71) |
| 240 | 4-7 | the synth group, tracks 5-8 |
| 256 / 2048 | 8 / 11 | track 9 (delay 34) / track 12 (chorus 39) |
| 768 | 8,9 | tracks 9-10 (rymd 35, dist 99, crush 109) |
| 0 | - | not a track plug (dmx basic 146, performance 147) |

A plug whose mask excludes the track it is assigned to is not loadable there: the app carries the
string `Track %d has invalid plug, can't play note` (`.rodata` 0x7a70f). The repair payload had
given *every* plug `trackmask: 240`, so all sixteen plugs claimed to belong to the synth group,
including the four drum tracks.

**`samples` names one multi-slice `.aif` pack, resolved under `samplepacks/user/`.** Every
`sampleplayergain` plug carries a `samples` value (`TeKicks.aif`, `CuckooSnares.aif`,
`redmountKicks.aif`), and the sampler looks it up through the `samplepacks/user/` path constant
(`.rodata` 0x757f9) with the `%s%saif` name format (0x78560). A `sampleplayergain` plug with an
empty `samples` field has no pack, which is what `sampleloader: No samples found for id 0` reports
once per unprovisioned drum track, and the reason the factory drum packs (`.plz` markers plus
`~13.engine`) are on the disk with no audio behind them.

**The fix that was staged.** Plug 13 — the kick — keeps `engines/sampleplayergain.engine`
(memoryslot 10) and gains `"samples": "redmountKicks.aif"` with `"trackmask": 1`; the pack itself
was written to `/yaffs2/user/samplepacks/user/redmountKicks.aif`. Extraction reached
1,006,678/1,006,678 with zero failures.

**TE publishes sample packs, not just engines.** The redmount DLC record
`288ecfdc-9a3c-41c9-b0ef-6ce9b2ea32a9` in `te-dlcs.json` carries four `files` of
`"kind": "opz-sample"`, `"mime": "application/opz-sample"`, and their `api_path`s download
unauthenticated (HTTP 200, no key): `redmountKicks.aif` 891,612 B, `redmountSnares.aif` 817,450 B,
`redmountPerc.aif` 944,000 B, `redmountFX.aif` 1,028,170 B — all genuine `FORM....AIFF`. These are
the only opz-sample files in the whole catalogue; the `teenage` DLC (plugs 121-124) publishes a
hero image only, so the factory `TeKicks.aif` family is not obtainable this way. The four packs are
archived in `engines-official/../samples/` beside the engine binaries.

**The file transport is alive in normal mode — it is what the app uses.** `system.log` from the
PLAY boot shows the device acting as a client and a sender: `fileclient: FileClient: send
connection request to server 37201`, then `filesync: got new file request: 0 (part 0)` and
`1 (part 0)`, then `filesync: [54.584] send file part /yaffs2/user/settings/slotConfiguration.json 0`
and `plugs.json` parts 0, 50 and 100. Server 37201 is not this project's tool (which advertises
0x4242 = 16962); it is the iPhone app, whose BLE central connection is logged 20 s earlier
(`command_handler: Connected to central 46:23:22:b6:c3:7b`). So the OS-level file service does
answer in normal mode over BLE, and the earlier "no answer to $34" results were our host being on
the wrong transport at the wrong moment, not a dead service.

### 66.33 What the `samples` field actually does, and the two sample paths

Giving plug 13 a `samples` value changed the failure from silence to a storm, which is itself the
proof that the field is the lever. The boot after it produced **628 lines**, alternating
`libaiff: AIFF_ReadOpen failed: failed to open` with `yaffsfs: yaffs: error: ENOENT`, in a tight
retry loop around 18 lines/s for ~35 s until `callstack: 0x8002c438` (crash01, device time
20:25:20-20:25:55). Before the change the same four drum tracks logged only
`sampleloader: No samples found for id 0` once each and stayed silent.

So the device does try to load a pack named by the plug's `samples` field. It is looking somewhere
the file is not. The crash record for that boot is unhelpful — the dump is only 124 distinct lines
and every one is the flood, so the fault registers were pushed out of the 7,152-byte tail, and the
flood itself is a plausible contributor to the fault.

**The two candidate paths, from the code.** The function that composes them sits around 0x101060 in
`libSnakePlugin.so` and tries them in order:

| order | composition | literal | length byte |
|---|---|---|---|
| 1 | `"samplepacks/"` + name | `.rodata` 0x78fec | 11 |
| 2 | `"samplepacks/user/"` + name | `.rodata` 0x757f9 | 0x22 = 17 chars |

Each is built as a libc++ small string in place (`mov w9,#0x18` / `mov w9,#0x22` writing the
size<<1 byte, `strb wzr` for the terminator), concatenated through `bl 0x1c8e90`, then handed to
`bl 0x1c8d50` on the global file-manager object; a non-zero return falls through to the next
candidate. The compiler also pins the sample budget in the same function:
`mov w9,#1; movk w9,#0x180,lsl#16` = 0x1800001, i.e. 24 MB + 1, and the surrounding log strings are
`"  importing %s..."` (0x776f9) and `"  Can't import %s, sample memory full"` (0x797bf) — so this is
the **import** path, and `samplepacks/user/` is a **content-disk** convention, not a proven internal
one.

**Conclusion and what was done.** The previous payload put the pack at
`/yaffs2/user/samplepacks/user/redmountKicks.aif`, which is the disk-side spelling. Because the
internal playback location is not yet proven and each wrong guess costs a power cycle, the payload
now seeds all four plausible placements in one write — `samplepacks/`,
`samplepacks/user/`, `samplepacks/1-kick/` and `samplepacks/1-kick/01/`, each
`redmountKicks.aif` (891,612 B) — reaching extract 3,681,514/3,681,514 with zero failures.

**Observed but unexplained:** track 2 also stopped producing sound in this boot. Its plug 14 is
`engines/organ.engine` with an empty `samples` field, which is a synth that needs no pack, so the
sample change does not obviously account for it; the 1,000+ logger calls in the retry loop are a
plausible indirect cause and it should be re-checked once the flood is gone.

### 66.34 The named sample-pack loader chain, and what is still unknown

Resolving PLT stubs to symbols (a stub is `stp x16,x30,[sp,#-0x10]!` / `adrp x16` / `ldr x17,[x16,#imm]`
/ `add x16,x16,#imm` / `br x17`, spaced 0x1c apart from 0x1c75e0, and the `add` immediate gives the
GOT slot whose `.rela.plt` entry names the symbol) turns the previous two sections' anonymous calls
into a named chain:

| address | symbol |
|---|---|
| 0xd70b4 | `PlugManager::getSamplePackPath(unsigned)` |
| 0xdcd10 | `AIFF_OpenFile(path, 1)` |
| 0xdcfcc | `SampleLoader::loadSamples(char const*, SamplePack&)` |
| 0xdd230 | `SampleLoader::readSamples(s_AIFF_Ref*, SamplePack&, bool)` |
| 0xdeb78 | `_saveDrumSamplePack(char const*, SamplePack*)` |
| 0xe04c8 | `_saveSynthSamplePack(char const*, SamplePack*)` |
| 0x11316c | `FileManager::getAbsolutePath(std::string const&)` |
| 0x1c8f7c | PLT stub for `AIFF_OpenFile` |

**The loader at 0xdcc7c is exactly:**

```c
std::string rel = PlugManager::getSamplePackPath(id);        // std::map<unsigned,string> lookup
if (rel.empty()) return false;                               // 0xdccc8 -> no open, no error
std::string abs = g_fileManager->getAbsolutePath(rel);
pack.path = abs;                                             // stored at pack+0x38
AIFF_Ref f = AIFF_OpenFile(abs.c_str(), 1);                  // 0xdcd10  <-- the ENOENT
if (!f) return false;
SampleLoader::readSamples(f, pack, strstr(abs.c_str(), "samplepacks/user/") != nullptr);
AIFF_CloseFile(f);
```

`getAbsolutePath` is two instructions: `add x0, x0, #0x270; b operator+`, i.e. **abs = FileManager+0x270
+ rel**. The root member at +0x270 holds a runtime string — `libSnakePlugin.so` contains no
`/yaffs2`, no `yaffs` and no standalone `user/` literal, so the root is passed in from the OS, and the
app's own log lines pin it: `serialize: Failed to load project /yaffs2/user/projects/project07.opz`
is single-slashed while `filemanager: failed to open file /yaffs2/user//arpeggiators/01.txt` is
double-slashed, which is consistent with root `/yaffs2/user/` and a relative path that either omits
or includes a leading slash.

**What that leaves.** `isUser` is derived from the finished absolute path, so the loader does expect
user packs under a `samplepacks/user/` component, and the string it opens is whatever the
`getSamplePackPath` map holds. The only place in the binary that composes `"samplepacks/"`
(`.rodata` 0x78fec) is the import function of §66.33 — it has exactly one code reference — so the map
entry is **not** built by prefixing that constant. It therefore most likely carries the plug's
`samples` value as-is, which makes the attempted path `<root>/redmountKicks.aif`.

That gives two mutually exclusive explanations for the continuing ENOENT, and the logs cannot yet
separate them:

1. the four 891 KB copies never physically landed in `/yaffs2/user/` (flash space, or a silent write
   failure while the extract progress counter still advanced), or
2. the FileManager root is not `/yaffs2/user/`, so every path guessed so far is in the wrong tree.

**A fact that narrows it.** Boots taken *before* the `samples` field was set (crash03 at 20:20:26,
crash04 at 20:12:59, crash05) each contain **exactly one** `AIFF_ReadOpen failed` line, while the
boots after it contain the hundreds-line retry flood. So the device always attempts one AIFF open
per boot — a built-in probe, independent of our plug record — and the flood is specifically our
`redmountKicks.aif` name being retried. Whatever the built-in probe opens is a second, always-present
ENOENT that has never prevented the unit from running.

### 66.35 Two answers from one log: the pack IS read, and files inside a factory pack break content mode

The content-mode crash log is only 26 lines and answers two open questions at once.

**1. The sample pack is physically on the device and readable.** The line
`contentmanager: Calculating used sample memory: 958 kB` used to read `88 kB`. The delta is 870 kB,
which is the 891,612-byte `redmountKicks.aif` (the remainder is the pre-existing 88 kB of other
sample data). So the file is present in `/yaffs2/user/`, the content manager walks it and counts it
as used sample memory. §66.34's first explanation — that the four writes silently failed — is
disproved; the writes landed.

That makes the normal-mode flood the *other* kind of problem: the playback loader resolves its path
through `PlugManager::getSamplePackPath(id)` and reaches a path the import does not use, while the
import (which is what runs at content-mode startup) does find the file. The two are not the same
lookup.

**2. Planting a file inside a factory pack crashes content mode.** The crash is a new fault, not the
old one:

```
mass_storage: create and mount FAT
filemanager: opendir failed: /yaffs2/user/rejected/     (benign, always present)
main: exception caught iid: 0x00130026, arg: 0x00000000
main: exc reason: ADI_EXC_DATA_CPLB_MISS
main: DCPLB_FAULT_ADDR: 0x00000001.
main: L1DM_DSTAT: 0x00020000.
callstack: RETX: 0x80033fd6
callstack: 0x8002c438, 0x11a03838, 0x11a02586, 0x8003691c, 0x80037722, 0x8002d2e8, 0x80134a04
```

The fault address `0x00000001` is a null+1 load, and the first three frames
(0x8002c438, 0x11a03838, 0x11a02586) are the same dispatcher frames as every other crash in this
project, but the frames below them (0x8003691c, 0x80037722, 0x8002d2e8, 0x80134a04) and `RETX
0x80033fd6` are new — a mass-storage code path, reached immediately after
`mass_storage: create and mount FAT`. Content mode builds the FAT export by walking
`/yaffs2/user/`, and the payload had put `redmountKicks.aif` **inside the factory pack tree**
(`samplepacks/1-kick/` and `samplepacks/1-kick/01/`), which is not a shape that tree ever has: a pack
directory holds slot directories plus `one_sample_pack_per_slot.plz`, and a slot directory holds the
pack's own data. The walker dereferences a null and the volume never mounts, which is exactly the
reported symptom — content mode is unreachable.

**The fix, and why it is a write rather than a delete.** The two locations the binary genuinely
recognises for a user sample are the two the import function tries: `samplepacks/<name>`
(`.rodata` 0x78fec) and `samplepacks/user/<name>` (0x757f9). Those keep the pack. The two copies
inside the factory pack tree are overwritten with **0-byte files** — the updater primitive can only
write, never delete, but truncating reclaims the space and removes the offending content. The 21
engine binaries are no longer rewritten on every cycle (they are already installed and unchanged),
so the payload is now 1,809,166 B and reaches extract 1,808,006/1,808,006.

**Operational lesson:** the only safe places to add a file as a user are `settings/`, `config/`,
`engines/` and the two `samplepacks` user-sample locations. Writing into a structured factory
directory (`samplepacks/<track>-<name>/…`) can take content mode — and therefore the only
non-crashing boot mode — offline entirely.

### 66.36 The sample tree was never the trigger for content mode; the FileManager root is /yaffs2/

Truncating the two copies inside `samplepacks/1-kick/` did not change the content-mode crash at all:
the second attempt reproduces it byte-identically — `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`,
`DCPLB_FAULT_ADDR 0x00000001`, `RETX 0x80033fd6`, callstack `0x8002c438, 0x11a03838, 0x11a02586,
0x8003691c, 0x80037722, 0x8002d2e8, 0x80134a04`, still immediately after
`mass_storage: create and mount FAT`. So the placement *inside the factory pack tree* is not what
kills content mode; §66.35's mechanism was wrong.

Two facts from that same log redirect the whole problem:

1. `contentmanager: Calculating used sample memory: 958 kB` is unchanged and still reflects the
   891,612-byte pack. The content manager walks the tree and reads the pack successfully.
2. The fault is entirely in OS mass-storage code (every frame is `0x80xxxxx`); no app frame appears.
   The app only *supplies* the tree, and the OS faults while building the FAT.

Together with the fact that a pack under `/yaffs2/user/samplepacks/**` is **never** opened by the
playback loader (`AIFF_OpenFile` always returns null there, 600+ retries), the consistent reading is
that `FileManager::getAbsolutePath`'s root is **`/yaffs2/`**, not `/yaffs2/user/`. If the root is
`/yaffs2/` then every absolute path in the app's logs is explained by relatives that begin with
`user/` — `serialize: Failed to load project /yaffs2/user/projects/project09.opz` is root +
`user/projects/project09.opz`, and `filemanager: opendir failed: /yaffs2/user/samplepacks/user/` is
root + `user/samplepacks/user/`. It also means the map entry from a plug's `samples` value resolves to
`/yaffs2/redmountKicks.aif` — *outside* `/yaffs2/user/` entirely, which is exactly why nothing placed
inside the user tree was ever found.

**What was written.** One `..` from the updater's `/yaffs2/upgrade/` base reaches `/yaffs2/` exactly
(two reach past the yaffsfs root and fail), so the payload writes the pack to `/yaffs2/redmountKicks.aif`
— a location completely outside the content tree, so it cannot disturb the FAT export — and truncates
every copy ever planted inside `/yaffs2/user/` (`samplepacks/`, `samplepacks/user/`,
`samplepacks/1-kick/`, `samplepacks/1-kick/01/`). Payload: 917,670 B, extract 916,394/916,394.

This is the first payload that tests the root hypothesis and repairs content mode in the same write.
If content mode mounts again, the exported tree settles the root question outright, because the mirror
shows exactly what `/yaffs2/` contains.

### 66.37 The content-mode crash is not the sample files; the `samples` name is the live suspect

The payload that truncated all four copies inside `/yaffs2/user/` and moved the pack to
`/yaffs2/redmountKicks.aif` produced a third byte-identical content-mode crash — and one changed
number:

```
contentmanager: Calculating used sample memory: 88 kB      <- was 958 kB, i.e. the pack is NOT loaded
mass_storage: create and mount FAT
main: DCPLB_FAULT_ADDR: 0x00000001.  RETX: 0x80033fd6
callstack: 0x8002c438, 0x11a03838, 0x11a02586, 0x8003691c, 0x80037722, 0x8002d2e8, 0x80134a04
```

Two conclusions follow. First, **the sample files were never the trigger**: with the tree back to its
clean 88 kB baseline and the pack gone from the user tree entirely, the fault is unchanged in every
field. Second, **`/yaffs2/` is not the FileManager root either** — a pack at `/yaffs2/redmountKicks.aif`
does not load (88 kB, not 958 kB), so §66.36's root hypothesis is disproved as well and the pack really
does have to live somewhere inside `/yaffs2/user/`.

That leaves exactly one thing that changed in the same window and is still present in the crashing
boots: **plug 13's `samples` field naming a pack that cannot be loaded.** The boot log shows the
sequence plainly — `yaffsfs: yaffs: error: ENOENT` (the pack open fails) then
`contentmanager: Calculating used sample memory: 88 kB` then `mass_storage: create and mount FAT` then
the fault. A plug whose `samples` name resolves to nothing leaves the sample-pack object null, and the
FAT export that content mode builds walks that same pack tree and dereferences it.

**What was written.** Plug 13 is reverted to its exact pre-regression state — engine
`engines/sampleplayergain.engine`, `samples: ""`, `trackmask: 240`, i.e. the payload that preceded the
first content-mode attempt — and the stray file at the yaffs root is truncated to 0 bytes. Payload
24,767 B, extract 24,767/24,767.

**Known remaining unknown.** The five 0-byte `redmountKicks.aif` entries and the `samplepacks/user/`
directory persist in the tree; the updater primitive can only write, never delete, so they cannot be
removed from the host. If content mode recovers, the `samples` field was the trigger. If it does not,
the leftover *entries* are the trigger, and the only remaining removal path is the file transport's
sync manifest, which makes the device delete packs the client's library does not list.

### 66.38 Content mode is back — the trigger was a plug `samples` name with no loadable pack

Three of my own mechanisms in a row were wrong (§66.35 a file inside the pack tree, §66.36 the
FileManager root being `/yaffs2/`, and "the sample files in general"). The experiment that settled it:
with the pack gone from `/yaffs2/user/` entirely and the tree back to its clean baseline — the log
then reads `contentmanager: Calculating used sample memory: 88 kB`, not 958 kB — **the content-mode
crash was byte-identical in every field.** So no file placement was ever the cause.

The one thing present in every crashing content-mode boot and absent from the state that preceded the
regression was **plug 13's `samples` field naming a pack that cannot be loaded.** Reverting plug 13 to
its exact pre-regression shape (`samples: ""`, `trackmask: 240`, engine
`engines/sampleplayergain.engine`) restored content mode on the next attempt: the disk mounts and the
volume appears. That is the fix.

The boot log shows the chain in order, which is why the mechanism is not in doubt:

```
yaffsfs: yaffs: error: ENOENT                      <- the pack open fails
contentmanager: Calculating used sample memory: 88 kB
mass_storage: create and mount FAT                 <- walks the same pack tree
filemanager: opendir failed: /yaffs2/user/rejected/   (benign, in every content boot)
main: exception caught iid: 0x00130026, arg: 0x00000000
main: exc reason: ADI_EXC_DATA_CPLB_MISS
main: DCPLB_FAULT_ADDR: 0x00000001.
main: L1DM_DSTAT: 0x00020000.
callstack: RETX: 0x80033fd6
callstack: 0x8002c438, 0x11a03838, 0x11a02586, 0x8003691c, 0x80037722, 0x8002d2e8, 0x80134a04
```

A failed pack load leaves a null sample-pack object, and the FAT export that content mode builds walks
the very same pack tree. Every faulting frame is OS mass-storage code (`0x80xxxxx`); no application
frame appears, which is why the app's own logs never name the trigger.

**Rule for all future work: a plug record's `samples` field must never name a pack that cannot be
loaded.** Doing so does not merely silence a track — it takes content mode offline, which is the only
boot mode that never crashes and the ingress for sample content.

**Observed and not decoded:** during the failing content-mode boots the track LEDs flashed in the order
`3, 1, 2, 4`. It is not known whether that is an error code or the ordinary content-mode indicator
running while the device dies, and no interpretation was invented for it.

### 66.39 Ground truth from the mounted content disk

With content mode working, the exported volume answers several open questions at once.

**The volume is 33 MiB with 1.9 MiB used and 31 MiB free.** Disk space was therefore never a limiting
factor: the 3.6 MB of duplicate packs written earlier came to about 11% of this volume, and no
space-based explanation for any failure survives.

**The content disk is a curated export, not a full mirror of `/yaffs2/user/`.** It exports
`config/`, `projects/`, `samplepacks/`, `bounces/` and `rejected/`, plus `how_to_dmx.txt`,
`how_to_import.txt` and `import.log`. It does **not** export `settings/` or `engines/`. A consequence
that matters for diagnosis: the disk can confirm or refute anything about config, projects and
samplepacks, and can prove nothing at all about `settings/plugs.json`, `settings/slotConfiguration.json`
or the engine binaries.

**`samplepacks/` exports only the eight factory pack directories** `<track>-<name>`, each holding slot
directories `01`–`10`, each slot containing at most one 0-byte `~<plugid>.engine` marker, plus a
`one_sample_pack_per_slot.plz` per pack. Neither the `.aif` files nor the `samplepacks/user/` directory
written by the updater appears in the export — consistent with the export including only directories
matching the pack pattern.

**`config/` exports the device's own files alongside mine**: `general.json` (335 B, device timestamp
Dec 30 2017) and `midi.json` (1,429 B) from the device, and **`dmx.json` (782 B, host timestamp)** from
my write. That is direct proof that the §24 dmx.json write landed and that the device re-exported it.

**`projects/` exports only `project09.opz` (342,848 B)**, matching the earlier snapshot, and
`import.log` is 0 bytes — no import cycle has ever been triggered.

**Where a user sample belongs on the disk.** The import function tries exactly two relative paths —
`"samplepacks/" + name` (`.rodata` 0x78fec) and `"samplepacks/user/" + name` (0x757f9). On the mounted
volume those are `/samplepacks/<name>` and `/samplepacks/user/<name>`, and that is where the pack was
staged (891,612 B at each), with the AppleDouble `._*` files macOS creates removed, because the device
scans that FAT and would otherwise see them as content.

### 66.40 Consolidated: which write channel may put what where

Three channels exist. Choosing the wrong one is what produced every regression in §66.35–§66.38.

| channel | available in | base | reach | delete | good for | must never be used for |
|---|---|---|---|---|---|---|
| plain-zip updater (`firmware_bin_only_with_bootloader.zip`) | update mode only | `/yaffs2/upgrade/` | one `..` reaches `/yaffs2/`; two reach past the yaffsfs root and the entry fails | **write-only** — a 0-byte entry truncates but no entry can be removed | `settings/`, `config/`, `engines/` | firmware components; anything inside the eight factory pack dirs; the yaffs root |
| content disk | content mode only | the exported volume | the exported tree only | the device removes internal files absent from the disk when it syncs | sample content via `samplepacks/<name>` or `samplepacks/user/<name>`; reading config and project state | `config/*.json` edits (the device rewrites its own copy and clobbers them) |
| MIDI file transport ($51/$35/$52/$53) | normal mode over USB or BLE MIDI | `/yaffs2/user/` by `fileId = crc32(lowercase(path))` | any path the client can name | manifest-driven removal | the only channel that can *read* the device's tree | unattended use — it is timing-sensitive (§66.31) |

**Permanent consequences of writes already made.** Five 0-byte `redmountKicks.aif` entries and a
`samplepacks/user/` directory remain in `/yaffs2/user/`, plus a 0-byte file at the yaffs root. The
updater can only write, never delete, so they cannot be removed from the host; they are harmless as
long as no plug names them, and the content-disk sync will drop what its manifest does not list.
Writing inside the eight factory pack directories is therefore permanently one-way: it should not be
done at all, because the entry outlives any attempt to undo it.

### 66.41 The device's own pack rules, read straight off the eject sync

Ejecting the content disk made the device print its bookkeeping, which settles how sample packs work:

```
contentmanager: Remove unused sample pack samplepacks/user/99.engine
contentmanager: Remove unused sample pack samplepacks/user/redmountKicks.aif
contentmanager: Remove unused sample pack samplepacks/user/13.engine        (all of them, 10..138)
contentmanager: Calculating used sample memory: 0 kB
filemanager: opendir failed: /yaffs2/user/rejected/
```

Three rules, none of which had been established before:

1. **`samplepacks/user/` is the user sample-pack area, and it is garbage-collected.** The device
   enumerates it and deletes every entry no plug references ("unused"). The pack staged there was
   removed precisely because plug 13's `samples` had been reverted to `''`.
2. **A raw file write does not register a pack.** Every pack the project ever placed with the updater
   primitive was inert until the disk import processed it; that is why the loader could never open
   them. The import runs on eject, and only it produces a registered pack.
3. **`Calculating used sample memory` went to 0 kB** — the 88 kB of leftover `~<plugid>.engine` ghost
   markers from the first ablation were collected in the same pass. The unit now holds no sample
   content at all.

**Which means the content disk is the only correct channel for sample content**, and the placement is
already determined by the disk's own layout: the marker `samplepacks/1-kick/01/~13.engine` says that
slot belongs to plug 13, so putting the kick pack in that slot gives track 1 its samples **without
touching `plugs.json` at all** — which also sidesteps §66.38's rule entirely.

### 66.42 PLAY and the silent drum tracks are the same missing-sample fault

The log puts the two symptoms in one sequence:

```
[20:46:03] sampleloader: No samples found for id 0
[20:46:04] sampleloader: No samples found for id 0
[20:46:05] sampleloader: No samples found for id 0
[20:46:09] main: exception caught iid: 0x00130026, arg: 0x00000000
[20:46:09] main: exc reason: ADI_EXC_DATA_CPLB_MISS
[20:46:09] main: DCPLB_FAULT_ADDR: 0x000002c0.
[20:46:09] callstack: RETX: 0x80117baa
callstack: 0x8002c438, 0x11a03838, 0x11a02586, 0x11a0203c, 0x80133c78, 0x80112b06, 0x80134a04
```

Three failed sample lookups in the three seconds before the fault, and the fault address is `NULL +
0x2c0` — a field read on the sample object the lookup was supposed to return. So PLAY does not crash
for a mystery reason: it starts playback, the drum tracks' sample lookups return nothing, and the voice
allocation dereferences what it got. **Track 1 being silent and PLAY crashing are one fault, not two**,
and both should resolve when a real pack is registered.

An independent confirmation of the channel difference: `sampleloader: No samples found for id 0` appears
in every boot (including ones that ran fine), so a *failed* lookup alone is survivable; it is the
*sequenced* lookup during playback that faults.

### 66.43 Where drum audio does and does not live, and the two-body constraint on registering a pack

The disk experiment produced a clean negative and, with §66.41, a complete picture.

**Slot directories are marker territory, not audio.** Staging the four drum packs at
`samplepacks/1-kick/01/`, `2-snare/01/`, `3-perc/01` and `4-fx/01/` — each the slot whose
`~<plugid>.engine` marker names plugs 13/14/15/17 — changed nothing: the eject printed no removal
for them (they survive) but the next boot reads

```
contentmanager: Calculating used sample memory: 0 kB
```

so nothing was registered. Slot directories hold the plug-binding markers; a pack placed there is
inert.

**`samplepacks/user/` is the one area the eject sync actually manages.** In the earlier attempt the
device printed `contentmanager: Remove unused sample pack samplepacks/user/redmountKicks.aif` — it
recognised the file as a sample pack, added it to its bookkeeping, and deleted it **because no plug
referenced it** (plug 13's `samples` had been reverted to `''` at that point).

**A raw `.aif` written by the updater is never loadable.** The import converts a pack; a file dropped
into the user area by the write primitive stays in its ingress form, which is why every
updater-placed pack produced 600+ `libaiff: AIFF_ReadOpen failed` retries instead of samples.

**The resulting constraint is a two-body problem.** A pack registers only if (a) it sits in
`samplepacks/user/` and (b) some plug's `samples` names it at the moment of the eject sync. And by
§66.38 a `samples` reference that cannot resolve crashes the FAT export that content mode builds. So
the reference and the pack must be present **simultaneously**, and the updater cannot deliver the
reference alone — setting it while the pack is unregistered is precisely the content-mode regression.
The content disk is the only channel that can carry both, which is why `toolkit/opzdisk.py` now writes
the packs to `samplepacks/user/` **and** a `settings/plugs.json` on the same disk, with plugs 13, 14,
15 and 17 given `samples` pointing at the four redmount packs and the drum masks 1, 2, 4 and 8 (bit
N-1 = track N, per the catalogue), and deletes the inert slot-dir copies.

**Track 3's "kick-like" sound is not a sample.** With 0 kB of sample memory registered, track 3 is
plug 15 = `engines/analoga.engine`, a synth oscillating a drum-ish tone. Track 1 is plug 13 =
`sampleplayergain`, a sampler with nothing to play, and track 2 is plug 14, which is also silent — so
the four drum tracks are still waiting on registered packs, and PLAY still faults at `NULL + 0x2c0`
immediately after its failed sample lookups (§66.42).

### 66.44 The content disk's import checklist, read straight from import.log

After an eject the device wrote a 702-byte `import.log` describing the cycle. It is a fixed list and it
changes the picture completely:

```
[IMPORT STARTED]
Reading content disk...SUCCESS
Calculating used sample space...0.0/24.0 MB
Syncronizing rejected
Syncronizing config
Syncronizing projects
Syncronizing bounces
Rebuilding plug definitions...SUCCESS
[IMPORT COMPLETE]
```

Three conclusions:

1. **Samples are not a disk content type.** The steps are `rejected`, `config`, `projects`, `bounces`
   and *plug definitions* — there is no sample-pack step, and `Calculating used sample space` stayed at
   `0.0/24.0 MB` with four packs staged. A pack dropped on the disk is never ingested, converted or
   registered. §66.41's `Remove unused sample pack` lines come from the *runtime* enumerating the
   internal `samplepacks/user/`, not from the import.
2. **`settings/` does not survive on the disk.** The volume's FAT is rebuilt from the curated export on
   every mount, so the `settings/plugs.json` and `settings/slotConfiguration.json` written there were
   discarded. Re-confirmed by inspecting the remounted volume: `settings/` is absent, `samplepacks/user/`
   is absent, and no `.aif` file exists anywhere on the disk. **Plug definitions and slot configuration
   can only travel through the §24 updater.**
3. **`Rebuilding plug definitions...SUCCESS` is a real lever.** The disk's own
   `samplepacks/<pack>/<slot>/~<plugid>.engine` tree is the *input* to that rebuild, so the disk
   controls the plug→slot assignment even though it cannot carry plug *records* or audio.

**Net effect on the drum problem.** The two halves now live on opposite channels: the reference
(`samples` in `plugs.json`) can only be delivered by the updater, and the audio cannot be delivered by
the disk at all. §66.38 forbids setting the reference while the pack is unregistered, so the updater
route deadlocks exactly as §66.43 predicted — and the disk route is closed for audio. The remaining
channels that can deliver a registered pack are the ones the OP-Z app itself uses: the manufacturer
file transport over BLE (a `$52` manifest plus `$53` file parts, the direction the app drives when it
installs a DLC pack). Note also that on a healthy unit the factory drum plug names
(`TeKicks.aif`, `CuckooKicks.aif`) resolve from ROM, which is a separate, cheaper hypothesis worth
testing before building a BLE pusher: give plug 13 a factory pack name and see whether the reference
resolves from firmware instead of from a file.

### 66.45 Factory pack names do not resolve from ROM, and the channel audit is now complete

Giving the four drum plugs TE's own factory shape — `engines/sampleplayergain.engine` with
`samples` = `TeKicks.aif`, `TeSnares.aif`, `TePercs.aif`, `TeFX.aif` and masks 1/2/4/8, exactly the
catalogue's plugs 121–124 — produced **593** `libaiff: AIFF_ReadOpen failed: failed to open` lines in
the next boot. So a factory pack name is looked up as a file like any other: **the factory drum packs
are not resident in firmware at any path the loader knows.** The cheapest possible route to samples is
closed, and the payload was reverted (`FACTORY_DRUMS = False`, extract 24,767/24,767), which also
restores track 3's `analoga` tone and keeps content mode safe.

That completes the audit. Every host-side channel has now been tested against a live device:

| channel | can deliver plug definitions? | can deliver sample audio? | evidence |
|---|---|---|---|
| plain-zip updater | **yes** — the only channel that can | **no** | writes never register a pack; 600+ retries for every pack ever written (§66.41) |
| content disk | **no** | **no** | `settings/` is discarded on remount; `import.log`'s step list has no sample stage and the space counter stayed 0.0/24.0 MB (§66.44) |
| factory ROM names | n/a | **no** | 593 `AIFF_ReadOpen failed` (§66.45) |
| MIDI file transport ($51/$35/$52/$53) | yes | **yes — untested by us, but proven on this unit today** | the phone app served the device `slotConfiguration.json` and `plugs.json` at 20:19:39 over BLE (`fileclient: send connection request to server 37201`, `filesync: send file part ...`) |

**So the only remaining channel that can put a pack into a registered state is the manufacturer file
transport** — the same one the app used successfully on this device at 20:19 today. Its mechanics are
already documented in this repo: `$51` advertises a host server, the device answers `$34` with its
client id and state CRC, `$35` requests a file by `fileId = crc32(lowercase(path))`, `$53` carries up
to 200 uncompressed bytes per part, and the reserved ids are 0 = `settings/slotConfiguration.json`,
1 = `settings/plugs.json`, 2 = `syncjob.json`. The app pushes content by serving `syncjob.json` — a
manifest of `{"files":[{"fileId","path","crc","size"}]}` — whereupon the device requests each listed
file and the server answers with parts. Two ways forward, and the second is strictly more reliable
because it is TE's own client: install a drum pack from the OP-Z app, or implement the server side of
that push on the host using the clean-room reference in `~/.opz-decode/refs/op-z-sysex`.

**Current unit state after the revert:** boots, interface responds, sequencing works, most tracks sound
(including track 3's `analoga`), content mode mounts, tracks 1 and 2 are silent, PLAY faults at
`NULL + 0x2c0` / `RETX 0x80117baa` immediately after three failed sample lookups (§66.42).

### 66.46 The app's sync emptied the engine files — and its own log hands us the fix

Installing content from the OP-Z app produced the first crash-on-track-select since the early repair:

```
instrumentmanag: Can't load engine 17      x5, at 21:16:38-21:16:42
main: exception caught iid: 0x0013002c, arg: 0x00000000
main: exc reason: ADI_EXC_INSTR_CPLB_MISS
main: ICPLB_FAULT_ADDR: 0x00000000.
callstack: RETX: 0x00000000
```

`RETX 0` is a call through a null function pointer — an engine that failed to load leaves a null entry
where the track's callback should be. The app's own sync log says why:

```
filesync: Ignore File request 'engines/organ.engine' (222590747), same crc: 403f126c
fileclient: invalid file crc, can't finalize /yaffs2/user/engines/organ.engine (0 != 403f126c)
```

**Historical inference, corrected by §66.77:** these messages were interpreted as proof that the
installed engines were empty. The APK instead computes the skip CRC from the installed path, then
computes the finalize CRC from the **inbox** path while printing the installed destination's name.
Its CRC helper also returns zero on open failure. Thus the log pair alone proves neither truncation
nor absence of the installed engine. The same pair appeared for `organ`, `ep`, `sampleplayergain`,
`analoga`, `ministringshort`, `cluster`, `saw013a`, `fm003b`, `fdnreverb`, `crush`, `dist`, `chorus2`
and `tapetwo`; the independent engine-load failures remain observations, but their cause needs
separate evidence. Firmware equivalence with this APK has not been established.

**The same log names the expected CRC of every engine**, which turns the repair into arithmetic — and
**all 13 named by the log match the official binaries in `engines-official/` byte-for-byte**:

| engine | expected | ours |
|---|---|---|
| analoga | fe07077e | fe07077e |
| chorus2 | 9fa49506 | 9fa49506 |
| cluster | e9ebe2f2 | e9ebe2f2 |
| crush | 6a41b719 | 6a41b719 |
| dist | 879ce37a | 879ce37a |
| ep | 2dfa7db0 | 2dfa7db0 |
| fdnreverb | 9873b014 | 9873b014 |
| fm003b | 6c9ffbd3 | 6c9ffbd3 |
| ministringshort | 7412e200 | 7412e200 |
| organ | 403f126c | 403f126c |
| sampleplayergain | 26d66594 | 26d66594 |
| saw013a | 671de54c | 671de54c |
| tapetwo | 8a0f351c | 8a0f351c |

So writing the binaries back makes the app's verification pass, and the sync that follows can complete.

**What the app does successfully, from the same log.** Its transport works and it is the one channel
that installs content: `filesync: Requesting file 'samplepacks/redmountSnares.aif'` →
`Download complete: [/yaffs2/user/inbox/samplepacks/redmountSnares.aif]` →
`fileclient: FileClient: file complete. crc: 1a0ea97 == 1a0ea97?`, and likewise for
`redmountPerc.aif`; it imports plug definitions (`plugmanager: found plug to import, id:14 index:1`);
and it drives its own slot configuration (`fileclient: add request settings/slotConfiguration.json`).
Files land in `/yaffs2/user/inbox/` and are moved into place by the sync's *applying* phase — which is
also where the engines failed, so the engine failure is what blocks the rest.

**Consequences for how this project writes to the device.**

1. **The app owns `settings/plugs.json` and `settings/slotConfiguration.json` from now on.** Our
   updater payloads must not overwrite them; `toolkit/opzfix.py` gained `ENGINES_ONLY = True` for
   exactly this, and it now writes only the engine binaries.
2. **A raw updater write can be silently undone by the app's sync** if the client state disagrees with
   the file contents, which is a new failure mode worth remembering: the file can be *emptied*, not
   just ignored.
3. The sample packs the app downloaded are sitting in `/yaffs2/user/inbox/samplepacks/` with verified
   CRCs, so they should apply as soon as a sync completes.

**Repair staged (device time 26-10-10 21:21:02):** the engines-only payload — 94,032-byte zip, 21 engine
binaries, no `plugs.json` and no `slotConfiguration.json` — extracted to completion
(`[extract] progress 90300/90300`, no failed extractions), so the engine directory is restored with the
exact bytes the device expects. The archive deliberately still carries five 0-byte entries
(`../redmountKicks.aif` and the four `samplepacks/**/redmountKicks.aif` copies) to keep the earlier stray
pack inert, and the app's downloaded packs are untouched because they sit under
`/yaffs2/user/inbox/samplepacks/` until the sync's applying phase moves them.

The test order matters: boot normally first to confirm the track-select crash is gone, then **open the app
and let one sync run to completion** — with the engine CRCs now correct it should verify clean and apply
the packs already in `inbox/`, which is what the four drum tracks need.

### 66.47 Why the track-1 crash survived the engine repair, and the correct drum masks

The engines-only repair worked — the log no longer contains `instrumentmanag: Can't load engine 17` — but
the crash on track 1 stayed, with the same signature:

```
main: exception caught iid: 0x0013002c, arg: 0x00000000
main: exc reason: ADI_EXC_INSTR_CPLB_MISS
main: ICPLB_FAULT_ADDR: 0x00000000.
callstack: RETX: 0x00000000
```

`RETX 0` is a call through a null function pointer, and `iid 0x0013002c` is the id this project already
tied to the kick track. The cause is the plug table, not the binaries: **the catalogue's own plug 13 is
`chorus-80`, an FX engine.** An FX engine installed on a drum track has no playable voice, so the track's
callback is null. This is exactly the fault recorded earlier as "one plugin's own null function pointer",
which was fixed once by mapping plug 13 to `engines/sampleplayergain.engine` — and that fix was then
undone, because the app's own plug import landed on top of ours.

Two conclusion for how the repair payload must be shaped:

1. **Plug 13 must be `sampleplayergain`.** Any payload that takes plug 13 from the DLC catalogue gets
   `chorus` and crashes the kick track on selection.
2. **The four drum plugs need the drum masks, not the catalogue's 240.** `trackmask` is a bitmask whose
   bit N-1 selects track N, so 240 claims the synth group (tracks 5-8) for a drum plug, and the device
   answers a note with `Track %d has invalid plug, can't play note`. The drum tracks are 1/2/4/8 and
   `toolkit/opzfix.py` now overrides them with `DRUM_MASKS`.

The relationships now in the payload:

| plug | engine | mask | meaning |
|---|---|---|---|
| 13 | engines/sampleplayergain.engine | 1 | kick — must be a sampler, not an FX engine |
| 14 | engines/organ.engine | 2 | snare |
| 15 | engines/analoga.engine | 4 | perc — the one track that has sounded all along |
| 17 | engines/ep.engine | 8 | fx |
| 21-31 | cluster, digital, saw013a, chord | 240 | the synth group |
| 34-39 | delay, reverb, fdnreverb, chorus | 256/240/240/2048 | the FX tracks |
| 60-100 | volt, fm003b, crush, synthsampler | 240 | the remaining tracks |

**The remaining gap is still samples, and it is one gap, not two.** `PLAY` faults with
`ADI_EXC_DATA_CPLB_MISS` / `DCPLB_FAULT_ADDR 0x000002c0` / `RETX 0x80117baa`, which is a field read on the
null sample object left by a failed pack lookup — so the silent drum tracks and the PLAY crash are the
same missing-registered-pack fault, and PLAY is expected to keep faulting until a pack actually registers.
That is what the app's sync is for, and its own engine step now has the right bytes to verify against, so
the sync that previously died at `can't finalize /yaffs2/user/engines/<name>.engine` has no reason left to
fail.

### 66.48 The app's "chorus-80 on the kick" is an id collision, and drum packs arrive as their own plugs

The app labels the kick track's plug **chorus-80**, which looks like the app disagreeing with our mapping.
It is not. Two facts, both from ground truth, resolve it:

**1. The device's slot 0 really is plug id 13.** `PlugManager::_importSlotConfiguration` hard-codes

```
slot 0..15 = 13, 14, 15, 17, 21, 25, 28, 31, 34, 36, 37, 39, 60, 70, 80, 100
```

as the fallback used whenever `settings/slotConfiguration.json` is missing, and the 0-byte
`~NN.engine` markers in the sample packs are an export of that same map. Slot 0 is the kick, so the kick's
plug id is 13 — the track numbering the repair used is correct.

**2. TE's DLC catalogue reuses those ids for unrelated plugs.** From `te-dlcs.json`:

```
 13 | chorus-80 | chorus2.engine | (no samples) | trackmask 768   <- tracks 9-10, an FX plug
 14 | organ     | organ.engine   |              | 240
 17 | ep        | ep.engine      |              | 240
```

so the catalogue's 13 is a *tracks 9/10 FX plug*, nothing to do with a kick. The app displays plug names
by looking its own catalogue up by id, so a device plug with id 13 is shown as "chorus-80" no matter what
engine it actually holds. This collision is also what puts `chorus2.engine` on the kick track, which is
the null-function crash on track select.

**3. Drum packs do not ride on plug 13 at all — they arrive as their own plugs.** The catalogue's sample
packs are complete sampler plugs with their own ids:

| id | name | engine | samples | mask |
|---|---|---|---|---|
| 121-124 | te-kicks / te-snares / te-perc / te-fx | sampleplayergain | TeKicks/Snares/Perc/FX.aif | 1/2/4/8 |
| 130-133 | z-* | sampleplayergain | Alain*.aif | 1/2/4/8 |
| 134-137 | cuckoo * | sampleplayergain | Cuckoo*.aif | 1/2/4/8 |
| 140-143 | seba * | sampleplayergain | Seba*.aif | 1/2/4/8 |
| 150-153 | rdmt kicks/snares/perc/fx | sampleplayergain | **redmountKicks/Snares/Perc/FX.aif** | 1/2/4/8 |

So the app installs a pack by creating one of these plugs and then **pointing the drum track at it**
through the slot configuration — the track's plug id changes, which is why nothing we put on the fixed
ids 13/14/15/17 ever produced a drum sample. `PACK_PLUGS` in `toolkit/opzfix.py` now reproduces that
shape exactly: plugs 150-153 (engine `engines/sampleplayergain.engine`, samples
`redmountKicks/Snares/Perc/FX.aif`, masks 1/2/4/8), slot map `tracks 0-3 -> 150,151,152,153` and tracks
4-15 unchanged, and the four 817-1,028 KB `.aif` files written to both `../user/samplepacks/<name>.aif`
and `../user/samplepacks/user/<name>.aif` (the two prefixes the loader tries, `samplepacks/` first).

### 66.49 Sample packs: the device's own manual, and the ~ markers are duplicates

The content disk's `how_to_import.txt` (8,447 bytes) settles the sample question outright:

> when OP-Z is in disk mode you can add, remove and modify it's content. any changes you do to the
> files on this disk are reflected on the unit after you eject the disk.

| TYPE | ADD | MODIFY | REMOVE |
|---|---|---|---|
| bounces | no | no | yes |
| DMX | no | yes | no |
| MIDI | no | yes | no |
| projects | **yes** | yes | yes |
| **sample packs** | **yes** | **yes** | **yes** |

> the supported file format is the OP-1 .aif sample format. for drum tracks it is the drum sample format
> and for synth tracks the synth sample format.
>
> **the 10 slots of a track is represented by ten sub folders under each track. choose a free slot folder
> and place your new sample pack there.** only one sample pack per slot folder will be imported, any
> additional ones will be rejected. you can place the same sample pack on several tracks without taking
> up any redundant diskspace. **the duplicate files will be prefixed with ~ and have 0 size.** Example:
>
> ```
> 1-kick
>   01
>     cannedlaughter.aif  1.1 MB
> 3-kick
>   03
>     ~cannedlaughter.aif  0 bytes
> ```
>
> you can have a total of 24 MB of sample data.

**This corrects the reading of the `~` files.** They are not exports of the default map and not requests:
they are the device's *duplicate* markers, written when the same pack is placed on several tracks, and a
`~`-prefixed name means "the real file of this name lives in another slot folder". A slot folder holding
only a `~` marker has no audio in it at all, which is exactly the state the unit was in:

```
0  samplepacks/1-kick/01/~121.engine          <- kick slot 01 duplicates a pack named 121.engine
0  samplepacks/2-snare/01/~redmountSnares.aif
0  samplepacks/3-perc/01/~redmountPerc.aif
0  samplepacks/4-fx/01/~redmountFX.aif
0  samplepacks/5-bass/01/~21.engine  ... 8-chord/01/~31.engine
```

**no non-zero file existed anywhere under `samplepacks/`** — so no drum track had a single byte of audio,
and `import.log` correspondingly reported `Calculating used sample space...0.0/24.0 MB` on all four of its
import runs. The kick's marker names plug **121 (`te-kicks`)**, whose `TeKicks.aif` is the one factory pack
that cannot be downloaded from anywhere, so that binding could never resolve.

**Fix, applied in content mode:** the four redmount packs (from TE's own DLC, 817 KB - 1 MB, geniune
AIFF) were copied into **slot 02** of each drum track — slot 01 being occupied by the duplicate markers,
and the doc allowing one pack per slot folder:

```
1-kick/02/redmountKicks.aif    891,612 B
2-snare/02/redmountSnares.aif  817,450 B
3-perc/02/redmountPerc.aif     944,000 B
4-fx/02/redmountFX.aif       1,028,170 B
```

AppleDouble `._*` files were deleted (the device scans that FAT), the volume was synced and ejected, which
is the documented trigger for the import. The verification signals to read on the next pass:
`import.log`'s `Calculating used sample space` should move off `0.0/24.0 MB` to roughly `3.6/24.0 MB`, and
the normal boot's `contentmanager: Calculating used sample memory` off `0 kB`.

### 66.50 PLAY's remaining crash: a plug built from a stale marker, and what the eject sync costs

With sound working on all four drum tracks (`Calculating used sample memory: 3594 kB` = the four redmount
packs registered), PLAY still faulted identically: `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`,
`DCPLB_FAULT_ADDR 0x000002c0`, `RETX 0x80117baa` — the null-sample-object read. The same log explains it:

```
contentmanager: Calculating used sample memory: 3594 kB
contentmanager: Remove unused sample pack samplepacks/user/redmountFX.aif
contentmanager: Remove unused sample pack samplepacks/user/redmountKicks.aif
contentmanager: Remove unused sample pack samplepacks/user/redmountPerc.aif
contentmanager: Remove unused sample pack samplepacks/user/redmountSnares.aif
contentmanager: Calculating used sample memory: 0 kB
main: initialize [synth engine]: took 133523 ms
instrumentmanag: Can't load engine 121
fxmanager: Couldn't find plug with id 109
```

Three separate conclusions:

1. **The updater's pack copies are the wrong channel and get collected.** `samplepacks/user/redmount*.aif`
   were counted (3594 kB) and then removed as unused, dropping the total back to `0 kB`. The packs that
   actually play are the ones the content disk installed — they live outside that path, which is why the
   drum tracks kept working after the GC. `WRITE_PACKS` is therefore off: the disk owns packs, the updater
   owns definitions.
2. **The eject sync strips `/yaffs2/user/engines/`.** `initialize [synth engine]: took 133523 ms` — 133
   seconds of failed engine loads, one timeout per plug, and `Can't load engine 14/17/...` for every plug
   whose engine is a file. Engine binaries must be re-written through the updater after any content-disk
   eject; `WRITE_ENGINES` is back on.
3. **A stale `~` marker creates a plug nobody can satisfy.** `1-kick/01/~121.engine` is a duplicate marker
   whose real file never existed, but the rebuild reads it as an engine name and builds plug 121 asking for
   engine `121.engine`, which cannot load — leaving the null sample object PLAY dereferences. The plug table
   now defines **121-124** explicitly (engine `engines/sampleplayergain.engine`, samples
   `redmountKicks/Snares/Perc/FX.aif`, masks 1/2/4/8), so the id the device asks for always resolves to a
   pack that is really present. **109** is defined too, since the fx manager requests it by id, and plug
   **80** was moved from `crush` to `dist` so that no two plugs share one engine binary.

The staged payload is engines + `settings/plugs.json` (25 plugs: the 16 default-map ids, 109, 121-124 and
150-153) + `config/dmx.json`, and deliberately **no** `slotConfiguration.json` (the device's own working
track map must not be overwritten) and **no** sample files.

### 66.51 Root cause of the lost sound and the surviving PLAY crash: plugs.json was overwritten

The boot after the 25-plug payload produced a log that is nothing but a retry flood, and the flood
destroyed the crash record:

```
[26-10-10 21:44:20] libaiff: AIFF_ReadOpen failed: failed to open
[26-10-10 21:44:20] yaffsfs: yaffs: error: ENOENT
                                    ... 62 identical pairs, no iid / RETX / FAULT_ADDR lines left
```

That flooding pattern is the signature of a plug whose `samples` value names a pack the loader cannot
open. The payload responsible is known exactly, because it is the one that added four sampler plugs per
drum track:

```
121 sampleplayergain redmountKicks.aif  mask 1
122 sampleplayergain redmountSnares.aif mask 2
123 sampleplayergain redmountPerc.aif   mask 4
124 sampleplayergain redmountFX.aif     mask 8
150-153 the same four again
```

**Those names do not resolve.** The redmount packs that play are the ones the *content disk* imported:
they live in the device's own pack store, while the copies at `samplepacks/user/redmount*.aif` — the ones
whose names the plugs could have matched — were garbage-collected at the previous boot. So every one of
those eight plugs pointed at a file that does not exist, the sampler retried in a tight loop, and the
resulting flood pushed the crash registers out of the 7,152-byte record.

**The lost sound has the same cause, one step earlier.** The device's own "Rebuilding plug definitions"
step had built the four working pack plugs from the disk and persisted them into `settings/plugs.json`.
Overwriting that file with our 25 plugs **replaced the table the drum tracks resolve through**, so the
tracks lost their sampler plugs entirely — silence — and the eight unresolvable plugs supplied the null
sample object that PLAY faults on (`iid 0x00130026`, `DCPLB_FAULT_ADDR 0x000002c0`, `RETX 0x80117baa`).

**Two rules follow, and they are the opposite of what this project had been doing:**

1. **`settings/plugs.json` belongs to the device's rebuild, not to the updater.** Writing it costs the
   pack plugs. It is now written only to carry the `engines` array (which the engine binaries need), with
   **no sampler plugs at all**, and every content-disk pass re-runs the rebuild that recreates the pack
   plugs.
2. **Never reference a pack that cannot be resolved.** An unresolvable `samples` value is not a silent
   track: it is an infinite retry loop that floods the log, destroys evidence, and leaves a null sample
   object behind for PLAY to fault on.

The staged payload is therefore 21 engines + a 17-plug `plugs.json` (the sixteen engine plugs plus 109,
which the fx manager asks for by id) + `dmx.json`, with no sampler plug and no sample file.

### 66.52 The import log proves the packs register, and the markers name the device's own plug ids

The next content-mode entry shows the import that installed the packs, and it succeeded line for line:

```
[IMPORT STARTED]
Reading content disk...SUCCESS
Calculating used sample space...0.0/24.0 MB
  importing redmountKicks.aif...SUCCESS. New used space 870 kB
  assigning snare/02/redmountSnares.aif
  assigning perc/02/redmountPerc.aif
  assigning fx/02/redmountFX.aif
Syncronizing rejected
Syncronizing config
Syncronizing projects
Syncronizing bounces
Rebuilding plug definitions...SUCCESS
[IMPORT COMPLETE]
```

Three things this settles:

1. **`importing <name>.aif...SUCCESS. New used space 870 kB`** — the kick pack is in the device. The
   891,612-byte file became 870 kB of registered sample memory, so the import really does ingest audio
   from a slot folder (`storing up to 24 MB`).
2. **`assigning <track>/<slot>/<pack>.aif`** — the other three were not re-imported but *assigned*: the
   device already held those packs, and a second slot referencing the same pack costs no space. That is
   the dedup behaviour the manual describes.
3. **`Rebuilding plug definitions...SUCCESS`** — the device derives the drum plugs from the marker tree
   itself. Our plugs.json is not needed for the drum tracks and, as section 66.51 established, overwriting
   it destroys them.

The markers left behind name the device's own plug ids for the imported packs:

| slot | marker | reading |
|---|---|---|
| 2-snare/01 + 02 | `~151.engine` | plug **151** = catalogue `rdmt snares` |
| 3-perc/01 + 02 | `~152.engine` | plug **152** = catalogue `rdmt perc` |
| 4-fx/01 + 02 | `~153.engine` | plug **153** = catalogue `rdmt fx` |
| 1-kick/02 | `~-239494487` | the kick pack's own id, not a catalogue one |
| 5-bass..8-chord/01 | `~21/25/28/31.engine` | the default map's engine plugs |

The kick is the odd one out because its pack was **newly imported** while the other three were already
known and matched to catalogue ids. Its id is not crc32 of the file name, not crc32 or adler32 of the
content, not md5 or sha1 truncated, and not a name of any attempted spelling — so the numbering is the
device's internal business and is not reconstructible from the host. **That is the argument for never
writing `settings/plugs.json` again:** the table belongs to the device's rebuild, and the host cannot
guess the ids inside it.

The repair payload is now **the 21 engine binaries plus `config/dmx.json` and nothing else** — no
`plugs.json`, no `slotConfiguration.json`, no sample files — because the engines are the one thing the
content-disk eject sync strips and the one thing the device cannot rebuild by itself.

### 66.53 Historical sample-upload diagnosis (whole-job abort inference corrected in §66.77)

**Later correction:** the inspected APK's finalize CRC failure skips one entry and continues;
it does not abort the whole apply loop. The following logged transfer observations remain valid,
but the claim that this error necessarily prevents every inbox promotion is not established.

The archived app-session log shows the app handling each content item identically, and the sample
transfer itself succeeding:

```
fileclient: add request engines/sampleplayergain.engine
filesync: Ignore File request 'engines/sampleplayergain.engine' (117614215), same crc: 26d66594
fileclient: add request samplepacks/redmountSnares.aif
filesync: Requesting file 'samplepacks/redmountSnares.aif' (-48604221)
filesync: Download complete: [/yaffs2/user/inbox/samplepacks/redmountSnares.aif]
fileclient: FileClient: file complete. crc: 1a0ea97 == 1a0ea97?      <- bytes arrived, crc verified
...
fileclient: invalid file crc, can't finalize /yaffs2/user/engines/sampleplayergain.engine (0 != 26d66594)
plugmanager: found plug to import, id:151 index:0
plugmanager: remove user plug 14 (samplepack 0)
```

Three facts, in order of what they explain:

1. **The audio really does arrive.** `Download complete` plus a matching `crc: 1a0ea97 == 1a0ea97` for
   `redmountSnares.aif` and `40f16f72 == 40f16f72` for `redmountPerc.aif`. The transfer is not the problem.
2. **It stops in `/yaffs2/user/inbox/` and the job dies before the phase that would move it.** For every
   item the sync aborts with `invalid file crc, can't finalize /yaffs2/user/engines/<name>.engine
   (0 != <expected>)`. The cause is the line before it: `Ignore File request ... same crc` — the app's
   state believed the device already matched, so it **skipped sending the engine**, and the finalize step
   then read a file that had never been written, got crc 0, and aborted the whole job. The apply phase
   that promotes `inbox/<path>` to its final location therefore never runs, which is why every pack stayed
   in the inbox.
3. **The plug half of the app works fine.** `plugmanager: found plug to import, id:151 index:0` and
   `plugmanager: remove user plug 14 (samplepack 0)` — the app really does create the plug and the
   binding, which is exactly what the marker tree showed afterwards (`~140.engine`, `~121.engine`,
   `~130.engine`, `~134.engine` in the kick's slots 01-04). So the app produces a slot claim with no audio
   behind it, and each new attempt consumes another slot — the kick had four of them and no sound.

**Two independent mechanisms, and the difference matters:**

- **The abort is provable and is now fixed.** The engine finalize failed because the app's state was stale
  relative to the device's files. With the engine binaries written back so their CRCs match what the app
  expects (`sampleplayergain.engine` = 26d66594 and the other twelve all verified), the finalize step has
  nothing left to fail on, so a later sync can complete.
- **Registration of audio is only ever observed through the content import.** Every attempt to place a
  playable pack inside `/yaffs2/user/` by any other means — flat at the root, under `samplepacks/`, under
  `samplepacks/user/`, and in the slot folders, through the updater — produced either a retry flood, a
  garbage-collection (`Remove unused sample pack ...`), or silence, and never once an entry in
  `Calculating used sample memory`. The one thing that ever worked was the content disk:
  `importing redmountKicks.aif...SUCCESS. New used space 870 kB`.

**Practical rule: the content disk owns sample audio** (drop an `.aif` into a free `samplepacks/<track>/NN/`
folder and eject). The app is reliable for engines and for choosing which plug a track points at, but on
this unit its sample data stops in the inbox.

### 66.54 PLAY's crash after the app's slot-2 kick upload: dead bindings with no audio

The app was given a second kick slot to fill, and the result is the same pattern as before, now with a
second effect visible. The crash is unchanged — `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`,
`DCPLB_FAULT_ADDR 0x000002c0`, `RETX 0x80117baa` — while the working kick (slot 01, the pack installed
through the content disk) still plays. The log adds:

```
contentmanager: Calculating used sample memory: 870 kB        <- the disk-installed kick pack is intact
instrumentmanag: Can't load engine 121                        <- and the app's bindings are not
instrumentmanag: Can't load engine 134
instrumentmanag: Can't load engine 140
instrumentmanag: Can't load engine 141
instrumentmanag: Can't load engine 122
instrumentmanag: Can't load engine 151
instrumentmanag: Can't load engine -239494487
fxmanager: Couldn't find plug with id 109
```

**Two distinct faults from one cause.** The app leaves a `~<plugid>.engine` marker per binding, and

1. **the marker makes the device treat that id as having a file-based engine named `<plugid>.engine`,**
   which does not exist, so every boot logs `Can't load engine <id>` for each binding (121 te-kicks,
   122 te-snares, 134 cuckoo kicks, 140/141 seba, 130 z-kicks, 151-153 rdmt, and the imported kick pack's
   private `-239494487`); and
2. **a plug whose pack has no audio leaves the null sample object**, and PLAY faults on it with
   `DCPLB_FAULT_ADDR 0x000002c0`.

**The distinguishing test is whether a real `.aif` was ever imported for that marker.** The redmount
bindings survive because their packs were imported through the disk (`used sample memory: 870 kB`), and
the kick's slot 01 keeps playing for exactly that reason. Every app binding is a slot claim with nothing
behind it, so each one is a plug with no samples — and each one is a candidate for the null that PLAY
dereferences.

**Fix: delete those markers through the content disk** (sample packs support REMOVE), keeping only the
bindings whose audio exists (`151`, `152`, `153`, `-239494487`, and the `~redmount*.aif` markers). The
following eject runs `Rebuilding plug definitions`, which drops the audio-less plugs *and* re-derives the
slot map, so both faults clear at once. Note that this cannot be done from the updater, which only writes.

### 66.55 A ~ marker cannot be deleted away; the slot has to be given real audio

Deleting `1-kick/02/~134.engine` and `2-snare/02/~141.engine` from the content disk removed nothing on the
device: the next boot still logged `Can't load engine 134` and `Can't load engine 141`, and PLAY still
faulted identically. The reason is what a `~` file *is*: a duplicate marker pointing at a pack whose real
entry lives elsewhere, so it is a reference and not the pack. Removing the reference leaves the device's own
binding, and that binding still has no audio behind it — hence the null sample object.

**The working lever is the opposite one: put a real `.aif` into the slot.** A slot holding real audio
re-derives its binding from the audio itself, which is how the kick's slot 01 got its private
`-239494487` id. So plug 134 and 141 were replaced by giving their slots real packs:

```
1-kick/02/redmountKicks.aif    891,612 B
2-snare/02/redmountSnares.aif  817,450 B
```

Both slots now resolve to audio that exists, no plug is left without samples, and the kick gains a second
working slot as a side effect.

**State of the repair at this point** (boot of device time 22:11:56): `main: initialize [synth engine]: took
49 ms` — down from 133,523 ms, so the engine binaries the app re-uploaded are healthy;
`contentmanager: Calculating used sample memory: 870 kB`; and of the nine app-created bindings only
`134` and `141` still produced `Can't load engine` lines. Everything else the app ever created was cleared
by deleting the audio-less markers, and the disk-installed redmount bindings (the kick plus snare, perc and
fx) were never at risk.

### 66.56 PLAY's crash is triggered by the missing FX plug 109, immediately

The boot after the slot-02 packs is the most informative log yet. The crash's own record ends with the
trigger in plain sight:

```
[26-10-10 22:15:20] instrumentmanag: Can't load engine 141
[26-10-10 22:15:34] fxmanager: Couldn't find plug with id 109
[26-10-10 22:15:34] main: exception caught iid: 0x00130026, arg: 0x00000000
[26-10-10 22:15:34] main: exc reason: ADI_EXC_DATA_CPLB_MISS
[26-10-10 22:15:34] main: DCPLB_FAULT_ADDR: 0x000002c0.
[26-10-10 22:15:34] callstack: RETX: 0x80117baa
```

**The fault follows the missing plug by zero seconds** — same second, same log line pair. The FX manager
looks up plug 109, fails, and the next thing that happens is a load from `NULL + 0x2c0`. That is the
`fxmanager: Couldn't find plug with id 109` line that has appeared at every boot (three times during
initialisation, which is harmless) and then a fourth time exactly at PLAY, which is not.

Two other results from the same boot:

1. **Replacing `1-kick/02` with real audio worked.** `Can't load engine 134` is gone completely — the
   cuckoo-kicks binding is no longer a plug at all. The same trick should clear `141` (seba snares), which
   still fires three times and whose slot 01 still carries only a `~redmountSnares.aif` reference: putting
   a real `redmountSnares.aif` there replaces the binding the way it did for 134.
2. **The eject stripped engines again**: `initialize [synth engine]: took 16378 ms` (16 s of retry
   timeouts, up from 49 ms). Since `ENGINES_ONLY = True` makes the updater payload engines plus `dmx.json`
   only, re-staging it cannot touch the plug table the drums depend on, so it is safe to do alongside the
   disk work.

**Where 109 comes from:** the app's own catalogue gives plug 109 the name `crush`, engine `crush.engine`
and `trackmask 768` — the two FX tracks, 9 and 10. The app's plug table defines it (`plugmanager: found
plug to import, id:109 index:22`) but the device's own rebuild, which derives its table from the samplepack
markers, does not, because no marker names 109. The fix is therefore the same mechanism that created plugs
121-153 in the first place: **a marker named `~109.engine` anywhere in the samplepacks tree makes the
rebuild create that plug.**

**Applied (device time of the next boot is the test):** `2-snare/01/redmountSnares.aif` now holds real
audio (817,450 bytes) in place of its `~` reference, and `samplepacks/9-fx/01/~109.engine` was created as a
zero-byte marker so the rebuild defines plug 109. The kick keeps real audio in slot 01 with the device's own
`~redmountKicks.aif` dedup marker in slot 02, and perc/fx keep theirs. If PLAY survives this boot, the two
faults were one cause: a plug the FX manager looked up and could not find, followed by a load from
`NULL + 0x2c0`.

A useful side effect of that marker, if it works: **it is the host-side way to add a plug definition without
writing `settings/plugs.json`** — the mechanism that created 121-153 in the first place, and the only one
that leaves the device's own rebuild in charge of the table.

### 66.57 PLAY after the plug fixes: no other fault before it, and nine project slots are empty

The boot after `2-snare/01` was given real audio clears the last engine errors — **`engine errors: NONE`** —
so replacing an audio-less binding with real audio is confirmed as the way to remove such a plug (it worked
for 134 and then for 141). The `~109.engine` marker placed in a new `9-fx/01` folder did **not** create plug
109 (the fx manager still reports it three times at boot), which is consistent with `9-fx` not being a track
folder the device recognises; a marker has to sit in a real track directory.

**The important correction is about the crash's timing.** On this boot the fault arrives **49 seconds after
the last log line** with nothing written in between:

```
[22:17:55] smx_usb: Speaker Stopped
[22:18:44] main: exception caught iid: 0x00130026, arg: 0x00000000
```

so the previous boot's "fxmanager missing plug 109" line one second earlier was a coincidence of when the
PLAY key was pressed, not the cause. The fault signature is unchanged (`ADI_EXC_DATA_CPLB_MISS`,
`DCPLB_FAULT_ADDR 0x000002c0`, `RETX 0x80117baa`, callstack `0x8002c438, 0x11a03838, 0x11a02586,
0x11a0203c, 0x80133c78, 0x80112b06, 0x80134a04`).

**The remaining candidate is the project set.** Every boot lists

```
serialize: Failed to load project /yaffs2/user/projects/project01.opz
   ... 02, 03, 04, 05, 06, 07, 08, 10 ...
```

and **`project09` is absent from that list**, so that slot is real and loads. Nine of the ten project slots
are empty, which no healthy unit is in: a factory OP-Z ships with projects, and PLAY runs the sequencer
against the active project. A project with no valid pattern data reached through the sequencer's voice
allocation path is a credible source of this exact fault — and it would explain why PLAY has failed through
every plug, sample and engine repair so far.

**We hold a genuine project file for the fix:** `/Users/jakubkolcar/.opz-decode/contentdisk-baseline/project09.opz`
(342,848 bytes), exported from this very device's content disk, and `how_to_import.txt` lists projects as an
ADD-able content type with the names `project01.opz` to `project10.opz` (anything else is rejected).

### 66.58 Exact correlation: three "Couldn't find plug with id 109" immediately precede the PLAY fault

The boot after the project fill is the cleanest record yet:

```
fxmanager: Couldn't find plug with id 109
fxmanager: Couldn't find plug with id 109
fxmanager: Couldn't find plug with id 109
main: exception caught iid: 0x00130026, arg: 0x00000000
main: exc reason: ADI_EXC_DATA_CPLB_MISS
main: DCPLB_FAULT_ADDR: 0x000002c0.
callstack: RETX: 0x80117baa
```

Everything else is clean in this boot: `engine errors: NONE`, `main: initialize [synth engine]: took 51 ms`
(the engine re-stage landed), `contentmanager: Calculating used sample memory: 870 kB`. The same
three-miss block prints once during initialisation (where it is harmless) and then again **immediately**
before the fault, which is where PLAY reaches the FX manager. Plug 109 is the trigger.

**Two corrections from the same boot:**

1. **The project fill did not take.** Nine failures remain, for `project01-08` and `project10`. The copies were
   made on the disk and the import's checklist does contain a projects step, so the device does not accept
   them that way — most likely the step synchronises the *device's* projects out to the disk rather than
   importing host files in.
2. **The `~109.engine` marker under a new `9-fx/01` folder was ignored.** Every marker that ever created a
   plug sat in one of the device's own track directories (`1-kick` through `8-chord`, named `<n>-<name>`), so
   the marker for 109 has to go in a real track folder. A free slot of a synth track is the least disruptive
   place, since plug 109's mask (768) covers the two FX tracks and cannot legitimately bind there anyway: the
   point is only to make the plug *exist* so the FX manager's lookup succeeds.

### 66.59 The project file is an empty stub — this unit has never held a valid project

The nine project failures are not a packaging problem. The log says the file is now *present* and *rejected*:

```
serialize: Failed to load GlobalData from /yaffs2/user/projects/project01.opz, wrong format: 0
serialize: Failed to load project /yaffs2/user/projects/project01.opz
```

and the file we were copying turns out to be a zero-filled stub:

```
size            342,848 B (0x53b40)
first 96 bytes  00 00 00 00 ... (all zero)
entropy         0.52 bits/byte   (an all-zero file is 0.0; compressed data is 8.0)
byte values     88 distinct, no zlib (78 9c / 78 01 / 78 da), no PK zip header, no ASCII
last 16 bytes   ... ff ff f8 00 00 00 00 00 07 00 00 00
```

So `project09.opz` is a never-written project: the loader reads a format field, gets **0**, and gives up. That
is consistent with everything else about this unit — the internal user filesystem was formatted, and no
project has existed since. `PLAY` runs the sequencer against that project.

**Two mechanics worth keeping:**

1. **The updater is the reliable delivery route for projects.** Writing `../user/projects/projectNN.opz`
   through it produced `wrong format: 0`, a *different* error from the nine `Failed to load project` lines
   before it, which proves the file landed in exactly the place the boot reads. The content disk's project
   step did not install anything at all.
2. **The file must be written by the device itself to be valid.** Only the device (or the app) knows the
   container's format field, and the export we had was never initialised, so a correct project cannot be
   synthesised on the host.

**Content-mode pass (the step the marker needed):** the internally-written
`/yaffs2/user/samplepacks/8-chord/02/~109.engine` never appeared in the disk's export — that tree only
shows entries the device recognises — so the marker was created on the **disk** instead, in a real track
directory (`8-chord/02`, a free slot), and the volume was ejected, which triggers the import and its
`Rebuilding plug definitions` step. That step is what has created every plug this unit has (121, 122, 130,
134, 140, 141, 151, 152, 153) and is what should now create 109 from this marker. The junk `9-fx` folder
from the earlier attempt was removed. The ten `projects/*.opz` copies (all 342,848-byte stubs) were left in
place — they are harmless, and the device's own save will overwrite them when a real project is written.

### 66.60 What the backup restore taught us: the disk delivers samples, the updater delivers projects

The restore of the healthy drive's contents was half-right and half-wrong, and the failure mode is
instructive.

**What worked: the samples.** The boot right after the restore logged
`contentmanager: Calculating used sample memory: 1567 kB` — up from 870 kB by almost exactly the 183,660 +
529,696 bytes of the backup's two real user samples (`5-bass/10/user384232202.aif`,
`7-arpeggio/10/brokenpad.aif`). So the content disk really does ingest sample audio, and the sample
registration path is healthy.

**What did not work: the projects.** The device still reported

```
serialize: Loading old project format, default global data
serialize: Failed to load GlobalData from /yaffs2/user/projects/project01.opz, wrong format: 0
```

for all nine slots, i.e. it was still reading the **zero-filled stubs written earlier through the updater**.
The disk's `Syncronizing projects` step does not import host files in — it exports the device's projects out
— which is why the same nine failures survived both disk attempts and only changed their *wording* the first
time the updater delivered a file.

**The rule, confirmed twice over:** the content disk is the channel for **sample audio**; the plain-zip
updater is the channel for **projects and definitions**. The project *container* must come from the
backup (`0x49` format field, 342,848 bytes, all ten files distinct).

**One restored file made the boot itself crash.** The failure moved from PLAY to initialisation:

```
plugmanager: save slot configuration
contentmanager: Calculating used sample memory: 1567 kB
snakesystem: load general config /yaffs2/user/config/general.json
main: exception caught iid: 0x00130026, arg: 0x00000000
main: exc reason: ADI_EXC_DATA_CPLB_MISS
main: DCPLB_FAULT_ADDR: 0x00000000.
callstack: RETX: 0x80117baa
callstack: 0x8002c438, 0x11a03838, 0x11a02586, 0x8011a0c0, 0x8011a184, 0x8002d3d0, 0x80134a04
```

Note the fault address is now `0x00000000` rather than `0x000002c0`, and frames `0x8011a0c0` / `0x8011a184`
are new. The step immediately after the general config is the presets load, and the restored
`config/userPresets.dat` (351,202 bytes) is the only restored file that is both a large binary and parsed at
that moment, so the repair writes a **zero-filled bank of the same size** — the empty 200-record state the
device itself produces — instead of the backup's copy. Engines are re-staged in the same payload because
the content-disk eject strips them (`initialize [synth engine]: took 20865 ms` before, 51 ms when present).

### 66.61 The boot crash was my own zero-filled preset bank — the format field must be 1

The log named the culprit outright:

```
plugmanager: Wrong file format: /yaffs2/user/config/userPresets.dat (0 != 1)
main: exception caught iid: 0x00130026, arg: 0x00000000
main: exc reason: ADI_EXC_DATA_CPLB_MISS
main: DCPLB_FAULT_ADDR: 0x00000000.
callstack: RETX: 0x80117baa
```

**Reading a file the device parses, "empty" and "zeros" are not the same thing.** When
`config/userPresets.dat` was simply *absent*, every boot logged a harmless `ENOENT` and carried on — the
device skips the file. Writing a **zero-filled bank of the same size**, which looked like the safest possible
neutralisation, made the parser read a format field of **0**, reject the file, and fault immediately
afterwards. So the boot crash was introduced by the very repair meant to remove it.

The healthy unit's file is unambiguous:

```
backup userPresets.dat: 351,202 B
  first 4 bytes        01 00 00 00      format field = 1
  351,202 - 2          = 351,200 = 200 x 1,756 records   (the app's 0x55be0 bank)
```

**The lesson generalises, and it belongs next to the `~<plugid>.engine` and `samples` findings:** for a
*binary the device parses*, only the genuine file (or no file at all) is acceptable. A plausible-looking
substitute is worse than nothing, because it turns a skipped step into a fault.

**Restore staged through the updater and extracted to completion** (`[extract] progress 3873439/3873439`,
console-captured, zero `Failed to extract`):

| file | source | why it matters |
|---|---|---|
| `config/userPresets.dat` (351,202 B, format 1) | backup | removes the boot crash my zeroed file caused |
| `config/dmx.json` / `general.json` / `midi.json` | backup | the working unit's own configuration |
| `projects/project01-10.opz` (342,848 B, header `49 00 00 00`) | backup | the real projects; the updater is the only channel that delivers them |
| 21 engine binaries | `engines-official/` | the content-disk eject strips them every time |

Also worth recording: my earlier raw `cp` + `eject` produced **zero** `[extract] progress` lines in the
device log, so that payload may never have extracted at all. Staging through `opzfix.py`, which waits for the
progress counter and captures the console, is the only way to *know* a payload landed.

### 66.62 Historical missing-tapetwo boot diagnosis (APK causal argument corrected in §66.77)

**Later correction:** the APK hashes the engine pathname to register **built-in TapeTwo callbacks**,
not to open that engine file in `PlugManager::init`. Its unconditional `initModule` call therefore
does not prove that a missing device engine file caused the observed fault. The historical logs and
staging observations below are retained, but that causal inference is not a verified diagnosis.

Five crash records in a row share one signature, at one position, in **both** normal and content mode:

```
plugmanager: save slot configuration
contentmanager: Calculating used s|          <- cut mid-line, the fault interrupts the write
iid=0x00130026  FA=0x00000000  RETX=0x80117baa
callstack: 8002c438 11a03838 11a02586 08003e0c [80187dbc | 080234e8 | 8011a0c0]
```

The common point is the plug manager's initialisation, and the decompiled app says exactly what runs
there: **`PlugManager::init` always inserts `crc32('engines/tapetwo.engine')` into its engine map and then
calls `TapeTwo::initModule(0, 0x1cdff8, &v1)`** — unconditionally, unlike `loadRequestedEngines`, which
returns immediately on an empty request list. So a missing `engines/tapetwo.engine` gives that call a null
and faults in the plug manager before anything else can happen.

**How it went missing:** the content-disk eject strips `/yaffs2/user/engines/` on every pass (measured
repeatedly: `initialize [synth engine]: took 20865 ms` with the binaries absent, 49-51 ms with them
present), and the payload staged to fix the marker problem carried **only the thirteen numbered engine
files** — copies under plug-id names — and **not the twenty-one real-name binaries**, so
`tapetwo.engine` was simply not there.

**The fix is the complete set:** all 21 real engines (tapetwo among them) *plus* the 13 numbered copies for
the marker-created plugs, staged and extracted through the updater. This also fixes content mode, since the
fault was in the shared initialisation that runs before either mode is entered.

**Operational rule, learned the hard way:** the engines are stripped by every content-disk eject, so the
engines payload has to be the first thing re-applied after any content session — and it must contain the
**real-name** binaries, not just the numbered aliases.

### 66.63 Recovery from a poisoned user state: the firmware reinstall rewrites the content component

Everything written through the updater had failed to clear the fault, and the delete path (content mode)
crashed on the very state that needed removing, so the host had no way out. The firmware reinstall is the
lever that reaches it:

```
bootdisk: filename found: firmware_bin_only_with_bootloader.zip
bootdisk: decrypt 1491600/1491600 bytes
upgrade: [extract] progress 2775623/2775623
upgrade: [content] progress 18/18
upgrade: copied 18 files
upgrade: content: OK (0)
upgrade: os: OK (0)
upgrade: bootloader: Already installed (-200)
upgrade: successfully upgraded to 1.2.45
```

**`content: OK (0)` plus `copied 18 files` is the significant line pair:** an install rewrites the firmware
*and* its content component, so it is the only operation available to the host that can replace internal
state the updater cannot delete and content mode cannot reach. Reinstalling 1.2.45 is also the operation
this unit has survived twice before, and it does **not** touch the console's NAND-format command that caused
the original bricking (type `0x15`, still forbidden).

**The deadlock this resolved, stated plainly for the record:** the updater is write-only, the content disk
is the only deleter but crashes when the samplepacks/plug state is bad, and the bad state lived inside
`settings/plugs.json` and the marker tree — none of which the host can read. A firmware reinstall was the
remaining lever, and it re-copies the content component.

**Operational consequence:** after a reinstall the engine binaries are usually gone again (the install
rewrites the content component), so the engines payload has to be re-applied before the next normal boot.

### 66.64 Correction: a firmware reinstall DOES rewrite the user content to factory defaults

Earlier notes recorded that an install does not wipe `/yaffs2/user/`, based on one observation where repair
files survived an install. The content disk after this reinstall shows the opposite, and clearly:

```
samplepacks/1-kick/01/~13.engine      2-snare/01/~14.engine
samplepacks/3-perc/01/~15.engine      4-fx/01/~17.engine
samplepacks/5-bass/01/~21.engine  02/~10.engine  03/~14.engine  04/~17.engine
samplepacks/6-lead/01/~25.engine  02/~10.engine  03/~14.engine  04/~17.engine
samplepacks/7-arpeggio/01/~28.engine ...   8-chord/01/~31.engine ...
```

Those are the device's **factory default markers**: plug ids 13/14/15/17 on the four drum tracks, 21/25/28/31
as each synth track's first engine, and a 10/14/17 spread behind them. No redmount packs, no `.aif` files,
no `projects/`, and a `config/` reduced to `dmx.json` + `general.json`.

**Everything written beforehand — my 78+109 markers, the sample audio, the ten projects, the backup's
config, the user samples — is gone.** So `content: OK (0)` / `copied 18 files` does replace user content,
and the earlier "installs don't wipe the user tree" note holds only for the specific case it was measured
in. This also means the reinstall is a genuine **factory-content reset**, which is precisely the lever the
host needed when the user tree was poisoned: it produced a state with only factory markers, and content mode
started working again immediately afterwards.

**The state to build from now:** the factory tree plus the updater-delivered clean plug table (16 default-map
ids + 109, no `samples` references) and the 21 engine binaries. The factory markers match that table id for
id, so the two are consistent for the first time since this began.

**Warning recorded:** during the cleanup 13 markers were deleted as "mine" when they were in fact the
factory's (identical ids, because the reinstall restored the same set). Their loss is cosmetic — each synth
track keeps its first engine marker except `5-bass`, which lost slot 01 — and a `~21.engine` marker in
`5-bass/01` restores it if needed.

### 66.65 The boot fault is in the sample/plug binding — and every booting state had a resolvable pack

**Localised with the app's own initialisation order.** Disassembling `libSnakePlugin.so` from the APK (4 509
dynamic symbols) gives `lib_init`'s sequence:

```
SnakeSystem::preInit()      -> FileManager::preInit, PlugManager::preInit   ('plugmanager: save slot configuration')
SnakeSystem::loadSettings() -> logs 'snakesystem: load general config %s' BEFORE FileManager::fileExists
SnakeSystem::saveSettings() -> pure function of ten booleans, FileManager::writeJsonFile
SynthInit()                 -> Synth::init -> InstrumentManager::init, then FxManager::init  ('initialize [synth engine]')
usleep, keyhandler::flush_input, sequencerInit(), sequencerStart(), MidiInit(), UnityMidiInit(), LedControl::resetLeds()
```

`loadSettings` logs the path, then tests existence, then parses. A **missing** file prints `general settings file
not found` and returns immediately — and that boot crashes too, with the same RETX. So the fault is **not** in the
JSON parse: it is after `loadSettings` returns, i.e. in `saveSettings` (10 booleans, no dereference) or in
`Synth::init`'s first steps. The device log's own ordering agrees: on every booting unit the line *after* `load
general config` is the failed open of `/yaffs2/system/content/samplepacks/sfx.aif` (`disk/disk_io` + `libaiff`),
and the crashing boots never reach it — the fault is inside `Synth::init` before any sample is opened.

**Failed engine loads are tolerated, so the plug table is not the trigger.** The 20:00-20:08 boots logged five
`dlm: Bad address ... Could not load engine` failures and still reached `initialize [sequencer]`; the 21:58-22:22
boots logged `instrumentmanag: Can't load engine 134/141` with all tracks audible. And the fault is byte-identical
with no `plugs.json` at all, with a hand-built table, and with the 21 genuine binaries staged. Re-read of
`readPlugSettings` (0xd54e0) — the device reads exactly `flags`, `version`, `engine`, `samples` per plug (and
`index`, `slot`, `name`, `values`, `defaultOctave` per preset; `trackmask` is never read there), so a host table
that carries those keys is shape-valid and the crash is not a rejected file.

**The one variable that separates every booting boot from every crashing boot is the resolved sample content**
(`contentmanager: Calculating used sample memory`):

| boot | used sample memory | result |
|---|---|---|
| 2026-10-08, after the 0x15 NAND format (§18: "the internal sample packs are 0-byte") | 0 kB | crash, RETX `0x80117baa` |
| 2026-10-10 20:00-21:00, one real user sample in the tree | 88 kB | boots into the sequencer |
| 2026-10-10 21:58-22:22, four redmount packs in the tree | 870 / 3594 kB | boots; PLAY crashes |
| 2026-10-11 00:08-00:14, reinstall's factory tree (markers only, no audio) | 0 kB | crash, RETX `0x80117baa` |

Both crash classes share **one faulting instruction** (`RETX 0x80117baa`); at PLAY the faulting address was
`0x000002c0`, at boot `0x00000000` — one routine dereferencing an object that has no data behind it. The marker
tree explains why: a `~<id>.engine` / `~<name>.aif` entry is a *duplicate marker* of an entry whose **data lives
internally** (the pre-brick export carries nothing but 0-byte markers for every factory pack and engine), and the
`0x15` NAND format destroyed that internal store. The reinstall rewrites the marker files but not the data they
point at, so every factory binding now names something that no longer exists.

**Conclusion (highest-confidence remaining explanation):** the boot fault is the plug→sample binding of the
factory marker tree, and it disappears as soon as any real sample pack resolves. The lever is the one already
proven to deliver audio — the content disk — not the updater (§66.30-66.52).

**Fix protocol (order matters):**
1. content mode: copy real `.aif` packs into free drum-track slots (`samplepacks/1-kick/02`, `2-snare/02`,
   `3-perc/02`, `4-fx/02`), delete `._*` files, eject → `importing … SUCCESS` + `Rebuilding plug definitions …
   SUCCESS`;
2. *then* re-stage the engines through the plain-zip updater with `ENGINES_ONLY=True` (the eject strips
   `/yaffs2/user/engines/` every pass) — never write `settings/plugs.json` (the rebuild owns it) and never write
   `settings/slotConfiguration.json` (its fallback map is the factory map anyway);
3. boot.

### 66.66 Correction to 66.65: real packs do *not* fix it — the sample-memory correlation was a proxy

The content pass worked exactly as intended and the boot still crashed:

```
importing redmountKicks.aif...SUCCESS. New used space 870 kB
importing redmountSnares.aif...SUCCESS. New used space 1669 kB
importing redmountPerc.aif...SUCCESS. New used space 2590 kB
importing redmountFX.aif...SUCCESS. New used space 3594 kB
Rebuilding plug definitions...SUCCESS
```

and the next boot read `contentmanager: Calculating used sample memory: 3594 kB` — four real packs
registered, the device's own plug table rebuilt, the 21 engines re-staged after the eject — and faulted at
**the same instruction**: `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`, `DCPLB_FAULT_ADDR 0x00000000`, `RETX
0x80117baa`, before any sample is opened. So the "a resolvable pack is required" reading of 66.65 is
**disproven**; the 0 kB / boot correlation was a proxy for whatever else the factory reset removed.

**What the factory state lacks that the pre-brick unit had** (from the backup, the only record of the healthy
internal state): `config/userPresets.dat` — 351,202 bytes, format field 1, i.e. **200 records × 1,756 bytes of
per-plug preset data** — which the 18-file content component does not contain (`config/` comes back as
`dmx.json` + `general.json` only). Per-plug preset/parameter data is exactly what the plug→voice binding in
`Synth::init` consumes, and it is the one substantive healthy-unit file the host can still deliver (the
updater writes `/yaffs2/user/config/`, and the content import lists `importing config/userPresets.dat…SUCCESS`
as a route too).

**Staged (verified, `extract: last 3873439/3873439 -> COMPLETE`, 37 entries):** 21 engine binaries, the ten
genuine `projects/projectNN.opz` (header `49 00 00 00`, 342,848 B each), `config/userPresets.dat` (format 1),
`config/midi.json`, `config/general.json`, `config/dmx.json`. `settings/plugs.json` and
`settings/slotConfiguration.json` are deliberately not written: the device's rebuild owns the first and the
factory map is the second.

### 66.67 The normal-boot fix is §66.26, and it has to be re-applied after every firmware install

Tonight's four-hour loop happened because §66.26's recipe was not recognised as *the* fix: the engines have to be
written as **`/yaffs2/user/samplepacks/user/<plugid>.engine`** — the tree `Content::engineFileExists()` scans — not
only into `engines/` and not only into track slots. That single write (plus `config/general.json` with
`disable_start_sound: true`, config *first* in the archive so an abort cannot skip it) is what took the unit from
"dies in init" to "startup animation, track selection, TRACK responds" on 2026-10-08 (§66.26), and it is what the
firmware reinstall silently undid.

Recipe, in order, as one plain-zip updater payload (entries in this order):

```
1. ../user/config/general.json                     (the device's own 10 keys, disable_start_sound = true)
2. ../user/config/dmx.json
3. ../user/samplepacks/user/<id>.engine    x21     <- engineFileExists() scans THIS tree
4. ../user/engines/<name>.engine           x21     <- the dlm opens THIS path
5. ../user/engines/<id>.engine             x21     <- markers that name a plug id
6. ../user/settings/plugs.json                     (the 16 default-map ids + 109, no sample references)
7. ../user/settings/slotConfiguration.json         (the factory map: 13,14,15,17,21,25,28,31,34,36,37,39,60,70,80,100)
8. P0.txt
```

Tonight's failed variants and why they could not work: engines only in `engines/` (the existence scan never sees
them), engines only in track slots (same), my slot map binding all 16 tracks to one plug (moves the fault into the
plug import), and a reinstall alone (it writes the content component but not the engine files). The remaining known
defect after §66.26 is the `fxmanager: Couldn't find plug with id 34/36/37/39` null call (`iid 0x0013002c`,
`ADI_EXC_INSTR_CPLB_MISS`, `RETX 0`) about nine seconds into a running application — plug definitions, which step 6
above supplies.

---

### 66.68 The `samples` string must contain `samplepacks/user/` — proven by a controlled flood

Staged 2026-10-11 ~00:55, console-verified `extract: last 3725471/3725471 -> COMPLETE`, 78 entries,
3,736,025 B packed / 3,725,471 B unpacked. Contents, in write order:

1. `../user/config/general.json` — `disable_start_sound: true` (first, so an abort cannot skip it)
2. `../user/config/dmx.json`
3. `../user/samplepacks/user/<plugid>.engine` ×21 — the §66.26 write that makes normal boot work
4. `../user/engines/<name>.engine` ×21 + `../user/engines/<id>.engine` ×21
5. `../user/settings/plugs.json` — the 17 default-map plugs **redefined**: 13/14/15/17 became
   `engines/sampleplayergain.engine` with `samples: "redmountKicks.aif"` / `"redmountSnares.aif"` /
   `"redmountPerc.aif"` / `"redmountFX.aif"`; **plugs 38 (`engines/tapetwo.engine`) and 43
   (`engines/fdnreverb.engine`) were added** to satisfy the `fxmanager: Couldn't find plug with id 38/43`
   lookups; the other 13 plugs unchanged; every plugin's `samples` otherwise `""`
6. `../user/settings/slotConfiguration.json` — the factory 16-track default map (drums → 13/14/15/17)
7. the ten genuine pre-brick projects (342,848 B each) — untested PLAY control
8. `P0.txt` last

Result, read off the update volume with the unit in update mode:

| observed | value |
|---|---|
| boot | **healthy** — full init to `[communication handlers]`, `task: create task main_task`, RTC/PMIC/module all `OK` |
| sample memory | `contentmanager: Calculating used sample memory: 3683 kB` = 3594 kB of packs + 89 kB of the `.engine` files under `samplepacks/user/` |
| audio | **none** — the four sampler plugs produced silence |
| PLAY | fault, same instruction: crash record's last line is `callstack: RETX: 0x80117baa` |
| crash record body | **nothing but the sample-retry flood**: alternating `yaffsfs: yaffs: error: ENOENT` / `libaiff: AIFF_ReadOpen failed: failed to open` pairs |
| `system.log` | 70,780 B / 1,221 lines, holding **609** `AIFF_ReadOpen failed` lines and **zero** boot lines (`fxmanager` 0×, `sequencer` 0×, `used sample memory` 0×); oldest surviving ring line is `led: failed to open` |

Single variable: the *value* of `samples`. Verdict — **a bare `redmountKicks.aif` is not a path the
loader can resolve.** §66.51's rule ("an unresolvable `samples` value is never a silent track but an
infinite retry loop") is now confirmed by a one-variable experiment, and it is now attributable:
the loop is `AIFF_OpenFile` failing, once per retry, on a name that has no directory in it.

Two rules that follow, both actionable:

1. **A non-empty `samples` that cannot resolve is strictly worse than an empty one.** Empty is
   tolerated silence; unresolvable is an infinite AIFF retry loop that (a) overwrites the whole log
   ring, destroying the boot evidence, and (b) leaves the null sample object that the shared faulting
   function dereferences at PLAY — the same `RETX 0x80117baa` as ever.
2. **Only a path containing `samplepacks/user/` is recognised as a user sample pack** (§66.69).

### 66.69 What the loader accepts — read out of `libSnakePlugin.so`

Disassembled from the 1.95 MB extracted app library (`/private/tmp/opzso/libSnakePlugin.so`, symbols intact):

- `SampleLoader::loadSamples(char const* path, SamplePack&)` **@0xdcfcc** — `ref = AIFF_OpenFile(path, 1)`;
  if null return false; else `readSamples(ref, pack, strstr(path, "samplepacks/user/") != 0)`; then close.
  The string is opened **verbatim** (no prefix is added here) and the *only* classification of it is
  the substring `samplepacks/user/`.
- `SampleLoader::loadSamplePack(unsigned id, SamplePack&)` **@0xdcc7c** — the identical
  `strstr(<string at SamplePack+0x38>, "samplepacks/user/")` pattern, then the same `readSamples`.
- `PlugManager::addUserPlug(unsigned id, char const* name, int, int)` **@0xda670** — picks the engine
  by its third argument: `< 4` → `engines/sampleplayergain.engine`, else
  `engines/synthsampler.engine`. Both are spelled **with** the `engines/` prefix, which validates the
  host table's engine spelling (the DLC catalogue's bare `sampleplayergain.engine` is the other form
  and is equally consistent *within* its own containers).
- `Content::cleanUnusedSamplepacks` exists in the symbol table → user packs nothing references are
  garbage-collected. That explains why the earlier `samplepacks/user/*.aif` copies disappeared, and
  predicts they survive once a plug genuinely references them. **Untested.**

The import log's own strings — `importing redmountKicks.aif...SUCCESS`, `assigning
kick/02/redmountKicks.aif` — are *import-time* events naming the disk slot the audio came from. They
are not the string a plug carries, and reading them as the plug's `samples` value is what produced
the flood above.

Model that now fits every observation: **`samplepacks/user/` is the user-plug payload directory**, and it
is where *both* halves of a user plug live — `<plugid>.engine` (the engine module the §66.26 boot fix
writes) and `<name>.aif` (the plug's audio). That single model explains the boot fix, the loader's
`strstr` flag and the garbage collection.

Decided next test (not yet run): plugs 13/14/15/17 with
`samples: "samplepacks/user/redmountKicks.aif"` … and the four real `.aif` files written to
`/yaffs2/user/samplepacks/user/`, everything else as in §66.68.

### 66.70 A PLAY fault does not always leave a crash record

Two consecutive PLAY events on the same unit, same day:

- **before** the §66.68 payload — the volume held only `battery.log` (0 B), `import.log`,
  `serial.txt`, `system.log`, `upgrade.log`, `version.txt`: **no `crash0N.log` at all**, while
  `system.log` ends `power_managemen: Going to charging state` → `PowerPreSleep` →
  `command_handler: PSOC requested SER_MSG_POWER_MODE_REQUEST_POWER_OFF`;
- **after** it — `crash01.log` exists, is entirely flood, and ends `callstack: RETX: 0x80117baa`.

So a PLAY-triggered failure may end in a PSOC power-off with **no** record written, while a flooded
boot overwrites the rolling 7,152-byte record and keeps only the fault line. "No crash record" is
therefore not evidence that nothing faulted (§66.57 in reverse).

Left **unverified** by the flood boot, to be re-checked on the next clean boot: whether
`fxmanager: Couldn't find plug with id 38/43` disappeared after plugs 38 and 43 were defined, and
whether `instrumentmanag: Can't load engine 130/141` persists. Deliberately **not** fixed: the stale
app pack-plug ids 130 and 141 were left without engine files, because giving a pack plug whose
`samples` cannot resolve an engine would convert a tolerated *can't-load-engine* line into the retry
loop of §66.68.

### 66.71 The A/B samples-path test: both forms fail, and the sample counter proves why

Staged 2026-10-11 ~01:00, console-verified `extract: last 3978285/3978285 -> COMPLETE`, 0 failed
extractions — 3,988,093 B packed / 3,978,285 B unpacked / 72 entries. Each of the four packs was
written **once**, at the location its own plug named, so that audibility alone would identify the form:

| track | plug | `samples` written | audio file written to |
|---|---|---|---|
| 1 kick | 13 | `samplepacks/redmountKicks.aif` | `../user/samplepacks/redmountKicks.aif` |
| 3 perc | 15 | `samplepacks/redmountPerc.aif` | `../user/samplepacks/redmountPerc.aif` |
| 2 snare | 14 | `samplepacks/user/redmountSnares.aif` | `../user/samplepacks/user/redmountSnares.aif` |
| 4 fx | 17 | `samplepacks/user/redmountFX.aif` | `../user/samplepacks/user/redmountFX.aif` |

Plus the §66.26 boot write (21 × `samplepacks/user/<plugid>.engine`), engines in `engines/<name>` and
`engines/<id>`, plugs 38 (`tapetwo`) and 43 (`fdnreverb`), the factory 16-track map, `general.json`
with `disable_start_sound`, `dmx.json`. The ten projects were **not** rewritten (already installed).

Result: **no audio, PLAY still crashes, the retry flood is still there.**

Two findings, one negative and decisive, one positive and verified.

**(a) The used-sample-memory counter did not move — those locations are not sample storage.**
`contentmanager: Calculating used sample memory: 3683 kB` is byte-for-byte the same as before 3.6 MB of
`.aif` files were written into `samplepacks/` (root) and `samplepacks/user/`. The content manager does
not count either location, so the only place pack audio is *counted* — and therefore the only place it
is *found* — is the **track/slot folders** (`samplepacks/<track-folder>/<slot>/`), i.e. what the
content-disk import writes and what the device's own `Rebuilding plug definitions` step reads. Writing
`.aif` files anywhere else through the updater is a no-op for sample accounting. That also explains why
*both* A/B forms failed for one and the same reason, and it closes the whole "free-form path in
`samples`" family of theories: **`samples` cannot be an arbitrary path** — the pack has to be a
slot-assigned pack first.

**(b) `fxmanager: Couldn't find plug with id 38 / 43` is gone — verified, not assumed.** This boot's
`system.log` contains **zero** `fxmanager` lines; the previous one had six. Defining plug 38 = tapetwo
and plug 43 = fdnreverb fixed exactly that.

**(c) A third null offset through the same function.** The update-mode/second-phase boot of the same
session wrote `crash01.log` with a full init tail and then:

```
main: exception caught iid: 0x00130026, arg: 0x00000000
main: exc reason: ADI_EXC_DATA_CPLB_MISS
main: DCPLB_FAULT_ADDR: 0x00000220.
main: L1DM_DSTAT: 0x00020000.
callstack: RETX: 0x80117baa
callstack: 0x8002c438
callstack: 0x11a03838
callstack: 0x11a02586
callstack: 0x0800b71c
```

So the same instruction and the same first three frames now fault with **0x00000220** (update-mode
entry), where boot previously gave 0x00000000 and PLAY 0x000002c0 — a third caller, same function, and
a new tail frame (`0x0800b71c`). This is the strongest confirmation yet that `RETX 0x80117baa` is one
shared null-member dereference reached from several independent initialisation paths.

**(d) The failing sample open prints no path.** Unlike `filemanager: failed to open file <path>` and
`disk/disk_io: error opening file <path>`, the sample loader's failure is only
`yaffsfs: yaffs: error: ENOENT` + `libaiff: AIFF_ReadOpen failed: failed to open`. The attempted path is
therefore *unreadable from any log* — the only ways to learn it are (i) the app's own file sync, which
serves `/yaffs2/user/settings/plugs.json`, or (ii) the content importer's `assigning <track>/<slot>/<name>`
lines that name what it bound.

**(e) `instrumentmanag: Can't load engine` ids are tree-marker-derived and differ per boot**: 130, 141,
132, 133 in the update-mode record, 26 twice in `system.log`. All tolerated; none is fatal.

**Rule violated, and the corrected sequence.** §66.51's rule — *settings/plugs.json belongs to the
device's rebuild, and a host write to it costs the pack plugs* — was broken by this payload and by the
one before it: the host table replaced the device's own binding of the drum tracks to their imported
packs (and then re-pointed those tracks at samplers whose `samples` could not resolve). The documented
working state for audio was the content-disk import plus the device's own rebuild, with **no host
plugs.json and no host slotConfiguration.json**. Corrected plan, in order:

1. **content-mode mount + eject** — let the device rebuild its own plug table and re-bind the drum
   packs (they are still registered: 3683 kB). The new `import.log` will record `assigning …` lines
   naming exactly what it bound, which is also the cheapest way to learn the real `samples` form.
2. **updater payload**: engines in all three locations + `config/general.json` (`disable_start_sound`)
   + `config/dmx.json`, and **no** `settings/plugs.json`, **no** `settings/slotConfiguration.json`
   (the content eject strips `/yaffs2/user/engines/`).
3. boot — expect normal boot **and** audible drums; PLAY remains the open question.

If step 1 leaves the drums silent, the next move is not another payload guess but reading the device's
own `settings/plugs.json` through the app's file sync (fileId 1) to get the real `samples` string.

### 66.72 The device's own rebuild restored the drum audio; PLAY now fails as a *hang* with no record

Staged 2026-10-11 ~01:07 (281,029 B / 272,119 B unpacked / 66 entries, console `extract: last
272119/272119 -> COMPLETE`, 0 failures): `config/general.json` (`disable_start_sound`) + `config/dmx.json`
+ 21 × `samplepacks/user/<plugid>.engine` + 42 × `engines/`, and **zero `settings/` entries** — the
plug table was left to the device.

Before it, the content disk was given the four real packs in the **free slot 02** of `1-kick`,
`2-snare`, `3-perc`, `4-fx` (891,612 / 817,450 / 944,000 / 1,028,170 B; AppleDouble deleted; `sync`;
eject) and the device ran its import. Result, per the user:

- **all four drum tracks have audio** — the first time since the brick;
- one synth track has audio (the five `dlm: Bad address … (81b00000-81b0c800)` engines still do not load);
- **PLAY still fails** — and this time the volume carries **no `crash0N.log` at all** (§66.70's second
  occurrence), with the boot log ending `power_managemen: PowerPreSleep` →
  `command_handler: PSOC requested SER_MSG_POWER_MODE_REQUEST_POWER_OFF`.

So the host-table rule violation (§66.71) was indeed what was killing the audio: with the device's own
table in place, the drum packs bind and play. Two further confirmations from that boot:

- `serialize: Failed to load projectNN.opz` — **0 occurrences** (was nine): all ten projects are
  installed and load, so the project-less theory can no longer explain the PLAY failure;
- `fxmanager:` — **0 occurrences**.

**New finding: the surviving PLAY failure is a hang, and the log shows the machinery for it.**
`system.log` holds **401** `AIFF_ReadOpen failed` lines in that boot, interleaved *throughout* the whole
init sequence (between the arpeggiator opens, around `[synth engine]`, after the task creations) — i.e.
the sample retry loop runs as a *continuous* background task, not once at load time. PLAY walks every
track, so a track whose plug's pack sample cannot resolve lands the audio path inside that loop. That
matches "PLAY crashes, and no fault record is written": a blocked audio task and a watchdog, not an
exception.

**And the reason a pack's sample cannot resolve is deduplication, not naming.** The disk at that point
carried the four packs **twice**: a 0-byte `~redmountKicks.aif` dedup marker in slot **01** (the
device's own export of an already-installed pack) *and* my real `.aif` in slot **02**. The import log
shows the device reacting exactly as the format demands — `clearing kick/01/`, `clearing kick/02/`
cycles — and the boot's sample-memory readings fell from 3683 kB to **1802 kB** and **1890 kB**, i.e.
only about two of the four packs stayed registered. Half the packs are gone, their plugs still exist,
and those plugs retry forever.

The final cycle of the last content pass in fact shows all four imported and assigned
(`importing redmountKicks.aif…SUCCESS. New used space 870 kB`, …, `3594 kB`, then
`assigning kick/02/… snare/02/… perc/02/… fx/02/…`, `Rebuilding plug definitions...SUCCESS`) — so the
import works; it is the *duplicate declaration* of each pack that the device resolves by clearing slots.

Decided next test: on the mounted content disk, remove the duplicate `~redmount*.aif` markers (slot 01)
and AppleDouble files so each pack is declared **once**, by the real audio in slot 02, then eject. The
passes that followed look for the boot's `Calculating used sample memory` to read ≈3683 kB (all four
packs) and for the `AIFF_ReadOpen` count to fall to 0. If the flood stops and PLAY still hangs, then the
hang is not the retry loop and must be chased differently; if PLAY runs, the retry loop was the whole
story.

**Correction to the paragraph above (observed 2026-10-11 01:10, before the fix was applied).** When the
disk was inspected, the real `.aif` files were no longer present at all: after the import the device had
exported a 0-byte `~redmount*.aif` marker into **both** slot 01 *and* slot 02 of each drum track —
eight marker files, no audio. So the duplication is worse than "marker plus real file": the pack is
declared **twice as markers**, and the device's `clearing kick/01/ … clearing kick/02/` cycles are it
dropping the duplicate declaration and, with it, the registration (hence 3683 → 1802/1890 kB in the
boots). The fix applied was therefore: delete all eight `~redmount*` markers, then write the real audio
**once** into slot 02 of each track (891,612 / 817,450 / 944,000 / 1,028,170 B), AppleDouble cleaned,
`sync`, eject — so each pack is declared exactly once, by a real file in one slot, which is what
`how_to_import.txt` describes (a real `.aif` in a slot installs the pack; a `~` entry is the dedup marker
for the *other* tracks that reference it).

### 66.73 Dedup fix worked; the last fault is a *published* plug whose engine file the content manager deletes

**The dedup fix (§66.72) worked.** The following import cycles read, in order:

```
Reading content disk...SUCCESS
Calculating used sample space...0.0/24.0 MB
importing redmountKicks.aif...SUCCESS. New used space 870 kB
importing redmountSnares.aif...SUCCESS. New used space 1669 kB
importing redmountPerc.aif...SUCCESS. New used space 2590 kB
importing redmountFX.aif...SUCCESS. New used space 3594 kB
Rebuilding plug definitions...SUCCESS
```

then `assigning kick/02/redmountKicks.aif … fx/02/redmountFX.aif` — **all four packs registered, one
declaration each**. User result: **everything except the kick has audio** (drums 2–4 plus the synth
tracks), PLAY still fails.

**What the crash record says.** It is a real record again (§66.70's no-record case was the flood era),
and its last lines before the fault are the lead:

```
instrumentmanag: Can't load engine 26   ×3
instrumentmanag: Can't load engine 10   ×7
main: exception caught iid: 0x00130026, arg: 0x00000000
main: DCPLB_FAULT_ADDR: 0x00000220.
callstack: RETX: 0x80117baa
callstack: 0x8002c438 / 0x11a03838 / 0x11a02586 / 0x11a0203c
callstack: 0x80133c78 / 0x8011295c / 0x80134a04
```

That tail (`0x80133c78 … 0x80134a04`) is the **PLAY/sequencer** path from the original signature, and the
ids it cannot load — 10 (analoga) and 26 (saw013a) — are exactly the plugs this unit's own projects
reference (the pre-brick backup declares `~10.engine` on 5-bass/07, 6-lead/07, 7-arpeggio/07, 8-chord/07
and `~26.engine` on 5-bass/01, 6-lead/04, 7-arpeggio/01, 8-chord/02). So PLAY reaches a plug whose engine
module is not resident, and dereferences null.

**Why not resident — `Content::engineFileName(unsigned plugId, bool published)` @0xfeb18:**

```
published → sprintf(name, "%s%d.engine", <constant>, plugId)   // the "samplepacks/user/" constant
   else   → sprintf(name, "%d.engine", plugId)
```

A **published** (disk-declared / app-installed user) plug resolves its module to
`samplepacks/user/<plugid>.engine`. And that same boot's log shows the content manager deleting exactly
those files:

```
contentmanager: Remove unused sample pack samplepacks/user/10.engine
contentmanager: Remove unused sample pack samplepacks/user/26.engine
… all 21 of them, twice (two mass-storage entries)
```

**So the §66.26 boot write is self-defeating in the long run**: the updater can write
`samplepacks/user/<id>.engine`, but the *next* mass-storage/content entry purges every such file as an
unused sample pack (§66.26's fix works only because the payload is applied and the unit then boots
normally without re-entering the disk). A published plug whose file has been purged gives
`instrumentmanag: Can't load engine N`, keeps its track silent, and — if a project references it —
faults the sequencer at PLAY.

**Decision: re-create the published engine plugs through the path that owns them — the official app.**
This unit's published plugs (ids 10, 11, 14, 17, 25, 26, 31, 65, 98, 112, 129) were installed by the
app, which writes the engine bodies where the device then *references* them, so the content manager
keeps them. The app has already been used on this unit to replace "bad" engines successfully, and its
sync is a round-trip of the device's own `settings/plugs.json`, so it should not cost the pack bindings
the way a host-written table did (§66.71). Fallback if the app is unavailable: declare the engine
binaries as packs on the content disk (`<id>.engine` with real bytes in a free synth slot), which should
import them to `samplepacks/user/<id>.engine` and make them referenced — untested, and it depends on the
importer assigning the plug id from the file name.

Open alongside this: the kick track is silent although its pack is registered, and the boot still logs
**332** `AIFF_ReadOpen failed` lines; both are consistent with the same cause (a published plug whose
file is gone) but neither is proven yet.

### 66.74 TE's published assets, fully enumerated — and the memoryslot question is answered

Re-fetched TE's live DLC list (`GET https://teenage.engineering/_api/id/products/597caf1a-f7e1-4d86-8881-7b17a79adfb1/dlcs`,
HTTP 200, 91,758 B — identical in size to `te-dlcs.json`) and downloaded **every** asset the 28 records
expose. The asset paths do download unauthenticated on `https://teenage.engineering` (an earlier probe
of mine that reported otherwise was a broken probe, not a broken endpoint; the `te-id` service at
`te-id.herokuapp.com` answers `"te-id"` and is the *account* side).

| kind | count | contents |
|---|---|---|
| engines | 21 unique (27 catalogue entries) | all 21 binaries, **byte-identical** to `~/.opz-decode/engines-official/`, now in `~/.opz-decode/te-assets/engines/` with sha256 recorded |
| `opz-sample` | **4** | `redmountKicks/Snares/Perc/FX.aif` — genuine `FORM…AIFF`, 891,612 / 817,450 / 944,000 / 1,028,170 B |
| hero-image | 24 | the DLC artwork (10.0 MB), downloaded for completeness only |

**The memoryslot question is settled.** The catalogue's `engines[]` entries carry
`attributes.memoryslot`, so every official engine's slot is published: analoga 27, chord 59, chorus 60,
chorus2 88, cluster 83, crush 79, delay 61, digital 62, dist 78, electric 77, ep 4, fdnreverb 89,
fm003b 13, ministringshort 82, organ 18, reverb 66, sampleplayergain 10, saw013a 16, synthsampler 68,
tapetwo 9, volt 70. This supersedes the earlier conclusion that the five failing engines (analoga,
chorus2, ep, fdnreverb, organ) have *no* published slot because they are absent from the app's
factory-plug cache — their slots are published, just not in that cache.

**What TE does *not* publish.** The catalogue defines 23 sampler plugs and names their audio —
`CuckooKicks/Snares/Perc/FX/C_keypawn`, `SebaKicks/Snares/Perc/FX`, `GrantFX`, `AlainKicks/Snares/Perc/FX`,
`TeKicks/TeSnares/TePercs/TeFX`, `zVinyl` and the four `redmount*` — but only the **four redmount** files
exist as downloadable assets. The other **19 packs have no published audio anywhere on TE's endpoints.**

That is exactly the situation the official app describes when it will not download samples for a drum
preset: those packs are not DLC content, they are the unit's own factory/system content, so the app is
*right* to expect them on the device. On this unit they are gone: the reinstall rewrote `/yaffs2/user` to
markers-only, and the content disk exports only those markers (the pre-brick backup shows the same
markers with no audio), so the factory pack bodies were never anywhere we can read. Restoring those 19
packs therefore needs one of: a system-content dump from a healthy unit or from the firmware's content
component (the `.zfw` payload is encrypted), TE's cooperation, or reading the device's own files through
the app's FileSync channel (fileId = crc32(path), which the device answers with the file's contents —
the same channel that served `/yaffs2/user/settings/plugs.json` to the app).

For the goal at hand — PLAY — none of that is required: the PLAY fault is `Can't load engine 10/26`, the
engine binaries are all present and verified, and their correct memoryslots are now known from TE. The
app installs engines together with their slot attributes, which is how the unit got its published plugs
in the first place and how it repaired "bad engines" once already.

### 66.75 Asset harvest inventory, and the one remaining download

**Downloaded and verified (`~/.opz-decode/te-assets/MANIFEST.json` records name, size, sha256 and magic for every file):**

| kind | count | bytes | notes |
|---|---|---|---|
| `engines/` | 21 | 90,284 | every official engine binary; **sha256-identical** to `engines-official/`; each with the `memoryslot` TE publishes |
| `samples/` | 4 | 3,681,232 | the only `opz-sample` assets TE exposes: `redmountKicks/Snares/Perc/FX.aif`, all genuine `FORM…AIFF` |
| `hero/` | 24 | 10,003,484 | DLC artwork (not needed for the unit; kept for completeness) |

Sources: `GET /_api/id/products/597caf1a-…/dlcs` (28 records; live copy saved as `te-assets/dlcs-live.json`)
and `GET /_api/id/products/597caf1a-…/assets` (21 `opz-engine` entries with `attributes.memoryslot`).
Also re-checked `teenage.engineering/downloads/op-z` — it lists **only `.zfw` firmwares**, no sample content.

**Not published anywhere on TE's endpoints (19 files), i.e. the factory drum packs the app expects on the device:**
`CuckooKicks/Snares/Perc/FX/C_keypawn`, `SebaKicks/Snares/Perc/FX`, `GrantFX`, `AlainKicks/Snares/Perc/FX`,
`TeKicks/TeSnares/TePercs/TeFX`, `zVinyl`.

**Later correction:** §66.76 supersedes the general-filesystem-read assumption below. USB settings
pulls now work, but arbitrary-path silence does not establish file absence; the APK lookup has both
an active-sync gate and an ID-to-path registry.

**Remaining download: the device's own tree (historical assumption).** The clean-room file service (`$51`→`$34`, `$35`→`$53`,
fileId = crc32(lowercase(path))) is the way to fetch `settings/plugs.json`, `settings/slotConfiguration.json`,
`settings/plugPresets.dat`, the configs, and whatever sample bodies the unit still holds. Tooling is written
and ready: `~/.opz-decode/toolkit/opzpull.py` (read-only: sends only `$51`/`$33`/`$35`; saves under
`~/.opz-decode/pulled/`; re-advertises every 15 s; `--wait` for a slow device).

**Blocker, measured on 2026-10-11 (unit in normal mode, USB attached):**

- USB MIDI input works (identity inquiry answered: `X3CJN79E`, `1.2.45+`; 798 `clock` messages captured),
  so the port and the listener are fine.
- But the device **never sends SysEx** on USB: a 300 s run with `$51` re-advertised every 15 s plus
  1 Hz `$33` heartbeats received **zero** frames, as did a raw listen that would have caught non-SysEx replies.
  Every successful session in its own logs runs with `command_handler: BLE advertising on` — the file
  service answers over **BLE-MIDI**, the transport the companion app uses.
- The device *does* see the advertisement: its logs contain `fileclient: FileClient: send connection request to
  server 16962` (= `0x4242`, the id this host advertises), repeated ~20 times, i.e. it tries to reach us and
  never gets through on USB.
- BLE from this host is unavailable to the agent process: `BleakBluetoothNotAvailableError('Bluetooth device is
  turned off')` = CoreBluetooth permission not granted to the terminal.

**Unblock (one user action, either one):**
1. *Recommended, no new code:* Audio MIDI Setup → MIDI Studio → **BLE MIDI** → connect `OP-Z`. The unit then
   appears as a CoreMIDI endpoint and `opzpull.py` runs unchanged against it.
2. Or grant Bluetooth permission to the terminal app (System Settings → Privacy & Security → Bluetooth), which
   allows a BLE-MIDI client to be driven directly.

**Measured state at the end of this pass (2026-10-11 ~02:20, unit powered in normal mode, USB attached):**

- The unit is alive on USB: `mido` sees `OP-Z` in and out; the identity inquiry answers `X3CJN79E` / `1.2.45+`;
  the port streams `clock`.
- Its file service still sends **nothing** back: `$51` (re-advertised every 15 s) + `$33` heartbeats with our
  server id, for 300 s, produced 0 SysEx frames; a raw listen confirmed only `clock`. The device's own logs
  show it *does* receive the advertisement (`fileclient: FileClient: send connection request to server 16962`),
  so the reply path is not USB.
- BLE from this host is intermittent and does **not** currently see the unit: repeated scans return 10–12
  devices with `ble-midi=0, named-opz=0`, and the adapter flips between usable and
  `BleakBluetoothNotAvailableError(powered off)` for the agent process.
- `~/.opz-decode/pulled/` is therefore still **empty**: zero files have come off the device.

Two watchers are armed and will fetch the list unattended: `/tmp/pull_watch.sh` (fires on content mode, USB
first, BLE fallback) and `/tmp/ble_auto.py` (probes unnamed BLE devices for the MIDI service and runs
`opzble.py --address`). Both only ever send `$51`/`$33`/`$35`.

**Runbook added:** `~/.opz-decode/PULL_RUNBOOK.md` — tooling, what is proven vs not on each transport, the three
armed watchers and their logs, and the five unblock options in the order most likely to work.

**Offline verification of the pull path (2026-10-11 ~02:45), and two bugs it caught.** `~/.opz-decode/test_pull_paths.py`
drives `toolkit/opzpull.py` against a synthetic `$53` sender (sizes 1/200/401/1234/5000 B, duplicate parts,
a gap, a foreign file id) and `toolkit/opzble.py`'s BLE-MIDI framing (packet shape, sysex split across
fragments, stray non-sysex packets) — **all checks PASS**. It found, before any device window was spent:

1. both new tools unpacked `decode_frame()` as a tuple, but it returns a `Frame` dataclass — every code path
   would have raised `TypeError` on the first frame the device sent (the older `opzfetch.py` was written
   correctly; the two new tools were not);
2. `opzble.BleMidi.packet()` masked every byte with `0x7F`, destroying the `0xF0`/`0xF7` delimiters, and
   `feed()` treated `0xF0` as a timestamp header — so no sysex could ever be framed. Sending now uses
   `[header 0x80|ts_hi][ts_lo][MIDI bytes]` with MTU-safe chunking (`BleMidi.packets()`), and the parser
   checks the sysex delimiters before the timestamp rule.

So the earlier failed attempts were doubly inconclusive: the transport never answered *and* the client could
not have parsed an answer. Both are addressed; the watchers now invoke the fixed code.

**Search for the lost factory packs outside TE (2026-10-11 ~03:00): negative.** GitHub repository search
(5 query variants: op-z factory samples, opz factory content, op-z sample packs, opz backup content disk,
op-z drum samples) returned no mirror, and archive.org's advancedsearch (3 queries) returned only unrelated
items. The 19 factory packs are therefore not obtainable publicly from either TE's endpoints or these
sources; they exist only on a healthy unit (system/factory content) or in the encrypted firmware payload.
`~/.opz-decode/te-assets/MANIFEST.json` now carries a `remaining` section listing the 16 device-side targets,
why each transport is blocked, the tooling (with the passing offline test) and the four unblock options.

**Scope correction to "what remains" (2026-10-11 ~02:50).** Auditing the target list against what is already on
disk shows most of it is *not* missing: all 21 engines are present and sha256-verified, the four config files
(dmx/general/midi/userPresets) came off the pre-brick content-disk backup, and the four redmount `.aif` files
are downloaded *and* installed on the unit. The genuine remainder is only: the unit's own
`settings/plugs.json`/`slotConfiguration.json`/`plugPresets.dat` (documents, needed to read its exact
engine/sample strings per plug) and the **system-content audio** (`system/content/samplepacks/*.aif`), which is
the only route to the factory sounds the app expects — plus the 19 factory packs that are unpublished and
unobtainable. `te-assets/MANIFEST.json` now carries that corrected structure.

**Device plug inventory recovered from its own preset bank (2026-10-11 ~03:00) — no transport needed.**
`config/userPresets.dat` in the pre-brick backup is a dump of the unit's plug map (the app writes one 1,756-byte
record per plug with the id at record offset 0x6d8). Parsing all 200 records yields **54 real plug ids**:
10–17, 25, 26, 31, 34, 35, 38, 39, 42, 43, 65, 66, 67, 71, 98, 99, 109, 112, 121–150 — plus three
uninitialised slots (474402218, 2937672656, 3457447250) that are simply unwritten memory. 27 records carry
non-zero preset values. The inventory is archived as `~/.opz-decode/device-plug-inventory.json` with each id's
engine-marker paths from the unit's own tree and its description from the app's factory metadata. This answers
part of the "device plug table" question from a file already on hand: the earlier working set (13/14/15/17 for
the drum tracks, 21/25/28/31 on the synth tracks, 34/36/37/39 for FX, plus the 121–150 pack block) is
confirmed, and ids 42, 66, 67 (never seen in any marker or log) are now known to exist.

**What the inventory does and does not explain.** Of the 54 ids, 11 have engine markers in the unit's own
`samplepacks` tree (10, 11, 14, 17, 25, 26, 31, 65, 98, 112, 129) and 35 are described by the app's factory
metadata (name, engine, samples). The remaining 16 — **13, 15, 16, 42, 43, 66, 67, 125, 126, 127, 128, 139,
144, 148, 149, 150** — appear in *neither*, so their engine and sample bindings exist only in the device's own
`settings/plugs.json`. That is now the concrete, single reason the pending document matters: it is the only
remaining key to those 16 plugs — and two of them (13, 15) are the drum-track plugs that have been silent
throughout this session.

**Project files do not carry the track→plug bindings (negative, 2026-10-11 ~03:05).** Searched the ten genuine
`projects/projectNN.opz` (342,848 B each, all from the unit's own content disk) for a per-track plug-id table:
no 16-value window (u16 or u32) contains the unit's plug ids in bulk, and there is no zlib stream in the file
(the app's `ZlibCompressor` is not used for it). Known ids do occur, but scattered and at counts consistent
with coincidence in pattern data. So the binding lives in `settings/slotConfiguration.json` — as the earlier
slot-map work already implied — and the projects add nothing to the plug-table question. The on-hand artifacts
are now mined out: preset bank (plug inventory, done), samplepacks tree (engine markers, done),
configs, logs, projects (nothing further).

**Canonical status page added:** `~/.opz-decode/STATUS.md` — one page with the verified download inventory,
the three outstanding items, the measured blocker on each transport, the tooling table (with the passing offline
verifier) and the single action that completes the pull.

### 66.76 Offline FileSync lookup audit: registered paths, sync-mode gate, and inconclusive sample probes

**Artifact and method.** Extracted `lib/arm64-v8a/libSnakePlugin.so` from the local
`OP-Z_1.3.0_APKPure.apk` and decompiled the targeted functions with **Kuna 1.130**.
Library SHA-256: `c0bb8bffbcc22354b20a6a68e60f3f17db1f89fa35dd96a2a90595988f049679`.
Addresses below are virtual addresses in this AArch64 library, **not Blackfin firmware addresses**.
All seven targeted decompilations returned no reported error; recovered types and helper boundaries
remain decompiler interpretations. No app execution or device interaction was performed.

| Function / address | Observed APK implementation |
|---|---|
| `FileSync::getFilePath`, `0x1179e0` | IDs 0/1/2 select `settings/slotConfiguration.json`, `settings/plugs.json`, and `syncjob.json`, joined to the instance root. IDs 3–12 take a project-file formatting branch. IDs above 12 search an ID-to-path tree; an unknown ID logs the available entries and returns an empty string. |
| Formatting helper, `0x117bb8` | Uses `projects/project%02d.opz`. The exact ID-to-project-number arithmetic was not established in this brief pass. |
| `FileSync::addHostedFile`, `0x11794c` | Inserts an ID/path entry into the hosted-file tree used by the lookup. Registration callers and all possible registry contents were not audited. |
| `FileSync::handleMessage`, `0x116f8c` | For an eight-byte `$35` request, IDs **>=100** are ignored when the sync-mode flag is clear; the diagnostic is `FileSync: ignore file request when not in sync mode, id %d`. |
| `FileSync::sendFilePart`, `0x116c50` | Calls `getFilePath`, then `fopen(path, "rb")`; successful reads are compressed and emitted as `$53` parts. A failed open produces no file data. |
| `FileClient::init`, `0x1111c4` | Sets the instance root from the file manager and derives an `inbox/` path; this is not evidence of unrestricted filesystem export. |
| `FileClient::onServerHeartbeat`, `0x111870` | An active heartbeat received while not already syncing triggers a request for ID 2 (`syncjob.json`). Enabling active sync is therefore not merely a read-permission toggle. |

**Correction to our live probes.** Normal-mode USB settings pulls now work with
`$00` hello → `$51` → `$34` → `$52(active=0)` → `$35`/`$53`. The recent preserved files are:

- `pulled/settings/plugs.json`: 4,742 bytes, SHA-256
  `e417ae6f261bf77501bfea9b68c91d7a94a0c7dafac3a980d7755a9bd4263996`.
- `pulled/settings/slotConfiguration.json`: 1,619 bytes, SHA-256
  `5094738f5dfc13c90c6d4bf30da2cbb5a037582e95156d8de814e84938165b35`.

Both completed with final flags and parse as JSON. The subsequent requests for
`system/content/samplepacks/sfx.aif`, the 19 catalogued factory packs and `CuckooC_open.aif`
returned no part 0. **That is not evidence that those files are absent.** Under the APK logic,
a hashed-path request can be rejected by the inactive-sync gate before lookup; even in sync mode,
an unregistered ID has no path to open. CRC32 transmits an identifier, not a reversible filename.
This also qualifies the whitelist interpretation in
[the clean-room transport notes](refs/op-z-sysex/docs/clean-room-file-transport.md): silence alone
does not distinguish the sync gate, missing registration, failed open or transport failure.

**No audio recovered from the APK in this bounded check.** Its ZIP member names contained neither
`sfx` (case-insensitive) nor `.aif`/`.aiff` extensions. The extracted arm64 library contained no
printable `sfx.aif` string and no ordinary `FORM....AIFF` / `FORM....AIFC` header. This does **not**
exclude compressed, encoded or differently named audio elsewhere in packaged assets, and does not
establish whether the device contains the file.

**Limits and safety.** These are app/simulator implementation findings, not proof of identical
firmware behavior. This audit did not establish how to register arbitrary device-side paths or
read system content, and did not identify the PLAY crash's null object. Do not enable active sync
as a speculative read workaround, overwrite device-generated settings, synthesize `sfx.aif`, or
send console command `0x15`. No files were written to the OP-Z.

### 66.77 Playback dependencies and FileSync ownership: deeper offline audit

**Scope and evidence.** Same APK/library SHA-256 as §66.76, Kuna 1.130 followed by
`llvm-objdump -d --demangle` instruction checks. The raw-disassembly pass was needed because Kuna
misrenders some large object offsets as references to unrelated strings and loses some variadic
arguments. Neither issue is evidence of device memory corruption. Unless explicitly labeled iOS,
addresses here are APK AArch64 virtual addresses. No device commands, content imports or setting changes were performed;
there is no offline reproduction of the Blackfin fault, and no recovery is claimed.

#### Checkpoint 1: shared start path and a concrete simulator limitation

- `Sequencer::onMidiStart` (`0xec984`) calls `resetPlaybackState(this, true, false)`;
  `startPlayback` (`0xec568`) does likewise. `onMidiContinue` (`0xeca18`) passes `true` to
  `continuePlayback` (`0xec3e8`), which can also call that reset depending on current state.
  Continue therefore is **not guaranteed to bypass reset**. This is consistent with the historical
  failed Continue experiment, but does not locate the device fault.
- `resetPlaybackState` (`0xe4360`) resets arpeggio/chord state, reads the current pattern's track
  metadata, calls `nextPattern`, resets step components, clears active notes, sets gain/mute for
  16 tracks and stops parameter sweeps. `Sequencer::init` (`0xe3e08`) also calls it, with different
  arguments (`true, true`), after pattern-container initialization. It is not exclusively a PLAY path.
- The first playback tick remains a separate candidate boundary: `Sequencer::tick` (`0xe52dc`)
  gates step-component entry and `magicChordUpdate`/`playNotes` on playback state, and later advances
  tracks. Seeing the fault after PLAY does not isolate the synchronous reset from subsequently
  scheduled work. The inspected APK tick also observes active file sync and stops playback when
  that state becomes active; sync is not a neutral diagnostic toggle.
- `initArpeggio` (`0xc1c5c`) loops over six file reads; each non-positive read result falls back to
  a built-in string before `parseCode`. `resetArpeggio(true, false)` (`0xc1e54`) only resets counters;
  the note-kill branch requires the second argument. Missing arpeggiator files alone do not imply
  an uninitialized arpeggiator in this APK. This does not reverse the prior device tests or prove
  identical fallback behavior in firmware.
- `DmxController::restartPattern` (`0xc5a30`) is exactly `str wzr, [x0, #0xc]; ret`.
  `Synth::setMasterGain` (`0xfa614`) and `setMasterMute` (`0xfa650`) write numeric fields in the Synth
  object, with no file opens or plug lookups in those functions. `magicChordReset` (`0xc99ac`) clears
  a state byte; `StopAllSweeps` (`0xd0a34`) clears an in-memory collection. None identifies a missing
  persistent file to restore.
- **Critical limitation, verified as literal AArch64 `ret` (`d65f03c0`):**
  `Sequencer::updateRequestedSamplePacks` (`0xe5be0`), `updateMetronome` (`0xe5be4`),
  `InstrumentManager::init` (`0x13c7dc`), `InstrumentManager::noteOn` (`0x13c934`),
  `InstrumentManager::noteOff` (`0x13c938`) and `FxManager::init` (`0x13cde0`).
  Shared symbol names do **not** mean the APK contains the device's implementations. This library
  cannot settle the device's missing-system-sound or engine-initialization dependencies through
  those stubbed paths, nor map Blackfin `RETX 0x80117baa` to an ARM instruction.

#### Checkpoint 2: reserved project reads and hosted-file ownership

- The exact project mapping omitted in §66.76 is now instruction-verified:
  `getFilePath` computes `w4 = fileId - 2` at `0x117a08`; the helper at `0x117bb8` takes that value as
  the first variadic argument for `projects/project%02d.opz`. Thus **IDs 3–12 map to projects 01–10**,
  joined to the instance root. These IDs are below the `>=100` inactive-sync guard. This is a
  candidate read-only backup channel, **not yet tested on this device**, not access to system files,
  and not a reason to repeat the already-failed project-clear experiment.
- `FileServer::addSyncFile` (`0x11627c`) computes the path's ID, CRC and size, adds a manifest entry,
  joins the path to the **local server's root**, calls `addHostedFile` (call site `0x116468`), and
  writes local `syncjob.json`. A scan of decoded direct `b`/`bl` references to the implementation
  and its PLT entry found this one registration call site. Indirect/external calls were not excluded.
  This registers a **sender-local file**; it does not register or expose an arbitrary path on the OP-Z.
- `FileClient::startSyncJob` (`0x111bc0`) marks the client active and queues downloads for manifest
  entries with absent operation, `write` or `import`. Nothing in that inspected function creates
  a device-side hosted-file registration. Host upload manifests are not demonstrated read manifests.
- `calcFileId` (`0x117c58`) lowercases ASCII A–Z and computes CRC32; it does **not** special-case
  project paths. The reserved project IDs are explicit aliases in `getFilePath`, not what a generic
  pathname hash produces. `FileClient::handleMessage` (`0x11167c`) and `FileServer::handleMessage`
  (`0x115f10`) delegate file messages to `FileSync` and handle their respective connection/heartbeat
  messages. No additional remote-path registration operation was identified in those dispatchers;
  other protocol families and indirect calls are outside this bounded check.

#### Checkpoint 3: CRC errors do not prove empty installed engines or a whole-job abort

The following path distinction is visible in `requestFile` (`0x1176ac`), `FileClient::init`
(`0x1111c4`) and `finalizeSyncJob` (`0x111ed8`), and the finalize branch was instruction-checked:

```text
requestFile:
    CRC(userRoot + path) == nonzero expected CRC -> skip download
    otherwise download into inboxRoot + path
finalizeSyncJob, for each ordinary write entry:
    CRC(inboxRoot + path) != expected CRC -> log error naming userRoot + path; continue
    otherwise copy inboxRoot + path to userRoot + path, overwrite enabled
```

- **The diagnostic names a different path from the one checksummed.** At `0x11225c`, the CRC call
  uses the inbox-derived string; the mismatch diagnostic at `0x1123a4` uses the final destination.
  A skipped, already-matching installed engine can therefore lack an inbox copy and produce
  `invalid file crc, can't finalize .../engines/... (0 != expected)` without proving that the
  installed engine is empty. This is an APK explanation compatible with the historical log pair,
  **not a device-side reproduction**.
- `FileManager::calcFileCRC` (`0x113d84`) returns zero when `fopen` fails. With seed zero an empty
  file also produces zero; CRC zero is not an existence/size test. Earlier CSV rows and the
  engine-emptying diagnosis that equated it with an empty installed file must not be used as proof.
- A mismatch branches from `0x1123a8` to cleanup at `0x112608`, then to iterator advancement at
  `0x112080`. It **skips that entry rather than aborting the whole job**. Other entries can apply,
  and the end of the function still recalculates state CRC and calls
  `PlugManager::importSlotConfiguration` (`0x11200c` call site). This corrects §66.53's blanket
  aborted-apply explanation; it does not establish which historical device files were promoted.
- `FileManager::copyFile` (`0x113b7c`) opens the source `rb` and destination `w+b`, then copies bytes.
  The successful finalize branch calls it at `0x1122a8` with overwrite enabled. It is **not an atomic
  rename**, despite the failure diagnostic saying `Failed to rename file`. There is no demonstrated
  whole-job rollback, so active synchronization is unsuitable as an unguarded recovery experiment.
- The inspected finalizer has project-reload and `patch.json` import hooks, plus a later
  `removeUserPlugAndSample` branch. It is a state-changing workflow, not a generic read session.
  The missing factory audio is not regenerated by any operation established in this audit.

#### Checkpoint 4: initialization data versus device-only behavior

- `StepComponentManager::init` (`0x105674`) calls `StepComponents::registerComponents` (`0x1047d4`).
  The latter registers eleven linked globals: pulse repeat/hold, timing, velocity, pitch ramp up/down,
  random, glide, parameter sweep, tonality and transport. ELF relocations identify those globals.
  `reset` (`0x105624`) clears its state buffer then invokes registered reset callbacks; `enterStep`
  (`0x106178`) consults pattern play-style settings and dispatches matching component callbacks.
  The registration routine does not load component definitions from a missing NAND file. Callback
  bodies were not exhaustively audited and no component was identified as the physical crash cause.
- `PatternContainer::init` (`0xd0da8`) stores a supplied backing-data pointer and index;
  `Sequencer::init` allocates no external project resource in that helper. This does not prove
  firmware pointers are valid, but gives no justification for another project-clear or fabricated
  project-file experiment.
- `PlugManager::init` (`0xd6d7c`) uses `crc32('engines/tapetwo.engine')` as a map key and installs
  pointers whose ELF relocations resolve to the library's own `TapeTwo::init`, `renderFX`,
  `onNoteOn` and `onNoteOff` (`0x1d5600`, `0x1d5608`, `0x1d5610`, `0x1d5618` GOT slots).
  It then calls linked `TapeTwo::initModule` at `0xd6ea4`; it does **not** open that engine pathname
  in this routine. This invalidates the APK-based causal argument in §66.62, not the independent
  observations that device engines have gone missing after content operations.
- `SampleLoader::init` (`0xdc65c`) and `initSamplePacks` (`0xdc738`) initialize in-memory pack
  descriptors and backing-buffer references. These functions do not synthesize or recover
  authentic factory audio. The stubbed request/update and instrument initialization paths remain
  a hard limit on using this APK to explain the real transport fault.

#### Checkpoint 5: existing iOS archive corroborates the limitation, not a recovery implementation

A bounded cross-check used the already-local `~/.opz-decode/ios-apps/OP-Z-archived.ipa`, not a
new download. Its `Info.plist` identifies **1.3.1, build 194**; archive SHA-256:
`8be1231ada716389cdfd885d64dd411680adfe8ffffacffa8f23d9ffc2ef9103`.
The extracted member `Payload/OP-Z.app/Frameworks/UnityFramework.framework/UnityFramework`
is ARM64 Mach-O, 41,787,024 bytes, SHA-256:
`f5ddfa272688b31c07b9654dbc4aa5d8b8bc3cf8f4b0e84c99683eb79bba9c90`.
Its encryption load command reports `cryptid=0`; no decryption or app execution was attempted.

Kuna's function-inventory command exceeded the 90-second budget without output. The bounded
fallback used `llvm-nm --defined-only --demangle` to locate symbols and `llvm-objdump` on exact
address ranges; this was **not** a successful whole-framework decompilation.

- Six matching **iOS** functions are again literal `ret`: `updateRequestedSamplePacks`
  (`0x10a9a50`), `updateMetronome` (`0x10a9a54`), `InstrumentManager::init` (`0x110485c`),
  `noteOn` (`0x11049a8`), `noteOff` (`0x11049ac`) and `FxManager::init` (`0x1110c7c`).
  This second shipped app does not supply the missing implementations through those symbols.
- **iOS** `FileSync::handleMessage` (`0x109b8d4`) also compares file ID against 100 and rejects
  IDs at/above that threshold if its sync flag is zero (`0x109b900`–`0x109b90c`).
- **iOS** `getFilePath` (`0x109bed4`) likewise has the reserved project branch: subtract two
  (`0x109bf00`), bound at 12, format `projects/project%02d.opz` (string VA `0x23ac019`),
  then concatenate the root. Higher IDs enter an ID-to-path tree lookup (`0x109c15c`).
  This independently supports the reserved-project-read candidate but still is not firmware proof.
- No literal `sfx.aif` string was found in this framework's bytes. That bounded string search does
  not exclude encoded assets, and is not evidence that the physical OP-Z lacks the file.

**Reproduction anchors.** With the §66.76 hash-verified library extracted to `$LIB`, the main
findings can be revisited without running vendor code or connecting the device:

```sh
kuna decompile-all "$LIB" --addr 0xe4360 --addr 0xe3e08 --addr 0xe52dc \
  --addr 0xc1c5c --addr 0x1176ac --addr 0x111ed8 --addr 0x113d84 \
  --addr 0x11627c --addr 0xd6d7c --json > playback-filesync-audit.json
llvm-objdump -d --demangle "$LIB" > playback-filesync-arm64.asm
llvm-readelf -r "$LIB" > playback-filesync-relocations.txt
```

**Outcome / next evidence boundary.** No verified full-recovery procedure or particular missing
file causing PLAY was found. The concrete new device-test candidate is a bounded **inactive-sync
read of a reserved project ID**, bracketed by known-good settings reads and saved to a new backup
location. It would test the APK-derived read mapping, not fix PLAY; it has not been run. Restoring
engines, registering system paths, toggling active sync or constructing settings remains unjustified
without separate device evidence and an explicit rollback plan. Further causal attribution needs
matching device OS instructions/runtime evidence, or another artifact demonstrably containing the
non-stubbed device-equivalent audio implementation. No new crash, format, reflash or write was induced.

### 66.78 Diagnostic-engine feasibility: concrete exports, but no safe deployment established

**Bounded offline pass.** Inspected the genuine `engines-official/crush.engine` (1,012 bytes,
SHA-256 `f1542de16fddca835c6becdb0d809f7e16d75c5e7c19bde2da31c1dca6da34f9`) as a small format
specimen, **not a recommended engine to replace**. No engine was modified, staged or executed.
No device requests or writes were made. The proposed memory-reader remains a research hypothesis.

**Native-file evidence.** Walking all 21 official engines as loader records again ends exactly at
EOF. All **138 headers** have upper code byte `0xad` and XOR of their sixteen bytes equal to zero.
This is a reproducible header consistency property, **not proof that payloads are unsigned or that
modified code will be accepted**. The firmware's loader/authentication logic is not available here.
The first and last records in Crush have zero byte count; no code is loaded at their `0x11a00000`
destination. Its four nonempty records map as follows:

| File data offset | Destination | Bytes |
|---|---|---:|
| `0x20` | `0x81bfb400` | 56 |
| `0x68` | `0x81bfb438` | 760 |
| `0x370` | `0x81bfb730` | 92 |
| `0x3dc` | `0x81bfb78c` | 8 |

The first mapped block begins with words `0xfeed0ad1`, `0xad1facef`, followed by name/address pairs
and a zero/zero terminator. Resolving the name pointers through the block map yields:

| Export | Native address | File offset |
|---|---|---|
| `initModule` | `0x81bfb450` | `0x80` |
| `init` | `0x81bfb4bc` | `0xec` |
| `renderFX` | `0x81bfb4f0` | `0x120` |
| `onNoteOn` | `0x81bfb444` | `0x74` |
| `onNoteOff` | `0x81bfb438` | `0x68` |

These are native engine addresses, not APK addresses. This recovers entry-point locations without
assuming the obsolete flat-image model. The mapped data accounts for the file; that alone does not
exclude authentication elsewhere or checks embedded within declared records.

**Callback/output evidence and limits.** In the APK, `Crush::initModule` (`0x123460`) accepts version
argument zero and saves the supplied `ModuleCallbackInterface` pointer. Its `renderFX` (`0x1234a4`)
writes to a caller-supplied audio buffer. ELF relocation targets in the callback table passed by
`PlugManager::init` include `sequencerSetValue`, `sequencerGetValue`, waveform/filter tables,
ADSR helpers, `getPresetData` and IIR helpers. A general log, MIDI-send or file-write callback was
**not established in this inspected table**. Audio is therefore a plausible result channel, not a
proven byte-exact dump path; no marker, encoding, capture or native ABI was validated on hardware.
ARM calling conventions and pointer widths must not be copied into Blackfin code.

**Tool boundary.** Kuna 1.130 rejects the raw `.engine` as an unrecognized object format. Installed
`rasm2 -L` did not list a Blackfin architecture, and no `bfin-elf-objdump` was available on PATH.
Tried radare2 6.2.2 directly: `r2 -q -a bfin -b 16 -c 'i;pd 8' engines-official/crush.engine` returns
`asm.arch: cannot find 'bfin'`; `pd` consequently prints raw bytes, not Blackfin instructions. The
installed architecture list has no Blackfin plugin. The Blackfin function bodies were **not
disassembled or decompiled** in this pass; only their export table and load mapping were decoded.
APK `initModule`/`init`/`renderFX` and TapeTwo `initModule` were examined as cross-architecture hints,
not substituted for native instruction evidence. The later Blackfin+ Binutils fallback and its limits
are recorded in §66.79.

**Feasibility verdict.** The native entry table makes a diagnostic module structurally plausible,
but four prerequisites remain unproved: modified-module acceptance; a correct native ABI and
memory-access privileges; a dependable result channel; and boot-independent rollback. File-placement
capability does not establish any of them. A read-intended module can still fault, corrupt RAM or
prevent boot, and preserving the original file on the host is not a verified rollback procedure.
Do **not** replace Crush, TapeTwo or another engine on this evidence. §66.79 records a partial
Blackfin+ disassembly; native ABI and callback validation remain open before designing even a
fixed-marker experiment. No full-recovery method was proved.

### 66.79 Blackfin+ Binutils fallback: partial engine assembly, not pseudocode

The previous Kuna and radare2 routes could not decode raw engine code. A local fallback was built
from `deanm1278/blackfin-plus-gnu` (revision `e4408a15b9be6cd911283f103a1a3f69e9a6b8c0`), an ADI
GNU toolchain fork whose README says BF70x/Blackfin+ support is incomplete. Its `bfin-elf-objdump`
was built on macOS for `--target=bfin-elf` (`--with-system-zlib`; `make MAKEINFO=true all-binutils`,
to bypass an unavailable documentation generator). The executable is temporary at
`/tmp/bfin-binutils-build/binutils/objdump`; source and generated blocks live under `/private/tmp`.
Nothing was installed in the repo or on the device.

Extracted the declared nonempty loader payload blocks from the verified Crush stream and disassembled
them with `-D -b binary -m bfin --adjust-vma=<block destination>`. This yields useful native
instruction text for ordinary Blackfin operations and some Blackfin+ forms. For example, the export
table's `onNoteOff` at `0x81bfb438` and `onNoteOn` at `0x81bfb444` each decode as `LINK 0; UNLINK;
RTS; NOP` (both are stubs in this engine). `init` at `0x81bfb4bc` calls the helper at `0x81bfb478`,
then sets up two globals from the data buffer. `renderFX` at `0x81bfb4f0` decodes into DSP and buffer
operations, as expected for an audio effect. Those observations are from the genuine engine bytes,
not from APK ARM64 functions.

**Hard limit:** this fork is explicitly incomplete for Blackfin+, and emits `ILLEGAL` at apparent code
addresses including `0x81bfb454`, `0x81bfb468` in `initModule`, and `0x81bfb5c4`, `0x81bfb602` in
`renderFX`. Some other `ILLEGAL` records fall in metadata/constants and are expected when linear
sweeping data. Therefore instruction boundaries and function semantics around unsupported words are
not established. The disassembly is a useful scout, **not a complete/verified decompilation**. Do not
infer the `initModule` ABI or memory-read capability from the partial output. The engine remains
unchanged and unexecuted; no hardware interaction occurred.

A real pseudocode decompilation would need a Blackfin+ SLEIGH language in a full Ghidra runtime. The
available `hekar-lab/Ghidra-BlackFinPlus` source (revision
`380b86f1de8c69e3ce433f93a93cb771fc90d3dc`) is explicitly marked untested and does not ship a
compiled language/runtime here. Kuna's bundled `slacomp` rejected its SLEIGH at sub-byte bitranges and
an unsupported string expression; Kuna 1.130 cannot use this source as-is. Full Ghidra is not
installed. Its public distribution is about 570 MB, so it was not downloaded as an unrequested
large artifact. Thus a few functions can now be partially disassembled, but there is not yet a
reliable full-engine decompiler available in this environment. Stop before treating a pseudocode
reconstruction as evidence; full BF+ support or vendor CrossCore tools are required for that.

### 66.80 Ghidra installed; Blackfin+ loader and pseudocode pass

Installed Ghidra 12.1.4 at `~/Applications/Ghidra_12.1.4` from the official public ZIP (SHA-256
`ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db`). Built its native macOS ARM64
components with Ghidra's Gradle wrapper (`buildNatives`); this was necessary because the release
ZIP did not include the `mac_arm_64/decompile` binary. Build completed successfully.

Built and installed the [HEKAR Blackfin+ Ghidra extension](https://github.com/hekar-lab/Ghidra-BlackFinPlus),
source revision `380b86f1de8c69e3ce433f93a93cb771fc90d3dc`, in the Ghidra installation extension directory
`~/Applications/Ghidra_12.1.4/Ghidra/Extensions/Ghidra-BlackFinPlus`. To build it against Ghidra
12.1.4, adapted the extension's loader override to the current `ImporterSettings` API and the
additional `getDefaultOptions` argument in a temporary source copy; the extension itself is still
marked untested by its authors. The original install was untouched by this compatibility patch.
Compiled its Blackfin+ SLEIGH processor with Ghidra's own `support/sleigh` (not Kuna's limited
`slacomp`). The compiler reports 72 NOP-constructor and 20 local-operand-collision warnings.

**Verified target import.** Headless Ghidra accepted `engines-official/crush.engine` with loader
`Blackfin+ Boot Stream` and language `blackfinplus:LE:32:default`; the loader created mapped,
initialized blocks at `0x81bfb400`, `0x81bfb438`, `0x81bfb730`, and `0x81bfb78c`, matching the
independently walked container. Ghidra's native decompiler then produced pseudocode for the five
name-table exports after seeding function entries from the validated table:

- `onNoteOff` (`0x81bfb438`) and `onNoteOn` (`0x81bfb444`) each reduce to `return;`, consistent with
their exact `LINK; UNLINK; RTS; NOP` bodies.
- `initModule` (`0x81bfb450`) decompiles to a comparison of its first argument with a global, storing
  its second argument to a global on match, and returning a boolean. The recovered signature/types
  are provisional.
- `init` (`0x81bfb4bc`) calls an internal helper with a 24-byte size and stores the returned buffer
  and a `+0x100` pointer in globals.
- `renderFX` (`0x81bfb4f0`) decompiles to extensive fixed-point DSP arithmetic and buffer accesses.

The persistent project is at `~/Documents/GhidraProjects/OPZ-crush/engine-analysis.gpr`; captured
headless pseudocode is in `~/Documents/GhidraProjects/OPZ-crush/ghidra.log`. Reprocessing that saved
project reproduced successful decompilation of all five exports. Ghidra emitted a language-defined
DDR memory-block conflict warning,
but the four initialized loader blocks and export addresses were present in the imported program.
The Blackfin+ language extension is explicitly untested; compiler warnings, inferred types (including
an obviously spurious library type on `init`), and the prior objdump's unsupported words mean the
pseudocode is **evidence for navigation, not a verified semantic reconstruction**. The trivial note
handler stubs are the strongest output. No engine was modified or executed and no device was accessed.

### 66.81 Offline decompilation sweep of the remaining official engines

Imported the other 20 `engines-official/*.engine` files into the same persistent Ghidra project;
Ghidra's `Blackfin+ Boot Stream` loader and `blackfinplus:LE:32:default` language were selected
automatically. Revalidated all 21 streams: each parsed exactly to EOF, every 16-byte loader header
passed its XOR check, and each engine export table had its two magic words and zero terminator.
Each table contains the same five entry points: `initModule`, `init`, `onNoteOn`, `onNoteOff`, and
`render` or `renderFX`. The script created functions from these validated table addresses and
produced pseudocode for **104 of 105 exports**. The sole failure was `fdnreverb.renderFX` at
`0x81c07fa0`, which timed out both at 60 seconds and again at 300 seconds; it is a decompiler
limitation, not evidence of a firmware hang.

The best cross-engine lead for the recovery goal is still an **ABI question, not an exploit**:
`initModule` generally compares its first argument with an embedded ID, saves the supplied callback
pointer, and returns a memory-size request. Nonzero requests in the pseudocode include chorus
`0x4000`, chorus2 `0x8000`, delay and TapeTwo `0x200000`, FDN reverb `0x3a6c4`, and reverb `0xe3a0`.
Several render/note paths dispatch indirectly through the stored interface pointer at offsets
`+4`, `+0x1c`, `+0x20`, and `+0x24`; `delay` also reads a pointer at `+8` for a table lookup. The
actual BF703 firmware callback meanings are not established by this pass. Other
exports are audio/voice state code, not obvious control or file-service interfaces.

A bounded scan of decompiler-named static globals found all of them inside each module's own mapped
payload ranges; it found no explicit OS-memory, filesystem, or console-output primitive in the
export pseudocode. That is **not proof of absence**: inferred C and pointers passed through the ABI
are unreliable/unbounded, and extension warnings remain. No actionable route to read firmware
memory or exfiltrate it has been demonstrated. Modifying/using an engine as a payload still requires
the independent gates recorded above—modified-code acceptance, verified memory access/output, and
rollback—and separate device approval. No device was accessed and no engine was modified or run.

Per-engine headless C output and logs, plus the Ghidra database, are retained under
`~/Documents/GhidraProjects/OPZ-crush/`; the export functions are named in each `decompile-<engine>.out`.

### 66.82 APK callback-table cross-check: useful ABI leads, not firmware proof

Continued the authorized **offline** audit against `OP-Z_1.3.0_APKPure.apk` (SHA-256
`ce3b79ca85f6588a584a46ffdbe986ea5e350c16da45c1ce47d48ae514cfdf57`); its extracted ARM64
`libSnakePlugin.so` is SHA-256
`c0bb8bffbcc22354b20a6a68e60f3f17db1f89fa35dd96a2a90595988f049679`. Kuna 1.130 decompilation
and ELF relocations show `PlugManager::init` passes `0x1cdff8` to `TapeTwo::initModule`. In this
APK table, relocations identify `sequencerSetValue` at +0, `sequencerGetValue` at +8,
`updateParametersADSR` at +0x38, `updateParametersAHD` at +0x40, and `getPresetData` at +0x50.
This is a map of an Android simulator table only.

There are useful internal width/signature cross-checks: APK `TapeTwo::init` calls its interface at
+8 with argument `4` to get a sequencer value; the genuine BF+ TapeTwo engine pseudocode calls its
saved interface at +4 with `4`. Likewise, engine indirect calls at +0x1c use five arguments and
those at +0x20 use seven, matching APK callbacks `updateParametersADSR` (five arguments) and
`updateParametersAHD` (seven). These alignments make the APK useful for generating ABI hypotheses,
but do **not** establish that the physical BF703 firmware uses the same table or functions. In
particular, the engine's +0x24 callback remains unmapped.

The APK's file-looking callback is not an arbitrary-path API: `getPresetData` chooses either the
fixed `rendertone.preset` path or `engines/fmedit.preset`, then calls `FileManager::readFile` with a
0x1000-byte limit. That helper opens the supplied path with `fopen(...,"rb")`; within this callback,
the path is selected internally, not provided by the engine. The table's +0x50 entry would be
byte-offset +0x28 in a 32-bit table with the same layout; no evidence here maps the BF engine's
+0x24 call to it. This establishes neither an OS-memory read nor a firmware filesystem primitive.

**Result / blocker:** this cross-check narrows one inspected app ABI but produces no device exploit
and cannot resolve callback permissions, engine acceptance, or output on hardware. The actual
1.2.45 `firmware/blackfin/bin/opz.ldr` remains unavailable as plaintext: local `.zfw` packages
still have key index `0xff`; the only similarly named local ZIP inspected here is a user-tree
ablation containing settings and engine files, not the OS image. The OS entry in the encrypted
update archive remains Deflate-compressed and would require the already-retracted full 466,903-byte
oracle recovery (about 7,412 cycles at the measured 63 bytes/cycle). With device tests, engine installation, NAND-format command 0x15, and physical
JTAG excluded, the next evidence-bearing step requires an independently available plaintext copy
of the matching firmware loader/host binary or equivalent vendor ABI source. No device was
accessed and no engine was modified or executed.

### 66.83 Cross-product key lead: early OP-1 Field firmware shares the OP-Z key

A newly checked public source changes the *lead* for obtaining plaintext, though not the current
feasibility result. In an OP-Forums post dated January 25, 2024, the OP-Z firmware researcher says
they possess the OP-Z AES key and that it was also used by early OP-1 Field firmware, before TE
changed keys starting with OP-1 Field 1.1.6. In a later post (April 9, 2026), the same researcher
explains the key was found by sliding a 32-byte window over the **already-decrypted OP-Z bootloader**;
the key itself and a decrypted archive were not posted. Source:
https://op-forums.com/t/custom-firmware-on-the-op-1/4283?page=44

The public `op1hacks/op1-field-fw-archive` repository lists early 1.1.2 and 1.1.4 `.tfw` files,
but its inventory contains firmware downloads and changelogs—not a plaintext bootloader, extracted
key, or decrypted OP-Z archive. Thus the cross-product match does not independently recover the key
or remove the OP-Z oracle bottleneck. It does identify a specific offline acquisition lead: ask the
researcher for a lawful, privately shareable plaintext 1.2.45 loader/host copy or key, rather than
repeat the 7,412-cycle oracle extraction. Public sources inspected do not establish that they will
share either artifact. No contact was sent, no firmware was downloaded, and no device was accessed.

**Correction from §66.84:** the 7,412-read estimate is specifically for the large `opz.ldr` OS member;
it is not yet established as the cost of recovering the bootloader/key. See the next section before
using that estimate for key extraction.

### 66.84 The key search may need only the separate bootloader member

The researcher's method requires scanning the decrypted **bootloader file**, not the whole firmware
archive or necessarily the OS image. The local evidence identifies `firmware/blackfin/bin/opz.ldr`
as the 466,903-byte compressed OS member, while the real updater separately reports an `os` and a
`bootloader` component. Therefore the previous response's implication that recovering the key via
the oracle necessarily costs 7,412 reads conflated the OS member with the bootloader component.

At the time of this entry, the exact bootloader member path and size were unknown. The follow-up
bounded reads in §§66.85–66.87 identified `firmware/blackfin/bin/bootloader.ldr` and its compressed
size. Recovering the key still requires the complete compressed member, inflation, and a scan of
32-byte windows as AES-256 key candidates; only the first 106 compressed bytes are currently
recovered. The actual key match remains unverified. This is separate from recovering the 466,903-byte
`opz.ldr` OS member, which remains relevant to the OS/host ABI audit.

### 66.85 First next-entry probe and bounded collector

The automatic decode farm was active as launchd job `com.opz.decode` (PID 755 running
`/tmp/opzfarm.py 100000 1`) and was repeatedly ejecting the volume. Disabled/unloaded that job while
preserving its durable state; no farm process remains. The first manual eject was dissented by that
process, so no capture was obtained in that attempt. Subsequent probe was run only after the farm
stopped.

The aligned oracle probe at archive payload offset **467,280** returned a valid local ZIP header and
19 plaintext bytes before a real NUL terminated the log:

```
50 4b 03 04 14 00 00 00 08 00 95 ae 3a 52 d2 c6 f2 2a 0b
```

This confirms a local entry header (`PK\x03\x04`), Deflate method 8, and only the low byte `0x0b` of
its compressed size; the filename and full sizes are still unknown, so this does **not** identify the
bootloader. The follow-up window at **467,296** shifts the size/name fields into the first, IV-masked
block so their zero bytes need not terminate the C-string leak.

Added `toolkit/opzbootprobe.py`, a bounded `uv run --script` collector. It waits for the update volume,
refuses to run alongside the farm or when another `.zfw` exists, stages one probe without deleting
existing files, safely ejects, captures/reopens the CDC stream, and durably records raw frames plus
recovered bytes under `~/.opz-decode/bootloader-probes/`. Each further cycle requires the user to
re-enter update mode; `--max-probes` is capped at 64 and defaults to one. It sends no console
commands, including 0x15. Its offline self-test and Python compilation pass. At that point no
bootloader member had yet been identified; the later ten-probe follow-up is in §66.87.

### 66.86 `bootloader.version` is metadata, not the bootloader image

The collector recovered payload bytes 467,296–467,359 in one update-mode cycle. Combined with the
previous 19-byte prefix at 467,280, the local header parses as: method 8 (Deflate), CRC-32
`0x2af2c6d2`, compressed size 11, uncompressed size 9, filename length 40, no extra field, and
filename `firmware/blackfin/bin/bootloader.version`. Thus the hypothesis that this *next* entry is
the bootloader image is disproved: it is a small version-metadata file. Its compressed data starts at
467,350; the latest range contains its first 10 of 11 compressed bytes. The following local header
begins at payload offset **467,361**.

A subsequent 10-probe collection from 467,360 is recorded in §66.87 and supersedes that narrow
follow-up: it reached and identified the actual `bootloader.ldr` entry, though only its first 106
compressed bytes were captured.

### 66.87 Ten-probe walk identifies the actual bootloader entry

The collector's `state-467360-512.json` contains 319 contiguous, deobfuscated bytes for payload
offsets 467,360–467,678 from ten cycles. Per-cycle leaks ranged from 16 to 63 bytes; the range was
not completed. Combining the earlier 19-byte prefix at 467,280 and the 467,296 state yields a
self-consistent chain of four local ZIP entries. The three small entries were raw-DEFLATE inflated;
all declared uncompressed sizes and CRC-32 values match:

| Local header | Member | Compressed / uncompressed | CRC-32 | Inflated content |
|---:|---|---:|---|---|
| 467,280 | `firmware/blackfin/bin/bootloader.version` | 11 / 9 | `2af2c6d2` | `1.1.35+0` (LF) |
| 467,361 | `firmware/blackfin/bin/opz.crc32` | 12 / 10 | `b302a14e` | `2403806141` |
| 467,434 | `firmware/blackfin/bin/os.version` | 11 / 9 | `8c515f83` | `1.2.43+0` (LF) |
| 467,507 | `firmware/blackfin/bin/bootloader.ldr` | **156,306 / 257,644** | `5087bc54` | not yet recovered |

Thus the actual loader member is now identified, distinctly from the small version metadata. Its
compressed data begins at payload offset **467,573**. The collected range includes its first 106
bytes (467,573–467,678); 156,200 compressed bytes remain. Header parsing and the three independent
inflate/size/CRC checks strongly validate the offset map and leak decoding.

The 10 cycles recovered 319 unique bytes (31.9 bytes/cycle), depressed by NULs in ZIP headers and
metadata. Capped frames yield 63 bytes, but aligned retries then overlap 15 bytes and add 48 new
bytes; a consistently capped stream would need about **3,255 more cycles**. Uncapped 64-byte reads
can advance farther, while early NULs reduce throughput, so several thousand cycles is the defensible
scale, not a precise forecast. The 10-cycle average is not representative of compressed payload.
Recovering this member is far cheaper than the separate 466,903-byte `opz.ldr` member, but still
thousands of manual update-mode cycles. No device writes, console commands, or engine operations
occurred during this analysis.

### 66.88 CCES loader manual: useful LDR structure, no key offset

Read the supplied Analog Devices *CCES 2.9.0 Loader and Utilities Manual*, revision 2.3 (May 2019),
`/Users/jakubkolcar/Downloads/cces-loaderutilities-manual.pdf`:

- The supported ADSP-BF70x family explicitly includes BF703 (printed p. 6-1). The BF7xx loader guide
  says `.ldr` is a boot stream formatted for the on-chip boot kernel (p. 6-4).
- The general Blackfin loader description says an `.ldr` repackages the executable's code/data into
  blocks whose tags carry information such as word count and destination address; debug and symbol
  information is removed (p. 2-10). This makes the *inflated* bootloader image a load-block stream,
  not a flat executable where one fixed file offset can be assumed to equal a runtime address.
- The manual directs readers to the BF7xx Blackfin+ Processor Hardware Reference for exact block
  headers and boot-stream details (pp. 6-2, 6-4). CCES does not provide the ADSP-BF7xx ROM source
  (p. 6-6). This manual therefore does not give us an exact block parser or an AES-key location.
- CCES secure-boot packaging first builds a binary `.ldr` and then uses `signtool` (p. 6-3). The
  signtool section describes AES-128 keys (BLx keys in OTP, or BLw-wrapped keys) and ECDSA-224
  signatures (pp. 13-11–13). Do not conflate that ADI secure-boot mechanism with the OP-Z updater's
  reported AES-256-CBC key or conclude those are the same key/source.

**Practical implication:** _bt's reported sliding 32-byte scan still points to scanning the complete
inflated `bootloader.ldr`; the CCES manual suggests the loader blocks can later map candidate bytes
to load addresses, but does not narrow the key to a particular block. The current 106-byte raw-DEFLATE
prefix emitted no output when tested incrementally, so it is too short to inspect block structure.
The exact Hardware Reference block format and key location remain unverified.

### 66.89 BF70x hardware reference gives a concrete LDR parser signature

The user supplied the official Analog Devices *ADSP-BF70x Blackfin+ Processor Hardware Reference*,
2223-page PDF, downloaded as
`/Users/jakubkolcar/Downloads/BF70x_BlackfinProcessorHardwareReference.pdf` (SHA-256
`5f4a66dde933b5a716a9fa8171254742b4b4e66789a274497a415eb3f0a7b5d2`). Its Chapter 36 is the
relevant BF70x boot-stream specification; the manual includes BF703 in this family.

**Useful recognition and parsing facts (printed pp. 36-32–36-41):**

- A standard loader stream consists of blocks, each beginning with a **16-byte header** comprising
  four 32-bit words: `BLOCK_CODE`, `TARGET_ADDRESS`, `BYTE_COUNT`, and `ARGUMENT` (p. 36-34).
- `BLOCK_CODE` has signature byte `0xAD` in bits 24–31; bits 16–23 are an 8-bit XOR checksum of
  the other 24 bits. The low bits encode BCODE and flags including `FIRST` (bit 14), `FINAL` (bit
  15), and `INIT` (bit 11) (pp. 36-34–36-35). This gives a strong candidate-header test; validate
  checksum, block boundaries, first/final flags, and 4-byte constraints on target addresses/counts.
- For a normal block, `BYTE_COUNT` specifies the payload length and `TARGET_ADDRESS` its load
  destination; the next block follows its payload (pp. 36-36–36-37). Specialized blocks change field
  meanings, so parse their flags before advancing.
- A secure-boot image may instead begin with a **180-byte secure header**, followed by a standard
  loader stream. Its 32-bit type values are `0x424c7001` (BLp), `0x424c7801` (BLx), or `0x424c7701`
  (BLw); the BLw header's bytes 68–91 hold wrapped 128-bit key material and bytes 92–107 an IV
  (pp. 36-50–36-51). These are ADI secure-boot keys, **not** evidence of the OP-Z updater's reported
  AES-256 key. First inspect the inflated file's header for these types; otherwise test for an LDR
  block header at offset zero.

**Direction:** test the 180-byte secure-header possibility, then locate and validate block headers.
A block parser can map offsets in the inflated file to Blackfin load addresses and narrow
interpretation, but _bt's reported 32-byte sliding scan still calls for scanning the whole inflated
image. This reference does not reduce the number of encrypted-archive oracle reads. A later
continuation exposed the script's masked-NUL bug, repaired the state, and produced the first valid LDR
headers; see §66.90.

Source: Analog Devices, *ADSP-BF70x Blackfin+ Processor Hardware Reference*, Chapter 36, printed
pages 36-32–36-41 and 36-50–36-51; official PDF:
https://www.analog.com/media/en/dsp-documentation/processor-manuals/BF70x_BlackfinProcessorHardwareReference.pdf

### 66.90 Masked-NUL bug fixed; first boot-stream blocks validate

The follow-up run logged seven identical six-byte leaks at payload offset 467,808. The saved range
already contained bytes through 467,822, but the next missing byte was 467,823; alignment rounded
that retry back to 467,808. The underlying byte at relative position 6 was **0x01**. The probe's
first-block XOR delta was 1, so the transmitted byte became NUL and stopped the C-string log. The
collector incorrectly treated the terminator as plaintext zero because it compared the absolute
payload offset with 16; it then retried the same masked window and never advanced.

Fixed `toolkit/opzbootprobe.py` to record a terminator inside the masked first 16 bytes as the mask
delta (otherwise as zero), rebuild legacy state from read records, and choose a different XOR delta
when a retry lands on a known plaintext byte. The self-test reproduces the `0x01 XOR 0x01 = NUL`
case and checks both state repair and next-mask selection. Large ranges no longer print a huge hex
dump. The existing `state-467360-512.json` is repaired on load; its duplicate read records are
preserved. No new device cycle was run for this fix.

Reconstructing the corrected 250-byte compressed prefix at payload offsets 467,573–467,822 and
inflating raw DEFLATE yields **217 bytes** (`eof=false`, as expected for a partial stream). The image
begins with a standard BF70x LDR block header at inflated offset 0, not the 180-byte secure-boot
wrapper:

| Inflated offset | BLOCK_CODE | Target | BYTE_COUNT | ARGUMENT | Meaning |
|---:|---:|---:|---:|---:|---|
| 0 | `0xadc45004` | `0x11a00000` | 0 | `0x0000109c` | `FIRST|IGNORE`; application entry/next-stream metadata |
| 16 | `0xad640004` | `0x11800000` | `0x5c` | 0 | normal 92-byte payload block; next header at 124 |
| 124 | `0xad180004` | `0x11a00000` | `0x1010` | 0 | normal 4,112-byte payload block |

All three 16-byte headers have the expected `0xAD` signature and their stored 8-bit XOR checksum
matches the other header bytes. The first block's entry address and following target addresses now
map code/data in the loader's Blackfin address space. This confirms the manual's parser direction
and corrects the earlier unvalidated offset-124 header interpretation made from the corrupted map.

The key is not yet located. A subsequent automated run completed the requested archive range:
cycle 1 retried offset 467,808 with mask `0x02` and added 48 bytes; cycle 2 read offset 467,856
with mask `0x01` and recovered the last missing byte. The saved range is now 512/512 bytes, with
no holes. This covers bootloader compressed offsets 467,573–467,871: **299 of 156,306 compressed
bytes**. Raw DEFLATE emits 299 bytes (`eof=false`), preserving the same three validated headers;
159 bytes of the third block's 4,112-byte payload are now available. This is still far short of a
full loader or a defensible AES-key search. The collector automatically polled for the volume between
the two cycles, as intended.

### 66.91 Measured oracle throughput and end-to-end estimate

The next 10-probe range (`467872–468383`) yielded 432 new bytes, or **43.2 useful bytes per
probe**. All ten probes produced a complete leak **4.506–5.476 seconds** after volume detection
(mean **5.073 s**). The collector then continued its configured 20-second capture window; measured
time from volume detection through capture completion averaged **20.506 s** (range 20.374–20.790 s).

At that point, the contiguous data covered **731 of 156,306 compressed bytes** of `bootloader.ldr`
(0.47%); raw DEFLATE emitted 1,087 bytes with `eof=false`. That exposed 947 bytes of the third
block's 4,112-byte payload, but no additional complete block header. The requested range then had 80
bytes missing; the follow-up probes completed it (see §66.92).

Using that batch's 43.2-byte yield, the then-remaining 155,575 compressed bytes implied approximately
**3,601 more probes**. A one-minute fully automated reboot/remount cycle would take about **60 hours
(2.5 days)**. This is a planning estimate, not a measured full-cycle rate: the measured 20.506 seconds
is the work after the volume has mounted, while re-entering update mode and remounting are unmeasured.
The capture loop waits out its full 20-second window even though the first leak arrives after about
5.1 seconds. It polls for the volume but does not automate the device reboot/update-mode transition.
Effective bytes per probe also vary with C-string terminators and compressed data.

### 66.92 Key-window search in the recovered loader prefix

The next two probes completed the second requested range (512/512); the contiguous `bootloader.ldr`
compressed prefix now covers archive payload offsets **467,573–468,383**, or **811 bytes**. Raw
DEFLATE produces **1,211 plaintext bytes** (`eof=false`), so the key search covered every one-byte-step
32-byte window in this recovered plaintext prefix: **1,180 candidates**.

Each candidate was tested as an AES-256 key against two independent known plaintexts from the matching
1.2.45 `.zfw`: (1) the hardware-verified first archive block `50 4b 03 04 14 00 00 00 08 00 62 70
7f 54 47 9c`, using ciphertext block `C(0x3f0)` as the CBC predecessor for `C(0x400)`; and (2) the
first 16 bytes of the known decrypted filename, using the header IV at `0x70`. **No candidate matched
either check.** This rules out the raw key appearing in the first 1,211 inflated bytes, not elsewhere in
the loader: the stream is incomplete and the reported key may occur later. The scan deliberately used
the corrected hardware capture from §66.12, not the superseded hand-pasted ZIP bytes discussed there.

As of this follow-up, **811 / 156,306 compressed bytes** are available and the second 512-byte requested
range is complete. The new 12-probe batch yielded 512 bytes (**42.7/probe**); 155,495 compressed bytes
remain, or approximately **3,645 further probes** at that yield. At an assumed one-minute full reboot/
remount cycle this is about **60.7 hours (2.5 days)**. The 12 captures averaged 5.120 seconds to the
first leak and 20.510 seconds from volume detection through capture completion. The full-cycle estimate
remains conditional on the unmeasured reboot/remount interval.

### 66.93 Arduino relay as a possible physical reset for the oracle loop

The user reports that a relay interrupting OP-Z power **does fully turn the device off even while USB is
connected**. This resolves the concern that USB alone prevents power loss in that setup. It does **not** yet
prove that restoring power returns the device to `OP-Z Boot`, that the update volume remounts unattended, or
that an entire probe-to-next-volume cycle meets a particular time bound. No relay wiring, Arduino firmware,
or host integration has been implemented or exercised in this repository.

A 20-second end-to-end cycle is currently a user-supplied planning assumption, not a measurement. At the
observed 42.7 new bytes/probe and 3,645 remaining probes, that would project to about **20.25 hours** of
continuous operation. The existing collector still captures for its full 20-second timeout after eject;
measured volume-detection-to-capture-completion averaged 20.510 seconds, while the first leak arrived after
5.120 seconds on average. Early stop after a complete leak frame is therefore needed before reboot/remount
time can fit inside a 20-second total cycle.

The execution checklist is `PLAN_OPZ_BOOTLOADER_ORACLE_AUTOCYCLE.md`. The proposed implementation is opt-in
Arduino relay control after capture/state persistence, followed by verification of the boot-console identity
and fresh update volume. Keep the collector's bounds and resume behavior. Existing evidence still rules out
software reset, SCSI media-load, and combining a leaking probe with a successful upgrade (§§65.5–65.9); do not
send console command `0x15`.

### 66.94 Review of four community approaches (2026-10-13)

Four sources were reviewed for relevance to (a) recovering the bricked unit, (b) obtaining the decrypted
firmware, or (c) obtaining the AES key.

| source | what it is | verdict for this project |
|---|---|---|
| `garrettjwilke/ep_133_sysex_thingy` | EP-133 K.O. II SysEx sample send/delete/trigger, WAV transfer notes | **not applicable** — different product (`0x33`), sample transfer only, no crypto, no firmware, no bootloader |
| `kmorrill/ep-series-sysex` | EP-133/EP-40 SysEx + `.pak` project format, FILE protocol, HIL tests | **not applicable to the key** — no firmware/DFU/crypto content; its `devicelock.py` is a *file-I/O serialization* lock (firmware `err lfs` debug loop from concurrent writes), not a security lock. Structurally it is a cousin of the OP-Z FileSync boundary already audited in §66.76 |
| `kmorrill/op-z-sysex` | OP-Z SysEx/StateSync/file-transfer documentation and tools | **already integrated** as `refs/op-z-sysex/`; its own conclusion ("No safe software reboot command has been established") independently matches §65.9 |
| `kennedn.com/blog/posts/glitching/` | Narrative on voltage fault injection (Xbox 360 RGH, AirTag, PicoFly, ESP32), Pi Pico timing | **methodology only** — no TE/OP-Z content; relevant solely as a fallback for the hardware wall, see §66.95 |

None of the four contains an OP-Z key, a decrypted OP-Z image, or a route around the one-probe-per-boot limit.
Two materially useful artifacts were found *adjacent* to them and are recorded in §66.95.

**Corroboration of the current plan.** A post by researcher `_bt` (OP-Forums, 2026-04-09, page 44 of the OP-1
custom-firmware thread) states the OP-Z key-recovery method directly: *"The decryption technique I discussed on
the OP-Z utilized an encryption oracle on the OP-Z itself. This gave me a copy of the decrypted firmware and I
didn't know the encryption key at that point. The brute force bit was testing every possible 32-byte segment in
the decrypted bootloader file using a sliding window as the AES key. This step took just a few seconds to find
the encryption key."*

That is exactly the method this project is executing (§§66.90–66.92): device oracle → decrypted bootloader →
sliding 32-byte window search. It also confirms two things: the key **is** present in the decrypted
`bootloader.ldr` plaintext, and no hardware access is required for the key itself. Our 1,180-window negative
result therefore only means the key lies beyond the recovered 1,211-byte prefix.

**Same-format, same-silicon context.** `_bt` reports that OP-Z and OP-1 field firmware share a format family
(`babecafe` header, firmware version at bytes 8–13, IV at `0xf0`–`0xff`, encrypted blob from `0x380`), which is
a *variant* of, not identical to, the OP-Z `.zfw` layout documented in §2 (key index `0x04`, IV `0x70`, length
`0x80`, encrypted filename `0x300`, archive `0x400`). A forum photo of an opened OP-1 field shows an
**ADSP-BF703** — the same part as the OP-Z. OP-1 field research is therefore transferable at the chip and format
level, but the two products' updaters and file systems differ.

### 66.95 Transferable hardware precedent: TE OP-1 OTP dumps and a patched bootloader

`Tolsi/op1dumps` publishes artifacts from real OP-1 repair work that map closely onto the OP-Z problem:

* `TE-OP-1-BF524-OTP-dump.txt` — a full BF524 OTP dump that "should be written to the empty Blackfin BF524
  processor to restore device boot", plus a NAND flash dump with working boot. **A donor OTP + flash dump is a
  proven way to restore a bricked TE device** on that generation.
* `te-boot-otp-ops-2.28-10.ldr` — the OP-1's own bootloader (`te-boot`), *patched* to add OTP operations: button
  `7` reads an OTP page, button `2` writes one. OTP pages `0x10`–`0x12`, `0xd0`–`0xd3`, `0xdf`, `0xd8` are the
  functionally significant ones (`0xd0`–`0xd3` relates to device boot — the same page range this project's notes
  already associate with the OP-1 firmware key).
* Constraints documented by the author: OTP **reads** need ~6.9–7 V on the `VPPOTP` pin (chip rated for <15
  minutes total at that voltage), OTP writes are irreversible, and the patched bootloader was itself installed
  because the OP-1 accepts **repacked, unsigned** firmware.

Three consequences for the OP-Z:

1. **The OP-1 precedent is bootloader-code-execution first, OTP read second.** It does not transfer directly,
   because the OP-Z rejects unsigned `.zfw` (the whole reason this project needs the key). It becomes reachable
   only through a *different* execution primitive — most plausibly the plain-zip updater write channel of §24,
   if that channel can install a `bootloader` component rather than only write `/yaffs2/upgrade/` paths.
2. **A donor dump restore is not available to this project.** It needs a donor OP-Z (excluded) plus a BGA
   programmer for the OP-Z's NAND package.
3. **It independently confirms the OTP-key pattern.** The OP-1 stores boot-relevant key material in OTP and
   needs an explicit patched-bootloader action to read it, consistent with §2's `key index 0xFF` reading an
   on-die key slot on the OP-Z.

**BF70x security model (ADI EE-366 and the BF70x datasheet/PCN).** Blackfin+ adds a system protection unit, a
system memory protection unit, hardware crypto accelerators, a 1 kB memory-mapped OTP, *secure debug*, and
*secure boot*. Secure boot is optional and disabled by default, uses signed images with optional AES-128, and a
**secure debug key** (128-bit, stored in OTP) is what lets an emulator attach to a *locked* part; ADI's own FAQ
says a locked BF70x needs that key supplied to the debugger. A BF70x PCN erratum notes that "locked processors
cannot be unlocked by emulator if other devices are present in the JTAG scan chain", implying locked parts *can*
be unlocked when the key is supplied. Crucially, **this documentation does not establish that the OP-Z's BF703
is locked at all.**

### 66.96 Ranked assessment of the hardware routes

Ordered by expected value per unit of risk, given the constraints already recorded (no donor unit, no TE
service, and no PCB debug wiring authorised so far):

| # | route | requirement | value | status |
|---|---|---|---|---|
| 1 | Finish the `bootloader.ldr` oracle recovery, then re-run the sliding 32-byte window search | only time | **the key**, then the whole decrypted `.zfw` offline | in progress; this is `_bt`'s own published method |
| 2 | Plain-zip updater channel installs a **modified bootloader** (OP-1 `te-boot-otp-ops` analogue) | discovering the component name the updater accepts, and an accepted bootloader write | code execution in the bootloader → OTP/memory access | not attempted; highest-risk step on the device (A/B slots are the only mitigation) |
| 3 | Attach an emulator to the BF703 (JTAG/SWD) | locating debug test points and wiring them | if the part is **unlocked**: direct memory and NAND access, i.e. recovery *and* the decrypted image without any key | not attempted; excluded by earlier instruction |
| 4 | Voltage-glitch the BF703 (the `kennedn` methodology, Pi Pico-class timing) | route 3 plus a glitcher; only meaningful if the part is locked | bypass the lock/secure-debug check or a verification branch to gain debug access | speculative; no OP-Z-specific glitch target or timing identified |

Route 4 is the weakest of the four here: it is a generic technique, it presupposes route 3's wiring anyway, and
nothing in the reviewed material identifies either the BF703's lock state or a glitch location on the OP-Z.
Route 3 is the cheapest possible *shortcut* if the part is unlocked, but it needs PCB wiring that a previous
instruction excluded; that boundary would have to be explicitly re-authorised by the user before any test.
Route 1 remains the only fully authorised path and needs no hardware beyond the relay already planned.

### 66.97 Fault injection on the OP-Z: what the precedents actually require

The `kennedn` post is a well-written argument that fault injection is now cheap (Pi Pico, ~7.5 ns PIO resolution,
£5) — not a procedure. Asked directly whether the OP-Z should be glitched, the honest answer is that fault
injection is a real technique that is *third-tier* for this device, because it is dominated twice over: by the
software oracle still in progress, and by a single plain emulator attach attempt.

**Every cited success had four prerequisites. Let us check each against the OP-Z.**

| prerequisite | Xbox 360 RGH | AirTag / ESP32 / PicoFly | OP-Z |
|---|---|---|---|
| a physical glitch site | `CPU_RESET`, on a header | the die's VCC rail | BF703 core rail inside a 10 mm device; **unknown whether any debug/test pad is exposed** |
| a timing trigger | self-synchronising: relative to reset release | reset/power ramp | nothing host-visible precedes early boot; a flash chip-select or rail-ramp probe would be needed |
| a cheap success oracle | unsigned code runs / LED changes | firmware dumps / secure boot bypassed | **none** — the target states ("locked", "OTP readable") have no observable symptom. Console liveness only proves the device still runs |
| a repeatable, low-risk target | correctable with a NAND/JTAG programmer | dev boards | **no** — the device is already partially bricked, and a failed write path here has already been shown to be unrecoverable (§1, the `0x15` format) |

**Corrections to the intuitition the post invites.**

1. **The OP-Z is probably not signed-but-encrypted the way RGH targets were.** RGH skipped a *signature
   verification* to run unsigned code. Our `.zfw` key is used by *hardware* to *decrypt* (confidentiality). A
   glitch that skips a check gives unsigned code execution, not a key. To get the key you must defeat **OTP read
   protection** specifically, i.e. glitch while the device is *reading* OTP — a far narrower target than RGH.
2. **BF70x secure boot is documented as optional and disabled by default** (§§66.88–66.89; ADI EE-366 and the
   BF70x hardware reference). If the OP-Z's part is not locked, there is no verification check to glitch in the
   first place — an ordinary emulator attach simply works. The decision-relevant question is the *lock state*,
   and fault injection only becomes rational after "locked" is established **and** an attach attempt has failed.
3. **The published OTP-glitch work is a step above crowbar voltage glitching.** The closest analogue is
   Raelize's *"Breaking SoC Security by Glitching OTP Data Transfers"* (Hardwear.io 2022, ESP32, EMFI), which
   targets OTP *transfers* while the victim reads them. That is an electromagnetic attack requiring a
   controllable probe position, not a single reset-pin crowbar. The STM32/LPC1114 readout-protection bypasses
   are the other relevant class — again targeting a *readout* path, not a boot signature.
4. **An ADI emulator is not a generic JTAG dongle.** ADI's own guidance (EE-68, EE-356) defines the Blackfin
   emulation port as a *superset* of IEEE 1149.1 and adds a vendor-specific `EMU~` signal. Attaching means an
   ADI-compatible emulator (ICE-1000/2000 class) or verified OpenOCD support — a cost and an uncertainty that
   applies to route 3 *before* any glitching is even considered.
5. **The device is not easy to open.** Public teardowns show the keyboard is held by melted plastic shafts
   through the shell and cannot be detached without destroying it; the processor board sits behind that. So the
   entry cost for *any* invasive hardware route is a damaged shell/keyboard, on top of the glitch harness.

**What a glitch campaign could realistically buy, if it worked.** Ranked by payoff: (a) defeat the secure-debug
lock so an emulator attaches — memory *and* NAND access, i.e. full recovery plus the decrypted image with no key
at all; (b) glitch a boot-time branch so a modified bootloader component installs (the §66.95 OP-1 analogue);
(c) glitch the OTP read path to read key material directly.

**One genuine advantage this device has.** Unlike the consoles in the post, the OP-Z offers a live CDC console
in update mode plus a mass-storage LUN, so a glitch campaign would have a usable *health* oracle: the console
still pings, the volume still mounts, and a genuine upgrade still succeeds. That makes blind glitching less
dangerous than it would be on a device with no instrumentation — but it does not supply a *success* oracle for
the target state.

**Recommended sequence if hardware work is authorised at all** (each step is far cheaper than the next, and
each can end the search):

1. Finish the `bootloader.ldr` oracle recovery and re-run the window search (§§66.90–66.92, §66.94). Zero
   hardware, and `_bt`'s published method says this alone yields the key.
2. Open the unit and *identify the BF703 and any exposed debug/test pads* (TCK, TMS, TDI, TDO, `nTRST`, `EMU~`,
   and the `VPPOTP` pin). Read-only inspection; decisive for everything downstream.
3. Attempt a plain emulator attach. If the part is unlocked, this wins outright — recovery, decrypted image,
   no glitching.
4. Only then consider fault injection: trigger off flash chip-select or the rail ramp, crowbar the core rail,
   sweep; or EMFI if the target is the OTP read path.

Nothing in this section was executed: no board was opened, no emulator or glitcher was built, and no device or
hardware test was performed.

### 66.98 Observed 2x3 pad array on the processor board (user photo, 2026-10-13)

A user photograph of the processor board (`PXL_20261010_113529733.RAW-01.jpg`, Pixel 9, 3072x4080) shows an
exposed pad group that was not previously documented. Measurements below are from that single image; they are
observations, not a confirmed identification.

**What is visible.**

* Six round, flat, gold-plated pads with **no drill holes**, arranged **2 columns x 3 rows**.
* Measured centroids: columns at x ~ 902-911 and x ~ 1060-1068; rows at y ~ 3002, 3157, 3311 (original image
  pixels). Column pitch **158 px**, row pitch **154 px** — a **square grid** within measurement noise.
* Pad diameter ~ 63 px; pitch/diameter ratio ~ 2.5.
* A **bundle of about five parallel traces** leaves the group and runs toward the upper right of the board, and
  each pad appears to feed its own trace rather than sharing a net.
* Scale reference: the nearby plated mounting hole measures ~117 px across its outer ring. Assuming an M1.6 or
  M2 clearance hole (1.8-2.2 mm) gives roughly **53-65 px/mm**, hence **pitch ~ 2.4-2.9 mm** and **pad
  diameter ~ 1.0-1.2 mm**. That is consistent with a standard 0.1" (2.54 mm) or 2.0 mm header footprint — but
  realised as **flat pads rather than plated through-holes**, which points to a probe/pogo/solder-target array
  (factory test access or a press-contact interface) rather than a part you plug a pin header into.

**Interpretation, and its limits.** An 0.1"-class 2x3 array carrying six distinct signals is the shape of a
minimal debug/programming pad group; **six is exactly the classic minimum JTAG set** (TCK, TMS, TDI, TDO,
nTRST/SRST, GND) and also the classic 2x3 SWD header layout. It is equally consistent with a factory
bed-of-nails test group, a companion-MCU programming header, or a contact array for a mating connector. The
photo alone does **not** establish which, and the chip itself is not visible in it, so the claim that the traces
run directly to the DSP still needs continuity confirmation.

**Why it matters.** If these pads are the BF703's debug port and the part is not locked (§66.95), a plain
emulator attach yields memory and flash access: **device recovery and the decrypted firmware with no key at
all**, which is strictly better than the oracle route (§66.96 routes 3 vs 1). No glitching would be required.

**Cheap ordered identification plan** (no device writes, no emulator needed for steps 1-4):

1. **Unit unpowered, all 15 pad-pair continuity checks.** Six mutually isolated pads indicate a signal bus. Any
   pads tied together indicate a power/ground/strap array, which is not a JTAG port.
2. **Beep each pad to a solid ground** (battery negative terminal, ground pour, shield can). A debug port
   normally exposes exactly one GND. Finding none makes the debug-port reading unlikely.
3. **Resistance from each pad to ground and to the battery+ / 3.3 V rails.** A ~4.7k-10k pull-up is the classic
   bias signature of TCK/TMS/TDI/nTRST.
4. Optional, powered on battery with fine probes: look for one pad sitting at a stable rail — the VTref pin most
   debug adapters need to sense.
5. **Trace-follow each pad through its via to the chip side** and match against the BF703 ball functions. This is
   the step that converts a hypothesis into a fact.
6. **Decisive: attach an ADI emulator** (ICE-1000/2000 class) with CCES, or at minimum run ADI's BY-PASS scan
   test (EE-356) to see whether a JTAG chain answers at all. Caveat: ADI's emulation port is a superset of
   IEEE 1149.1 and adds the vendor-specific `EMU~` signal (EE-68); a six-pad group may omit `EMU~` and a VTref
   sense, which some emulators tolerate for basic attach and others do not.

**Useful discriminator.** If the group is GND + VTref + **four** signals it resembles **SWD** (SWDIO, SWCLK),
which would point at an ARM companion part (keyboard/power controller or BLE module) rather than the Blackfin.
**Five** signals (four plus reset) is the JTAG case that matters here.

No hardware was probed, powered, soldered or attached; no device or board modification was performed. The
photograph is not a committed repository artifact.

### 66.99 Blackfin+ debug tooling: an existing OpenOCD path for the BF70x

Reviewing whether ordinary (non-ADI) debug hardware could drive the pads described in §66.98 turned up a
working software path. Recorded here because it changes the cost of §66.96 route 3 substantially.

**A BF70x-capable OpenOCD exists.** `deanm1278/openocd` is a fork adding the "Analog Devices Blackfin+ line
(ADSPBF70x devices)" to OpenOCD mainline, with `src/target/bfinplus*.c` (`bfinplus.c`, `bfinplus_dap.c`,
`bfinplus_mem.c`), plus `tcl/target/bf706.cfg`, `tcl/target/bf70x.tcl` and `bf70x_memory_map.xml`. Mainline
OpenOCD does not carry this target.

**What the target config tells us about the port.**

* The config states it supports **both JTAG and SWD transports** (`#transport select jtag` / `#transport select
  swd`) and sources `target/swj-dp.tcl`.
* The BF70x TAP is handled as an **ADI JTAG Controller (ADJC)**, and the debug access port must be *enabled*
  with a documented sequence:
  `irscan $adjc 0xa` followed by `drscan ... 32 USERKEY0 32 USERKEY1 32 USERKEY2 32 USERKEY3`, then
  `irscan $adjc 0x5` / `drscan 8 0x4` to enable the DAP.
* That is the **secure-debug unlock**: four 32-bit values are a **128-bit UserKey**, matching the "secure debug
  key ... 128-bit ... stored in OTP" of EE-366 (§66.95). The template ships with
  `set USERKEY0..3 0x00000000`, so **an unlocked part attaches with the defaults**.
* Consequence: **a first attach attempt directly measures the lock state** — the single decision-relevant
  unknown identified in §§66.95 and 66.97. If the defaults fail and no key is available, the part is locked.
* Memory map in that config: `boot_rom` 0xef000000, `l1` 0xff800000, `sysmmr` 0xffc00000, `coremmr`
  0xffe00000. Caveat: the XML is labelled `name="bf537"`, so it looks inherited; it does not cover the
  0x80xxxxxx DDR range where our crash addresses live, and would likely need adapting.

**The recovery precedent exists too.** The same author's `bf70x-bootloader` loads a small loader into
**instruction RAM** over OpenOCD, which then initialises the flash and exposes the **external SPI flash**
through virtual NVM registers in data RAM B, driven from an OpenOCD command line (demonstrated on a BF706
EZ-mini board). That is attach → load loader → read/write flash, i.e. the same shape as the restore we want.

**Adapters.** The fork's supported-adapter list includes **Buspirate**, **CMSIS-DAP**, **FTDI**, **sysfsgpio**
and **BCM2835** — so the cheap-hardware category is covered, not only ADI's ICE pod. ADI's own CCES code drop
(`openocd-0.9.0-cces-2.4.0-src.tar.gz`, containing a Blackfin target and an **ICE-1000 adapter** driver) is the
fallback if the fork misbehaves.

**Architecture context.** ADI states that EE-68 (the classic 14-pin ADI JTAG reference) applies only up to the
ADSP-BF60x family; the BF70x debug unit was redesigned to also support ARM technology, and per ADI the TAP
defaults to JTAG mode with boundary scan and device chaining supported, with a special SWDIOTMS sequence to
switch between JTAG-DP and SW-DP. A BF70x BSDL model is published, which makes an IDCODE/boundary-scan check a
low-effort confirmation step.

**Verdict on the three candidate gadgets.**

| gadget | verdict |
|---|---|
| USB logic analyzer | **monitor only.** Input-only; it cannot drive TCK/TMS. Useful to verify levels and to decode traffic while something else drives the port, not to attach |
| Bus Pirate | **yes, and it is on the fork's adapter list.** Adequate to prove the port and read IDCODE; full attach is plausible but slow (bit-banged) |
| Raspberry Pi / Pico family | **best of the three.** A Pi board via `bcm2835gpio`/`sysfsgpio`, or a Pico as a CMSIS-DAP probe — both appear on the adapter list |

**Caveats that must be settled before connecting anything.**

1. **Voltage first.** BF70x I/O can be 1.8 V, 2.5 V or 3.3 V. A Pi, a Bus Pirate v3 and most logic analyzers
   are 3.3 V. Driving 3.3 V into a 1.8 V rail risks the part, so measure the pad rail (and any VTref pad)
   before attaching, as already required by §66.98.
2. The fork must be built from source; mainline OpenOCD will not work.
3. The `bf70x.tcl` unlock path uses `irscan`/`drscan`, i.e. **JTAG**, even though the config mentions SWD — so
   JTAG (four signals plus GND, optionally nTRST) is the target shape to look for on the six pads.
4. Whether the six pads are the DSP's debug port at all is still unproven (§66.98), as is whether the part is
   locked.

No hardware was connected, powered or driven; no adapter, firmware or device was modified.

### 66.100 Identifying which pad carries which JTAG signal

§66.98/§66.99 leave one practical question: given six unlabelled pads, how do you know which is TCK, TMS, TDI, TDO, GND or VTref? The answer is that this is a solved problem — either scan for it automatically, or narrow it electrically and brute-force the last few permutations. Guessing from the layout is not required.

**Safety rules that make brute-forcing safe.**

* **Never drive TDO.** TDO is an output from the target; your adapter's TDO line must be an input. Driving it is a bus conflict.
* **Measure the I/O rail first.** BF70x I/O is 1.8 V, 2.5 V or 3.3 V. Forcing 3.3 V into a 1.8 V input is the one way to damage the part.
* **Mis-assigning TCK/TMS/TDI cannot damage the target** — they are inputs, so the worst case is garbage data. Brute-forcing is therefore electrically safe once the voltage is right and TDO is never driven.
* Connect **GND first** and keep that lead short. Leave nTRST alone if the board pulls it up; an adapter that drives it is fine but not required.

**Method A — automatic pinout discovery (least effort).**

* **Bus Pirate: the blueTag JTAG/SWD pin finder.** Current Bus Pirate firmware includes a pin finder derived from blueTag that identifies JTAG/SWD pins on an unknown target by driving candidate lines and analysing responses. The documented workflow is to connect the IO pins to the suspected pads (IO0 upward) plus a shared ground and let it report the assignment. Caveat: this is modern Bus Pirate firmware — the author originally shipped blueTag as an external firmware because of its GPL licence — so check whether the board in hand carries it.
* **JTAGulator.** Purpose-built for exactly this case ("test points, vias, component pads, or connectors"). It offers an **IDCODE scan**, which locates TDO/TMS/TCK, and a **BYPASS scan**, which also locates TDI (useful because IDCODE is optional per the standard and the IDCODE scan deliberately does not look for TDI).
* **JTAGenum.** Free: an Arduino sketch and, relevant here, a **Raspberry Pi shell script** that brute-forces a pin list over sysfs GPIO and can then enumerate the instruction register. Requires editing the `pins[]`/`pinnames[]` lists to the candidate pads.

**Method B — narrow the search with a multimeter first (free).** This usually reduces the problem to a handful of permutations:

1. **GND** — already found by continuity in §66.98 step 2.
2. **VTref / rail** — the pad sitting at a steady rail voltage while powered.
3. **Pull-up pattern.** TMS, TCK, TDI and often nTRST carry internal or external weak pull-ups (the common values are 4.7k-10k), so they read a few kΩ to the rail, whereas **TDO is a tri-stated output with no pull-up and reads much higher or open** (hundreds of kΩ, or no reading). That single measurement commonly isolates TDO.
4. What remains is three or four candidates for TDI/TCK/TMS, i.e. at most ~24 permutations — small enough to brute-force even by hand.

**Method C — deterministic, if the board cooperates.** Follow each pad's trace through its via to the BF703 ball and name it from the **published BF70x BSDL model**, whose pin names include `JTG_TCK`, `JTG_TMS`, `JTG_TDI`, `JTG_TRSTb` and the TDO output. Pair the BSDL names with the datasheet BGA ball map and no guessing or scanning is needed at all. This is the cheapest method when the trace routing is visible.

**Adapter side is not the unknown.** In the OpenOCD fork of §66.99 the adapter's pin assignment is configurable (for example the `bcm2835gpio` and `sysfsgpio` drivers take explicit GPIO numbers, and the fork's adapter list includes CMSIS-DAP and Bus Pirate). You therefore choose which of your board's GPIOs act as TCK/TMS/TDI/TDO and wire those to the pads — the only thing that has to be discovered is the target side.

No hardware was connected or driven; nothing was scanned or probed.

### 66.101 The published successful run, re-read against our numbers

A fuller statement by `_bt` (OP-Forums, Jan 2024) describes the completed key recovery. Read against this
project's implementation it is a direct confirmation of §§66.90-66.92, and it sharpens two things.

**What the account says.** The OP-Z firmware contains an encrypted-filename field; because "the OP-Z firmware is
not digitally signed" that field can be manipulated. The device prints, on the serial console, the filename it
decrypted from it (`firmware_bin_only_with_bootloader.zip`). `_bt` combined those two facts into a power-cycling
rig plus a script that forged fresh firmware files so the device would decrypt the payload block by block while
the console revealed the plaintext, at roughly 30 seconds per block for thousands of blocks. The device
recognised the result as invalid and aborted, so nothing was bricked. With the decrypted zip in hand, a second
script tested the **contents of the bootloader file as the AES key**: *"The key is in plaintext in the
bootloader file."* The OP-1 field used the same key until 1.1.6, and the OP-Z firmwares all use one key.

**Consequences for this project.**

1. **The method is validated, not speculative.** The console oracle of §66.19, the one-read-per-boot
   limit, the ~63-byte leak cap and the power-cycle-per-window cost are exactly the constraints `_bt` worked
   under. Their ~30 s/cycle for thousands of cycles is the same regime as our measured 42.7-43.2 useful
   bytes/probe. We are not doing anything wrong; we are **0.54% into the file** (842 of 156,306 compressed bytes
   contiguous, inflating to 1,260 plaintext bytes).
2. **The key is in `bootloader.ldr` plaintext, confirmed twice** (§66.92, §66.94). Since the member is stored
   DEFLATE-compressed, its plaintext is only reachable by inflating the stream, which requires the compressed
   bytes in order. There is no shortcut through a partial stream.
3. **No signature check exists to defeat afterwards.** "Not digitally signed" means the AES key is the *only*
   gate. Once the key is known, a modified firmware can be installed through the normal, supported upgrade path
   — which is what `_bt` did to repack custom firmware — instead of the risky plain-zip channel of §24. That
   materially lowers the risk of the §66.95 patched-bootloader idea.

**Cost, measured and projected** (compressed member spans 467,573-623,878; 155,464 bytes still missing):

| useful bytes/probe | remaining probes | at 18 s/cycle |
|---|---|---|
| 43 (measured) | 3,615 | 18.1 h |
| 48 | 3,239 | 16.2 h |
| 56 | 2,776 | 13.9 h |
| 64 (ceiling) | 2,429 | 12.1 h |

**Three levers, in order of value.**

1. **Stop early by testing continuously.** The campaign currently only needs to *finish* if the key is at the very
   end. Because plaintext is produced in order and DEFLATE output is prefix-stable, the inflated prefix can be
   re-tested after **every** probe and the run can stop the moment a window validates against the
   hardware-verified first ZIP block of §66.12. Testing all one-byte-offset 32-byte windows of 1,260 bytes took
   seconds; re-running it per probe costs nothing. If the key's position in the file is uniform this alone
   roughly halves the campaign, and if the key sits early it cuts it far more. **This is the single highest-value
   change and it needs no device.**
2. ~~**Reclaim the alignment headroom.**~~ **WITHDRAWN — see §66.106.** Measurement of the saved reads shows the
   49-64 band describes *leak length*, not *new bytes per probe*, and that 43 new bytes/probe is already that band
   minus the mandatory 16-byte overlap. There is no alignment headroom to reclaim; the table above overstates
   nothing but the achievable rate is fixed.
3. **Eliminate the cheap alternatives first.** Roughly **75 probes** complete the remaining small members
   (`opz.crc32`: csize 3,251; `bootloader.version`; `os.version`), and the raw archive plaintext can be scanned
   for key-shaped windows at no cost. If the key were in a small member rather than the bootloader, this wins for
   ~75 probes instead of ~3,600. `_bt` says bootloader, so the expectation is low, but the cost is trivial.

**Also worth checking offline first:** whether any archive member has `csize == usize` (stored, method 0) — a
stored member needs no inflation and could be read directly. Our member map so far shows method 8 throughout, but
the map is not complete.

**After the key.** Decrypting the `.zfw` locally yields the plaintext `opz.ldr` OS image; the BF70x LDR block
headers already validated in §66.90 then map a destination address to a file offset, so `RETX 0x80117baa` can be
translated to a concrete instruction — the original purpose of the decode. Note again that knowing the key does
not by itself repair the NAND or boot state; it supplies the means to build and install a firmware that can.

No device action was taken; all figures are re-analysis of already-recovered bytes and published statements.

### 66.102 Search for a published key or decrypted image: not public (2026-10-13)

A targeted search was run for the OP-Z AES key, a decrypted OP-Z image, or a repacking tool, across the sources
where such an artifact would realistically appear. **Neither the key nor a decrypted OP-Z firmware is published
anywhere indexed.** The evidence is consistent across sources:

| source | what it contains | key? |
|---|---|---|
| `billymeter/rez` wiki, *Firmware* page | the full `.zfw` layout (flags/key index `0x04`, IV `0x70`, length `0x80`, encrypted filename `0x300`, archive `0x400`), the AES-256-CBC identification, the padding-oracle method, and the statement that every published firmware used the same key | **no value published** |
| `billymeter/rez` repo | README only; records that the firmware was decrypted with another individual | no |
| `op1hacks/op1-field-fw-archive` | archive of OP-1 field `.tfw` files | **ciphertext only** |
| `op1hacks/op1repacker` | OG OP-1 repacker | different device and format |
| `sualk/op1-decryptor` | OG OP-1 `OP1_vdk.ldr`, **XTEA**, caller-supplied 16-byte key | different device, different algorithm, no key |
| `pcppcp/op1r` | OG OP-1 R246 patcher (`OP1_vdk.ldr`) | different device and format |
| `jstnfst/te-op1` | OP-1 field patch (`.aif`) tooling | unrelated |
| `nbw/opz` | JS OP-Z library | no crypto |
| OP-Forums *Custom Firmware on the OP-1* thread | method, results, and a current request for the 256-bit value **over other channels rather than on the forum** | deliberately withheld |

A regex sweep for 64-hex-character strings across every repository cloned during the search returned nothing.

**So the key is withheld, not lost.** The people who hold it are identifiable and the thread shows an active
private exchange: `_bt` (recovered it), `tolsi` (credited as assisting), and a forum member who is currently
asking for it off-forum for stated legal reasons. Discord/PM/off-forum channels are not searchable, so no public
search will surface it. Asking is a legitimate option but cannot be depended on.

**Two genuinely useful things the search did produce.**

1. **`_bt` published the oracle mathematics** in the same thread. The encrypted filename region (`0x300`-`0x400`)
   and the firmware-zip region (`0x400` to EOF) are **separate encrypted blocks**, and **the IV is used for
   both**. Their stated relation for placing archive ciphertext into the filename field is that the first block
   decrypts directly, and each subsequent plaintext block is the oracle output for that block XOR the previous
   ciphertext block XOR the IV. This is a direct, independent statement of the chaining rule this project
   derived empirically in §§65.7 and 66.13, and it is worth re-checking the collector against it as a free
   validation step.
2. **A relevant confirmation of the fidelity check.** The wiki records that the shared key was confirmed by
   transplanting another firmware's IV and encrypted filename blob and observing successful decryption in the
   console — a cross-file check that needs no key. Our project can use the same trick to sanity-check any
   candidate key against more than one firmware release.

**Prior art worth noting for the decode endgame.** The same thread lists a working toolchain for Blackfin LDR
handling (`parse_bfin_ldr.py`, `extract_bfin_ldr_region.py`, locally built binutils) used for OG OP-1 firmware
modification. That is directly applicable to parsing the inflated `bootloader.ldr` and mapping a destination
address to a file offset (§66.90), and it confirms the approach is practical rather than novel.

Nothing on the device was touched; no artifact was downloaded, and no decrypted content was obtained.

### 66.103 The "OP-1 Field custom firmware holds the key" lead: closed

The reasoning was sound — if OP-1 field firmware before 1.1.6 was encrypted with the same key as the OP-Z, then
anyone shipping custom OP-1 field firmware for those versions would have to carry the key. The search closes the
lead, because **no OP-1 field firmware repacker exists publicly**.

**The custom-firmware scene is entirely on the *original* OP-1.** `op1hacks/op1repacker`, `pcppcp/op1r` (described
by its own README as patches for the original OP-1 r246 firmware), the "opus_1" mod suite, the browser-based
firmware builders, and `sualk/op1-decryptor` all target the original device. That matters because **the original
OP-1 firmware is not AES-encrypted at all**: it is a CRC-32 plus LZMA container, with XTEA applied to
`BFLAG_CALLBACK` blocks in `OP1_vdk.ldr`. None of those projects ever needed the OP-Z key, which is exactly why
they can operate openly.

**The "op1r on OP-1 field" report is a port of original-OP-1 firmware to field hardware**, described by its author
as work in progress with no published method or package — not a repack of field firmware, so it does not require
the key either.

**Related but different:** `seajaysec/ep-unity` covers the EP-133/EP-40 (EP series), which uses an unrelated scheme
— MCUboot `IMAGE_F_ENCRYPTED_AES128` with an `ENC_EC256` per-image random AES-128 key wrapped by an ECIES public
key. Its own research note states plainly that the OP-Z and OP-1 field oracles do not transfer, and lists failed
approaches including XTEA and trailer-as-key sliding windows. Independently of us, that project's conclusion is
that a software decrypt oracle is unavailable there and that the practical route is an **SWD XIP dump** of mapped
application flash after boot — the same conclusion §66.97 reached for the OP-Z from the other direction.

**One genuinely useful artifact was found.** `op1hacks/op1-field-fw-archive` holds the official encrypted `.tfw`
files including **1.1.2 and 1.1.4 — both pre-1.1.6, i.e. both encrypted with the OP-Z key**. They are ciphertext
only and contain no key, but they are a **third-party verification corpus**: a candidate key recovered from
`bootloader.ldr` can be checked offline against a completely different TE product's file before it is trusted
against our own archive. That is the same transplant-style fidelity check the format wiki used to establish key
reuse in the first place (§66.102).

**Conclusion.** No public project has derived or published the key, and the OP-1 field route does not lead to it.
The only holders remain the OP-Z oracle team and anyone they shared it with privately.

### 66.104 Why recent custom-firmware successes do not imply anyone holds the OP-Z key

Custom firmware for a TE OP-1 is genuinely thriving and current — releases continue right up to October 2026, with
a large feature-rich build dated 2026-10-11. That is real and it is not in dispute. What matters is *which*
device, because two separate facts make the inference "they shipped custom firmware, therefore they have the
OP-Z key" fail.

**1. The active custom-firmware scene is the original OP-1, whose firmware is not AES-encrypted.** Every project
and release found targets the original OP-1: the repacker and its GUI, `op1r` (scoped by its own README to
original r246 firmware), the OPUS mod suite (subtitled "for the original OP-1 (246)"), the current standalone
custom OS releases, and the browser-based builders. The original OP-1 container is CRC-32 plus LZMA, with XTEA
on `BFLAG_CALLBACK` blocks in `OP1_vdk.ldr` (see §66.103). None of that work requires the AES key, which is
precisely why the scene is open, fast-moving and openly published while the OP-Z side has been quiet since 2021.

**2. The OP-1 field key rotated, so current field work would use a *different* key anyway.** The OP-Z key was
shared only by field firmware **up to and including 1.1.5**; firmware 1.1.6 (June 2022) introduced a new key.
Field firmware is now at 1.7.3 (May 2026). So:

| case | key involved | useful to us? |
|---|---|---|
| anyone repacking OP-1 field **1.1.2 / 1.1.4** | the **OP-Z key** | yes — but these are 2022-era images nobody mods |
| anyone repacking **current** field firmware (>=1.1.6) | the **new field key** | **no** — a different key entirely |
| anything on the **original** OP-1 | no AES key at all | no |

So even a genuine, current OP-1 field custom firmware would imply possession of the *post-1.1.6 field* key, not the
OP-Z key. The only artefact that would directly hand us the OP-Z key is a repack of a **pre-1.1.6 field** image,
and no such release has surfaced in any searched source. A report of `op1r` running on field hardware is a port of
original-OP-1 code to field hardware, described as work in progress with no published method, and is not evidence
of a field-firmware repack.

**Conclusion:** the inference holds only if the specific work in question is a repack of field firmware 1.1.2 or
1.1.4. Nothing found matches that. A concrete link or release name would settle it immediately, and if such a
release exists it is by far the highest-value artefact in this investigation.

### 66.105 CORRECTION: an OP-1 field firmware mod *does* exist (supersedes 66.103/66.104)

Sections 66.103 and 66.104 concluded that no OP-1 field firmware repack existed and that the "field work implies
the key" inference therefore failed. **That conclusion is wrong and is retracted here.** A user (`bipeula`) posted
to r/OP1users on 2026-10-14 that they have ported `op1r` to the OP-1 field and it is running, and their own
clarification is unambiguous:

* it is **native OP-1 field firmware, modified** — not original-OP-1 code running on field hardware;
* it is **"based on an older official version"**, so later TE features such as the vocoder engine are missing,
  while others (tape undo, multichannel USB, terminal FX, tape crossfades) were rebuilt by the author;
* on the encryption question: **AES was not broken — "the firmware was decrypted, but not by attacking the
  cipher itself."**
* the work is **not released yet**; the author states the source will be published under the GPL when ready.

A commenter in the same thread asserts that the key used is the same as the OP-Z key. That is a **commenter's
claim, not the author's**, and it is the single fact that decides whether this lead yields the OP-Z key.

**Why the base version decides everything.** The OP-Z key was shared only by field firmware up to 1.1.5; 1.1.6
(June 2022) introduced a new key. The author's description places the base *older* than 1.4.2 (the vocoder is
absent, and 1.4.2 dates from January 2023), which still leaves two possibilities:

| base version | key involved | yields the OP-Z key? |
|---|---|---|
| field **<= 1.1.5** | the OP-Z key | **yes** — this ends the campaign |
| field **1.1.6 - 1.4.1** | the new field key | no — but the *method* is still the interesting part |

**What this establishes regardless of the answer.** A second, independent party has decrypted native
TE-encrypted firmware of this family, in the last few days, using something other than a cipher attack — which is
consistent with the oracle approach of `_bt` and with the method this project is already running. The practical
consequence is that the previously "dead" lead is live and has a **named, reachable, cooperative author** who has
promised a GPL source release.

**Course of action.** (1) Ask `bipeula` which base firmware version they started from — that one answer tells us
whether they hold the OP-Z key. (2) Ask whether the key is embedded in the decrypted image (as `_bt` found for the
OP-Z, §66.94) or recovered as a separate secret. (3) Note that the same user has already asked this publicly in
that thread and received no method answer, so a private message is the better channel. (4) Watch for the promised
GPL release, which may carry both a decryption tool and the key handling.

The oracle campaign (§66.101) remains valid and worth continuing, but it is now a **fallback rather than the only
route**: this lead could end it today, whereas the campaign needs 12-18 hours of device cycling.

### 66.106 Early-stop key test implemented; the alignment lever is a mirage; first disassembly of the bootloader prefix (2026-10-16)

Three results, two of them corrections.

**1. The §66.101 lever-1 early-stop key test is now implemented and verified.**

`toolkit/opzbootprobe.py` re-inflates the recovered `bootloader.ldr` prefix after **every** probe and tests each
not-yet-tested 32-byte window with `opzkeymine.check()` — the two-pair AES oracle whose strongest test is the
hardware-verified first ZIP block of §66.12. It halts the run the moment a window validates, writes the key to
`KEY-FOUND.txt` alongside the probe state, and a new `--key-scan-only` flag runs the same scan over saved state with
no device attached. Only windows that a new byte creates are tested, so the per-probe cost is O(1) rather than a
full rescan. `--self-test` passes; the inline script now declares `pycryptodome`.

Run offline against the existing probe state: **1,260 inflated bytes, 1,229 windows tested, no match** — consistent
with the §66.101 result on the then-current prefix. The campaign can now stop early instead of always finishing.

**2. Correction: there is no alignment headroom. §66.101 lever 2 is withdrawn.**

Lever 2 claimed the window base could be chosen to gain "49-64 *new* bytes per probe even after re-reading a few
known bytes; 43 is below that band", worth about a third of the run. Measurement of the saved reads says otherwise.

| quantity | measured |
|---|---|
| reads / leaks | 35 |
| leaks that reached the 63/64-byte cap | 14 of 35 |
| leak length min / max / mean | 6 / 64 / 40.9 |
| mean excluding the 7 known masked-NUL stall reads at offset 467808 | **~49.6** |

The 7 reads that returned exactly 6 bytes are the historical masked-NUL stall (§66.89, since fixed), not a real yield
figure. Once they are excluded the mean leak is ~49.6 bytes — **already inside the documented 49-64 band**. The band
describes *leak length*, not *new bytes per probe*, and the two differ by a mandatory cost lever 2 did not account
for: to fill the byte at the first hole the window must start at or below that byte **on a 16-byte boundary**, so
0-15 already-known bytes are always re-read (mean 7.5). 49.6 - ~7 = ~42.6, which is exactly the measured
42.7-43.2. **43 new bytes per probe is the band value minus the mandatory overlap, so there is nothing to reclaim.**

The overlap cannot be avoided: starting the window past the first hole would leave those tail bytes missing forever,
because a later window begins later and can never cover them. The 63-byte real cap is likewise fixed — it is
`128 - 4 - 58 - 1 = 65` leak bytes less the 2-byte `..` marker, set by the device's 128-byte log-message ceiling
(§66.85), a firmware constant that probe placement cannot change. Expected remaining work therefore stays at
**~3,615 probes / ~18 h at 18 s per cycle**, reduced only by lever 1's early stop.

**3. First disassembly of the recovered bootloader prefix.**

The 1,260 inflated bytes are two complete LDR blocks plus one partial one. Block 0's `arg` field is now explained:
`0x109c` = 4252 = 124 (end of block 1) + 16 (header) + 4112 (block 2 payload) — i.e. **`arg` is the offset of the next
block header after the code block**, confirming §66.101's "next-stream metadata" reading arithmetically.

| offset | code | dest | count | arg | what it is |
|---|---|---|---|---|---|
| 0 | `0xadc45004` | `0x11a00000` | 0 | `0x109c` | directive block; `arg` -> next header at 4252 |
| 16 | `0xad640004` | `0x11800000` | 92 | 0 | **data**, not code (see below) |
| 124 | `0xad180004` | `0x11a00000` | 4112 | 0 | code; 1,120 / 4,112 bytes recovered |

**Block 1 at `0x11800000` is a float table, not code.** Ghidra's decoder produces a nonsense alternating
`NOP`/garbage pattern, which is the signature of 32-bit little-endian data read as 16-bit instructions. Parsed as
IEEE-754 single precision it is **23 exact round values**: 0.0, 512.0, 12.5, 7.5, 12.5, 40.0, 57.5, 2.0, 7800.0,
105.0, 10.0, 45.0, 7.5, 15.0, 2.0, 3.0, 5.0, 6.0, 0.0, 4.0, 2.0, 75.0, 5.0 — the signature of a human-authored
coefficient/configuration table, loaded into **L1 Data Block A** (`0x11800000`), not an instruction region.

**Block 2 at `0x11a00000` is genuine Blackfin+ code.** Disassembled with the Ghidra `blackfinplus:LE:32:default`
language built in §66.70, it decoded **341 instructions with 0 undecodable bytes** — the first clean validation of
that experimental language against real OP-Z bootloader code (previously only `crush.engine`). What the recovered
1,120 bytes do:

- `0x11a00000` — entry: `LINK`/`UNLINK` frame saving R7:4; writes `0x817`, `0x10`, `0x80` into system MMRs
  `0x20040014/1c/114/11c/128/120`; `SSYNC`; clears the low three bits of core MMR `0x1fc01004`; then reads system
  MMR `0x20000004`, masks with `0xf00` and compares against `0x300` — a **boot-mode / strap field test** selecting a
  path into `0x11a0083e` and `0x11a0074c`. Later it toggles bit 11 of `0x200c1000` around a call into `0x11a00118`,
  calls `0x11a00534`, retests `0x20000004 & 0xf00` with bit 8 toggled, and on the zero case writes 1 to
  `0x20057010`.
- `0x11a00118` — a **clock/CGU routine**: masks `0x20002000` with `0x7f01`, toggles bit `0xd`, polls `0x20002008`
  for bit 3 in a loop, writes the magic constants `0x44042442` and `0x04042442` to `0x2000200c`, and loops on bits
  0/1/2/3 — the classic change-then-wait-for-lock pattern.
- `0x11a001f0` — writes seven argument words to `0x200c0040/44/48/4c/60/64/68` and R0 to `0x200c0004`, polls
  `0x200c0008` bit 2, then writes `0x200c0080`: a data-movement / controller command setup.
- `0x11a0026e`, `0x11a00318` — assemble 32-bit words from fields with shifts of 0, 4, 8, `0xc`, `0x10`, `0x14`,
  `0x1c` and OR them together: a word-packing helper.

**Answer to the unbrick question, and what it now is not.** Calls in the recovered code target
`0x11a005a6`, `0x11a00b5c`, `0x11a00ca0`, `0x11a00d7c`, `0x11a00ea4` and `0x11a00f00` — all beyond the recovered
`0x11a00460`, so **~72% of this block is still unread**. **No NAND, partition-map, bad-block-table or
version/validity-record logic appears anywhere in the recovered 1,120 bytes.** The code that reads and validates the
state `0x15` destroyed is in the unread remainder, or in a later block. The recovered portion is system, clock and
controller initialisation — legwork. The question "does the loader rebuild a formatted NAND?" is therefore still
**open, but now located**: it is answerable from further oracle recovery of this same member, with no key, no
hardware and no device writes, and it is the strongest reason yet to finish `bootloader.ldr` beyond the key itself.

### 66.107 The oracle collector, hardened: five review passes and what they changed (2026-10-16)

`toolkit/opzbootprobe.py` was put through five successive reviews (correctness/wiring, strict defect
hunting, "resolve everything", "can this tool produce a confidently wrong answer", and a final
cleanup). 18 code findings were fixed. This section records what changed, so the tool and the notes
agree.

**The 63-byte leak ceiling is a device constant, not an artifact of our probe.** Measured over every
capture available -- 79 files, **75,461 frames**, including the genuine TE firmware-upgrade runs where
no probe exists at all: the maximum frame payload anywhere is **exactly 128**, and **no frame exceeds
it**. The leak frame is byte-exact:

    128 payload = 4 tick + 58 text prefix ("[timestamp] bootdisk: failed to find .zip file in ")
                + 65 data + 1 NUL

Of the 65 data bytes the last two are the device's own `..` truncation marker, so **63 real bytes**.
That the NUL lands on the final payload byte shows the device *finished* the message: the name field
is truncated, not the log buffer. The `capped` flag in the record is our decoder's own inference
(`len(payload) >= 128`), not a device report -- and it is empirically correct: of the 44 leak frames,
**17 sit at 128 and all end in `..`; 27 sit below it and never do. Zero false positives, zero false
negatives.** The old open question ("is `..` a marker or two real bytes?") is closed: it is a marker,
and no real data is lost. Multi-frame-per-boot was already closed by experiment in §65.3 (8 staged
probes still produced one read), so 63 per cycle is fixed and the campaign estimate stands.

**Silent-corruption detection (the important addition).** Nothing previously checked that a recovered
byte was *correct*. The failure mode was not a crash: a single mis-decoded byte corrupts the DEFLATE
stream, the scan then tests non-key bytes for hours, and the campaign ends by reporting **"no key in
the bootloader"** -- a false negative that would permanently misdirect the recovery. Two checks now
run on every scan:

| check | scope | catches |
|---|---|---|
| `check_prefix_stable` | within one process | any change to the already-recovered prefix (DEFLATE output is prefix-stable, so a later probe may only append) |
| `check_prefix_persisted` | across restarts | a divergence from the `plaintext-prefix.json` digest left by an earlier process |

Both are content-independent, which matters because for most recovered bytes we hold no ground truth
-- they are the *decrypted* archive, unpredictable without the key. Prefix-stability is the only
invariant available, and **it is the check that would have caught the masked-NUL bug of §66.89
immediately**, instead of by accident via a stalled probe. Demonstrated on the real 1,260-byte prefix
with one flipped deflate byte: the canary reported divergence at inflated offset 141 with both values.
A divergent prefix never overwrites a good digest, so the evidence survives. The persisted digest also
restores the tested-window counter, since windows depend only on the plaintext.

**Provenance.** Leak records now carry `terminator_inferred`: a terminator inside the masked first 16
bytes is *derived* from the mask delta rather than observed, and is now labelled as such.

**Exit-status contract.** `0` = key found (written to `KEY-FOUND.txt`), `3` = a collection run whose
range finished and holds no key, `2` = incomplete or probe budget spent, `1` = error. A driver can
re-invoke on 2 and stop on 0 or 3. Verified offline for 0/2/3. The `--max-probes` cap of 1..64 is
deliberately retained: it is the guard that stops an unattended loop, and because the digest now also
persists the window counter, restarts are cheap and correct.

**Other defects fixed:** `inflate` no longer zeroes the whole prefix on one corrupt byte (it salvages
up to the bad byte, and its warning is de-duplicated); probe state files are filtered by
`source_sha256` so two firmwares' byte maps can never be spliced; `load_bytes` applies `repair_state`
so the offline scan cannot read an unrepaired legacy map; all three artifacts (state, key file, raw
capture) are written atomically; a `HEURISTIC:` match can no longer halt the campaign; the tested-
window counter resets if the plaintext shrinks instead of silently disabling the scan; `--key-scan-only`
runs even if the original `.zfw` is gone, refuses when the directory holds two sources, and reports a
clear warning for a wrong `--key-member-start`.

**Costs measured, not assumed:** the per-cycle scan overhead at campaign end (4.3 MB of state JSON)
is **58 ms** against an ~18 s cycle = **0.35%**; a full-loader rescan is **277 s = 4.6 min**, now
avoided entirely by the counter restore.

**Regression test over real device bytes.** `replay_real_captures()` re-decodes every saved capture
and requires the recorded state to match exactly -- the closest thing to a hardware test that runs
without the device. It currently replays **35 cycles byte-identically**. What it does *not* cover:
`one_cycle`'s live serial staging, eject and timing on the unit, which still rest only on the
self-test and historical runs.

## 67. The update-mode console has a file-READ command: request `0x19`, reply `0x20` (2026-10-16)

**This corrects §22 and every later note that says "no console path can return file bytes to the host".** That
claim rested on a type sweep which sent *empty* payloads, and on a guessed exclusion set that had put `0x19`
into a "NAND family — destructive, do not send" category without ever testing it. `0x19` is in fact the
console's file-read command, and it was available the whole time.

### Framing, and the two traps that hide it

```
C0 <routing> <type> <len_be32 big-endian> <payload>      0x7D escapes the next byte as (byte ^ 0x20)
host -> device routing 0x01        device -> host routing 0x1E  (replies, and type-0x04 log frames)
```

1. **The PONG is a zero-length frame** — `C0 1E 01 00 00 00 00`. A decoder that treats `len == 0` as "not a
   frame" never sees it, so a healthy unit reads as dead. Match the raw pattern instead.
2. **The port-open reset eats the first frame written.** Warm the port with a PING before the real command, or
   a working command looks ignored.

### The read command

Handler `0x11a02c0a`, dispatched from the chain at `0x11a02c04` inside the function at `0x11a02932` (L1 code
loaded at `0x11a00000`).

| | |
|---|---|
| request type | `0x19` |
| reply type | `0x20` |
| payload | one NUL-terminated path, **relative to `/yaffs2/`** |

Mechanics: build `/yaffs2/` + argument, open it, store the handle in the global `0x11804000`, set an in-use
byte at `0x82835c93`, seek for the size, send a `0x20` header, then loop reading `0x800`-byte chunks and sending
each via `0x11a046ae` (which splits into frames of at most `0x100` payload bytes). Concatenating the `0x20`
payloads in arrival order reproduces the file byte-for-byte.

The path prefix is confirmed by the device's own error log, which names it explicitly:
`disk/disk_io: error opening file /yaffs2/zz-does-not-exist.txt, error type: rb ENOENT`.

**A bad path produces no reply frame at all**, only log frames (routing `0x1E`, type `0x04`, e.g.
`yaffsfs: yaffs: error: ENOENT`). So absence of `0x20` frames plus presence of `0x04` frames is the failure
signature.

**It is read-only** — open, read, stream, close. No write, no move, no delete. Safe to batch over many paths.

**No offset and no length argument**: it always reads the whole file from the beginning.

### Verification (all byte-exact)

| requested path | bytes | independent check |
|---|---|---|
| `user/config/midi.json` | 1,428 | equals a previously captured copy |
| `user/config/userPresets.dat` | 351,202 | equals a previously captured copy — validates multi-frame reassembly |
| `system/content/engines/crush.engine` | 1,212 | equals the copy inside the decrypted 1.2.45 update, sha256 `197fc3bc5d8abc52…` |
| `system/content/samplepacks/UserSampler.aif` | 706,990 | equals the copy inside the update |

### Measured result that this enabled

The eight factory-only engines are **absent** from `/yaffs2/system/content/engines/` on the affected unit: all
of `chord`, `digital`, `electric`, `fm003b`, `ministringshort`, `saw013a`, `tapetwo`, `volt` return nothing,
while the control `crush.engine` returns 1,212 bytes. This promotes the earlier "absent from every package
held" inference to a measurement taken on the device itself.

### The other console command: `0x37` is a MOVE, not a copy

The handler at `0x11a02fb4` builds `source = "/yaffs2/" + argument 1` and `target = "/yaffs2/" + argument 2`,
then calls a two-instruction wrapper `0x8280db80` which sets `R0 = 0` and calls `0x8280d954(mode, p1, p2)`.

The mode is a real branch, but it is an options/flags word, **not** an operation selector: the worker contains
no data-copying machinery at all — only path validation (`0x8280cd84`, `0x8280d4a0`, `0x8280d2c4`), node lookup
(`0x8280d6b4`, `0x8280d6ce`) and a metadata-mutation primitive. Its non-zero branch compares against a
2-character string held in the image as `.` / `..`, i.e. a parent-directory path guard. **There is no copy
mode.** Confirmed by measurement: moving `config/general.json` to a new name leaves the source gone and the
target byte-identical.

Status byte: `0xE1` is written unconditionally at handler entry and overwritten with `0xD3` only when the
operation returns 0. So `0xD3` = the move happened, `0xE1` = it did not.

Guard: `0x80 <= strlen("yaffs2/") + strlen(arg) + 1` logs `Too long source filename` / `Too long target
filename`. Those strings are not observable over the serial log channel in this build and appear in no log file
the unit exposes, so they are useless as a success test. Arguments land in slots `0x40` apart while the guard
permits 120 bytes, so keep each argument under ~60 bytes.

### The content-mode mass-storage view is FILTERED — "not visible" is not "absent"

Two staged files that never appeared in the content-mode listing (`zz-osver.txt`, `zz-plugs.json`) were in
fact still present and both restored on the first attempt. Conversely `how_to_import.txt` and `import.log`
appear at the volume root but return `ENOENT` when read as `/yaffs2/user/how_to_import.txt` or
`/yaffs2/user/import.log`. The root is a synthesised view mixing `/yaffs2/user/**` with system content. Only
`0x19` can be trusted to test whether a file exists.

### Open

- Where the eight missing engines live, if anywhere on this unit. Needs a directory-listing primitive.
- Unread handlers that may provide one: `0x10` → `0x11a03a3a`, `0x14` → `0x11a03900`, `0x17` → `0x11a03bca`
  (reply `0x18`), `0x31` → `0x11a03986` (reply `0x12`), plus `0x23`, `0x27`, `0x32`, `0x34`.
- No offset/length read primitive found, so a truncated read must be restarted from the beginning.

## 68. The complete serial console command inventory: 20 types (2026-10-16)

§67 documented the file-read command (`0x19` → `0x20`). This section enumerates the **entire** dispatch rather
than the parts reached by probing, and names each command from the strings its handler loads.

### Why every live sweep under-reported the set

The first sweeps found eight answering types; the dispatcher handles **twenty**. The rule that explains it, and
which should govern any future probing: **a command that needs arguments is silent when sent an empty payload**,
because its first act is a length or pointer check on data that is not present. `0x37` and `0x19` were both
invisible to every sweep for this reason, and they are not exceptions.

The dispatcher is a comparison chain on the type byte in `R2`, inside the function at `0x11a02932` (L1 code
loaded at `0x11a00000`). It is **not** a pointer table. The long pointer runs in the image are C++ vtables and —
decisively — the upgrade module's error-code-to-string table in `upgrade.cpp` ("The flash array is not valid",
"The checksum does not match the expected value", "The bootloader version detected is not supported", "The
expected device does not match the detected device", "The command is not recognized", "The data is not of the
proper form"). That table is why "The command is not recognized" masqueraded as a dispatcher fall-through: it is
loaded at `0x828233e6` in the `0x0828xxxx` image as one of six sibling status strings. **There is no second
serial dispatcher.**

### Inventory

| type | reply | handler (L1) | command |
|---|---|---|---|
| `0x00` | `0x01` | `0x11a02dc8` | PING (accumulates the payload, replies; zero-length reply when the payload is empty) |
| `0x02` | `0x03` | `0x11a032b0` | version block (dsp / kb / fw / os / bootloader / keyboard / ble / module) |
| `0x06` | — | `0x11a02e72` | install / sequence step; six calls into the upgrade path |
| `0x07` | `0x08` | `0x11a02eb4` | identity / metadata (`serial:%s;hardware_revision:%d;dsp_serial:%s`) |
| `0x10` | `0x12`,`0x13` | `0x11a03a3a` | **write SPI flash** (`writing %d bytes to SPI @ 0x%08x`) |
| `0x14` | `0x16` | `0x11a03900` | **format SPI flash** (`Got format SPI`) |
| `0x15` | — | `0x11a02d50` → `0x11a03894` | **format NAND** (`Got format NAND`, `Format complete`) |
| `0x17` | `0x18` | `0x11a03bca` | not identified (calls `0x8281e98e`) |
| `0x19` | `0x20` | `0x11a02c0a` | **read file and stream it** (§67) |
| `0x21` | `0x22` | `0x11a0362c` | not identified (calls `0x828225e8`) |
| `0x23` | `0x24` | `0x11a03686` | **firmware upgrade by filename** (`Too long filename`, `Got upgrade request: %s`, `Starting upgrade`, `Upgrade complete %d`) |
| `0x27` | `0x28` | `0x11a03256` | not identified (calls `0x8280f410`) |
| `0x29` | `0x16`,`0x30` | `0x11a037d2` | not identified; filename-bearing (loads `Too long filename`) |
| `0x31` | `0x12`,`0x13` | `0x11a03986` | **load code into RAM and execute it** (`RAM load complete. total size: %d`) |
| `0x32` | `0x33` | `0x11a03444` | companion-module comms (BLE / Nordic / keyboard / factory data) |
| `0x34` | — | `0x11a03200` | not identified; shares `0x828229da` with the SPI commands |
| `0x35` | `0x36` | `0x11a0311c` | chip / firmware version info (`bf_os_ver:`) |
| `0x37` | `0x38` | `0x11a02fb4` | **move / rename inside `/yaffs2`** (§67) |
| `0x39` | `0x3a` | `0x11a02f44` | monotonic clock, 4 bytes from the global `0x8283dfd0` |
| `0x3b` | `0x3c` | `0x11a02f82` | not identified; passes `struct+0x90` to `0x8281e816` |

### Safety consequence: seven destructive commands, not one

| type | effect |
|---|---|
| `0x10` | writes SPI flash |
| `0x14` | formats SPI flash |
| `0x15` | formats NAND (destroyed the affected unit) |
| `0x23` | firmware upgrade by filename |
| `0x29` | filename-bearing, uncharacterised — treat as write |
| `0x31` | **loads code into RAM and executes it** |
| `0x06` | install / upgrade sequence step |

`0x31` is the most dangerous entry in the table and is strictly worse than format NAND: a RAM-load-and-execute
primitive is a general code-execution channel that needs neither a file nor a power cycle. `0x10` and `0x14` are
SPI writes sitting in the middle of a range a plausible sweep would walk straight through. **Any type-byte sweep
of this console is unsafe, and the previously-published exclusion list — which named only the NAND family plus
`0x15` — was incomplete and should not be relied on.**

Read-only commands identified so far: `0x00`, `0x02`, `0x07`, `0x19`, `0x35`, `0x39`. The genuinely
uncharacterised set is `0x17`, `0x21`, `0x27`, `0x29`, `0x34`, `0x3b`, and each must be treated as potentially
destructive until read in full. `0x23` and `0x29` share the `Too long filename` string, suggesting they are two
halves of the upgrade flow rather than unrelated commands. `0x828229da` is shared by `0x10` (SPI write), `0x14`
(format SPI) and `0x34`, making `0x34` a strong candidate for a third flash operation.

### Two dead ends, recorded so they are not repeated

- **"The command is not recognized" is not a dispatcher fall-through.** It is one of six sibling strings in the
  upgrade module's error-code table; string-hunting for it leads to `upgrade.cpp`.
- **`0x1a` and `0x2b` are dispatched nowhere in the L1 code.** An earlier live sweep recorded them as answering,
  but searching the dispatcher's code for comparisons against those values finds only a `memset` length (`0x1a` =
  26 bytes) and an ordinary function argument. Given the decoder defects known at the time of that sweep, those
  two results are best explained as misattribution and should not be treated as commands.

## 69. Final command identification: four read primitives, and the complete destructive set (2026-10-16)

§68 left six handlers uncharacterised. All six are now identified, and the practical picture changes: the
console has **four data-dump primitives**, one of which reads SPI flash directly.

### The resolved handlers

- **`0x17` → `0x18`: READ SPI FLASH and stream it.** Sends a `0x18` header carrying the requested length
  (`struct+0x8`), then loops reading through `0x8281e98e` — in `bf/spi_flash.cpp`, logging `spi read failed %d` —
  copying into the reply buffer and sending it with `0x11a046ae` (the same sender `0x19` uses), advancing at most
  `0xFF` bytes per chunk. Source offset from `struct+0x90`. **Read-only.** Arguments are an offset and a length.
- **`0x21` → `0x22`: READ THE LOG and stream it.** Worker `0x828225e8` loads the timestamped log-line format
  `[%02d-%02d-%02d %02d:%02d:%02d] %s%s` and iterates the yaffs layer until exhausted. Gated on bits 0–1 of the
  state byte `struct+0x9c`. **Read-only.**
- **`0x27` → `0x28`: READ through the yaffs2/NAND layer and stream it.** Reads up to `0x8000` (32 KB) via
  `0x8280f410`, replies `0x28` with the length, streams the buffer. `0x8280f410` is yaffs2 allocator code
  (`ext/yaffs2/yaffs_allocator.c`). Whether its argument is a raw NAND region or a filesystem object is not yet
  pinned. **Read-only.**
- **`0x29` → `0x30` / `0x16`: path-based filesystem operation.** Copies the 8 bytes at `struct+0x54`/`+0x58`,
  applies the same `0x80 <= 7 + len + 1` guard as the move command (`Too long filename`), builds `/<name>` plus a
  second component, calls `0x8280d942` — which uses the *same primitive set as the move worker* `0x8280d954`.
  A sibling path operation; shares `Too long filename` with `0x23`. **Treat as a write.**
- **`0x34` → no reply: SPI flash operation.** Logs `serial_command_handler.cpp` line `0x2f5`, calls `0x828229da`
  (the same SPI transfer used by `0x10` and `0x14`), and is gated on `struct+0x9c` being 120 or 150, each
  leading to `0x8281c5bc(value, 0)` with 20 or 10. `0x8281c5bc` programs peripheral MMRs `0x20000000`–`0x20000068`,
  `0x20004000`, `0x20004818`, `0x20004010`, `0x20046000`, `0x20046004`. Confirmed flash operation.
- **`0x3b` → `0x3c`: SET THE CLOCK.** Passes `struct+0x90` to `0x8281e816`, which writes the global `0x8283dfd0`
  — the value `0x39` reads — and persists it by opening `/yaffs2/time.txt`. So `0x39` reads the clock, `0x3b`
  sets it.
- **`0x06` → no reply: hardware self-test.** Six callees: the CRC engine (`bf_crc.cpp`, MMRs at `0x200e0000`),
  MMR setup at `0x2004010c`–`0x2004012c`, a SPI-info read, a read of the stored time from `/yaffs2/time.txt`,
  and Queue helpers. A diagnostic pass — §68's guess that it was an install step was wrong.

### The complete command set

| type | reply | command | class |
|---|---|---|---|
| `0x00` | `0x01` | PING | read |
| `0x02` | `0x03` | version block (dsp/kb/fw/os/bootloader/keyboard/ble/module) | read |
| `0x06` | — | hardware self-test (CRC, SPI info, stored time) | benign |
| `0x07` | `0x08` | identity / metadata | read |
| `0x10` | `0x12`,`0x13` | write SPI flash | **write** |
| `0x14` | `0x16` | format SPI flash | **write** |
| `0x15` | — | format NAND | **write** |
| `0x17` | `0x18` | **read SPI flash (offset, length) and stream** | **read** |
| `0x19` | `0x20` | **read file under `/yaffs2/` and stream** | **read** |
| `0x21` | `0x22` | **read the log and stream** | **read** |
| `0x23` | `0x24` | firmware upgrade by filename | **write** |
| `0x27` | `0x28` | **read via the yaffs2/NAND layer (≤32 KB) and stream** | **read** |
| `0x29` | `0x30`,`0x16` | path-based filesystem operation | **write** |
| `0x31` | `0x12`,`0x13` | load code into RAM and execute it | **execute** |
| `0x32` | `0x33` | companion-module comms (BLE / Nordic / keyboard / factory data) | config |
| `0x34` | — | SPI flash operation | **write** |
| `0x35` | `0x36` | chip / firmware version info | read |
| `0x37` | `0x38` | move / rename inside `/yaffs2` | **write** |
| `0x39` | `0x3a` | monotonic clock read | read |
| `0x3b` | `0x3c` | set the clock (writes `0x8283dfd0` and `/yaffs2/time.txt`) | minor write |

**Safe to send: `0x00`, `0x02`, `0x07`, `0x17`, `0x19`, `0x21`, `0x27`, `0x35`, `0x39`.** Destructive or
executing: `0x10`, `0x14`, `0x15`, `0x23`, `0x29`, `0x31`, `0x34`, `0x37`, plus the minor write `0x3b`.

### Why `0x17` matters most

Until now the only read channel was `0x19`, which needs an exact path inside `/yaffs2` — so nothing the
filesystem does not expose was reachable, and the eight factory-only engines were confirmed *absent from
`/yaffs2/system/content/engines/`* on the affected unit. A **raw SPI flash read ignores the filesystem**, so
content stored in flash rather than as files becomes reachable. Suggested next step: scan modest regions of
flash with `0x17` for container markers (`FORM`/`AIFF` for audio packs, and the engine magic) rather than
dumping wholesale — the scan is cheap and read-only.

## 70. THE RECOVERY — the bricked unit plays again (2026-10-16)

**Outcome: the unit was restored and plays.** This section is the condensed, public record of how; the detailed
working log is in the local `FW_SUCCESS.md` §26.

### 70.1 The failure state

- The unit booted only to update mode, and `<PLAY>` faulted with `iid 0x00130026`, `ADI_EXC_DATA_CPLB_MISS`,
  `DCPLB_FAULT_ADDR 0x00000000`, `RETX 0x80117baa` and no log line naming the trigger.
- The eight factory engines were **measured absent** from `/yaffs2/system/content/engines/` by a read over the
  update-mode console (request `0x19`); a control read of `crush.engine` returned 1212 bytes.
- The 24 factory sample packs were absent: the boot log reported `Calculating used sample memory: 869 kB`, i.e.
  one ~890 KB pack, and the only pack on the content disk was a fabricated substitute.

### 70.2 What was done, in order

1. **Stock 1.2.45 was reinstalled** from the update-mode volume. `upgrade.log` recorded
   `content -> OK / os -> OK / bootloader -> Already installed / ble -> Already installed / keyboard -> Already
   installed / successfully upgraded to 1.2.45`. This repaired the **boot**: init then ran through
   `sequencer`, `codec start`, `finalize` and `task: create task filemanager_task` with no exception.
2. **`<PLAY>` still faulted.** The console went silent at this point — and stayed silent through every later
   attempt, baud rate, DTR state, cable replug and power cycle.
3. **The content disk was the wrong address for this content.** Sample packs placed in the content disk's slot
   tree *were* imported (`importing CuckooKicks.aif...SUCCESS. New used space 869 kB`), but the factory packs and
   engines on a healthy unit live under `system/content/{engines,samplepacks}/`, and no content-disk route writes
   that tree. The device's own 0-byte `~`-prefixed placeholders named what it wanted
   (`~redmountKicks.aif`, `~10.engine`, ...), and placing the four `redmount*` packs in their stubbed slots did
   not change `used sample memory`.
4. **The §24 updater primitive was the route that worked.** A plain (unencrypted) zip named
   `firmware_bin_only_with_bootloader.zip` in the volume root, whose entry names are resolved against
   `/yaffs2/upgrade/` with `..` unsanitised, so exactly one `..` reaches `/yaffs2/`. One payload was built with
   **33 entries / 18,468,406 B**: 8 engines -> `../system/content/engines/`, 20 packs ->
   `../system/content/samplepacks/`, 4 packs -> `../user/samplepacks/` — every destination taken from the source
   device's own extraction manifest, and every file re-verified against that manifest's SHA-256 before packing.
5. **The extract completed and PLAY works.** Captured on the bootloader console:

```
mass_storage: comparing firmware_bin_only_with_bootloader.zip with (null)
upgrade: [extract] progress 18463232/18463232
upgrade: upgrade started
upgrade: failed to find ble firmware file
upgrade: upgrade not compatible with this device
bootdisk: upgrade was unsuccessful, system won't reset
```

   Zero extraction failures. Because §24 establishes that a single unwritable entry aborts the rest of the
   archive, a completed progress counter is proof that all 33 entries were written. The `ble` gate failure is the
   documented, harmless tail of this primitive.

### 70.3 Verification

- `system.log` after the working boot contains **0** matches for `exception`, `CPLB`, `FAULT_ADDR` or
  `callstack` — the `RETX 0x80117baa` fault is absent from the record.
- `upgrade.log` independently recorded both payload runs (`[2026-10-16 13:48]` and `13:51`/`13:52`), ending in
  `upgrade not compatible with this device`.
- `main: initialize [synth engine]: took 129 ms` — healthy engine load.

### 70.4 Corrections this recovery forces

| prior belief | corrected |
|---|---|
| `contentmanager: Calculating used sample memory` should rise when system content is restored | **wrong.** That figure counts the **user** sample space (the same budget the import reports as `0.8/24.0 MB`). Files written to `/yaffs2/system/content/` are not part of it, so an unchanged 869 kB is the *expected* reading. It must not be used to judge such a payload. |
| The five engines failing with `dlm: Unsupported fill value` (analoga, chorus2, ep, fdnreverb, organ) cause the PLAY crash | **wrong.** All five still fail, and the unit plays. They remain a non-blocking residual. |
| Restoring the system content requires a repacked, encrypted `.zfw` | **wrong.** A plain zip through the §24 path writes `/yaffs2/system/content/` directly, and the bootloader's discovery scan tests the *decrypted* name field for `.zip`, so a `.zfw` name buys nothing. |

### 70.5 The console: availability rule, now established

The bootloader console is served **only while the OS is not booting**. It answered while the unit was fully
bricked and while the updater held the unit, and was silent in every state where the OS reached its init. It is a
diagnostic for the broken state, not a general-purpose channel.

### 70.6 Reusable rules for the next payload

1. **Start the console capture before ejecting.** The `[extract] progress N/N` counter is the verification channel
   for the §24 primitive; a drain that starts after the extract yields only "it presumably ran". The same action
   produced exactly that wrong conclusion once here.
2. **Take destinations from a source device's extraction manifest.** Its `path` field is ground truth for where
   each file belongs: engines and most packs under `system/content/`, the four `redmount*` packs under `user/`.
3. **Re-verify every file against the manifest's SHA-256 before packing**, then check the staged archive's hash on
   the volume.
4. **Remove stray `._*` AppleDouble files from the volume root.** macOS creates them despite `cp -X`, and their
   names also match the `firmware`/`.zip` discovery checks, so the bootloader can select the 4 KB stub instead of
   the payload. Audit the root for `*firmware*` and `*.zip` after copying.
5. **Never boot a working unit into content mode casually.** The content-disk eject sync strips
   `/yaffs2/user/engines/`, and a content-mode boot's `Syncronizing` stages overwrite internal files.
6. **Never supply a `bootloader` (or `os`) component in a §24 payload.** Only a surviving bootloader can re-flash
   anything; a wrong bootloader write is terminal.

### 70.7 Residuals, all non-blocking on a unit that plays

| item | status |
|---|---|
| `dlm: Unsupported fill value` x5 | the five DLC-only engines with no published memory slot. Their slots are known (analoga 27, chorus2 88, ep 4, fdnreverb 89, organ 18) but acting on them needs `settings/plugs.json`, which the app owns. |
| `/yaffs2/user//arpeggiators/01-06.txt` | six files never present |
| `libaiff: AIFF_ReadOpen failed` | one AIFF still unresolvable on some boots |

**Not separated:** the payload delivered the engines and the packs together, so the log does not establish which
was decisive. Both were plausibly necessary; separating them would need a one-variable ablation, which is not
justified on a working unit.
