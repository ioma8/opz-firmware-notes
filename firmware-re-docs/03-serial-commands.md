# 03 — The serial console: framing, the command set, and the update path

Two independent evidence sources are used here, and they are labelled throughout:

- **[FW]** — recovered statically from the decrypted images by decompilation/string analysis (this work).
- **[DEV]** — measured on the physical unit in earlier sessions of this project.

Where only **[DEV]** exists, the firmware source for it has **not** yet been located (see
"Open problem" at the end — this is a real limitation, not a gap I am papering over).

## 3.1 Frame format

```
C0 <routing> <type> <len_be32> <payload>
```

| field | meaning |
|---|---|
| `0xC0` | start-of-frame, **sent raw, never escaped** |
| routing | `0x01` host→device, `0x1E` device→host; `0x2E` is used for OS-originated traffic |
| type | command byte; the reply uses **command + 1** |
| len | 4-byte big-endian payload length |
| payload | **only this is escaped**: `C0`/`7D` → `7D` followed by `byte ^ 0x20` |

> ⚠️ **The trap that cost this project a full day.** Escaping the frame's **leading `C0`** (putting
> `7D E0` on the wire) makes the device answer *nothing at all* — no PONG, no reply, no log frame — in
> every mode, at every baud, both DTR states, surviving cable replug and a power cycle. It looks exactly
> like a dead console. Build frames with `toolkit/opzcopyprobe.py::encode` or
> `sergey-extraction/opzget.py::encode`, which emit the header raw and escape only the payload.
> See `FIRMWARE_ANALYSIS.md` §71.1.

> **Cross-chip confirmation.** The nRF52832 BLE image implements the same framing primitives — `0xC0`
> start-of-frame, `0x7D` escape with XOR `0x20`, and a big-endian length field — read independently from its
> own byte parser (`FUN_00027eb8`). Its header is nibble-packed (`(length << 4) | destination`, destination
> must be `3`) and it applies a **32-bit message-id allow-list** admitting only ids `4`, `8`, `17` and `0x13`
> for long frames. See doc `07` §7.2e.

**Reply classification.** Log frames are type **`0x04`** (routing `0x1E` from the bootloader, `0x2E`
from the OS). A PONG is routing `0x1E` **type `0x01`** — the *same routing* as bootloader logs. Classify
by **type**, not routing, or a log frame is mis-read as an answer. `toolkit/opzframe.py::frames()` drops
length-0 frames, so a PONG must be matched on raw bytes.

## 3.2 The command set

The bootloader's own handler-file string is `..\src\serial_command_handler.cpp` **[FW]**, present at
`0x82836d78` in the bootloader image. Its sibling module strings in the same region are
`SerialMessageHandler.cpp` **[FW]**, plus the per-channel reply formatters listed below.

### Device-verified commands [DEV]

The complete serial command inventory was established in earlier work (`SERIAL-COMMANDS-SET.md`,
20 types). The responses measured on this unit in update mode, with the documented encoder:

| type | reply | command | class |
|---|---|---|---|
| `0x00` | `0x01` | PING → PONG (empty payload) | read |
| `0x02` | `0x03` | version block → `dsp hw revision: dvt2…` | read |
| `0x06` | — | hardware self-test (CRC engine, SPI info, stored time) | benign |
| `0x07` | `0x08` | identity/metadata | read |
| `0x10` | `0x12`,`0x13` | write SPI flash | **write** |
| `0x14` | `0x16` | format SPI flash | **write** |
| `0x15` | — | format NAND | **write** |
| `0x17` | `0x18` | read SPI flash (offset, length) and stream | read |
| `0x19` | `0x20` | read file under `/yaffs2/` and stream | read |
| `0x21` | `0x22` | read the log and stream | read |
| `0x23` | `0x24` | firmware upgrade by filename | **write** |
| `0x27` | `0x28` | read via the yaffs2/NAND layer (≤32 KB) and stream | read |
| `0x29` | `0x30`,`0x16` | path-based filesystem operation | **write** |
| `0x32` | `0x33` | companion-module comms (BLE/Nordic/keyboard) | config |
| `0x34` | — | SPI flash operation | **write** |
| `0x35` | `0x36` | chip / firmware version info | read |
| `0x37` | `0x38` | move / rename in `/yaffs2` | **write** |
| `0x39` | `0x3a` | monotonic clock read | read |
| `0x3b` | `0x3c` | set the clock (`0x8283dfd0` + `/yaffs2/time.txt`) | minor write |

