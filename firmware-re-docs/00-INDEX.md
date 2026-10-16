# OP-Z Firmware Reverse Engineering — Findings

Reverse engineering of the **decrypted** Teenage Engineering OP-Z firmware (1.2.45) using Ghidra
12.1.4 with the `Ghidra-BlackFinPlus` extension, which ships the `Blackfin+ Boot Stream` loader and
the `blackfinplus:LE:32:default` processor language.

Everything here is derived from the decrypted image — no device access required, no writes performed.

## Source material

Decrypted with the recovered AES key; the archive is `z_firmware_1_2_45_decrypted.zip`:

| member | size | what it is |
|---|---|---|
| `firmware/blackfin/bin/opz.ldr` | 828,136 B | the OS / application image — **1,993 functions recovered** |
| `firmware/blackfin/bin/bootloader.ldr` | 257,644 B | the bootloader — serial console, updater, NAND |
| `firmware/blackfin/system/content/engines/*.engine` | 8 files | factory engines |
| `firmware/nordic/bin/nrf52832_opz.bin` | 80,972 B | BLE companion image (Nordic nRF52832, loads at **`0x23000`**) |
| `firmware/psoc_keyboard/bin/*.cyacd` | 2 files | keyboard/PSoC firmware (CYACD format) |

`firmware/versions.txt` records the release composition:

```
ble        1.1.9   from 02dec6f8c027e7fb8d14a02a2a80d69bfc0875ac
bootloader 1.1.35  from 9094de8ca5689feb4bf30c59292fcec3133374d0
blackfin   1.2.43  from c7df33fcaa98c2a64f0a577647a2e3cca92313bb
engines    1.2.38  from 6847c866c6116a0ac303ba75e206121a9d4c75fd
keyboard   1.2.26  from 4ec16d959751740e9a088c2e9e51d2f35d5e50aa
```

## Findings documents

| doc | contents |
|---|---|
| `01-ldr-format-and-image-layout.md` | the ADI `.ldr` container format, how to locate the images, the memory maps, and the full source tree (75 files) |
| `02-string-and-symbol-inventory.md` | rodata inventory: boot stages, on-disk layout, plug schema keys, USB identities, crash-log ring |
| `03-serial-commands.md` | the serial console: framing, the 21-command dispatch, reply types, and the update path |
| `04-hidden-features-and-easter-eggs.md` | the undocumented config command channel, debug hooks, and the OP-1 patch rejection |
| `05-midi-sysex-and-config.md` | the MIDI SysEx surface: message classes, the opcode map, the ring-buffer geometry and accessors, and `config/midi.json` |
| `06-rtos-and-system-services.md` | the two-RTOS architecture (uC/OS-III + SMX), named tasks, the labelled mutex inventory, power management and the CRC paths |
| `07-companion-processors.md` | the other two CPUs: the nRF52832 BLE image (load base corrected, dispatcher and transport decompiled), its protobuf descriptor with hash + 64-byte signature, the PSoC 5LP power/USB-PD controller (CYACD format, 387 functions, two-level dispatch), and the **`.engine` container + module ABI** |
| `08-colour-slots-and-light-flush.md` | the light-slot engine: 5-byte RGBA+mode slot records, the two-variant 20-entry palette and its interpolating lookup, the three parallel buffers, the change-only packet builder with its 60-tick blink phase, and the **Blackfin→PSoC type `0x10`** transport it leaves on |

## Headline findings