Measured replies **[DEV]**, verbatim:

| sent | reply | payload |
|---|---|---|
| `0x00` | `0x1e` / type `0x01` | PONG (empty) |
| `0x02` | `0x1e` / type `0x03` | `dsp hw revision: dvt2…` |
| `0x07` | `0x1e` / type `0x08` | `serial:…;hardware…` |
| `0x35` | `0x1e` / type `0x36` | `bf_os_ver:1.2.43;bf_bl_v…` |
| `0x19` | — | needs a path payload; a wrong path draws **no reply** |
| `0x2b` | — | one-shot, answered only after a format |

### The dispatcher, recovered [FW]

The console command handler is **`FUN_block8__11a02932`** — 4,892 bytes, in the `block8::` overlay space.
It is the same `0x11a02932` address that earlier notes recorded, now correctly resolved. It was located
by querying the reference manager over the string range (`§3.6`), and it references
`..\src\serial_command_handler.cpp` and every reply format string.

It dispatches on a single state byte, **`DAT_82852e94`**, compared against the command number. The
complete set of comparisons found:

| `DAT_82852e94` | cmd | handler behaviour recovered from the decompilation |
|---|---|---|
| `0x00` | `0x00` | PING — with an **empty payload it replies immediately** (type `0x01`); with a payload it buffers it and only replies once the full length has arrived |
| `0x02` | `0x02` | builds `dsp hw revision: %s\n`, then `kb hw revision: %d\n` … |
| `0x06` | `0x06` | hardware self-test (CRC / SPI / stored time) |
| `0x07` | `0x07` | metadata |
| `0x10` | `0x10` | write SPI flash |
| `0x14` | `0x14` | format SPI flash |
| `0x15` | `0x15` | format NAND |
| `0x17` | `0x17` | read SPI flash and stream |
| `0x19` | `0x19` | read file and stream; builds `/yaffs2/` + name, guards with `Too long filename\n` |
| `0x21` | `0x21` | **read a file** into a `0x8000` (32 KB) buffer and stream it, replying type `0x22` |
| `0x27` | `0x27` | yaffs read/stream; replies type `0x28` |
| `0x29` | `0x29` | **file write** — builds `/yaffs2/<path>`, guards `Too long filename\n`, writes, replies |
| `0x31` | `0x31` | **RAM payload receive** — accumulates bytes into a RAM buffer; on completion logs `RAM load complete: total size = %u` and records `0x02` |
| `0x32` | `0x32` | companion-module (BLE/Nordic) comms; on parse failure logs `failed to parse data from ble`, replies type `0x33` |
| `0x34` | `0x34` | **blackfin reset request** — logs `blackfin reset was requested` from `serial_command_handler.cpp` line `0x2f5` (757), then branches on state `0x78` → reset arg `0x14`, `0x96` → reset arg `10` |
| `0x35` | `0x35` | builds the version block: `fw_version`, `os_version`, `bootloader_version`, `keyboard_version`, `ble_version`, `module_type`, `module_version` |
| `0x37` | `0x37` | move/rename in `/yaffs2` |
| `0x39` | `0x39` | clock read |
| `0x3b` | `0x3b` | clock write |

**That is 21 command codes, matching the 21-entry jump table at `0x82836c14` exactly** (`§3.6`). The
table and the dispatch are the same structure seen from two sides, which is the cross-check that makes
this identification solid rather than plausible.

### The reply-type rule, confirmed from the firmware [FW]

The reply types the handler emits, extracted from every call to the send function
`FUN_block8__11a0452c`:

```
0x01  0x03  0x08  0x12  0x13  0x16  0x18  0x20  0x22
0x24  0x28  0x30  0x33  0x36  0x38  0x3a  0x3c
```

Every one is **`command + 1`** for a command in the set
`0x00, 0x02, 0x07, 0x11, 0x12, 0x15, 0x17, 0x1f, 0x21, 0x23, 0x27, 0x2f, 0x32, 0x35, 0x37, 0x39, 0x3b`.
This confirms the `command + 1` reply rule from the device's own code rather than from observation alone,
and it independently corroborates the command numbering in the table above.

Two details recovered here that were not previously known:

- **`0x31` is a RAM payload receiver**: it writes incoming bytes into a RAM buffer, and when the
  accumulated count matches the declared length it logs `RAM load complete: total size = %u` and signals
  status `0x02`. Together with `0x34`'s reset primitive this is a complete **load-and-run** capability
  over the serial console.
- **`0x21` is a 32 KB file reader** replying type `0x22` — distinct from `0x19`'s streaming read, which
  matters when choosing a read primitive.
- **The `0x35` version reply includes a hard-coded build date string, `Jan 26 2021`**, between the
  bootloader version field and the keyboard version field (visible at `0x82836b5c`). Any parser of the
  `0x35` reply must expect that literal, or it will mis-frame the fields.

Recall from `FIRMWARE_ANALYSIS.md` §71.1 that `0x06` is served only in the `0x78`/`0x96` state values
while `0x00`, `0x02`, `0x07` and `0x35` belong to console mode `0x11` — the dispatch table above shows
*why*: the state byte gates which command bodies are reachable at all.

## 3.3 The update/install path map [FW]

The bootloader contains the complete set of paths it moves files between. This is the authoritative map
of the install mechanism, and it is the same primitive the recovery work used:

```
/yaffs2/upgrade/                                     the staging root
/yaffs2/upgrade/%s                                   per-component staging
/yaffs2/upgrade/progress.log                         install progress
/yaffs2/upgrade/firmware/firmware.version
/yaffs2/system/firmware.version
/yaffs2/system/content/%s                            -> content lands here
/yaffs2/user/%s                                      -> user tree lands here

/yaffs2/upgrade/firmware/blackfin/bin/bootloader.ldr / bootloader.version
/yaffs2/upgrade/firmware/blackfin/bin/opz.ldr / opz.crc32 / os.version
/yaffs2/upgrade/firmware/blackfin/system/content/
/yaffs2/upgrade/firmware/nordic/bin/nrf52832_opz.bin / .dat / nordic.version
/yaffs2/upgrade/firmware/psoc_keyboard/bin/SnakeKeyboardModule_{EVT4,DVT2}.cyacd
/yaffs2/upgrade/firmware/psoc_keyboard/bin/keyboard.version
/yaffs2/upgrade/firmware/module.cyacd / module.type / module.version

/yaffs2/last_upgrade/firmware/psoc_keyboard/bin/SnakeKeyboardModule_EVT4.cyacd
/yaffs2/firmware_auto.zip                            auto-install image
/yaffs2/os.ldr / os.version / os.crc32               the live OS
/yaffs2/tmp/                                         working dir
```

Two things fall out of this map that were not previously recorded as firmware facts:

1. **`/yaffs2/last_upgrade/` is a real retained copy** of the previously-installed keyboard firmware.
   This is the "stale marker" location that earlier probing could not reach, because the SysEx file
   service matches registered IDs rather than paths (`FIRMWARE_ANALYSIS.md` §71.4).