1. **The OS image decompiles.** 1,993 functions in `opz.ldr`, 1,389 in `bootloader.ldr` (47 of them in
   overlay address spaces), 342 in the nRF52832 BLE image and 387 in the PSoC image — **4,111 functions
   across four CPUs**. The rodata retains 75 original source paths under `C:\snake-software\`, which is what
   makes the architecture readable rather than guessed. See doc `01` for the container and memory map and
   doc `07` §7.2 / §7.4 for the two companion images.

2. **An undocumented text command channel exists in the OS**, carried in SysEx-like MIDI messages inside
   `FUN_80040922`. Carrier frame: `F0 00 20 76 01 62 <~len & 0x7F> <text ≤31 chars>`. It drives debug and
   mode globals directly — `enable-debug`, `enable-verbose-log`, `enable-controller-mode`, `enable-battery-log`,
   `enable-uart-log`, `debug-crash`, `debug-save`, plus `restart-into-bootloader`, `restart-into-synth` and
   `restart-into-content`, the last of which even writes the `/yaffs2/contentmode.plz` marker so content mode
   can be entered in software.
   See doc `04` §4.1 for the carrier frame and the full command table.

3. **The serial console handler is decompiled** — `FUN_block8__11a02932`, dispatching 21 command codes
   (`0x00, 0x02, 0x06, 0x07, 0x10, 0x11, 0x14, 0x15, 0x17, 0x19, 0x21, 0x23, 0x27, 0x29, 0x31, 0x32, 0x34,
   0x35, 0x37, 0x39, 0x3b`) through a 21-entry jump table at `0x82836c14`, with **every reply emitted as
   `command + 1`**. Framing note that cost real time: the frame header is emitted **raw** and only the payload
   is escaped.
  
  
  
   See doc `03` §3.1 (frame), §3.2 (dispatcher) and §3.6 (why the handler lives in an overlay).

4. **The CYACD status protocol is decoded** — `FUN_828233b6` maps a 16-code Cypress status word through two
   tables selected by bit `0x4000` (bit clear = general errors, bit set = row-programming errors), logging
   `psoc error: %d,%s,%s` from `upgrade.cpp` line 260. This is why "The command is not recognized" is *not* a
   console message but CYACD row-programming status 5.
  
  
  
  
  
  
  
  
   See doc `07` §7.4d for the mapper and doc `03` §3.4 for the same status set among the install
   result strings.

5. **`0x34` is a Blackfin-reset primitive** (logging `blackfin reset was requested` from
   `serial_command_handler.cpp` line 757, resetting with argument `0x14` or `10` depending on the state byte),
   and **`0x31` is a RAM payload loader**: it accumulates bytes into a RAM buffer and on completion logs
   `RAM load complete: total size = %u` and signals status `0x02`. Load-and-run over the console needs no
   flash write. See doc `03` §3.2, the device-verified command table.

6. **The project is internally called `snake`** (`C:\snake-software\…`), built on Windows with the ADI
   toolchain, with the OS and bootloader sharing one tree as separate links of `src/shared`, and third-party
   `ext/yaffs2`, `ext/libaiff-5.0` and the licensed `ext/smx_usb`.
   See doc `01` §1.x for the source tree and doc `02` §2.5 for the plug/engine vocabulary.

7. **MIDI SysEx carries the console-style command surface over MIDI**, with three separate paths: a ranged
   opcode family into an engine queue, a second family into the file manager, and the discrete
   text/config/identity classes. The front end is a **standard MIDI stream parser** — a 4 KB staging buffer,
   an expected-length table per status byte, an inside-SysEx flag, a separate real-time path, and
   `Sysex message interupted. Read %d` / `Midi message too big. Ignoring.` / `unhandled common message 0x%02x`
   / `unhandled real_time message 0x%02x` diagnostics, fed on the USB side by a **4-byte USB-MIDI packet pump**
   (`UsbMidi.cpp`) with its own reassembly checks. Both MIDI ring buffers are documented to slot size and
   head/tail offsets, and an earlier conclusion that the opcode map was therefore "a dispatch map, not a usable
   command list" turned out to be **half wrong**:

   - **the file-manager half was retracted and is now enumerated.** A split-immediate scan of `0x81ADFF58`
     (not the reference manager, which had missed it) found the queue's **pop** at `0x801290c8` and its
     **consumer loop** at `0x80129c24`, which pops into a fixed global record at `0x81AE098C`, reads the opcode
     at `0x81AE0AC8` (`+0x13C`), serves **both roles** from one task (`ctx+0x1dc` server, `ctx+0x1dd` client) and
     runs per-role timer upkeep. Its opcodes are named from the firmware's own logs: `0x33` client heartbeat,
     `0x34` client request, `0x35` file request, `0x51` file-sync operation, `0x52` server heartbeat,
     `0x53` file part, `0x55` sync state — seven implemented types plus a distinct `0x60` class, with a 32-bit
     file id and a part number, and every other value in the window ignored. See doc `05` §5.3.2.
   - **the engine half holds, under the stronger method.** Re-running that split-immediate scan on both engine
     queue contexts gives six sites each, every one inside the pop, the push or the initialiser, with no
     unidentified function among them — so there is no hidden consumer for `0x00`–`0x1B`, and those opcodes stay
     unreachable in these images. See doc `05` §5.7.
8. **The OS runs two RTOSes at once** — uC/OS-III for the application and a vendored SMX stack for USB — with
   every task, mutex and semaphore **named in the binary**. The OP-Z can act as a USB *host* for audio
   interfaces, MIDI devices, hubs and FTDI gear, with an explicit downstream power budget.
   See doc `06` §6.1–§6.3 (tasks and synchronisers) and §6.4 (power sequence).

9. **Ghidra's Blackfin+ analyser swallows functions.** One `size=1` stub hid the entire Queue A pop. There
   are exactly 47 such stubs (46 in the L2 ROM library range, one at `0x80116b00`), so **"0 references" must
   not be read as dead code** without testing with a split-immediate search *against a control group*. The same
   lesson recurs on the BLE image, where the wrong load base cost seven phantom functions. See doc `05` §5.7
   and doc `07` §7.2.

10. **The archive carries three CPUs, not one**: the Blackfin OS + bootloader, an nRF52832 (Cortex-M4) BLE
    image, and a PSoC 5LP (Cortex-M3) power/USB-PD controller. The BLE descriptor carries a **32-byte hash and
    a 64-byte signature**; the PSoC uses the Cypress **CYACD** row format; and `opz.crc32` is a verified plain
    `zlib.crc32` of the whole `opz.ldr` file including its 16-byte header, so a repacked image can be
    re-stamped.
   See doc `07` §7.1 (identity files), §7.2 (BLE), §7.3 (its signed descriptor) and §7.4 (PSoC
   format).

11. **A raw-binary import with the wrong load base fails silently, and "it looks like code" is not evidence.**
    The BLE image loads at base **`0x23000`** (the standard nRF5 SoftDevice S132 v5 application base), not
    `0x20000`. The test that settles it is whether the image's own stored pointers resolve: at `0x23000`,
    197 literal-pool words point into the data/string region and **129 land exactly on a string start**,
    versus **0** at `0x20000` and a control maximum of 25. The earlier argument that `0x20000` was confirmed
    by an 8-entry pointer table resolving to `push {…,lr}` prologues is **retracted** — both candidate file
    offsets hold plausible prologues, so it proved nothing. Consequence: 342 functions instead of 318, and the
    BLE dispatcher comes out as one function instead of seven. See doc `07` §7.2.

12. **The "keyboard" PSoC is really the power, charging and USB-PD controller.** Reassembling the CYACD
    image at base `0x1900` gives 387 functions and a `..\PSOCCommon\` source tree containing
    `power_management.c`, `charger.c`, `pmic.c`, `flx6408.c`, `fusb302.c` and a full `FUSB302/core/PDPolicy.c`
    USB-PD stack with Apple VDM handling. It monitors the Blackfin and can reboot the system
    (`No BF pong, REBOOT needed!!`), negotiates a real USB-PD contract as source *or* sink, and owns the
    `ps*` power state machine. See doc `07` §7.4 — which also corrects a mis-attribution in doc `06`.
    **The assembled image is 2 bytes ahead of flash**: strip the first two bytes (or load the raw assembly at
    `0x18FE`), which takes the analysis from 203 to 387 functions. See doc `07` §7.4.

13. **The BLE message dispatcher is decompiled, and its 20 message types are identified by number.** One
    function, `FUN_00028aa4` (3,010 addresses), dispatching on the byte at record `+2` through a 129-entry
    jump table at `0x28af8`; 109 of 129 entries point at the function's own epilogue, so unhandled types are
    ignored. Notable: type `0x06` is the **power request** (sub-command `0x10` active / `0x12` standby / `0x14`
    off / `0x16` charging / `0x18` low battery), type `0x00` is **PING**, type `0x08` parses a `key:value;`
    serial-provisioning string, types `0x19`/`0x21` reach **Bluetooth Direct Test Mode**, and type `0x09`
    with the magic word **`0xBEBAFECA`** enables **factory mode** in software. Type `4` frames bypass the
    table and are routed into the BLE-OPZ companion channel, and types `0x11`/`0x12` are the raw
    staging/checksum path. The dispatcher has **no direct callers**: it is installed as a function pointer at
    SRAM `0x20006320` and invoked with `blx` by an event state machine
    (`FUN_00027688` → `FUN_00029bb4` → `FUN_0002894c` → `FUN_00027eb8`). That transport layer speaks the **same
    SER_MSG framing as the Blackfin** — `0xC0` SOF, `0x7D` escape XOR `0x20`, a `(length<<4)|destination`
    header with destination `3`, and a 32-bit id **allow-list** admitting only ids `4`, `8`, `17` and `0x13` for
    long frames. The link is an **interrupt-driven UARTE** (verified by the `0x40002000` base literal and the
    `RXD.AMOUNT` register at `+0x53C`, not merely by its log strings) and the two directions are deliberately
    asymmetric: a 32-byte input
    ring framed byte-by-byte into a 0x218-byte record, and a **1 KB output ring drained in ≤255-byte chunks**
    with `uart invalid addr` / `uart busy` / `uart forbidden` / `Failed to send to uart` as its error set. See doc `07` §7.2b–§7.2e.

14. **The BLE image's string pool *is* addressed by stored pointers** — the previous "unreachable" finding was
    a wrong-base artifact and is withdrawn (129 exact string starts at `0x23000`). Relatedly, the descriptor
    block at `SRAM 0x20004890` is named `SEGGER`/`RTT`/`Terminal` with two 2 KB buffers, so that FIFO is the
    **SEGGER RTT log pipe**, not the BLE-MIDI FIFO. See doc `07` §7.2.

15. **The engine modules are Blackfin+ relocatable modules with a five-function ABI.** All 21 `.engine` files
    share a container (payload length = file size − 16, magic `0xfeed0ad1 0xad1facef`, an export table of
    name/target pairs) and export exactly **`initModule`, `init`, `render` or `renderFX`, `onNoteOn`,
    `onNoteOff`**. That is where note events end up, and it is the second reason the ranged MIDI families'
    per-opcode semantics are not in `opz.ldr` — there is no command table in an engine to find. The container's
    two `0xadXX` header fields are **shown not to be checksums** (the `0xAD` byte is constant across all 21
    files; ~100 candidate checksums over eight regions matched at most one engine each), leaving a probable
    family/type code.
   See doc `07` §7.5 for the container layout and the module ABI.

16. **The PSoC's request → reply map is read out of the code.** Every handler builds its reply with
    `FUN_000140d4(length, type)`; where a dedicated reply exists the type is **request + 1** (18→`0x13`,
    128→`0x81`, 145→`0x92`), the same rule as the Blackfin console, with shared telemetry replies `0x26`
    (12 B), `0x28` (8 B) and `0x31` (6 B) reused by requests `37`/`60`/`67`. Type `128`'s status byte **echoes
    the incoming routing nibble**, confirming the nibble-packed header from a fourth image, and type `145` is a
    liveness/heartbeat message. See doc `07` §7.4c.

17. **The PSoC string pool is still not addressed by stored pointers** — tested, not assumed. In the
    PSoC image a naive raw-word search reports 412 hits (267 distinct), but only **9 of 924** strings actually
    start at a referenced address; the rest are 1-byte alignment artifacts. A 40× over-report if read naively.
    The reason is now explained rather than left open: the strings are reached **through the dispatch table**
    (146 entries, 39 implemented types, default `FUN_000047b4`), and the table is found from the dispatcher's
    own literal rather than by scanning. Type `0` dispatches a **second** time through a 6-entry sub-command
    table at `0x1adc0`, with its values coming from a 256-entry **piecewise-linear duty/brightness curve** at
    `0x1add8` (index 0 = off, ramp `0x083`→`0x3ff`, slopes 1 then 3, two unexplained `0x0001` exceptions). See
    doc `07` §7.4b/§7.4c.

18. **One power-mode enum is shared by all three CPUs, carried in both directions, and it now has names.**
    The Blackfin's `command_handler_kb.cpp` logs `PSOC requested SER_MSG_POWER_MODE_REQUEST_ACTIVE / _STANDBY /
    _POWER_OFF / _CHARGING / _LOW_BATT` plus `Unknown power mode requested: 0x%02x`, and dispatches byte
    `− 0x10` through a **9-entry table at `0x815C9754` whose shape is the mirror image of the PSoC's own table
    at `0x1ad50`** (same slots `{0,2,4,6,8}`, same odd-slot fallback). The PSoC's type-`20` handler is the
    *receive* path that sets its state byte; the Nordic BLE image handles the same five codes in its type `6`.
    The consequence is architectural: the PSoC's **power-off** and **charging** requests raise the OS's own
    restart/shutdown flag `DAT_81003e80` (the flag the hidden `restart-into-*` commands use), so **the
    power/USB-PD controller can command the main CPU to shut down and go to charging**.
    Separately, PSoC message type `112` with a 4-byte payload **`DE AD BE EF`** writes `0x05FA0004`
    (VECTKEY | SYSRESETREQ) to `AIRCR` — **a software reset by magic word**. See doc `07` §7.4c and doc `04`
    §4.6.

19. **The OP-Z drives DMX lighting, and the lighting rig is a *track you play*.** The sequencer's note
    dispatcher calls a DMX hook with the track and note; **track `14` is the lighting track**, where nine
    scale-spaced notes (**56, 58, 61, 63, 66, 68, 70, 73, 75**) select nine fixture/colour slots and the twelve
    notes between them are explicitly ignored — and every *other* note, including anything above the range,
    falls through to **index 0** because both switches initialise to zero before the case list (only those
    twelve values are ignored). The controller is a singleton at `0x81015e9c` initialised with
    sentinel fields and an 18-byte zeroed region, its colour modes are encoded by decomposing a packed value
    into up to four channel bytes, and profiles/fixtures come from `config/dmx.json`
    (`profiles`/`profile`/`fixture`/`channels`/`rgb`). **The firmware also ships the vendor manual for this
    feature** — `readme/how_to_dmx.txt`, which names the channel types (`red`/`green`/`blue`/`white`/`color`/
    `intensity`/`fog`/`knob1`-`knob8`/`on`/`off`/a fixed value), documents the `profiles` and `config` blocks,
    and its **mode-driven channel encoders** are decompiled (a reversed-bit 16-bit pack for mode 0, a 15-channel
    walk for mode 4, a slot getter keyed on the same `0xe` track index, and a fade counter), its controller API
    is located by call site (init / apply-with-enable / mode setter / colour encoder), its **mode numbers are the
    lighting animations** (the pump drives mode 13 with a 500-unit duration and an index, and the readme's
    "animation 14" note fits), and **the wire side is now read too**: the frame sender `FUN_8003ae20` fills a
    fixed buffer at `0x802d190` with a `00 06 <count LE16> 00` header, logs `Failed to write dmx data` at
    **`DmxController.cpp:620`** when the interface status `& 0x9e` is non-zero (the reference the earlier round
    could not find), and sends `count + 5` bytes in **56-byte blocks** through the generic 64-byte USB-block
    submitter `FUN_8000b55c`; the tick pump `FUN_8003af18` only runs while the device state byte `DAT_0801fa75`
    is `0x10`, arming a 100-tick and then a 10-tick period. The twelve notes §5.8 called *ignored* are the
    **preview-LED slots 1–12** (the nine fixture notes light no preview), and the fade routine's 5000-unit idle
    path is animation `1`, duration 200.
    states **up to 16 fixtures each with a preview LED**, and says the data leaves **through a USB DMX
    interface** — which is what doc `06`'s `USBH_FTDI232Mutex` is for. Note `fog` is *"triggered by animation
    14"*. See doc `05` §5.8, §5.8b and §5.8c.

20. **The firmware ships its own manuals, and they close gaps the decompiler could not.** The image contains
    `readme/how_to_dmx.txt` (DMX channel types, `profiles`/`config`, up to 16 fixtures, the USB-DMX output —
    doc `05` §5.8) and `readme/how_to_import.txt` (the per-type add/modify/remove chart, the **`rejected`**
    folder, **5** bounces, **ten** `projectNN.opz` projects, one pack per slot, `~`-prefixed 0-byte duplicates,
    and the vendor's own description of every `midi.json` key). The import readme's claims are cross-checked
    against the firmware's own path strings.

21. **The install integrity gate is the ZIP entry CRC — decompiled, not assumed.** The upgrade path's
    extractor (`FUN_block8__11a04ab6`, `upgrade.cpp`) checks each extracted file against the **CRC stored in the
    zip entry** and logs `[extract]: CRC check failed for %s (%d)` (line `0x3ac`); it does **not** validate the
    `.cyacd` per-line trailer — which its own parser nevertheless **decodes as ASCII hex** (`FUN_82803cf8` is the
    hex-digit decoder, with a 1536-byte line reader and a fixed 256-byte payload), and it accepts a second
    vendor extension **`.cyacd2`** that no shipped component uses (doc `07` §7.4). The packets it sends to the
    PSoC are Cypress-format — **`0x01` SOP, command, 16-bit LE length, payload, 16-bit LE checksum, `0x17` EOP** —
    with the checksum selected at runtime between **SUM** and a **reflected CRC-16/`0x8408`**, and the row size
    taken from the PSoC's own metadata. Its **15 command bytes** are enumerated from the packet builders, and the
    numeric half matches Infineon's published bootloader command set **in every packet and response size** —
    `0x31` Verify Checksum, `0x32` Get Flash Size, `0x33` Get App Status, `0x34` Erase Row, `0x36` Set Active App,
    `0x37` Send Data, `0x38` Enter Bootloader (6-byte key), `0x39` Program Row, `0x3A` Verify Row, `0x3B` Exit
    Bootloader — while `0x35` Sync Bootloader and `0x3C` Get Metadata are **never used**, and the letter
    commands `0x44`/`0x49`/`0x4A`/`0x4C`/`0x4D` fall outside that documented set. So a repacked
    `firmware_bin_only_with_bootloader.zip` must have
    correct per-entry ZIP CRCs, and the Blackfin stream writer selects its base from a flag byte (`0x50000` or
    `0x10000`) while writing an `0xc`-byte record at `0xb004` and a 2-byte one at `0xd000`. See doc `03` §3.3.

22. **The bootloader has a file-presence auto-install hook.** `/yaffs2/firmware_auto.zip` is checked at boot by
    `FUN_82824d46`; if present the bootloader installs it, **deletes it**, logs `Upgrade complete` and resets.
    No key combo, marker or version query gates the trigger, and the file is reachable from the update volume via
    a single zip entry named `../firmware_auto.zip` — so an update can be staged to install itself on the next
    boot. Payload validation and per-entry zip CRCs still apply. See doc `03` §3.3 and doc `04` §4.5c.

23. **The light engine is a slot table, a two-variant palette and a change-only companion flush.** Lighting
    state is a **5-byte record per slot** (four colour components plus a mode tag) in one global array at
    `0x802d3a4`, written by a small API (`FUN_8003d3be` raw, `FUN_8003d56e` / `FUN_8003d352` / `FUN_8003d3f0`
    palette-driven) where the second argument is a **colour-wheel index** (`value >> 4`) rather than a channel
    byte. The colour comes from **one 20-entry 4-channel palette at `0x81015fec`** read at `i` and `i + 10`: the
    two halves are identical **except at the two interpolated hues**, which have a brighter variant, and
    `FUN_8003d48a(index, component, level)` cross-fades between the halves on a **piecewise level ramp**
    (`< 0x40` bright, ramp to `0xc0`, then dim) before scaling by the level. The flush `FUN_8003d1e0` diffs the
    current table against a previous copy and emits only **changed** 6-byte records `00 <index> <c> 00 00 <c2>`
    into a packet buffer capped near `0xa0` bytes (max `0x9a` = 25 records), re-sending entries whose mode tag
    is `1` whenever a **60-tick blink phase** (counter modulo `0x3c` at `0x815c94b0`, phase = first half) flips.
    The ticker `FUN_801313f4` then sends the packet with the **shared L1-overlay companion sender
    `FUN_11a01d24(ctx+4, 0x10, …)`** — the same `0xffffffff, 0, 0xff, 0xff` tail the documented
    `Set button debounce` message uses, but message **type `0x10`** instead of `0x14`; the sender is used by
    **both** companion handlers (doc `04` §4.6b), so the receiver is *inferred* from the payload's shape
    (`..\PSOCCommon\leddriver.c`, doc `07` §7.4) rather than read from the call. When nothing changed it instead
    flips two **GPIO direction lines** (`FUN_8002b388`/`FUN_8002b3b6` write `REG_PORTA_DIR_SET`/`CLR` and
    `INEN_SET`/`CLR` with the `0x20`/`0x80` port stride). The DMX controller's own address is now read rather
    than inferred: `FUN_8003c5a4` ends with `DAT_81015e9c = param_1` and its single caller passes the literal
    `0x802d2f0`. See doc `08` §8.1, §8.3, §8.5 and §8.6.

24. **The Score context hides a signal generator and an audio routing switch behind a vtable slot.**
    `ScoreContext.cpp` installs a context vtable at `0x81113a98`, and one slot wraps a **numbered command
dispatcher** (`FUN_80123274`) gated on the Score context being active. Its codes include a **signal generator
with a 6 dB step attenuator** — the gain byte steps down from 0 dB in 6 dB increments, `… gain: %ddB` is logged
each time and below −59 dB the generator switches itself off — and a **two-position audio routing switch** that
rewrites four audio-graph connections (`0xc`→`6`/`7` with `6`/`7`→`10`/`11`, or `6`→`6`, `7`→`7` with `0xc`→
`10`/`11`) and flips a pair of **GPIO direction** lines with the same two helpers the light flush uses. Three
further codes toggle light slots 8–10 through the slot API of doc `08`, and the same file sends a 4-byte
**type `0x21`** companion message (`set mode %d %d %d %d`) and carries the string `send debug flags to psoc: %d`.
None of it appears in the official documentation. See doc `04` §4.6b.

## Confidence levels

Every fact in these documents is marked, implicitly or explicitly, as one of:

- **[FW]** — **statically recovered**: read out of the decrypted image (decompiled, disassembled, or decoded
  from bytes and tables).
- **[DEV]** — **device-measured**: observed on real hardware over the serial console, the update volume or the
  content volume.
- **[SPEC]** — **vendor-documented**: stated by the chip vendor's own documentation (for example Infineon's
  PSoC bootloader application notes, used to *name* the command bytes in doc `07` §7.4). Where the spec and the
  decompiled code disagree, the code wins and the disagreement is recorded.

Where a claim is inferred rather than read (for example the protobuf field *names* in doc `07` §7.3, or the
`0x18FE`/`0x1900` framing of the PSoC image), it says so at the point of the claim.

## Reproducing the analysis

```bash
# 1. decrypt (needs the recovered key)
uv run --script toolkit/opzrepack.py --source z_firmware_1_2_45.zfw \
    --key-file ~/.opz-decode/opz.key --decrypt-to /tmp/fw.zip
unzip -q -o /tmp/fw.zip -d /tmp/opz-fw

# 2. Blackfin OS + bootloader (loader and language auto-detected from the .ldr signature)
GH=/path/to/Ghidra_12.1.4/support/analyzeHeadless
$GH /tmp/opz-proj OPZ -import /tmp/opz-fw/firmware/blackfin/bin/opz.ldr
$GH /tmp/opz-proj OPZ -import /tmp/opz-fw/firmware/blackfin/bin/bootloader.ldr

# 3. BLE companion - base matters, 0x20000 gives confident nonsense
$GH /tmp/ble-proj BLE -import /tmp/opz-fw/firmware/nordic/bin/nrf52832_opz.bin \
    -processor "ARM:LE:32:Cortex" -loader BinaryLoader -loader-baseAddr 0x23000

# 4. PSoC companion - strip the leading 2 bytes first (doc 07 section 7.4)
python3 - <<'EOF'
import pathlib
raw   = pathlib.Path('SnakeKeyboardModule_DVT2.cyacd').read_bytes()
lines = [l.strip() for l in raw.split(b'\n') if l.strip().startswith(b':')]
rows  = {int(l[1:7], 16): bytes.fromhex(l[7:7+512].decode()) for l in lines}
img   = bytearray(512*256)
for r, d in rows.items(): img[r*256:(r+1)*256] = d
pathlib.Path('kb_DVT2_fixed.bin').write_bytes(img[0x1900:0x20000][2:])
EOF
$GH /tmp/kb-proj KB -import kb_DVT2_fixed.bin \
    -processor "ARM:LE:32:Cortex" -loader BinaryLoader -loader-baseAddr 0x1900