2. **`/yaffs2/firmware_auto.zip` is a boot-time auto-install hook, and the trigger is now decompiled.** The
   condition is simply *file presence* — there is no key combination, no marker file and no version query in
   the trigger itself:

   ```c
   /* FUN_82824d46 */
   iVar1 = FUN_828231a2("/yaffs2/firmware_auto.zip", &DAT_828376c4);   /* open; -1 = absent */
   if (iVar1 >= 0) {
     log("found auto upgrade, upgrading");
     iVar2 = FUN_828249d8(iVar1 != 0, 0, 0);        /* run the upgrade from that handle */
     if (iVar2 != 0) log("failed to upgrade");
     FUN_8282314c(iVar1);                            /* close                */
     FUN_8280d942("/yaffs2/firmware_auto.zip");      /* DELETE the zip       */
     log("Upgrade complete");
     FUN_828202e6();                                 /* reset / continue boot */
     FUN_8281c5bc(10, 0);
   }
   ```

   So: **drop a zip at that path and the next boot installs it, deletes it, logs `Upgrade complete` and
   resets.** A small overlay routine (`FUN_block8__11a04d7c`) only tests for the file's existence, which is
   consistent with the overlay side asking "is there an auto-upgrade pending?".

   **How that file can get there is the interesting part.** The update-volume extractor writes each zip entry to
   `/yaffs2/upgrade/<entry name>`, which is why the recovery work could place content with entries like
   `../user/engines/<name>.engine` — one level up from `/yaffs2/upgrade/` is `/yaffs2/`, so an entry named
   `../firmware_auto.zip` lands exactly on this hook. That makes the hook reachable **from the update volume
   alone**, using the same primitive documented above, and it is the mechanism that turns a single update into a
   *boot-triggered* one.

   Two caveats keep this from being a free pass: the payload still goes through the normal upgrade validation
   (the device's own `upgrade.log` has recorded `upgrade not compatible with this device` for mismatched
   payloads), and every extracted file must have a correct **zip entry CRC** (§3.3 above). Only the Nordic
   component carries its own signature (its `.dat` descriptor, doc `07` §7.3).

### What the bootloader actually verifies during an install [FW]

Decompiling the extractor settles what integrity check an update is subject to, which matters before anyone
repacks a component:

```c
/* FUN_block8__11a04ab6 - the zip extractor, upgrade.cpp */
FUN_8282b440(auStack_148 + iStack_c, 0xa0, "/yaffs2/upgrade/%s", auStack_148);
iVar1 = FUN_block8__11a049be(param_1, auStack_c8);        /* extract one entry      */
iVar2 = FUN_82821ab4(auStack_c8, 0);                      /* CRC of the extracted file */
if (iVar2 != iStack_184)  log(upgrade.cpp, 0x3ac,
        "[extract]: CRC check failed for %s (%d)", auStack_148, iVar2 != iStack_184);
```

So **the integrity check is the ZIP entry's CRC**, compared against the extracted file — not the `opz.crc32`
sidecar, and not any per-line trailer inside a `.cyacd` (see doc `07` §7.4). The same routine logs
`[extract]: %s progress %d/%d`, `[extract]: Bad zip file` (line `0x37b`) and
`[extract]: Failed to extract file %s` (line `0x3a4`), so a failed install is diagnosable from the extract
counter alone. Two consequences:

- a repacked `firmware_bin_only_with_bootloader.zip` must have **correct ZIP CRCs per entry** — recomputing the
  container CRC is a normal zip operation, so this is the gate to satisfy;
- the bootloader writes the Blackfin stream through `FUN_82823ebc`, which selects its base from a flag byte
  (**`0x50000` or `0x10000`**), writes an `0xc`-byte record at `0xb004` and a 2-byte record at `0xd000`, and
  logs `bootloader: wrote bootloader to …` (upgrade.cpp lines `0x306` and `0x317`). Those two addresses are the
  boot stream's own header slots, which is why they are written separately from the payload.

### The component updater orchestrator, decompiled [FW]

The PSoC component's updater is `FUN_82823854` and it shows what a component install actually is — useful
before attempting one:

```c
/* wait for the PSoC to be in its bootloader */
iVar7 = 3;
while (true) {
  func_0x11a03ddc(&ctx);  func_0x11a0452c(&ctx, 0x29, 0);
  FUN_11a001f6(1000000);                       /* ~1 s settle */
  if (FUN_8282033a(DAT_11804904, 0) != 0) break;   /* bootloader present? */
  if (--iVar7 == 0) { log("PSoC doesn't seem to be in bootloader …", upgrade.cpp 0x215); break; }
  log("PSoC doesn't seem to be in bootloader …", upgrade.cpp 0x219);
}
/* send the image through the generic file-send engine, with a callback table */
local_164 = &LAB_82823634;                     /* progress callback */
local_168 = &PTR_LAB_8283761c;                 /* the sender's vtable    */
iVar7 = FUN_8280354c(0, file, &DAT_82835cb0);  /* the transfer itself    */
if (iVar7 != 0) { FUN_828233b6(); iVar1 = 4; } /* map the 16-code CYACD status */
/* on success: keep a retained copy of what was installed */
FUN_82821b9e(file, "/yaffs2/last_upgrade/firmware/psoc_keyboard/…", 1);
```

and the progress callback is where the row numbering comes from:

```c
void FUN_82823634(undefined4 ctx, int row)
{
  if (row == 0x1ff) FUN_8281dc14();            /* 511 = the FINAL row */
  else              FUN_8281dba8(DAT_8283d9d8, DAT_8283d9dc);
  log(upgrade.cpp, 0x1ab, "psoc upgrade row %u", row);
}
```

The updater's own CYACD parsing and its **wire protocol** are documented in doc `07` §7.4 — including the
fact that the bootloader accepts a **second, TE-authored extension `.cyacd2`** alongside `.cyacd`
(`FUN_82803efc` dispatches on the suffix), which no shipped component here uses, and that the packets it sends
to the PSoC are Cypress-format: **`0x01` SOP, command byte, 16-bit LE length, payload, 16-bit LE checksum,
`0x17` EOP**, with a checksum selected at runtime between **SUM** and a **reflected CRC-16/`0x8408`**. The
per-row payload limit comes from the PSoC's own metadata struct rather than a constant. The updater drives
**15 distinct command bytes** (`0x31`–`0x3B`, `0x44`, `0x49`, `0x4A`, `0x4C`, `0x4D`), enumerated from the
packet builders in doc `07` §7.4 — including `0x3B` with no payload at all and `0x37`/`0x4D` with
variable-length payloads. The numeric ones are named by Infineon's published bootloader spec, and **every
decompiled packet and response size matches it** (`0x31` Verify Checksum, `0x32` Get Flash Size, `0x33` Get App
Status, `0x34` Erase Row, `0x36` Set Active App, `0x37` Send Data, `0x38` Enter Bootloader, `0x39` Program Row,
`0x3A` Verify Row, `0x3B` Exit Bootloader). Notably the OP-Z **never** issues `0x35` Sync Bootloader or `0x3C`
Get Metadata, and the letter commands `0x44`/`0x49`/`0x4A`/`0x4C`/`0x4D` are outside that documented set — they are a **second
bootloader dialect** driven by their own session routine, whose replies must begin with the `@EIV:` banner (doc
`07` §7.4).

Two details worth keeping: the **final row is `0x1FF` (511)** — exactly the last row present in the shipped
`.cyacd` files, which is an independent confirmation of the row range in doc `07` §7.4 — and a failed install
reports code **`4`** after the status mapper runs, while a failed *retained copy* reports **`6`**. The
orchestrator also posts an 11-byte message (`FUN_82822f48(&ctx, 0xb, buf)`) at the end, which is how the rest
of the system is told the component install finished.

## 3.4 The component vocabulary and install result strings [FW]

From the bootloader's `upgrade.cpp` region:

```
module    content    bootloader    keyboard        (component names)
resumed   started    (force)                       (log prefixes)
Already installed
Completed successfully
[extract]    [content]    [module]    [nordic]    [bootloader]    (log tags)
```

Error vocabulary — **the full set of install failure reasons**:

```
The provided key does not match the expected value
The verification of flash failed
The amount of data available is outside the expected range
The data is not of the proper form
The command is not recognized
The expected device does not match the detected device
The bootloader version detected is not supported
The checksum does not match the expected value
The flash array is not valid
The flash row is not valid
The flash row is protected and can not be programmed
The application is not valid and cannot be set as active
The application is currently marked as active
An unknown error occured
File is not accessable
Reached the end of the file
The bootloader is not ready to process data
The operation was aborted
```

### These are the Cypress PSoC status codes, and the mapping is fully recovered

That list is not prose — it is the **CYACD / PSoC bootloader status enumeration**. The decoder is
`FUN_828233b6` in the bootloader, and it decompiles cleanly:

```c
void FUN_828233b6(uint param_1)
{
  uVar1 = param_1 & 0xff;
  if ((param_1 & 0x4000) == 0) {          /* <-- bit 0x4000 selects which of two tables */
    pcVar2 = s_unknown_error_82837744;
    if (uVar1 != 0) {
      pcVar2 = s_File_is_not_accessable_82837f94;   /* default for this table */
      switch(uVar1) {
      case 1:  /* File is not accessable */
      case 2:  pcVar2 = s_Reached_the_end_of_the_file…;
      case 3:  pcVar2 = s_The_amount_of_data_available_is_o…;
      case 4:  pcVar2 = s_The_data_is_not_of_the_proper_fo…;
      case 5:  pcVar2 = s_The_command_is_not_recognized…;
      case 6:  pcVar2 = s_The_expected_device_does_not_mat…;
      case 7:  pcVar2 = s_The_bootloader_version_detected_i…;
      case 8:  pcVar2 = s_The_checksum_does_not_match_the_e…;
      case 9:  pcVar2 = s_The_flash_array_is_not_valid…;
      case 10: pcVar2 = s_The_flash_row_is_not_valid…;
      case 0xb:pcVar2 = s_The_bootloader_is_not_ready_to_p…;
      case 0xc:pcVar2 = s_The_application_is_currently_mar…;
      default: pcVar2 = s_The_operation_was_aborted…;   /* 0xff, else unknown_error */
      }
    }
  } else {                                 /* (param_1 & 0x4000) != 0 -- row-programming table */
    pcVar2 = s_Completed_successfully…;    /* status 0 = success */
    switch(uVar1) {
    case 1:  pcVar2 = s_The_provided_key_does_not_match_t…;
    case 2:  pcVar2 = s_The_verification_of_flash_failed…;
    case 3:  /* amount of data … */
    case 4:  /* data not of proper form */
    case 5:  /* command not recognized */
    case 6:  /* expected device mismatch */
    case 7:  /* bootloader version not supported */
    case 8:  /* checksum mismatch */
    case 9:  /* flash array not valid */
    case 10: /* flash row not valid */
    case 0xb:pcVar2 = s_The_flash_row_is_protected_and_c…;
    case 0xc:pcVar2 = s_The_application_is_not_valid_and…;
    case 0xd:pcVar2 = s_The_application_is_currently_mar…;
    case 0xe: /* unknown_error */
    case 0xf:pcVar2 = s_An_unknown_error_occured…;
    }
  }
  /* the two tag strings are "[bootloader]" vs a bare form */
  pcVar3 = (param_1 & 0x4000) ? s__bootloader__82837754 : &DAT_82837764;
  FUN_828229da(s____src_upgrade_upgrade_cpp_82837ca8, 0x104,
               s_psoc_error___d__s__s_82838010, param_1, pcVar3, pcVar2);
  …
}
```

What this establishes:

1. **The keyboard module is upgraded over the CYACD protocol**, and the bootloader implements a CYACD
   **host**: it receives status bytes from the PSoC and translates them to log text. The log format
   string is `psoc error: %d,%s,%s` at `0x82838010`, logged from **`upgrade.cpp` line `0x104` (260)**.
2. **Bit `0x4000` of the status word is a table selector**, not an error flag. With it clear, status `0`
   means nothing was reported and status is a *general* error; with it set, status `0` means
   **`Completed successfully`**.