```

The Blackfin extension must be installed under `Ghidra/Extensions/Ghidra-BlackFinPlus`. Note that it is **not**
in the standard Ghidra distribution — without it the `.ldr` files do not import (Ghidra rejects the
`Blackfin:LE:32:default` language id, which is a different, ARM-like id that does not exist here). The two
companion images need no extension at all.

**The analysis scripts.** The six scripts the method notes in this document set rely on are in
`ghidra-scripts/` at the repository root, and they are all standalone `GhidraScript`s — no build step. Run any of
them with `-postScript <Name>.java <outfile> <args…>` and `-scriptPath` pointing at that directory; **use the
resolved (symlink-free) path**, because `analyzeHeadless` canonicalises the argument and then fails to match it
against the script path it printed:

```bash
GH=/path/to/Ghidra_12.1.4/support/analyzeHeadless
S=ghidra-scripts

# decompile functions by address (creates them if the region is unanalysed)
$GH /tmp/opz-proj OPZ -process opz.ldr -noanalysis -scriptPath $S \
    -postScript Decomp2.java /tmp/out.c 0x8003ae20 0x8003d1e0

# raw disassembly of a range, N instructions, following instruction lengths
$GH /tmp/opz-proj OPZ -process opz.ldr -noanalysis -scriptPath $S \
    -postScript DumpRange.java 0x8003ae20 60

# who calls this, and where is this function
$GH /tmp/opz-proj OPZ -process opz.ldr -noanalysis -scriptPath $S \
    -postScript CallersOf.java /tmp/callers.txt 0x8003c5a4 \
    -postScript FnAt2.java /tmp/fn.txt 0x8003ae60

# find a materialised address (the split-immediate scan) and map a region's log call sites
$GH /tmp/opz-proj OPZ -process opz.ldr -noanalysis -scriptPath $S \
    -postScript FindXImm.java /tmp/xref.txt 0x81015ccc \
    -postScript LogMap.java /tmp/logmap.txt 0x8012f1e4 0x8003a000 0x8003d800
```

The limits of each are stated where they are used — in particular `FindXImm` finds materialised addresses and
**never function calls** (doc `05` §5.8c, doc `08` §8.7), and `LogMap`'s line number is only correct when it is
read from the `LdImmToReg R1` that immediately precedes the call (doc `08` §8.8).

## Load bases

The thing that silently breaks a raw-binary import, so it is worth stating once:

| image | load base | how it was derived |
|---|---|---|
| `opz.ldr` | loader-supplied | Blackfin+ boot-stream loader |
| `bootloader.ldr` | loader-supplied | same |
| `nrf52832_opz.bin` | **`0x23000`** | `Reset` vector and 47/48 vector entries land in the image; 129 stored words land on exact string starts (0 at `0x20000`, control max 25) |
| keyboard `kb_DVT2.bin` | **`0x1900`** after stripping the leading 2 bytes (raw: `0x18FE`) | `Reset` = `0x1911` lands on `push {r4,lr}`; literal pools become 4-aligned; functions recovered go 203 → 387 |

## Verifying this document set

These documents are meant to be edited as the reverse-engineering continues, so the
mechanical invariants are checked by a script that ships with them:

```bash
python3 firmware-re-docs/check_docs.py              # exits non-zero on a problem
python3 firmware-re-docs/check_docs.py --self-test  # proves each check has teeth
```

It verifies: **code fences balanced** in every document, **the findings table matches the
files present**, **every headline item's `doc NN §x.y` pointer resolves to a real section**,
**no duplicate headline numbers**, and the **privacy invariants** (no unit serial, no quoted
private material, no 64-hex strings — a lone `.opz-decode/opz.key` *path* is reported as a
note, not a failure). `--self-test` seeds one fault of each kind into a throwaway copy and
fails if any goes undetected.

Prose §-references *inside* paragraphs are deliberately **not** machine-checked: they are
written four different ways in these documents (`doc 07 §7.4`, `` `07` §7.4``,
`§7.4c of doc 07`, and series such as `doc 07 §7.1, §7.2, §7.4`), and a resolver that has to
choose between two documents named in one sentence produced false alarms in both directions.
The rule that works when checking by hand is: *the §x.y belongs to the document whose token
is nearest it in the same sentence or table cell.*

## Repository note

`firmware-re-docs/` must be committed **by explicit path**, never with `git add -A`: the repository also
carries tracked private device data (for example `pulled/settings`), and a broad add risks committing it.