3. The two tables share most codes but differ in the upper range — in particular `0x0b` is
   *bootloader not ready* in the general table versus *flash row protected* in the row table, and `9`
   resolves to `The flash array is not valid`/`local_10` in both. So a naive reading of one table would
   misreport the other.

This supersedes the earlier note that these were "the full set of install failure reasons". They are the
**PSoC protocol's** status vocabulary, surfaced through the installer's logging — which is a materially
more useful fact, because it means the CYACD handshake between the Blackfin and the keyboard PSoC can be
decoded with these tables.

## 3.5 Module communication [FW]

```
failed to read factory data from flash
failed to parse data from keyboard
failed to communicate with keyboard
failed to parse data from ble
failed to communicate with nordic
```

Plus `smx set Ilim callback: %dmA` and `smx session active callback: %d` **[FW]**, which are the SMX USB
stack's power/session hooks (see `ext/smx_usb/` in the format doc). Type `0x32` is the companion-module
comms command, and these strings are its failure modes.

## 3.6 The overlay problem, and how to work with the bootloader code

**This was the blocker for most of this document, and it is now solved — recorded here so the next
person does not lose the same time.**

The bootloader's L1 instruction code is **present** in `bootloader.ldr`, but Ghidra imports it into
**separate overlay address spaces**:

```
block7   block7::11a00000 - block7::11a0017f   size=0x180   overlay=true
block8   block8::11a00180 - block8::11a04f5b   size=0x4ddc  overlay=true
block3   11a00000         - 11a0100f          size=0x1010  overlay=false
```

The plain (non-overlay) space holds only `block3` (`0x11a00000`-`0x11a0100f`, the reset/startup code I
verified instruction-by-instruction) plus `block9`. So:

- Reading `0x11a02608` in the **plain** space fails with
  `MemoryAccessException: Unable to read bytes at ram:11a02608`.
- The **same address** is fully present in `block8::`, and the bytes there are real code
  (`20 91 79 60 c8 55 0f 0c 06 10 15 60 …`).

The cause is the `.ldr` container's structure: `bootloader.ldr`'s second top-level block is itself a
**multi-level boot stream**, and its `count` field covers only the first child subtree
(`0x2e8c`), while a following child (`dest=0x11a00180`, `count=0x4ddc`) extends past that span. That is
why a hand-written walker mis-parses it while the Blackfin+ loader handles it correctly. **Do not
hand-roll this container; let the loader do it.**

The consequence of the overlay is that the code is analysable but the *string cross-references do not
resolve as scalar immediates*. The technique that works instead:

1. Run full analysis on the imported bootloader (11 s; yields **1,389 functions, 47 in the overlay**).
2. Use Ghidra's **reference manager** over an address *range*, not scalar-immediate matching:
   `rm.getReferenceDestinationIterator(new AddressSet(lo,hi), true)`. Querying the range
   `[0x82837ddc, 0x82837dfc]` immediately returns the two DATA references from
   **`FUN_828233b6 @ 0x828233b6`** that made §3.4 possible.

Scalar-immediate searching — the method that worked so well on the OS image for the hidden command
dispatcher — **returns zero hits in the bootloader** for these strings, because the references are
stored as data words, not materialised by `LdImmToReg`. Chasing that dead end was the single biggest
cost of this section.

### Still open

The bootloader's own **console command dispatch** (the `0x00`/`0x02`/`0x19`/`0x35` handlers) has not yet
been located. The strongest lead is the **21-entry jump table at `0x82836c14`** — 21 entries pointing at
`0x11a02608`, `0x11a02698`, `0x11a026a4`, … — sitting in `block35`, immediately adjacent to the
`..\src\serial_command_handler.cpp` string at `0x82836d78`. A 21-entry table next to the handler's source
path is very likely the sub-command table, but the targets must be dereferenced **in the `block8::`
overlay space** and matched against the 20 documented command types. That is the next concrete step.

*(The OS image needs none of this: it decompiles in the plain space, 1,993 functions, which is why
`04-hidden-features-and-easter-eggs.md` rests on source-level evidence.)*
