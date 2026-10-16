# 07 — The companion processors: BLE and keyboard firmware

The `.zfw` archive carries **three** processors, not one. `opz.ldr` (Blackfin) is covered in docs `01`–`06`;
this document covers the two I had not analysed: the **Nordic nRF52832** Bluetooth chip and the **Cypress
PSoC 5LP** keyboard controller. Both are separate CPUs with their own firmware, and both formats are
documented here for the first time in this project.

```
firmware/nordic/bin/nrf52832_opz.bin    80,972 B   ARM Cortex-M4, BLE stack
firmware/nordic/bin/nrf52832_opz.dat       135 B   protobuf firmware descriptor
firmware/psoc_keyboard/bin/SnakeKeyboardModule_DVT2.cyacd  234,529 B   PSoC 5LP (Cortex-M3)
firmware/psoc_keyboard/bin/SnakeKeyboardModule_EVT4.cyacd  238,218 B   PSoC 5LP (Cortex-M3)
```

## 7.1 Version and identity files

| file | contents | note |
|---|---|---|
| `firmware/firmware.version` | — | overall image version |
| `firmware/versions.txt` | per-component versions + git hashes | see doc `00` |
| `blackfin/bin/os.version` | `1.2.43+0` | the Blackfin OS |
| `blackfin/bin/bootloader.version` | `1.1.35+0` | |
| `blackfin/bin/opz.crc32` | `2403806141` | decimal CRC32 of `opz.ldr` |
| `nordic/bin/nordic.version` | `1.1.9+0` | BLE |
| `psoc_keyboard/bin/keyboard.version` | `1.2.26+0` | keyboard |

Note the **`+0` suffix** on every version string: the version format is `major.minor.patch+build`, and the
`+0` build counter is what the bootloader compares when it reports `Already installed`.

### `opz.crc32` is a plain CRC32, verified

`opz.crc32` is a **decimal ASCII** string (`2403806141`), not four raw bytes — easy to mis-read. And it is
not a bespoke checksum: it is exactly `zlib.crc32` of the whole `opz.ldr` file.

```python
zlib.crc32(open('opz.ldr','rb').read()) & 0xffffffff   # -> 2403806141  ==  the file's contents
```

That is a verified match, and it means the OS image integrity check is a **standard CRC32 over the entire
file including its 16-byte container header** (the payload alone gives `1909867152`). So a repacked or
patched `opz.ldr` can be re-stamped by recomputing one well-known value — a materially useful fact for
anyone working on image modification.

## 7.2 The Nordic BLE image (`nrf52832_opz.bin`)

### Load base is `0x23000` — and getting this wrong fails *silently*

A plain ARM Cortex-M4 firmware with a standard vector table. The `SP` and `Reset` values are the key to the
load address:

```
[0x0000] SP    = 0x20010000      <- SRAM top, consistent with nRF52832 (64 KB RAM at 0x20000000)
[0x0004] Reset = 0x00032091      <- odd => Thumb
[0x0008] 0x000320B9   NMI
[0x000C] 0x000320BB   HardFault
[0x0010] 0x000320BD   MemManage
[0x0014] 0x000320BF   BusFault
[0x0018] 0x000320C1   UsageFault
[0x002C] 0x000320C3   PendSV
[0x0030] 0x000320C5   SysTick
```

Every handler sits at `0x320xx`, but the image is only `0x13c4c` bytes — so **`0x32091` cannot be an address
in a base-0 image**. Of the 48 vector entries, **47 are real code addresses only at base `0x23000`**: at that
base every one lands inside the image (`Reset` at file offset `0xf091`, which decodes to
`ldr r1,[pc,#0x18]; ldr r2,[pc,#0x1c]; ldr r3,[pc,#0x1c]; subs r3,r3,r2`). `0x23000` is the standard nRF5
SoftDevice S132 v5 application base, which is why it is a round number.

**The decisive test: do the image's own stored pointers resolve?** A raw-binary import is only correct if the
32-bit values in the code's literal pools are valid addresses *at that base*. Counting the stored words that
land inside the image's data/string region, and how many land exactly on the first byte of a string:

| base | words pointing into the data/string region | of those, exact string starts |
|---|---|---|
| `0x20000` | 49 | **0** |
| **`0x23000`** | **197** | **129** |
| random control (200 bases) | — | mean 0.835, max 25 |

129 exact string starts against a control maximum of 25 is not a coincidence: at `0x23000` the code really
does address the string pool. The literal word at vaddr `0x29034` is `0x35160`, and file `0x12160` is
`"Ping? Pong!"`; at base `0x20000` that same word, `0x35160`, is 5,460 bytes past the end of the file.
Corroborating absurdity at the wrong base: 40 of the 48 vector entries would point into printable ASCII.

**Retracting my earlier "independent confirmation".** Earlier versions of this section argued for `0x20000`
because the 8-entry pointer table at file `0x11b74` (contents `0x258a1`, `0x25881`, `0x25871`, …) resolves
there into `push {…, lr}` prologues. That argument was **worthless**: file `0x58a0` holds `10 b5 06 4c`
(`push {r4,lr}`) *and* file `0x28a0` holds `38 b5 0c 4c` (`push {r3,r4,lr}`) — both candidate offsets hold
plausible Thumb prologues, so "it looks like code" discriminates nothing. Only the string-pointer test
settles a load base.

**My first passes used base `0x0` and then `0x20000`, and neither failed — they succeeded wrongly.** At base
`0x20000` Ghidra reported 318 functions; the same import at `0x23000` reports **342**, because the literal
pool now resolves and the analyser stops inventing functions out of data. At `0x20000` the whole dispatcher
section was chopped into seven unrelated "functions" (§7.2b); at `0x23000` it comes out as the single function
it is. The lesson is worth stating plainly: a raw-binary import with the wrong base produces no error, only
wrong answers. **Require the stored pointers to resolve, and check `SP`/`Reset` against the image size.**

### Correct import command

```bash
analyzeHeadless <proj> <name> -import nrf52832_opz.bin \
    -processor "ARM:LE:32:Cortex" -loader BinaryLoader -loader-baseAddr 0x23000
```

No vendor extension is needed — this uses stock Ghidra ARM support, unlike the Blackfin images.

This is the chip that implements the BLE MIDI transport and the companion-module protocol (`0x32` in the
serial command set, doc `03`).

### It analyses immediately, and the result is substantively new

Analysis completes in **2 seconds** with **342 functions**, all in the correct region. I verified the import
end to end:

```
Using Loader: Raw Binary
Using Language/Compiler: ARM:LE:32:Cortex:default
FUNCTIONS = 342
```

The recovered strings turn the BLE chip from a black box into a documented component. What they establish:

**BLE-MIDI is implemented here, not in the Blackfin.**

```
MIDI INIT................
Failed to initialize MIDI ble fifo: %lu
BLE_MIDI:FAILED TO SEND OVER BLE: %d, len %d, r: %d (%d/%d)
BLE_MIDI: te_fifo_get failed :%d (%d/%d)
rwBLE_MIDI: invalid conn handle
Re-negotiating connection parameters for BLE-MIDI. Expected conn interval < %d, actual %d
```

So the OP-Z's BLE-MIDI goes through a **FIFO on the Nordic chip**, with an explicit connection-parameter
renegotiation because BLE-MIDI needs a short connection interval. That is the concrete constraint to know
if BLE-MIDI timing ever misbehaves.

**DTM mode — a Bluetooth Direct Test Mode implementation.**

```
DTM mode!                                     Enabled DTM mode
Enabled DTM cmd 0x%02x freq 0x%02x length 0x%02x payload 0x%02x
dtm_init() failed: 0x%08x                     dtm_set_txpower() failed
dtm_cmd() setup reset failed: 0x%08x          dtm_cmd() failed: 0x%08x
```

DTM is the **RF test interface** used for regulatory certification: it lets test equipment command the
radio directly (channel, length, payload pattern). Its full command path — init, TX power, setup reset,
cmd — is present with error reporting. This is a factory/test-only entry point and is worth documenting as
such: it is a *radio* control surface, not a user feature, and should not be exercised on a working unit.

**Factory mode, and the serial/identity exchange with the Blackfin.**

```
Enabling factory mode                    Not in factory mode.
Got serial %s from Blackfin (%s)         Wrote serial %s
Serial %s of incorrect length (%d)      hw_rev:%d;sw_rev:%s;serial:%s
opz metadata hw rev %d (%s)             opz metadata sw rev %s
opz metadata serial %s                  Failed to parse serial from %s
```

This is the other end of the identity exchange documented in doc `03`: the Blackfin's `0x07` metadata reply
carries `serial:%s;hardware_revision:%d;dsp_serial:%s`, and here the Nordic chip receives and writes that
serial. The `hw_rev:%d;sw_rev:%s;serial:%s` string is the shared serialisation form.

**A greeting/handshake protocol between the two chips.**

```
Sending greeting request      Got greeting request from 0x%02x
Got greeting reply            Unexpected greeting!
Ignoring message - too short  Unreasonable length. Resetting state.
Resetting state due to SOF. Current state %d
Ping? Pong!
process_sysex() couldn't obtain current MTU, using default one (%d)
```

`process_sysex()` on the Nordic side, plus `SOF` state-machine reset and an MTU-fallback path, shows the two
processors speak a **framed, length-checked protocol with a greeting handshake** — the same framing
philosophy as the serial console (doc `03`), implemented independently over UART.

**Power states are driven from the Blackfin.**

```
Got standby power request      Got active power request
Got off power request          Got charging power request
Got low battery power request
Entering standby / Entered standby / Resuming from standby / Finished resuming from standby
Wake-up pulse detected, resuming hardware
Failed to set up wake-up sensing. Error %d     Scheduling failure on wake-up pulse
```

Five power modes requested by the host, plus a **wake-up pulse** mechanism to resume the radio. This pairs
with the Blackfin's own `power_sleep()` and suspend sequence (`06-rtos-and-system-services.md` §6.4) — the
power architecture spans both chips.

**Buttons and factory commands.**

```
key0 pressed  key1 pressed  key2 pressed  key3 pressed
short press   long press
Handling USB_ID_GND command       Handling USB_ID_FLOAT command
Failed to clear USB_ID on SER_MSG_COMMAND_USB_ID_GND. Error %d
Show current state led            Enabling factory mode
```

`USB_ID_GND` / `USB_ID_FLOAT` are USB OTG role-selection commands the Blackfin sends over; `key0`-`key3`
with short/long press is the BLE module's own button handling (the OP-Z's side buttons), and there is a
`SerialMessageHandler` naming convention (`SER_MSG_COMMAND_*`) shared with the Blackfin code.

**SEGGER debug strings are present** (`SEGGER`, `Terminal`), which is the RTT/logging layer — expect SEGGER
RTT to be available on the Nordic chip for firmware debugging.

### The image's internal structure and its debug sentinels

The image splits into four regions, which is worth knowing before searching it:

| region | vaddr (base `0x23000`) | contents |
|---|---|---|
| vector table | `0x23000`–`0x233ff` | 47 real handlers, all at `0x320xx` |
| code | `0x23400`–`0x34b40` | 342 functions |
| descriptor/pool | `0x34b40`–`0x34c00` | **`0xdeadc0de` sentinels + a pointer table** (below) |
| string pool | `0x34c00`–`0x36c4c` | 126 strings ≥5 chars from file `0x11c00`, incl. all the DTM/factory text |

At vaddr `0x34b40` (= file `0x11b40`) there is a small structured region worth recording, because it contains
two things a future analyst needs:

**`0xdeadc0de` appears twice**, at `0x34b60` and `0x34b68`, each followed by a distinctive value
(`0xf11e01ff`, `0xf11e01fe`). `0xdeadc0de` is an explicit **debug sentinel** — these look like canary or
firmware-identity markers, and the two occurrences with adjacent counter-like values suggest a paired
slot/counter structure rather than padding.

**An 8-entry Thumb pointer table** at `0x34b74` (file `0x11b74`; all eight values odd). Its targets land on
plausible prologues at both candidate bases, so it does **not** discriminate the load base (see §7.2) — but
it does look like a **dispatch or ISR/message handler vector**, a natural place to trace the BLE chip's
message flow.

Immediately after it, at `0x34b94`, sits a compact parameter block that reads as configuration:

```
0x34b94: 0x1000   (4096)   <- a size, or a RAM/flash window
0x34b98: 0x4      (4)      <- a count
0x34b9c: 0x1      (1)
0x34ba0: 0x1      (1)
0x34ba4: 0x7D0    (2000)   <- a timeout/interval (2000 ms would be plausible)
0x34ba8: 0x7      (7)
```

And at `0x34bac` (file `0x11bac`) a **128-bit value**:

```
b4 e2 e9 30  34 07  4d 06  ab 50  5a 31 1d 8c a7 da
b4e2e930-3407-4d06-ab50-5a311d8ca7da     (as a UUID string)
```

A 16-byte value with the byte pattern of a UUID v4 (`4d06` in the version nibble position) sitting next to a
config block is a strong candidate for a **BLE service or characteristic UUID**. I have **not** confirmed
this against a GATT enumeration, so it is recorded as a lead with the bytes given — the exact value is
documented either way, which is what matters for anyone matching it against a live device.

### The string pool *is* addressed by stored pointers — the earlier "unreachable" claim is withdrawn

Earlier versions of this section said all the pool's strings were *not* referenced by any stored address. That
was an artifact of the wrong load base and is **withdrawn**.

At base `0x23000`, **197** stored 32-bit words point into the image's data/string region and **129** land
exactly on the first byte of a string, referencing **122 distinct strings** — against a control group of 200
random bases with a mean of `0.835` and a maximum of `25` (§7.2). The referenced set is exactly the behaviour
set: `main…main9`, `DTM mode!`, `Ping? Pong!`, `Got active power request`, `opz metadata hw rev %d (%s)`,
`uart busy`, the `BLE_GATT*` event log block, and so on. The call sites are therefore **findable by address
search**, which is what makes §7.2b possible.

One sub-hypothesis stays rejected: that the pool is reached as 16-bit offsets from a `0x10000` base. Its 16
"hits" all landed mid-string (`'ing.\n'`, `'ong!'`), the signature of accidental arithmetic. That rejection is
about the *mechanism*; the "unreachable" conclusion does not survive the base correction.

### The named SRAM channels, and the FIFO behind them

One real consequence of the corrected base: the literal pools now name SRAM structures. `FUN_0002bde8`
(vaddr `0x2bde8`) is a generic **ring-FIFO get** with three modes (single-span, wrapped-single-span, and a
looping multi-span copy), and its lazily-initialised descriptor block at `SRAM 0x20004890` is named:

```
descriptor +0x00 : "SEGGER"      +0x07 : "RTT"
descriptor +0x18 : "Terminal"    +0x1c : 0x20004000   (2 KB buffer)
descriptor +0x48 : "Terminal"    +0x4c : 0x20004800   (2 KB buffer)
```

So `0x20004000`/`0x20004800` are **SEGGER RTT / terminal log pipes** — this pairs with the `SEGGER` and
`Terminal` strings in the inventory, and it corrects an earlier guess of mine that this descriptor code was
the BLE-MIDI FIFO. The **`te_fifo` API the BLE-MIDI strings report on is a separate instantiation** of the
same idea (its errors are `BLE_MIDI: te_fifo_get failed :%d (%d/%d)` and `MIDI te_fifo_put failed`), so do not
assume the RTT descriptors are the MIDI ones.

The important part is that the descriptor shape is now known: `+4` data pointer, `+8` capacity, `+0xc` head,
`+0x10` tail, `+0x14` mode, at an `0x18` stride — the fields the get/put loops use.

### 7.2b The BLE message dispatcher, decompiled

At the correct base this is **one function**, `FUN_00028aa4` (vaddr `0x28aa4`, file offset `0x5aa4`, **3,010
addresses**) — the chip's entire incoming-message handler. At the old base the same bytes came out as seven
unrelated "functions" with a fabricated `switchD_00025af2` among them; that fabrication is why the previous
version of this section described a dispatcher that does not exist. The single-function recovery is the
clearest single sign that `0x23000` is right.

**Entry and dispatch** (decoded from the raw bytes, since this is the part analysis kept losing):

```asm
0x28aa4  push.w {r4,r5,r6,r7,r8,r9,lr}
0x28aa8  ldrb   r2,[r0,#2]        ; message type = byte at record+2
0x28aaa  mov    r4,r0             ; r4 = the message record
0x28aac  sub.w  r0,r2,#0x11
0x28ab0  cmp    r0,#1
0x28ab4  sub.w  sp,sp,#0x464      ; 1,124-byte frame
0x28aba  cmp    r2,#4
0x28abc  beq.w  0x28cfc           ; type 4 -> separate side path
0x28abe  ...                      ; types 0x11/0x12 -> 0x28d18 side path
0x28acc  add.w  sp,sp,#0x464      ; <-- THE EPILOGUE
0x28ad0  pop.w  {r4,r5,r6,r7,r8,r9,pc}
0x28ae4  ...
0x28aec  cmp    r2,#0x80          ; bounds check: valid types are 0..0x80
0x28aee  bhi    0x28acc           ; out of range -> epilogue
0x28af0  adr    r3,[0x28af8]      ; table base
0x28af2  ldr.w  pc,[r3,r2,lsl #2] ; jump to table[type]
```

So the dispatcher is also an **incremental byte-stream parser**: called with one byte at a time it appends to
the record's buffer until the count reaches the expected length, which is why the signature is
`(char *msg, uint byte, …)`:

```c
uVar13 = (uint)(byte)param_1[2];                       /* message type */
...
uVar9 = *(uint *)(param_1 + 0x208);                    /* count */
if (uVar9 < 0x1f8) *(char *)(param_1 + uVar9 + 0x10) = (char)param_2;
*(uint *)(param_1 + 0x208) = uVar9 + 1;
if (expected != uVar9 + 1) return;                     /* frame not complete yet */
switch (uVar13) { ... }
```

The record layout the body uses:

| offset | meaning |
|---|---|
| `+2` | **message type** — the switch index |
| `+4` | expected frame length |
| `+0x10` | payload buffer (capacity `0x1f8` = 504 bytes) |
| `+0x208` | write cursor / bytes received |
| `+0x210` | second cursor (used while resynchronising) |
| `+0x214` | short marker (checksum/length limit) |

The assembly target is a fixed **`0xF7`-byte staging buffer at SRAM `0x20006540`** (`memset(buf,0,0xf6)`), and
the frame's type byte lands at buffer `+6`. Framing state lives in a byte at SRAM `0x2000674c` holding
`0`/`1`/`2`; bytes `0xf0` and `0xf7` — **MIDI SysEx start/end** — drive it, and `(b & 0xf0) == 0xf0` with the
state already non-zero is treated as data. A length/checksum helper `FUN_00032a98(ptr,len)` runs before
dispatch and on failure logs `process_sysex() couldn't obtain current MTU, using default one (%d)`.

**The table.** 129 entries × 4 bytes at vaddr `0x28af8` (file `0x5af8`); all 129 values odd (Thumb), **21
distinct targets**, and **109 of the 129 entries share one target, `0x28acd`** — which clears bit 0 to
`0x28acc`, the function's own epilogue. **Unhandled message types are ignored, not handled by a default
body** (that is a correction to the previous version of this section, which credited the default with real
code). The 20 populated types are:

| type | handler role, read from the decompiled body |
|---|---|
| `0x00` | **PING** — logs `Ping? Pong!` |
| `0x02` | **identity request** — builds `hw_rev:%d;sw_rev:%s;serial:%s`, replies type `0x09` |
| `0x06` | **power request**, sub-command = payload `+0x10`: `0x10` `Got active power request`, `0x12` `Got standby power request`, `0x14` `Got off power request`, `0x16` `Got charging power request`, `0x18` `Got low battery power request` |
| `0x07` | second identity builder, replies type `0x08` |
| `0x08` | **serial provisioning** — `strtok`s the 32-byte payload on `";"`, splits `key:value` on `":"`, key `serial`; errors `Serial %s of incorrect length (%d)` and `Failed to parse serial from %s` |
| `0x09` | **factory-mode magic**: if the payload's first word is **`0xBEBAFECA`** it sets the factory flag and logs `Enabling factory mode`, otherwise it replies with sub-command `4` |
| `0x0b` | **greeting request** — `Got greeting request from 0x%02x`, replies type `0x0c`; a second greeting logs `Unexpected greeting!` |
| `0x0c` | greeting reply (`Got greeting reply`); completes the handshake when payload `+0x10 == 7` |
| `0x10` | **payload forwarding to the registered source**: if the source object at `0x2000664c` exists, `len < 3` logs `Ignoring message - too short`, otherwise the payload is copied into the source's buffer (`FUN_0002a298`) |
| `0x13` | **system command**, sub-command = record byte `+8`: `1` `Resetting system` (reply `0x14`, then reset), `2` `Got adv on`, `5` `Got disconnect`, `6` radio sleep, `7` connect-to-MAC (`CONNECT_TO MAC missing`, else 6 address bytes at `+0x11`), `8` `Handling USB_ID_GND command` (`FUN_0002605c(0x1d,…)`; failure logs `Failed to clear USB_ID on SER_MSG_COMMAND_USB_ID_GND. Error %d`), `9` `Handling USB_ID_FLOAT command`, `0x10` `Show current state led` |
| `0x19` | **DTM mode enable** — with payload `'/'` logs `Enabled DTM mode` (reply sub-command `0x40` vs `0x41`), then `FUN_00028a48(0,0x5f)` |
| `0x21` | **Bluetooth Direct Test Mode command** — 4 payload bytes drive `dtm_init()`, `dtm_set_txpower(4)`, `dtm_cmd()` setup-reset, then `dtm_cmd(freq,length,payload)`; success logs `Enabled DTM cmd 0x%02x freq 0x%02x length 0x%02x payload 0x%02x`, failures log `dtm_init() failed`, `dtm_set_txpower() failed`, `dtm_cmd() setup reset failed`, `dtm_cmd() failed` |
| `0x22` | **one-byte status query** (gated on the source pointer at `0x20005e97`): calls `FUN_00031fa0`, replies type `0x23` with sub `0x46`, or sub `0x45` carrying the returned byte |
| `0x24` | **LED control** — takes the low three bits of payload `+0x10`, passes them **bit-reversed** to `FUN_00027630` |
| `0x25` | setter — stores payload `+0x10` at SRAM `0x20003d30`, replies type `0x26` (sub `0x42`, `0x49` when accepted) |
| `0x27` | query, replies type `0x28` with 8 bytes |
| `0x29` | address-conditional query, replies type `0x30` (sub `0x22`, `0x87`); compares the first payload byte against `0xa1` |
| `0x32` | query, replies type `0x33` with 8 bytes |
| `0x34` | status reply type `0x35` carrying a byte from SRAM `0x20004df4` |
| `0x80` | **factory configuration** — outside factory mode logs `Not in factory mode.`, otherwise parses `key:value;` pairs out of 32 bytes with the same `";"`/`":"` splitter as type `0x08` |

**Two findings worth their own line.**

- **`0xBEBAFECA` is a factory-mode magic.** Type `0x09` with that 32-bit word in the payload flips the chip
  into factory mode in software; type `0x80` then writes the factory configuration. That is a complete,
  host-drivable provisioning path that appears in no user-facing tooling.
- **Bluetooth Direct Test Mode is reachable through this message path** (types `0x19` and `0x21`), not only
  through a debugger: a full `dtm_init` / `dtm_set_txpower` / `dtm_cmd` chain, so the radio can be put under
  external test control by whoever can send those frames. Treat it as factory/test-only.

**How this was verified.** Every claim above is from `FUN_00028aa4`'s decompilation at base `0x23000`, with the
log strings resolved by reading the contents of each literal-pool word (e.g. the word at vaddr `0x29034` is
`0x35160`, which is `"Ping? Pong!"`; the word at `0x296b4` is `0x35464`, which is
`"Got active power request"`). The 20 switch cases Ghidra recovers are exactly the 20 populated table indices
(`0,2,6,7,8,9,b,c,10,13,19,21,22,24,25,27,29,32,34,80`), which cross-checks the table walk against the code.

### 7.2c The two side paths, and a cross-check on the table walk

The dispatcher has two branches that bypass the table, and both are now read.

**Type `4` is a routing bypass, not a command.** Right after the type byte is fetched:

```asm
0x28cfc  ldr  r3,[0x0002901c]   ; 0x20006640 - a RAM slot holding a handler pointer
0x28cfe  ldr  r0,[r3,#0x0]
0x28d00  cbz  r0,0x00028ac0     ; not registered -> fall back to the buffered path
0x28d06  mov  r3,r1             ; r3 = the incoming byte
0x28d08  mov  r2,r4             ; r2 = the message record
0x28d0a  ldr  r1,[0x00029020]   ; 0x20006654 - the channel state
0x28d0c  bl   0x00029e88        ; hand the whole record to the registered handler
```

`FUN_00029e88` is the **BLE-OPZ channel**, not a MIDI decoder: its own log strings are
`BLE_OPZ: te_fifo_put failed :%d (%d/%d)` and it shares `process_log() couldn't obtain current MTU, using
default one (%d)`. So a type-`4` frame is forwarded into the OPZ/Blackfin module channel over BLE when that
channel has been registered at `0x20006640`, and is otherwise treated as ordinary buffered input. That is the
link between this dispatcher and the companion-module protocol in doc `03`.

**Types `0x11`/`0x12` are the raw accumulation / framing path.** They are taken before the table
(`type − 0x11 < 2`) and run the byte-staging state machine directly instead of a command body:

```asm
0x28d18  count = rec[0x208]
0x28d1e  count == 0 -> byte goes to SRAM 0x20006544
0x28d22  count == 1 -> byte goes to SRAM 0x20006545
0x28d26  otherwise  -> byte goes to 0x20006546 + rec[0x210], both cursors advance
0x28d50  if (b & 0x80) ...          ; framing/state transitions on 0xf0/0xf7
0x28d6a  bl 0x00032a98              ; length/checksum over the staged frame
0x28da2  if (state == 2) state = 0  ; release the frame
```

So `0x11`/`0x12` are **transport** types: their payload is reassembled into the `0x20006540` staging buffer
and length/checksum-validated, with per-byte state held at `0x2000674c` and the two cursors at record
`+0x208`/`+0x210`. They are the frames that the SysEx/`FUN_00032a98` machinery exists for.

**Cross-check that the table walk is right.** Table index `0` holds `0x28db7`; file offset `0x5db7` is
`add r6,sp,#0x248; memset(&local,0,0x218); FUN_0002ac9c(4,"Ping? Pong!")` — exactly the `case 0` body Ghidra
recovered. So the raw table indices, the decompiled `switch` cases and the resolved log strings all agree,
which is what lets the §7.2b table be trusted at the per-type level.

**Still not read:** the event handlers that *call* this dispatcher, and the `0x28cfc`/`0x28d18` side paths
beyond their routing role.

### 7.2d Who calls the dispatcher — the installation chain, and the SRAM map

`FUN_00028aa4` has **no direct callers at all**, which is why an earlier pass could not place it. The reason is
that it is invoked through a **function pointer in SRAM**. The chain is now verified end to end:

```asm
; FUN_0002894c(0x28aa5): register the handler
0x2894c   ...  *DAT_000289e0 = param_1        ; DAT_000289e0 -> SRAM 0x20006320

; FUN_00027eb8: the event state machine invokes it (three sites)
0x27f9e   ldr  r2,[0x281a8]                   ; &0x20006320
0x27fa0   ldr  r0,[0x281ac]                   ; the 0x218-byte record
0x27fa2   ldr  r2,[r2,#0x0]                   ; r2 = the registered handler
0x27fa6   blx  r2                             ; call FUN_00028aa4(msg)
...
0x28012   ldr  r2,[0x281a8]
0x28014   ldr  r0,[0x281ac]
0x28016   ldr  r2,[r2,#0x0]
0x2801c   blx  r2                             ; call FUN_00028aa4(msg, byte)
```

and the registration is performed while the link is being brought up:

| stage | function | what it does |
|---|---|---|
| app bring-up | `FUN_00027688` | calls `FUN_0002a6cc` (init the **MIDI FIFO**: `MIDI INIT................`, `Failed to initialize MIDI ble fifo: %lu`) and `FUN_00029bb4` (start the **OPZ link**) |
| link start | `FUN_00029bb4` | stores its three arguments into SRAM `0x20006544`, `0x2000664c`, `0x20006650`, calls `FUN_0002894c(0x28aa5)`, posts a 14/1/1 event, and on a stale-link window (`ticks - last > 0x8000`) posts an 11/2/3 event and logs **`Sending greeting request`** |
| registration | `FUN_0002894c` | writes the dispatcher pointer to **SRAM `0x20006320`**, sets its flags, and posts the link event parsed from the descriptor at `0x34f14` |
| invocation | `FUN_00027eb8` | event state machine; loads `0x20006320` and `blx`es it with the 0x218-byte record — passing the incoming byte in `r1` on one path, which matches the `(msg, byte, …)` signature recovered in §7.2b |

That is the same "handler installed at runtime and called through a slot" pattern as the Blackfin MIDI queues
(doc `05` §5.7), and it is why a static call-graph search for callers comes up empty on both.

**The BLE image's SRAM map, as far as the message path uses it** — all of these were read out of literal
pools, so they are addresses, not guesses:

| SRAM | role |
|---|---|
| `0x20006320` | **the registered message handler** (the dispatcher pointer) |
| `0x20006540` | 0xF7-byte frame-staging buffer (`memset(..., 0, 0xf6)`) |
| `0x20006544`, `0x20006545`, `0x20006546` | staging cursors for frame bytes 0, 1 and 2+ |
| `0x20006640` | the **type-`4`** forwarding target (the BLE-OPZ channel handler) |
| `0x20006644` | stale-link timestamp |
| `0x2000664c` | the current source/stream object (used by type `0x10` and the OPZ channel) |
| `0x20006650` | third link argument stored by `FUN_00029bb4` |
| `0x2000674c` | the SysEx framing-state byte (`0`/`1`/`2`) |
| `0x20004890` | SEGGER RTT / terminal FIFO descriptor block (§7.2) |

### 7.2e The BLE transport layer reuses the Blackfin's framing vocabulary

One layer below the dispatcher sits `FUN_00027eb8`, the **byte-level transport parser**. It shares the
Blackfin console's framing primitives (doc `03`) — `0xC0` start-of-frame, `0x7D` escape with XOR `0x20`, and a
following big-endian length — but it is **not byte-identical**: the Blackfin frame is
`C0 <routing> <type> <len_be32> <payload>`, while here the first header byte is *nibble-packed*
(`(length << 4) | destination`) and the type byte comes before the 4-byte big-endian field. So this is the
same framing *family* with a different layout, found independently in a second CPU — which is what makes the
shared `0xC0`/`0x7D` rules credible as a TE convention rather than a one-chip quirk.

Read off the decompile and its literals:

| element | value |
|---|---|
| byte source | a **32-byte ring** at SRAM `0x20005ee4` (`head & 0x1f`, data at `struct + 9`) |
| receive record | **0x218 bytes at SRAM `0x20006328`** |
| `0xC0` | **SOF** — zero the receive record, restart the state machine |
| `0x7D` | **escape** — the *next* byte is XORed with `0x20` (`uVar12 = uVar12 ^ 0x20`) |
| header byte | `(length << 4) \| destination`, destination must be `3`, else `Got unexpected destination 0x%02x. Ignoring.` |
| message id | next byte, must be `≤ 0x86`, else `Unreasonable length. Resetting state.`; stored at record `+2` |
| following 4 bytes | assembled **big-endian** into record `+4` (`<<24`, `<<16`, `<<8`, OR) |
| id allow-list | `(0x00020110 >> id) & 1` → **ids `4`, `8`, `17` pass**; plus `id == 0x13` handled separately, and any frame whose length is `< 0x1f` |
| out-of-frame byte | `Got unknown byte 0x%02x. Expecting SOF.` |
| completion | the registered handler is called by `blx`; on the long path, record `+0x208` (bytes received) is compared with record `+4` (expected) |
| transmit | the second half of the same function drains a **second ring** in the other direction |

Two things are worth singling out.

**The id allow-list is real and narrow.** Long frames are accepted only for ids `4`, `8`, `17` and `0x13` —
which are exactly the "special" types the dispatcher handles specially: `4` routes into the BLE-OPZ channel,
`8` is serial provisioning, and `0x11`/`0x13` are the raw staging and system-command paths (§7.2b/§7.2c).
Everything else must be a short frame (`< 0x1f`). That is a deliberate two-tier policy, not an accident of
the parser.

**The destination nibble is checked.** The header byte carries a *destination* in its low nibble and the
parser rejects anything other than `3` with an explicit log line, so the framing has addressing — consistent
with the Blackfin's routing byte (doc `03`), and further evidence that one TE transport protocol runs across
all three chips.

**The output half is now read too, and it is asymmetric by design.** `FUN_00027eb8`'s second half is the
*transmit* pump for the same link, and it is a different shape from the receive side:

| | receive | transmit |
|---|---|---|
| ring | **32 bytes** (`head & 0x1f`, data at `ctx+9`) | **1024 bytes** (`0x400` wrap, data at `ctx+9`) |
| unit | one byte at a time, framed into a 0x218-byte record | bulk chunks, clamped to **255 bytes** (`0xff`) per call |
| gate | framing state machine (`0xC0`/`0x7D`/length) | "at least **9** bytes queued" before it will start a frame |
| handoff | `blx` to the registered handler (`0x20006320`) | `FUN_00026a30(ctx, ring + head + 9, len)` |
| back-pressure | — | a **pending byte** at `ctx+2` while a chunk is in flight, and the return value means "more to send" |

The transmit pump is `FUN_00027e0c`, and it is named by its own error vocabulary — the whole reason it is easy
to identify:

```c
iVar2 = FUN_00026a30(ctx, ring + head + 9, len);   /* len clamped to 0xff */
if      (iVar2 == 0x00) *(byte *)(ctx + 8) = 0;                 /* done: clear pending */
else if (iVar2 == 0x10) log("uart invalid addr");
else if (iVar2 == 0x11) log("uart busy");
else if (iVar2 == 0x0f) log("uart forbidden");
else                    log("Failed to send to uart");
return more_than_a_chunk_remained;
```

So the Nordic's link to the Blackfin is a **UART** with its own 1 KB output ring and a 255-byte chunk limit,
and the submit function validates that the buffer is in RAM (`(addr & 0xe0000000) == 0x20000000`, i.e. the
easyDMA requirement) before accepting it — which is why `uart invalid addr` exists as a distinct error. The
four UART diagnostics (`uart invalid addr`, `uart forbidden`, `uart busy`, `Failed to send to uart`) are the
strings to grep for in a device log when the BLE chip cannot talk to the main CPU.

**That "UART" was an inference from the log strings, so I checked it against the hardware — it is a UARTE.**
The image contains the peripheral base as a literal at VA `0x26d14`: **`0x40002000`**, which is the
nRF52832's **UARTE0** instance. It is read by `FUN_00026be4`, the driver's completion/error handler, and the
register offsets it touches identify the block precisely:

```c
iVar1 = DAT_00026d14;                      /* 0x40002000 = UARTE0 */
if (*(int *)(iVar1 + 0x124) == 0) {        /* EVENTS_ERROR */
  if (*(int *)(iVar1 + 0x110) != 0) {      /* the driver's own pending/flag slot */
    *(undefined4 *)(iVar1 + 0x110) = 0;
    if ((byte)expected == (*(uint *)(iVar1 + 0x53c) & 0xff)) {   /* RXD.AMOUNT */
      ... clear the pending byte at ctx+0x17 ...
      (*(code *)ctx_record[1])(local_20, *ctx_record);           /* the registered callback */
```

`0x53C` is UARTE's **`RXD.AMOUNT`** register (the easyDMA byte counter), which is what makes this UARTE and
not a plain UART — a plain UART has `RXD` at `0x518` and no `AMOUNT` register at all. And the handler's job
closes the loop with the transmit pump: it clears the *pending* byte the pump sets while a chunk is in flight
and then invokes the registered callback, which is what re-enters the transport to send the next chunk. So the
link is **interrupt-driven UARTE with easyDMA**, not a polled port.

**Peripheral inventory of the BLE image**, as a by-product of that search — every absolute base in the
nRF52832 peripheral window that appears as a literal:

| base | block | refs |
|---|---|---|
| `0x40001000` | RADIO | 6 |
| `0x40002000` | **UARTE0** | 2 |
| `0x40003000` | SPIM0/TWIM0 | 2 |
| `0x40006000` | GPIOTE (+ a `0x6100`–`0x611c` pin-select run) | 6 |
| `0x40008000`, `0x40009000`, `0x4000a000` | TIMER0, TIMER1, TIMER2 | 2, 1, 1 |
| `0x4000c000` | TEMP | 1 |
| `0x40010000` | WDT | 5 |
| `0x40011000` | RTC1 | 6 |
| `0x4001a000` | NVMC | 1 |
| `0x4001b000` | PWM1 | 1 |
| `0x4001e000` | RTC2 | 1 |
| `0x4001f000` | I2S | 2 |
| `0x40000000` | POWER/CLOCK | 1 |

Read as "what the BLE chip drives", that is a **radio plus its own timers, RTCs, watchdog and GPIO, with a
UART back to the Blackfin**.

**Checked, because a 32-bit value in a code region can also be an instruction encoding.** All 38 occurrences
of these bases sit at addresses that are **outside every function body** in the analysis — i.e. in literal
pools, which are data by construction — so none of them is a coincidental instruction word. The `I2S`
reference is the one to still treat with care for a different reason: an SDK driver can be linked without ever
being used, so a peripheral constant shows the address is *in the image*, not that the block is driven at
runtime.

## 7.3 The protobuf descriptor (`nrf52832_opz.dat`)

135 bytes, and it decodes cleanly as **protobuf**. Structure:

```
f2 (bytes, 132)                       <- the descriptor message
   f1 (bytes, 62)                     <- firmware metadata
      .f1 varint = 1
      .f2 (bytes, 58)
         .f8  varint = 1              <- type / variant
         .f2  varint = 0x34 (52)      <- a size
         .f3  (bytes) = a501          <- flags
         .f4, .f5, .f6 varint = 0
         .f7  varint = 0x9e19c         <- offset or length
         .f8  (bytes, 36)             <- a 32-byte HASH (f8/08 03 12 20 + 32 bytes)
         .f9, .f10 varint = 0
   f2 varint = 0
   f3 (bytes, 64)                     <- a 64-byte SIGNATURE
```

Two fields stand out:

- **`.f8` carries a 32-byte digest** (SHA-256 length), nested under a sub-message whose field `0x42`
  contains `08 03 12 20` followed by exactly 32 bytes.
- **`f3` carries exactly 64 bytes** — the length of an Ed25519 or ECDSA-P256 signature.

So the Nordic image ships with a **hash and a detached 64-byte signature**, and the same descriptor
structure is what the bootloader would validate. This is a real, previously unrecorded piece of the
firmware-trust model: the BLE component is signature-checked, whereas (per doc `03`) the main `.zfw`
container is only **AES-encrypted with a key index byte**, not signature-verified.

## 7.4 The PSoC keyboard format (`.cyacd`)

**This is the Cypress CYACD row-based programming format**, and the layout is now fully recovered.

### File structure

```
line 0:  <silicon_id 8 hex><silicon_rev 2 hex><checksum 2 hex>
line N:  ':' <row 6 hex> <256-byte data as 512 hex> <trailer 6 hex>
```

Measured on both files:

| property | DVT2 | EVT4 |
|---|---|---|
| file size | 234,529 B | 238,218 B |
| header | `100A11A00000` | same |
| silicon id | `0x100A11A0` | same |
| rev / checksum | `00` / `00` | same |
| data lines | 445 | 452 |
| rows | 25 … 511 | 25 … 511 |
| rows missing | 42 | 35 |
| row data | 256 B each | 256 B each |

The header `100A11A00000` splits as **silicon id `0x100A11A0`**, **silicon revision `0x00`**, **checksum
`0x00`**. `0x100A11A0` is the PSoC 5LP device id.

### The trailer is not a plain CRC — and I tested it properly

Each data line ends in **6 hex characters** (3 bytes). The trailer is **not** a length field: its first two
hex characters take **168 distinct values** across the 445 lines (`00` ×66, `01` ×21, `04` ×12, `9A` ×9, …),
which rules out my first guess of a length-plus-CRC split.

I then tested the trailing bytes as a checksum against every combination of:

- **polynomials**: CRC-16/CCITT (`0x1021`), CRC-16/IBM/ARC (`0xA001`)
- **initial values**: `0x0000` and `0xFFFF`
- **scopes**: the 256 data bytes; the 4-byte row number + data; data + row number
- **simple forms**: single-byte sum, 16-bit sum, XOR

**All failed** on every row tested — and a later, wider sweep over all 445 DVT2 rows failed too: four
functions (byte sum, XOR, big-endian **and** little-endian 16-bit word sums) crossed with four regions
(`data`, `header+data`, `rownumber+data`, `data+header`) and six stored-value interpretations
(`trailer[0:2]` and `[1:3]`, big- and little-endian, plus `[0:3]`) produced **zero** combinations matching even
half the rows. So the trailer is not a linear sum of the row in any of those arrangements.

**The useful part is what the firmware does *not* do with it, which is now decompiled evidence rather than an
open question.** The OP-Z never validates the CYACD per-line trailer. What the upgrade path actually verifies
is the **ZIP entry CRC of every extracted file**, in the overlay routine `FUN_block8__11a04ab6`
(`upgrade.cpp`):

```c
iVar2 = FUN_82821ab4(auStack_c8, 0);            /* CRC of the extracted file            */
if (iVar2 == iStack_184) iVar1 = 0; else iVar1 = -0x69;
if (iVar1 != 0) log(upgrade.cpp, 0x3ac, "[extract]: CRC check failed for %s (%d)", name, iVar2 != iStack_184);
```

So a `.cyacd` is protected in transit by the **zip container's CRC**, then handed on as rows
(`psoc upgrade row %u`), and the row-level status comes back as one of the 16 Cypress codes (§7.4d) — including
`The checksum does not match the expected value`, which is a **Cypress bootloader** status, not an OP-Z one.
The trailer is therefore a Cypress-side construct: nothing in these four images computes or checks it, and the
`The checksum does not match the expected value` string is the OP-Z *reporting* what the PSoC's bootloader
said.

**How far that claim was checked, precisely.** I read three routines on this path: the zip extractor
(`FUN_block8__11a04ab6`, which verifies the entry CRCs), the PSoC updater's orchestrator (`FUN_82823854`, which
waits for bootloader mode, hands the file to the generic send engine `FUN_8280354c` with a progress callback,
maps the 16-code status table on failure and retains a copy in `/yaffs2/last_upgrade/…`), and that progress
callback (`FUN_82823634`, `psoc upgrade row %u`, final row `0x1FF`). None of them touches the line text. The one
place a trailer *could* still be inspected is inside `FUN_8280354c` and its callees — the generic send engine —
which I have **not** read line-by-line. So the accurate statement is: *no routine on this path that I have read
validates the trailer, and the only unread candidate is the send engine*.

**A third sweep tested the vendor's own documented row-checksum rule** — after the protocol specification
described in §7.4 was found to be the right family, the natural remaining hypothesis was its file-side rule:
`2's complement of (ArrayID + RowNum + Size + Data)` with the row number *big-endian in the file*. Tested in
~50 arrangements over all 445 rows (ArrayID present or absent, row big- or little-endian, three size forms,
and 8-, 16- and 24-bit complements), it produced **no 16-bit match at all** and only chance-level byte
coincidences (32 of 1335 byte slots). So the trailer is not the documented Cypress row checksum either.

**That closes the item in the only way it can be closed from these images**, and it is a better answer than
"unresolved": the algorithm is not needed to assemble, verify or install a keyboard image — build the rows,
recompute the **zip** CRC, and the device will accept it. I am still not guessing at the trailer itself, and
the reason is worth keeping: it is the kind of detail where a confident wrong answer costs someone else real
time, which is exactly what happened to me on the frame encoder in `FIRMWARE_ANALYSIS.md` §71.1.

**The bootloader's CYACD parser is now read, which sharpens the trailer question to "decoded but never
compared".** The parser is a small family of routines in `bootloader.ldr`:

| routine | role |
|---|---|
| `FUN_82803eda` | opens the file and remembers the handle in `DAT_82838f00` |
| `FUN_82803efc` | **extension dispatch** — finds the last `.` and compares the suffix against **`.cyacd2`** and then **`.cyacd`**; the `.cyacd2` branch decodes hex one byte at a time (`buf[0] << 4 | buf[1]`) and returns a distinct code when the decoded byte is `0x00` |
| `FUN_82803cf8` | **the hex-digit decoder**: `'0'`–`'9'` → `c-0x30`, `'a'`–`'f'` → `c-0x57`, `'A'`–`'F'` → `c-0x37`, anything else → 0 |
| `FUN_82803e46` | **line reader** into a **`0x600`-byte (1536) buffer**, then a walk of that buffer |
| `FUN_82804060` | field extraction (row number + payload) into an 800-byte record |
| `FUN_8280313a` | **the per-record step**: mode `0` → `FUN_82802b80(row, …, buf, …)` (the program path), mode `1` → `FUN_82802c4c(row, …)`, mode `2` → a third path |
| `FUN_828032c2` | the session state machine: enter bootloader (`FUN_828027c0`), setup (`FUN_82803648`), loop records, then finish/verify/reset (`FUN_82802a2e`, `FUN_82802d76`, `FUN_82802a94`) |

Two facts fall out of that which the format alone did not give:

- **The CYACD text really is parsed as ASCII hex** (`FUN_82803cf8` is an unambiguous hex decoder), and the
  **line buffer is 1536 bytes** — comfortably larger than a 525-character data line, *including* its 3-byte
  trailer. So the trailer **is read as text and decoded**, and only then is it not compared: no routine on the
  path I read (extractor, orchestrator, line reader, field extractor, per-record step) compares a tail value,
  and the row payload is taken as a fixed 256 bytes.
- **There is a second, TE-authored extension: `.cyacd2`.** The bootloader accepts it alongside `.cyacd`, with
  its own decode branch, so the format has a vendor variant that the shipped keyboard images do not use. That
  is a new lead worth remembering: a `.cyacd2` file exists in TE's toolchain even though the four images here
  contain only `.cyacd`.

**The wire protocol the updater speaks is now decompiled too** — and it is the Cypress bootloader packet
format, which is why the status vocabulary in §7.4d was recognisable. `FUN_82803726` is the packet finaliser:

```c
pkt[0]    = 0x01;                       /* SOP  */
pkt[1]    = cmd;                        /* command byte - 0x39 on the program path */
put_u16_le(pkt + 2, total_len - 7);      /* 16-bit LITTLE-ENDIAN payload length */
uVar2     = FUN_82803682(pkt, total_len - 3);
put_u16_le(pkt + total_len - 3, uVar2);  /* 16-bit LITTLE-ENDIAN checksum */
pkt[total_len - 1] = 0x17;               /* EOP  */
```

and `FUN_82803682(buf, len)` computes the checksum with **two selectable algorithms**, switched by the global
`DAT_8282d200`:

| `DAT_8282d200` | algorithm |
|---|---|
| `1` | **reflected CRC-16, polynomial `0x8408`, init `0xFFFFFFFF`, then complement **and** byte-swap** |
| otherwise | **two's complement of the byte sum** (`0 - sum & 0xffff`) |

and the published protocol explains what that global is: the bootloader's **checksum-type byte** — *"if this
byte is 0, the checksum is a basic summation; if it is 1, the checksum is CRC-16"* (AN68272). So
`DAT_8282d200` is the device's reported checksum type, not a local preference, and the updater follows it.

One discrepancy worth recording rather than smoothing over: the app note *describes* the CRC mode as
"CRC-16-CCITT, polynomial `0x1021`, init `0xFFFF`, no final XOR", whereas Cypress's own reference implementation
— and the OP-Z's decompiled `FUN_82803682` — use the **reflected** polynomial `0x8408` with init `0xFFFFFFFF`
and a final **complement plus byte-swap**. Those are the same CRC family in different conventions, and the
code is the authority here; anyone reimplementing should follow the decompiled form (which matches Cypress's
reference C source, including the `~crc` and the byte-swap), not the prose.

So the updater implements **both** Cypress checksum types with a runtime selector, and the packet framing is
`0x01` SOP, command, 16-bit LE length, payload, 16-bit LE checksum, `0x17` EOP — with `0x01`/`0x17` being the
Cypress bootloader's own start- and end-of-packet bytes. Two further details from the per-record path:

- **the payload size is not a constant**: it comes from the bootloader's own metadata struct —
  `*(short *)(DAT_82838df8 + 0x10) - 7` for the row split, and `- 10` for the packet — so the *device* tells the
  host how much fits in one row, and the host chunks accordingly (`FUN_82802af4` is that chunking loop);
- **rows below `0x40` (64) are erased before being written** (`if (row < 0x40) FUN_828026f4(row)` inside
  `FUN_82802b80`), which is why the shipped keyboard images start at row 25 and why the updater does not need a
  mass-erase step.

**The command set is enumerable from the packet builders themselves**, because every wrapper ends in a
`FUN_82803726(pkt, len, cmd)` call with the command byte as a literal. Walking the 17 call sites gives **15
distinct commands**:

| cmd | builder | packet | payload | expected response |
|---|---|---|---|---|
| `0x31` | `FUN_82803974` | 7 | **none** | 8 |
| `0x31` | `FUN_82803bf8` | 8 | 1 byte at `pkt[4]` | 8 |
| `0x32` | `FUN_828039c2` | 8 | 1 byte at `pkt[4]` | 11 |
| `0x33` | `FUN_82803a7c` | 8 | 1 byte at `pkt[4]` | 9 |
| `0x34` | `FUN_82803934` | 10 | byte + `u16` (`pkt[4..6]`) | 7 |
| `0x36` | `FUN_82803adc` | 8 | 1 byte at `pkt[4]` | 7 |
| `0x37` | `FUN_82803a32` | **`payload + 7`** | variable — the chunk splitter | — |
| `0x38` | `FUN_82803774`, `FUN_828037b6` | 13 with data / 7 without | optional 6-byte buffer | 15 |
| `0x39` | `FUN_82803876` | variable | row byte + `u16` + data from `pkt[7]` — the **program path** | — |
| `0x3A` | `FUN_828038d2` | 10 | 3 bytes | — |
| `0x3B` | `FUN_8280385a` | 7 | **none** | 7 |
| `0x44` | `FUN_82803bc2` | 11 | 4 bytes via `FUN_828036f2` | — |
| `0x49`, `0x4A` | `FUN_82803b12`, `FUN_82803b6a` | — | filled via `FUN_828036f2` | — |
| `0x4C` | `FUN_82803c1e` | 16 | 9 bytes: `pkt[4]` + 8 copied bytes | 7 |
| `0x4D` | `FUN_82803c58` | **`payload + 7`** | variable | 7 |

(The 7-byte minimum is the bare frame: 4 header bytes, 2 checksum bytes, 1 EOP byte.)

**The numeric half of that table can now be named, and the naming validates the decompilation.** Infineon's
published PSoC 3/4/5LP bootloader protocol (AN60317 / AN68272) defines exactly this command set, and **every
shape I decompiled matches it** — command byte, payload layout, packet size *and* response size:

| cmd | name [SPEC] | my decompiled shape | spec |
|---|---|---|---|
| `0x31` | **Verify Checksum** | 7-byte request, 8-byte response | no data in; 1 data byte out → 8-byte response ✓ |
| `0x32` | **Get Flash Size** | 1-byte payload, 11-byte response | array ID in; 4 data bytes out → 11 ✓ |
| `0x33` | **Get App Status** | 1-byte payload, 9-byte response | app number in; 2 data bytes out → 9 ✓ |
| `0x34` | **Erase Row** | 10-byte packet, 7-byte response | array ID + row `u16`; no data out ✓ |
| `0x36` | **Set Active App** | 8-byte packet, 7-byte response | app number in; no data out ✓ |
| `0x37` | **Send Data** | **variable, `payload + 7`** | N data bytes, chunked ✓ |
| `0x38` | **Enter Bootloader** | 13 bytes with a 6-byte buffer | 6-byte key; 8 data bytes out → 15-byte response ✓ |
| `0x39` | **Program Row** | byte + `u16` + data from `pkt[7]` | array ID + row `u16` + data ✓ |
| `0x3A` | **Verify Row** | 10-byte packet | array ID + row `u16` ✓ |
| `0x3B` | **Exit Bootloader** | 7-byte packet, no payload | no data ✓ |

That is eight independent agreements on packet *and* response sizes, including the 6-byte key on Enter Bootloader
and the array-ID-plus-row layout on Program Row — so the decompiled table above is corroborated rather than
merely plausible.

**Two documented commands are absent from the OP-Z's call sites**: `0x35` **Sync Bootloader** and `0x3C`
**Get Metadata**. The updater never resynchronises the session and never reads metadata — it opens with
`0x38`, queries flash size with `0x32`, erases rows below 64, programs, verifies and exits.

**The letter family `0x44`, `0x49`, `0x4A`, `0x4C`, `0x4D` is not part of that documented set** — and reading
its call graph says what it is instead. The five builders are driven by a **second session implementation**
(`FUN_828031ee` for `0x44`/`0x49`/`0x4A`, `FUN_8280341e` for `0x4C`, `FUN_8280326c` for `0x4D`) rather than by
the numeric session state machine, and their shapes are U32-argument commands:

| cmd | payload | evidence |
|---|---|---|
| `0x44` | one `u32`, via `FUN_828036f2` (a `put_u32_le` helper) | `FUN_82802ea2` |
| `0x49`, `0x4A` | two `u32`s | `FUN_82802dee`, `FUN_82802f04` — each **also runs the same chunking loop** as `0x37`/`0x39`, but with the limit at `device_max − 0xf` instead of `− 7`/`− 10` |
| `0x4C` | 9 bytes: one byte plus **two `u32`s split into 8 bytes** — a header field and the file's **accumulated 16-bit checksum** (identified below) | `FUN_82803030` |
| `0x4D` | a variable-length blob | `FUN_828030d0` |

And that second session **validates a response banner**, and its three callers show the family's structure:

```c
/* FUN_828031ee - one upload routine, three modes */
FUN_82804102(request, len, &hdr, buf, ...);
if (mode == 0)      FUN_82802dee(...);   /* the two-u32 chunked sender  -> command 0x49 */
else if (mode == 1) FUN_82802ea2(...);   /* single u32 argument         -> command 0x44 */
else if (mode == 2) FUN_82802f04(...);   /* the other chunked sender    -> command 0x4A */
if (ok && callback) callback(0, hdr >> 16);          /* streaming with progress */

/* FUN_8280341e - builds 0x4C's arguments from the file itself */
FUN_82803ff6(file, ...);                  /* parse the record header                 */
FUN_828028b8(param_4, f1, f2, &local_14, 0);
FUN_8280417e(&uStack_c, ..., file);        /* derive a value (checksum/length?)       */
FUN_82803030(uStack_15, uStack_c, 0);      /* command 0x4C <- (header field, derived) */

/* FUN_8280326c - the 0x4D path */
if (len < 5 || memcmp(reply, "@EIV:", 5) != 0) return 1;   /* banner required */
FUN_82803df0(len - 5, reply + 5, ...);     /* skip the banner, parse the rest         */
FUN_828030d0(hdr, buf);                    /* command 0x4D <- blob                    */
```

so the dialect reads as a **variant of the same Cypress protocol that is tagged with an `@EIV:` banner**: commands
`0x44`/`0x49`/`0x4A` are the three modes of one upload routine (single u32, and two chunked senders whose device
limit is `device_max − 0xf`), `0x4C` carries a **header field plus a value computed from the file**
(`FUN_8280417e` — identified below), and
`0x4D` sends a blob that arrived **behind the `@EIV:` banner**.

**What `0x4C` carries, and where the row size comes from, are now identified.** `FUN_8280417e` — the routine that
derives `0x4C`'s second argument — is a **whole-file pre-pass over the `.cyacd`**:

```c
uVar1 = FUN_8282b2cc(DAT_82838f00);              /* remember the file position */
*pOut1 = -1; *pOut2 = 0;
do {
  iVar2 = FUN_82803e46(&hdr, linebuf);           /* read a line (the 1536-byte reader) */
  if (iVar2 == 0 && *linebuf == ':') {           /* only ':' data lines                */
    iVar2 = FUN_82804102(hdr, linebuf, ...);      /* parse one record                    */
    if (*pOut1 != 0) *pOut1 = 0;                 /* clears a sentinel once data is seen */
    *pOut2 = in_stack_00000000 + *pOut2;         /* ACCUMULATE a 16-bit field per line  */
  }
} while (iVar2 == 0);
if (iVar2 == 2) iVar2 = 0;                        /* 2 = end of file                     */
if (iVar2 == 0) FUN_8282b2b4(DAT_82838f00, uVar1, 0);   /* seek back                   */
```

so `0x4C` announces **(a header field, the sum of the per-line 16-bit parser output over the whole file)** — an
**expected-checksum announcement** sent once, before the streaming commands. It is the letter dialect's counterpart
of the numeric dialect's `0x31` Verify Checksum.

And `FUN_828028b8` explains where the **row size** used by every chunking loop comes from: it zeroes a **64-dword
block at `0x82838dfc`**, stores the new metadata pointer into **`DAT_82838df8`**, dispatches through the first dword
of its argument (`(*(code *)*param_1)()` — a vtable-style call), and then calls `FUN_828037b6`, the **`0x38` Enter
Bootloader** builder. So the order is: reset the device-info block → enter the bootloader with the 6-byte key →
read the limits back out of that block; `device_max − 7` / `− 10` / `− 0xf` in the chunk loops are fields of it.

So the letter commands belong to a **different bootloader dialect**, one that
identifies its messages with an `@EIV:` tag — the most plausible target being the plug-in **module**, which this
same updater family carries as `module.cyacd` alongside `module.type`/`module.version`. That last step is an
inference and is labelled as one: what is *established* is the second session, the `@EIV:` banner check, and the
shapes above. I still do not assign vendor names to these five bytes.

One caveat on the byte counts: in this family the wrappers return *either* `(packet length, data offset)` or
`(packet length, expected response length)` depending on the function, so the "length" I quote above is the one
that the `FUN_82803726` call itself receives (verified per wrapper); the response sizes are separate and I did
not tabulate them.

The *data* is unambiguous regardless of the trailer: 256 bytes per row, row number in the header, and the
assembled image validates as a Cortex-M vector table.

Note also that the row field is **6 hex characters, not 8 as in Intel HEX**, and the rows are strictly
incrementing by 1 (`25, 26, 27, …`) — so this is the Cypress CYACD variant, not Intel HEX, despite the
superficial `:`-prefix resemblance.

### Row numbering is a byte address

Rows run `25 … 511`, and `row × 256 = row << 8` is exactly the flash **address**. So `row 25` = offset
`0x1900`, and the rows are sparse — the missing rows are simply unprogrammed flash, not corruption.

Assembling the rows into a 512 × 256 -byte image and reading at **`0x1902`** yields a textbook Cortex-M
vector table:

```
[0x1900] 01 00            <- 2-byte prefix (row/record marker), see below
[0x1902] 0x20004000   SP            <- SRAM, PSoC 5LP has SRAM at 0x20000000
[0x1906] 0x00001911   Reset         <- ODD => Thumb
[0x190A] 0x0001477D   NMI
[0x190E] 0x0001477D   HardFault
```

Reading the same bytes at `0x1900` instead gives `SP = 0x40000001` — clearly nonsense — so the 2-byte
alignment is not a judgement call, it is the only reading that produces a valid vector table.

And `0x1911` (the Reset target) resolves to real Thumb code at `0x1912`:

```
0x1912:  b5 10        push  {r4, lr}      <- LE16 0xb510
0x1914:  4b 02        ldr   r3, [pc, #8]  <- LE16 0x4b02
0x1916:  83 f3 88 08  msr   ...
0x191a:  f0 13 0c ff  bl    ...
0x191e:  00 40 00 20
```

**The `b510` at `0x1912` is the proof:** the Reset vector `0x1911` masks to `0x1910`, and the Thumb
instruction stream therefore begins at `0x1912` — exactly where `push {r4, lr}` sits. The assembled row
image *is* the flash image, with the vector table at `0x1900 + 2`.

So the keyboard firmware is a **Cortex-M3 image** and can be loaded into Ghidra with `ARM:LE:32:Cortex`
once reassembled as above.

The two builds **EVT4** and **DVT2** are the engineering- and design-validation bring-up revisions — the same
names the device reports in its `0x02` reply (`dsp hw revision: dvt2`, doc `03`), which is how the running
keyboard revision can be identified. That is a directly useful link: the `0x02` reply tells you which of
these two images is actually running on a given unit.

### Reproducing the extraction

```python
import pathlib
raw   = pathlib.Path('SnakeKeyboardModule_DVT2.cyacd').read_bytes()
lines = [l.strip() for l in raw.split(b'\n') if l.strip().startswith(b':')]
rows  = {int(l[1:7], 16): bytes.fromhex(l[7:7+512].decode()) for l in lines}
img   = bytearray(512*256)
for r, d in rows.items(): img[r*256:(r+1)*256] = d
# IMPORTANT: the assembled rows are 2 bytes ahead of flash - strip the first 2 bytes
img_fixed = img[0x1900:0x20000][2:]      # flash 0x1900.. now at offset 0
open('kb_DVT2_fixed.bin','wb').write(img_fixed)
# vector table at flash 0x1900 (SP 0x20004000, Reset 0x1911),
# code from flash 0x1910 = `10 b5` (push {r4,lr}); load at base 0x1900
```

### Resolved: the assembled image is 2 bytes ahead of flash

An earlier version of this document flagged this as an open contradiction. **It is now resolved, and it was a
real bug**: the image assembled from the `.cyacd` rows is **2 bytes ahead of the flash the CPU sees**. The
correct load is therefore either base **`0x18FE`** on the raw assembly, or — better, because round numbers
survive review — **strip the first two bytes and load at `0x1900`**.

Three independent witnesses, in increasing order of strength:

1. **The Reset vector lands exactly on a function prologue.** `Reset` = `0x1911`, so the handler starts at
   flash `0x1910`. In the raw assembly that is file `0x10` = `01 00 10 b5 …` (`lsls r1,r0,#0` as a
   *first* instruction — implausible). Strip two bytes and flash `0x1910` = file `0x12` = `10 b5 02 4b …`
   = `push {r4,lr}; ldr r3,[pc,#8]` — a textbook Thumb entry. Likewise the vector table itself: raw, the
   initial `SP` sits at flash `0x1902` (2-mod-4, which a Cortex-M vector table cannot be); stripped, `SP` is
   at `0x1900`.

2. **The literal pools stop being 4-byte aligned.** Scanning for 32-bit words that are plausible pointers
   (SRAM `0x2000xxxx` or an odd in-image address):

   | image | alignment | plausible words | longest consecutive run | runs of ≥4 |
   |---|---|---|---|---|
   | raw | ≡ 0 (mod 4) | 109 | 1 | 0 |
   | raw | ≡ 2 (mod 4) | **1,230** | **32** | **58** |
   | stripped | ≡ 0 (mod 4) | **1,230** | **32** | **58** |
   | stripped | ≡ 2 (mod 4) | 109 | 1 | 0 |

   Compilers emit literal pools on 4-byte boundaries, so exactly one alignment can be right. The table is
   unambiguous.

3. **The analysis quality changes discontinuously.** Same file, same Ghidra, only the 2-byte strip:

   | | raw | stripped |
   |---|---|---|
   | functions recovered | 203–208 | **387** |

   Nearly double the function count is what you expect when prologues stop being decoded off by one
   halfword.

**Consequences, all of which are applied below.** The dispatcher's table-base literal resolves to a valid
table base; the table becomes **146 entries** (types `0`–`0x91`, exactly matching the code's bound) instead
of a 152-entry table with a phantom leading zero; its targets are **real function entries**, not interior case
labels; the ID→address map shifts down by one; and the shared primitives are `FUN_000140d4` and
`FUN_00018a88`, each 2 below the earlier published names.

**What was never affected.** The `.cyacd` *format* findings (row = byte address, 256-byte rows, sparse rows,
the unidentified 3-byte trailer), the string inventory, the `..\PSOCCommon\` source attribution and the
existence and contents of the dispatch table — all read from bytes rather than addresses, and all unchanged.

### It decompiles, and it is *not* just a keyboard controller

The reassembled image loads into Ghidra at base **`0x1900`** with stock ARM Cortex support and analyses in 2
seconds to **387 functions** on the 2-byte-stripped image (203 on the raw one — see the box above):

```bash
analyzeHeadless <proj> KB -import kb_DVT2_fixed.bin \
    -processor "ARM:LE:32:Cortex" -loader BinaryLoader -loader-baseAddr 0x1900
```

The recovered source paths show what this chip actually does. **"Keyboard" is a misnomer** — it is the
OP-Z's **power, charging and USB-PD controller**:

```
..\PSOCCommon\power_management.c      power state machine
..\PSOCCommon\charger.c               charger control
..\PSOCCommon\pmic.c                  PMIC
..\PSOCCommon\flx6408.c               the FLX6408 USB power switch
..\PSOCCommon\fusb302.c               the FUSB302 USB-C PD PHY
..\PSOCCommon\FUSB302\core\PDPolicy.c           USB Power Delivery policy engine
..\PSOCCommon\FUSB302\core\vdm\vdm_callbacks.c  Vendor Defined Messages
..\PSOCCommon\FUSB302\core\vdm\te\vdm_te.c      TE-specific VDM handling
..\PSOCCommon\keyboardmodule.c        the keyboard module (one part of it)
..\PSOCCommon\leddriver.c             keyboard LED driver
..\PSOCCommon\i2c.c                   I2C bus
..\PSOCCommon\Sleep.c                 sleep/watchdog
..\PSOCCommon\OS_Resources.c           RTOS resources
..\PSOCCommon\logfile.c               logging
```

`..\PSOCCommon\` indicates a **shared Teenage Engineering platform module** reused across products —
FSUSB302/PDPolicy/VDM are upstream USB-PD stack components, while `vdm_te.c` and `keyboardmodule.c` are
the TE-specific layers.

**The power state machine is fully observable from its strings.** The states are:

```
psStandby   psOnHost   psOnCharging   psCharging   psPowerOff
psPowerOffCharging   psDeadBatt
PowerSleep  PowerPreSleep  PowerWakeup  FusbSleep
```

And the battery/thermal policy:

```
Battery too low, %d mV < %d        Battery ok, %d mV > %d
Shutting down now due to low voltage        Batt low, shut down
shutdown after %d ms               Going to standby
Shutdown aborted                   Going to charging state
REASON VOLT PMIC dropped           REASON OT
No BF pong, REBOOT needed!!        PMIC warning, REBOOT if no pong!
```

`No BF pong, REBOOT needed!!` is notable: **the power controller monitors the Blackfin with a ping and can
reboot the system if the Blackfin stops answering.** That is a hardware-level watchdog over the main CPU, and
it explains why a hung Blackfin eventually recovers rather than staying wedged.

**USB Power Delivery is fully implemented**, including Apple-specific VDM handling:

```
VDM: detected Apple device, enable DR/PR swap.
USB status update (requested by: %s): Legacy cable / Detached / Detached (OCP) / Attached (cc: %d)
contract Voltage: %dmV, MaxCurrent: %dmA getadvc %dmA
Sink detected (we feed power) contract Voltage: %dmV, Operational Current: %dmA
PolicySinkEvaluatePRSwap %d      update data role: %s
t: %dmA      set charger mode: %x      flx_set_hostmode:
Set charger input limit %d mA, previous:%d
```

So the OP-Z negotiates a real **USB-PD contract** (voltage and current) rather than just drawing 5 V, and it
can act as **either source or sink** (`Sink detected (we feed power)`, `update data role`). The Apple VDM
handling means it specifically interoperates with Apple chargers/cables.

**A full PMIC reset-reason vocabulary** (useful for field diagnosis, since each has a distinct string):

```
Last PMIC reset reason: VPOR reached / Voltage drop / Software forced by On /
    Software forced by charger / XRES pin triggered / Overtemperature / On pressed /
    On from standby / Unknown
reset reason: was caused by WDT
reset reason: Occured protection violation that requires reset
reset reason: Cortex-M0 requested system reset.
```

**Hardware revision detection.** The PSoC distinguishes board revisions at runtime:

```
no FLX        DVT1 detected        OK:DVT2 or later        SAFETY CHECK
```

That pairs with the `dsp hw revision: dvt2` reply in the serial command set (doc `03`) and with the two
shipped keyboard images (EVT4 / DVT2, §7.4).

**Task and watchdog instrumentation.** The RTOS tasks are named, and there is a per-task watchdog:

```
MAINTASK   SYSTICTASK   UARTTASK   FUSBTASK
Task %s caused a watchdog reset!
WD warning! %s not updated for %d ms
stack overflow %s
Peripherals not sleeping!!
```

**Charger and fuel-gauge specifics**:

```
MAX77818_FG_STATUS_ICF (i2c failure) - clearing
Battery Attached event / Battery Detached event
re-init fuel gauge         battery is missing so charge current is %dmA
Battery voltage is correct --> stop pulsing      pulse %u/%u: ENABLE (%u mV)
DISABLE [%u %u %u] (%u mV)
```

`MAX77818` is the fuel gauge / charger IC, and the `pulse`/`DISABLE`/`ENABLE` messages describe a
**pulsed charging** scheme for a deeply-discharged battery — the standard technique for recovering an
over-discharged Li-ion cell. `Battery voltage is correct --> stop pulsing` is the exit condition.

The identity exchange with the Blackfin is here too:

```
serial:%s;psoc_id_low:%lu;psoc_id_high:%lu
serial        blackfin        connected to te unit, ignore vbus update
PowerState in DSP unknown       Unknown power state requested
UNHANDLED REQ @SER_MSG_SET_FUSB_STATUS_IRQ     FUSB got unexpected command %d
```

So the PSoC reports its **own serial and a 64-bit chip id** (low/high halves), and it speaks the same
`SER_MSG_*` command vocabulary as the Blackfin — the third place that naming convention appears (after the
Blackfin and the Nordic chip). **This is the third endpoint of the same serial protocol.**

### Correction: the power/suspend log lines come from *here*, not the Blackfin

Doc `06` §6.4 listed the suspend sequence — `Going to charging state`, `PowerPreSleep`, `Wake Leds` — among
the **Blackfin** power strings. Checking the actual provenance settles it:

| string | in `opz.ldr` (Blackfin) | in the PSoC image |
|---|---|---|
| `Going to charging state` | **0** | 1 |
| `PowerPreSleep` | **0** | 1 |
| `Wake Leds` | **0** | 1 |
| `LedSleep` / `LedWake` | **0** | 1 |
| `psStandby` / `psOnHost` / `psCharging` / `psDeadBatt` | **0** | 1 |

The device log lines that earlier device work attributed to a graceful Blackfin shutdown therefore originate
from the **power controller**. The Blackfin does have `power_sleep()` and its own suspend path (doc `06`
§6.4), but the `ps*` state machine and the `Going to charging state` / `PowerPreSleep` messages are PSoC-side.
This is exactly the kind of attribution error that is easy to make when two chips log to the same serial
stream, and it is worth correcting rather than leaving.

A second error in the same area: that earlier session also read `Wake Leds` as an **OS** log frame on
routing `0x2e`. Given the string lives only in the PSoC image, the frame is more likely a third-party log
relayed through the routing layer than an OS log — one more reason to classify frames by content rather
than by routing alone.

### 7.4b Is the PSoC string pool reachable? Yes it decompiles, no it is not addressed

The PSoC image decompiles properly — `FUN_0001a70a`, the last function before the string pool, comes out as a
clean GCC C++ exception-unwind helper, and the PMIC code reads as real I2C register access
(`func_0x000193da(0x40, 0x33, …)`). So the analysis is sound and the code region is fully covered: functions
run `0x1900`-ish through `0x1a70a`, and the string pool begins at `0x1aa9e`.

I then tested whether the strings are reachable, since that was left open:

| test | result |
|---|---|
| Ghidra reference manager over the whole pool range `0x1aa00`–`0x1d200` | **0** non-data refs |
| Thumb `LDR Rt,[PC,#imm]` resolving to each documented string | **0** |
| Thumb `LDR.W Rt,[PC,#imm12]` | **0** |
| raw 32-bit words pointing into the pool | 412 hits, i.e. **267 distinct** addresses — but investigate |
| …of those, how many land on a true string **start** | **9 of 924 strings**, and most are 1-byte alignment artifacts |

The 412 raw-word hits (267 distinct addresses) look promising at first, and they are a **trap**: many point
at single bytes (`0x01b400` → `'\x01'`) or at mid-string positions. Counting them naively over-reports
reachability by more than 40×. Comparing against the 924 actual string starts gives the real answer: **9** —
and the survivors (`b'\xc0]ERROR3 I2C 0x%02x 0x%x'`) are themselves mostly mid-string hits from adjacent
arithmetic.

The dense clusters that *do* look table-like — e.g. `0x18862`–`0x188DE`, which holds a run of pointers into
the `Last PMIC reset reason: …` strings — turn out to be **mixed literal pools**: string pointers interleaved
with code addresses (`0x1cf24`) and SRAM addresses (`0x2000xxxx`). They are emitted per-function by the
compiler, not a symbol table, which is why no clean extraction is possible.

**Conclusion, verified rather than assumed:** the PSoC image's string pool is more than 40× over-reported by a
naive raw-word count, and the survivors are mostly mid-string alignment artifacts.

**This negative result was re-checked against the failure mode that overturned the BLE load base (§7.2).** The
method there was to sweep candidate load bases and count stored words that land *exactly* on a string start;
at the right base the count spiked to 129 against a control maximum of 25. Repeating that sweep on the PSoC
image over candidate bases `0x0`–`0x2000` gives a **flat** `10`–`22` at every base — no base makes the pool
addressable. So unlike the BLE case, this negative is not a base artifact.

By contrast, **the BLE image behaves differently**: with the base corrected its pool *is* addressed (129 exact
string starts, §7.2). So the two companions are not the same case, and the BLE behaviour findings in §7.2b are
read from decompiled handlers rather than from strings. The strings here are real (they are in the image and
correspond to real code paths); only their *call sites* are out of static reach.

### What the pool region actually contains

Looking at the bytes rather than counting pointers gives the answer. The string block ends immediately before
the dispatch table, and the table itself is a clean run of 32-bit code addresses. Read at the **corrected**
alignment (`0x1aae4`, 4-aligned) the first entries are:

```
flash 0x1aae0:  00 00 00 00        (the 2 bytes of padding/terminator before the table base)
flash 0x1aae4:  0x000057fa   type 0   -> FUN_000057fa
flash 0x1aae8:  0x000057ee   type 1   -> FUN_000057ee
flash 0x1aaec:  0x000055e6   type 2   -> FUN_000055e6
flash 0x1aaf0:  0x000047b4   type 3   -> the default handler
flash 0x1aaf4:  0x000047b4   type 4
flash 0x1aaf8:  0x000047b4   type 5
flash 0x1aafc:  0x000155c6   type 6   -> FUN_000155c6
```

Two properties are worth recording:

- **The entries are even.** The Blackfin tables use odd (Thumb) pointers; this Cortex-M3 table does not.
  On M-profile bit 0 of a branch target is ignored and the core is always in Thumb state, so an even value is
  a perfectly good function entry — which is why the "even ⇒ not a branch target, these must be IDs" reading
  in an earlier version of this document was wrong.
- **The table's own shape is the evidence for the base.** 146 entries, exactly `0x91 + 1` from the bound
  check in the dispatcher, with `0x47b4` as the dominant value (**107** of 146) and 39 distinct handler
  entries.

The earlier "558 values, 295 distinct, `0x047b4` × 121" scan covered the whole pool region rather than the
table, so it mixed the table with other data — the table-local figures above are the ones to quote.

So this region's job is not to index strings at all: **the strings are reached through the dispatch table**,
which is why a search for string pointers finds almost nothing (9 of 924, §7.4b) while a search for in-image
words finds hundreds. The correct way in is the table, which is what §7.4c now does from the dispatcher's own
literal.

### 7.4c The dispatch table, walked: 146 message types → 39 handlers

The table after the strings is the **command/message dispatch table**. With the 2-byte correction applied it
decodes cleanly and self-consistently:

| property | value |
|---|---|
| location | flash `0x1aae4` – `0x1aadcb` (the base the dispatcher's own literal points at) |
| size | **584 bytes = 146 entries × 4** |
| index | **message type byte** — the *first byte of the message* (see below) |
| implemented types | **39** |
| default entry | **`0x47b4`**, used by the other **107** types |
| handler range | `0x47f0` – `0x155c6` |

The index and the bound come from the dispatch code itself, which is unambiguous:

```asm
0x47e4  ldrb r3,[r6,#0]      ; r3 = message[0]  (the type byte)
0x47e6  cmp  r3,#0x91
0x47e8  bhi  0x47b6          ; type > 0x91 -> ignore / default path
0x47ea  ldr  r2,[pc,#0x130]  ; r2 = 0x1aae4, the table base
0x47ec  lsls r3,r3,#2
0x47ee  ldr  r3,[r2,r3]      ; r3 = table[type]
0x47f0  mov  pc,r3           ; tail-jump into the handler
```

`0x91 + 1 = 146` entries, which is exactly the table length — so the table length is *derived from the code*
rather than from a scan, and the earlier "152 entries with index 0 = 0" reading was the 2-byte-misaligned one
(the phantom leading zero entry disappears).

The 39 implemented types and their handler entries:

```
  0  0x57fa    1  0x57ee    2  0x55e6    6  0x155c6   7  0x565a
  9  0x5636   11  0x5368   12  0x52d2   16  0x5818   18  0x57ce
 20  0x55b4   21  0x5452   23  0x5728   24  0x56da   32  0x57ac
 37  0x514c   39  0x51e8   41  0x51ba   48  0x51a0   51  0x5166
 53  0x521e   56  0x5202   58  0x523c   60  0x50f8   61  0x5286
 63  0x5254   67  0x5038   69  0x4fa2   70  0x14f88   71  0x4f7e
 72  0x4f72  112  0x4f3c  128  0x4e4a  134  0x14e32  135  0x4e86
136  0x4d6a  137  0x4b38  144  0x4a92  145  0x47f0
```

The **gaps are the information**: a type with no entry falls through to the default, so this list *is* the
implemented message vocabulary of the PSoC. As on the Blackfin, the numbering is uneven (dense low range, a
run at `128`–`137`, a jump to `144`–`145`), i.e. an enum that grew over time rather than a compact map.

**What each type does, read from the code it calls.** Classifying each handler by the subsystem its callees
belong to — using the `..\PSOCCommon\*.c` source-path strings that each callee carries — gives the message
vocabulary of the chip without guessing from names:

| type | handler | subsystem it drives |
|---|---|---|
| `0`, `1`, `7`, `9`, `16`, `18`, `23`, `24`, `32`, `69`, `71`, `72`, `112` | `0x57fa`, `0x57ee`, `0x5650`+`0xa`, `0x55e6`+`0x50`, `0x57fa`+`0x1e`, `0x57ce`, `0x5704`+`0x24`, `0x5650`+`0x8a`, `0x57ac`, `0x4fa2`, `0x4f7e`, `0x4f72`, `0x4f3c` | `power_management.c` — power state |
| `2`, `20` | `0x55e6`, `0x55b4` | `fusb302.c` + `pmic.c` + `power_management.c` — USB-C PD + PMIC |
| `11`, `12`, `21`, `61` | `0x5368`, `0x52d2`, `0x5452`, `0x5286` | `charger.c` + `fusb302.c` + `pmic.c` — charging + PD |
| `37`, `39`, `41`, `48`, `51`, `60`, `67` | `0x514c` (± offsets), `0x50f8`, `0x5038` | `charger.c` + `power_management.c` |
| `53`, `56`, `58`, `63` | `0x521e`, `0x5202`, `0x523c` (± offsets), `0x5254` | `charger.c` + `fusb302.c` + `pmic.c` + `power_management.c` |
| `128`, `135`, `136`, `137` | `0x4e4a`, `0x4e86`, `0x4d6a`, `0x4b38` | `charger.c` (`137` is `charger.c` alone) |
| `6` | `0x155c6` | `i2c.c` — I2C bus recovery |
| `134`, `70` | `0x14e32`, `0x14e32`+`0x156` | utility (character table, see below) |
| `144`, `145` | `0x4a92`, `0x47f0` | no source-path strings — small handlers |

So the PSoC's host-facing message vocabulary is **a power-management API**: power state, charger, PMIC,
USB-PD/FUSB302 and I2C recovery. That is the same conclusion the string inventory reached (§7.4), now
confirmed from the dispatch side.

Three handlers carry a concrete string, which pins their purpose:

| type | string | reading |
|---|---|---|
| `7`, `24` (`FUN_00005650`) | `serial:%s;psoc_id_low:%lu;psoc_id_high:%lu` | **identity reply** — the PSoC reports its own serial and 64-bit chip id, the third endpoint of the same `serial:…` reply form the Blackfin uses (`03` §3.x) |
| `6` (`FUN_000155c6`) | `Can't unblock the SDA, something is hogging the line, and it's not a chips` (`i2c.c`) | **I2C bus recovery** — the SDA-unblock escape hatch, reached as a message type |
| `134` (`FUN_00014e32`) | `!"#%&'()*+./012345` | a **character table** (punctuation + digits) — validation for a serial/name string |

**Each handler builds its reply with `FUN_000140d4(length, type)`,** so reading the call sites gives the
PSoC's **request → reply map** without guessing. The rule that holds where a dedicated reply exists is
**reply type = request type + 1** — the same rule documented for the Blackfin console (doc `03`) — with a set
of **shared reply types** reused by several requests:

| request | reply built | reply type relation | what the handler does |
|---|---|---|---|
| `2` | `(9, 9)`, `(1, 10)`, `(n, 8)` | dedicated + shared | builds the 9-byte status payload `0,1,0,2,0,0x1a,0,0,4` (see below) |
| `11` | `(1, 0x0c)` | dedicated | 1-byte reply |
| `12` | `(1, 0x0c)` | dedicated | 1-byte reply |
| `18` | `(8, 0x13)` | **18 + 1** | 8-byte blob from the SRAM struct at `0x200039b8` |
| `37` | `(0xc, 0x26)`, `(8, 0x28)`, `(6, 0x31)` | shared | three different replies from one request |
| `56` | `(4, 0x39)` | **56 + 1** | 4-byte reply |
| `58` | `(1, 0x40)`, `(2, 0x3e)` | shared | 1- or 2-byte reply |
| `60` | `(0xc, 0x26)`, `(8, 0x28)`, `(6, 0x31)` | shared | same three replies as `37` |
| `67` | `(7, 0x44)`, `(0xc, 0x26)`, `(8, 0x28)`, `(6, 0x31)` | shared | four replies |
| `112` | `(8, 0x28)` | shared | 8-byte reply |
| `128` | `(1, 0x81)` | **128 + 1** | 1-byte status, see below |
| `145` | `(2, 0x92)` | **145 + 1** | 2-byte reply + watchdog window, see below |

The shared replies — `0x26` (12 B), `0x28` (8 B), `0x31` (6 B) — are the PSoC's **telemetry vocabulary**: the
same three reply types are produced by requests `37`, `60` and `67`, so those requests are three ways of
asking for the same status block at different granularities rather than three unrelated messages.

**Three handlers read in full**, which is what turns the table from "subsystem" into "action":

```c
/* type 18 - 8-byte status/identity blob */
void FUN_000057ce(void) {
  iVar1 = FUN_000140d4(8, 0x13);            /* reply type 19 = 18 + 1 */
  disableIRQinterrupts();
  copy(*(iVar1 + 4), DAT_00005ab0, 8);      /* DAT_00005ab0 -> SRAM 0x200039b8 */
  ...
```

`DAT_00005ab0` resolves to **SRAM `0x200039b8`**, so the eight bytes are a runtime-filled identity/status
struct, not a flash constant — which is why the reply cannot be read statically even though its *shape* can.

```c
/* type 128 - 1-byte status reply that echoes the routing nibble */
void FUN_00004e4a(void) {
  iVar1 = FUN_000140d4(1, 0x81);             /* reply type 129 = 128 + 1 */
  **(undefined1 **)(iVar1 + 4) = 4;         /* payload byte = 4 */
  if (*DAT_00004e90 != 0 && req_len < 0x21) func_0x0000609a();
  *(byte *)(iVar1 + 1) = *(byte *)(iVar1 + 1) & 0xf0 | *(byte *)(req + 1) >> 4;
  FUN_0001414c(iVar1);                      /* queue the reply */
}
```

The penultimate line is the interesting one: the reply's status byte has its **low nibble set from the high
nibble of the request's routing byte** (`req[1] >> 4`). That is the same nibble-packed header field described
for the BLE transport in §7.2e (`(length << 4) | destination`), so the PSoC is **echoing the incoming
routing/destination nibble back** in its acknowledgement — a concrete cross-chip confirmation of the header
layout, found in a fourth image.

```c
/* type 145 - 2-byte reply plus a watchdog window refresh */
void FUN_000047f0(void) {
  iVar1 = FUN_000140d4(2, 0x92);             /* reply type 146 = 145 + 1 */
  **(undefined1 **)(iVar1 + 4) = 0x62;
  *(undefined1 *)(*(int *)(iVar1 + 4) + 1) = 0;   /* payload 0x62, 0x00 */
  *(byte *)(iVar1 + 1) = *(byte *)(iVar1 + 1) & 0xf0 | *(byte *)(req + 1) >> 4;  /* same nibble echo */
  *DAT_00004b20 = 0xffffffff;                /* liveness sentinel */
  if (DAT_00004b24 < (ctx[0x68] - ctx[0x6c])) FUN_00005c38();
  if ((ctx[0x68] - ctx[0x6c]) < ctx[0x74])   FUN_00005a3a();
  ctx[0x74] = ctx[0x68] - ctx[0x6c];
  yield(...);                                /* does not return here */
}
```

So type `145` is a **liveness/heartbeat message**: it answers with `0x92 0x62 0x00`, stamps a `0xffffffff`
sentinel and refreshes a timing window. That pairs with the PSoC's Blackfin-side watchdog (`No BF pong,
REBOOT needed!!`, §7.4) — the same liveness idea in the host-facing direction.

### The handlers, read: the shared power-state enum, a magic-word reset, and the driver bank

Reading the remaining handler bodies turns the table above from "subsystem" into "action". Three findings are
worth more than the per-type list, so they come first.

**1. The power-state codes are a *shared* enum between the PSoC and the Nordic chip.** Type `20` stores its
payload's first byte and dispatches it through a **9-entry table at `0x1ad50`** after subtracting `0x10`, with
`payload[0] > 0x18` logging `Unknown power state requested`:

| `payload[0]` | handler | action |
|---|---|---|
| `0x10` | `FUN_000067c4` | sets the power-state byte at `DAT_0000691c+7` to **6** |
| `0x12` | `FUN_000067d8` | sets it to **5** |
| `0x14` | `FUN_0000659e` | the off/`0xCA`-marked path (larger body, calls the identity reply builder) |
| `0x16` | `FUN_000067b2` | sets it to **7** |
| `0x18` | `FUN_000067aa` | sets it to **1** |
| `0x11`, `0x13`, `0x15`, `0x17`, anything `> 0x18` | `FUN_000067cc` | logs `Unknown power state requested` |

and every one of the five real handlers then sets bit 4 of the register at `DAT_00006738 + 0x1c` under an
interrupt lock:

```c
/* FUN_000067aa - payload[0] == 0x18 */
*(undefined1 *)(DAT_0000691c + 7) = 1;          /* power-state byte */
disableIRQinterrupts();
*(uint *)(DAT_00006738 + 0x1c) |= 0x10;         /* latch the request */
```

**And the Blackfin side of the same message has now been found, which names the enum and confirms the
shape.** The OS's `C:\snake-software\src\shared\command_handler_kb.cpp` — the handler for the PSoC ("kb")
messages — contains the five log strings and the fallback:

```
0x815c9588  PSOC requested SER_MSG_POWER_MODE_REQUEST_ACTIVE
0x815c95bc  PSOC requested SER_MSG_POWER_MODE_REQUEST_STANDBY
0x815c95f0  PSOC requested SER_MSG_POWER_MODE_REQUEST_POWER_OFF
0x815c9628  PSOC requested SER_MSG_POWER_MODE_REQUEST_CHARGING
0x815c965c  PSOC requested SER_MSG_POWER_MODE_REQUEST_LOW_BATT
0x815c9690  Unknown power mode requested: 0x%02x
```

So the five codes have **official names**, and the fallback wording matches the PSoC's own
`Unknown power state requested` — the two sides were built from one enum.

The Blackfin's dispatch is at `0x80131ae6`: it takes the received byte, subtracts `0x10`, requires `< 9`, and
jumps through a **9-entry table at `0x815C9754`**:

and each handler's full action — two stores and, for two of the five modes, the OS's shutdown flag:

| byte | handler | logs | `DAT_81004750` ← | `DAT_815c94ac` ← | also |
|---|---|---|---|---|---|
| `0x10` | `0x80131cc4` | `…REQUEST_ACTIVE` | `R7` (the byte) | `0x10` | — |
| `0x11` | `0x80131b10` | `Unknown power mode requested: 0x%02x` (line `0x176`) | — | — | — |
| `0x12` | `0x80131ce0` | `…REQUEST_STANDBY` (line `0x160`) | **5** | `0x12` | — |
| `0x13` | `0x80131b10` | unknown | — | — | — |
| `0x14` | `0x80131d08` | `…REQUEST_POWER_OFF` (line `0x165`) | **0** | `0x14` | **`DAT_81003e80 = 1`** |
| `0x15` | `0x80131b10` | unknown | — | — | — |
| `0x16` | `0x80131d38` | `…REQUEST_CHARGING` (line `0x16b`) | **2** | `0x16` | **`DAT_81003e80 = 1`** |
| `0x17` | `0x80131b10` | unknown | — | — | — |
| `0x18` | `0x80131d68` | `…REQUEST_LOW_BATT` (line `0x171`) | **1** | `0x18` | — |

**The two companion-requested shutdowns are the interesting rows.** `DAT_81003e80` is the OS's
*restart/shutdown* flag — the same one the hidden text commands set (`restart-into-bootloader` sets
`0x3e80`+`0x3e81`, `restart-into-content`/`-synth` set `0x3e80`+`0x3e82`, doc `04` §4.1). So when the PSoC
requests **power-off** or **charging**, the main CPU responds by raising the shutdown flag *without* a target
flag — i.e. the **power/USB-PD controller can command the OP-Z's CPU to shut down and go to charging**. That
is a real architectural statement: the companion that watches VBUS decides when the unit powers down, and the
Blackfin obeys through the same flag its own restart commands use.

**What the recorded mode is used for beyond that flag is not established.** Ghidra's reference manager findsfive *writes* to `DAT_815c94ac` and five to `DAT_81004750` and **no reads**; a scalar search for the addresses
finds nothing either. A raw byte scan for the little-endian dwords is **not a valid cross-check here** — the
Blackfin+ analyser materialises these constants in split form (high half before low half, per the note in doc
`01`), so a dword scan returns 0 hits for an address that demonstrably appears in `StDregToM32bit` operands.
So "no reader found" rests on the reference data alone, and given the analyser's known gaps (doc `05` §5.7)
it means *unlocated*, not *unused*.

A second, smaller cross-chip match falls out of the same table: the Blackfin's state values
(`DAT_81004750` = **5** standby, **1** low-batt, **0** off, **2** charging) coincide with the PSoC's own state
byte values for standby (**5**) and low-batt (**1**) — read from two different images. The charging and active
values differ (the PSoC uses `7` and `6`), so the two state enums overlap but are not identical; that is
recorded as observed rather than unified into one enum.

**That table is the mirror image of the PSoC's own table at `0x1ad50`** — same nine slots, same
`− 0x10` index, same populated pattern `{0, 2, 4, 6, 8}`, and the same odd-slot behaviour of falling to an
"unknown mode" logger. Two independently-built images on two CPUs using the identical dispatch shape is the
strongest evidence in this document that the companion protocol is a **shared source component**, which doc
`01` already saw as `src/shared/` (`command_handler_kb.cpp` for the PSoC, `command_handler_ble.cpp` for the
Nordic).

**Direction, stated precisely.** The Blackfin's strings say *"**PSOC requested** …"*, so on this path the PSoC
originates the request and the Blackfin records it (`DAT_815c94ac`). The PSoC's own type-`20` handler, by
contrast, *sets its own* power-state byte and latches it — a receive path. So the same message (byte `0x10`–
`0x18`) is used **in both directions** between the Blackfin and the PSoC, and the Nordic image handles the same
five codes in its type `6`. The correct statement is therefore: *one power-mode enum, shared across all three
CPUs and carried in both directions* — not a one-way request from the Blackfin. The earlier wording in this
document ("the Blackfin's power request is one message format addressed to two chips") was right about the
sharing and wrong about the direction, and it is corrected here.

**One open conflict with that reading, now resolved in this document's favour by decompiling the handler.**
Doc `04` §4.6b reads the Blackfin's button-debounce setter directly (`FUN_80131700`): it sends a **two-byte**
payload `{1, value}` under type **`0x14` = 20**, i.e. at this document's index `20` — the row above that reads as
*"sets its own power-state byte and latches it"*. Decompiling `FUN_000055b4` (index `20`) shows the row is
**incomplete rather than wrong**: the handler stores `payload[0]` into the dword at `0x20000690` and `payload[1]`
into the byte at `0x200000cd` **unconditionally**, and only afterwards interprets `payload[0] - 0x10` as a power
mode through the 9-entry table at `0x577c`. A debounce payload of `{1, value}` therefore stores its two bytes and
falls to the default handler, which is why it works. So the handler is a **generic two-byte `{field, value}`
setter with an optional power-mode tail**, and the Blackfin's type byte is this table's index — verified on three
types (`0x90`↔`144`, `0x20`↔`32` with `payload[0] = 3` in the populated set, `0x14`↔`20` with a two-byte
payload). The same match names the receiver of doc `08`'s light flush: type `0x10` is index `16`, i.e. the
interior entry `0x5818` inside `FUN_000057fa`, a body that reads `payload[0]` as a sub-command under a `5 < uVar1`
guard — and that byte is the constant `0x00` the flush writes.

**2. Message type `112` with the payload `DE AD BE EF` is a system reset** (`FUN_00004f3c`). The guard is
exact — length 4 and the four bytes compared individually — and the effect is a write to the Cortex-M's
`AIRCR` with the standard reset magic:

```c
if (*DAT_000052f8 != 0 && req_len == 4 && payload[0]==0xDE && payload[1]==0xAD
                                            && payload[2]==0xBE && payload[3]==0xEF) {
  *AIRCR = (*AIRCR & 0xffff) | 0x05FA0004;     /* DAT_00005348 -> 0xE000ED0C, DAT_0000534C -> 0x05FA0004 */
  ...                                          /* then reply (8, 0x28) */
}
```

`0xE000ED0C` is `AIRCR` and `0x05FA0004` is `VECTKEY | SYSRESETREQ` — i.e. **0xDEADBEEF is a software-reset
trigger** on the PSoC, in the same family as the Blackfin's console `0x34` reset (doc `03`) and the Nordic's
`0xBEBAFECA` factory magic (§7.2b). It is a hidden entry point of exactly the kind doc `04` §4.6 collects.

**3. Types `11`/`12` initialise a driver bank, and type `21` writes single channels into it.** Type `11`
replies `(1, 0x0c)` with payload `7` and then writes a long run of **{counter = 0, enable = 1, period =
0xf000} triples** to `0x2000062x`–`0x2000065x`; type `12` requires the payload's first byte to be `7`, derives
a channel offset multiplier from the context, and runs the same initialisation; type `21` takes a channel
`1..13` and writes `{value, period}` at an **8-byte stride** into the same table at `DAT_20000624`, with a
**`1000` clamp** and a **zero-value rejection** that does not return.

The rest of the per-type actions, read from the bodies:

| type | action |
|---|---|
| `2` | builds the 9-byte status payload `0,1,0,2,0,0x1a,0,0,4` plus a reply carrying the device id read from flash (`0x13` = 19 bytes) and a 64-bit value assembled from byte globals |
| `6` | the I2C SDA-unblock path (`Can't unblock the SDA…`, `i2c.c`) |
| `7`, `24` | identity reply `serial:%s;psoc_id_low:%lu;psoc_id_high:%lu` |
| `11`, `12` | driver-bank initialisation (above) |
| `18` | 8-byte blob from SRAM `0x200039b8`, reply `0x13` |
| `20` | power-state enum (above) |
| `21` | per-channel driver values, `1000` clamp (above) |
| `32` | `payload[0]` indexes a **19-entry table at `0x1ad74`** (values above `0x12` call the default handler first); populated slots are `1, 3, 5, 17, 18, 19`, everything else is the default |
| `60` | `FUN_000050f8` — **power-management write**: `payload[0]` is a sub-command (`0`, `1`, `2`), `payload[1]` is a value that is multiplied by ten and handed to `FUN_00016230`; copies a `0xc`-byte block into `ctx+0x30` and a 6-byte block into `ctx+0x44`; writes `0xab` to a charger register at `+0x30`; and one branch **resets the PSoC** via `*AIRCR = (*AIRCR & 0xffff) \| 0x05FA0004`. Sent by the Blackfin's `SnakeSystem.cpp` service, which arrives with the same ×10 scale already applied (doc `05` §5.8c) |
| `61` | `FUN_0000523c` — **charger query**: stores `payload[0]` at `ctx+0x4a`, reads the charger at I2C **`0x69`** (`MAX77818`) through `FUN_00018d9c(…, 100)` with a non-returning failure path, and replies with two bytes — a zero and the 16-bit register at `ctx+0x4c` **divided by ten** |
| `112` | `0xDEADBEEF` → `AIRCR` reset (above) |
| `128` | 1-byte status reply that echoes the routing nibble (below) |
| `135` | passes the request's routing nibble to `FUN_0000f274`, then the default handler |
| `136` | clears the low **12 bits** (`DAT_00004f34` = `0x0fff`) of a 16-bit register at `ctx+0x16` with a read-back spin |
| `137` | the MAX77818 charger path (`FUN_00018f0c(0x69, 0xb7, buf, 100)`) |
| `144` | **set debug flags**: stores the payload's 16-bit value and logs through `FUN_0001006c(…, 0x280, "Set debug flags %d")` |
| `145` | liveness/heartbeat reply `0x92 0x62 0x00` plus a watchdog-window refresh |

Type `32`'s table is a good example of how sparse these dispatch tables are: of 19 slots, six are populated and
the other thirteen point at the default handler — so "type 32" is really six sub-commands with a shared
fallback, the same shape as type `0`'s six-opcode script (§7.4c).

**The 39 targets are not all function entries — and this time that was checked address by address.** With the
alignment fixed:

| shape | count | examples |
|---|---|---|
| target **is** a function entry | **28** | `0x57fa`, `0x55e6`, `0x5038`, `0x4b38`, `0x47f0` |
| target is **inside** a shared function, at an offset | **11** | `0x565a` and `0x56da` both inside `FUN_00005650`; `0x51e8`/`0x51ba`/`0x51a0`/`0x5166` inside `FUN_0000514c`; `0x5286`/`0x5254` inside `FUN_0000523c`; `0x5636` inside `FUN_000055e6`; `0x5818` inside `FUN_000057fa`; `0x5728` inside `FUN_00005704` |
| no containing function recovered | **1** | `0x14f88` (immediately after `FUN_00014e32`, so the same body) |

So the earlier blanket statement is worth restating correctly: the table is **mostly** real function pointers —
28 of 39 — but several types deliberately share one body at different entry offsets, which is what a compiler
emits when handler prefixes are identical. Anyone treating every entry as an independent function would
mis-attribute those 11.

**The default is a real function, not a null and not an interior label.** `0x47b4` is `FUN_000047b4`
(60 bytes), a polling loop:

```asm
0x47a2  movs r3,#0x0
0x47a4  ldr  r2,[0x4b0c]
0x47a6  strh r3,[r2,#0x0]
0x47a8  ldr  r3,[0x4b10]
0x47aa  movs r1,#0xa            ; 10
0x47ac  ldr  r0,[r3,#0x0]
0x47ae  bl   0x18d9c            ; an I2C/register read
0x47b2  cmp  r0,#0x1
0x47b4  bne  0x47a2             ; <-- the default entry points HERE
0x47b6  bl   0xd28e             ; only continues when the read returns 1
```

and it is invoked by name from other handlers (`FUN_000057fa` and `FUN_000057ee` both `bl 0x47b4` when they
hit a malformed or short message). So an unimplemented or malformed type lands in a retry loop that reads a
register until it returns `1`, instead of doing nothing.

### A decompiled handler

The table's populated slots resolve to **decompilable code**. `FUN_00004b38` is reached from index `138` and
comes out as 273 lines of real logic — peripheral I2C transactions, register bit manipulation and state
flags:

```c
void FUN_00004b38(undefined4 param_1)
{
  if (*_DAT_00004e90 != '\0') {
    FUN_000087ae(param_1, param_1);
    uVar7 = 4;
    if ((short)*_DAT_00004e98 != 0) { uVar7 = 7; }
    FUN_00015842(uVar7);
    *(undefined1 *)in_stack_0000000c = 0x44;
    puVar8 = (ushort *)func_0x00018f0e(0x69, 0xb7, in_stack_0000000c, 100);   /* I2C xfer */
    *_DAT_00004e98 = *_DAT_00004e98 & 0xfe;                                   /* clear bit 0 */
    *_DAT_00004ea0 = *_DAT_00004ea0 & 0xfd;                                   /* clear bit 1 */
    if (*(char *)((int)_DAT_00004ea4 + 2) != '\x01') {
      if (*(char *)((int)_DAT_00004ea4 + 2) == '\0') { puVar8 = (ushort *)func_0x000063c4(); }
      *(undefined1 *)((int)_DAT_00004ea0 + 2) = 1;
    }
    …
```

`func_0x00018f0e(0x69, 0xb7, buf, 100)` is an I2C write to address `0x69`-with-subaddress-`0xb7` and a
100-byte buffer — the `MAX77818` charger/fuel-gauge part referenced in §7.4 uses that address family. So the
handler is a **charger-control path**, consistent with the documented message vocabulary.

**This closes the "no function body has been read" gap for the PSoC image**: code identified *from the
dispatch table* decompiles normally, which is a better route than hunting string references — the strings are
reached through this table, so the table is the correct place to start.

### Correction: the entries are real function pointers (the "case labels" reading was the 2-byte bug)

An earlier version of this document concluded that the table's targets were **interior `switch` case labels**
rather than function entries, and cited `0x47b6` ("a branch target inside `FUN_00004b38`") as the proof. That
conclusion came from the misaligned analysis and is **withdrawn**.

With the 2-byte correction, Ghidra recovers real functions at the great majority of the 39 targets — **28 are
function entries** and 11 are interior offsets into a shared body (the full breakdown is in §7.4c). The
examples the earlier text used as "case labels" are all genuine entries now:

| target | recovered as | size |
|---|---|---|
| `0x47b4` (default) | `FUN_000047b4` | 60 B |
| `0x47f0` | `FUN_000047f0` | — |
| `0x4b38` | `FUN_00004b38` | 82 B |
| `0x57fa` (type 0) | `FUN_000057fa` | 68 B |
| `0x57ee` (type 1) | `FUN_000057ee` | — |

So the PSoC table is structurally the **same as the Blackfin tables** (doc `03`, doc `05`): an array of
function pointers, indexed by the message type byte and tail-jumped into with `mov pc`. The earlier "unlike
the Blackfin images, these are case labels" note was wrong, and it was wrong for the same reason the BLE load
base was wrong: a 2-byte offset that produces plausible-looking but incorrect structure.

The residue of truth in that earlier reading is that **some** entries are not entries: 11 of the 39 point
into a shared body at an interior offset (identical handler prefixes merged by the compiler). That is a real
structural property of this table, just not the one that was claimed, and it is enumerated in §7.4c.

### 7.4d The message pipeline behind the dispatch table

Walking from the table into the shared helpers gives the concurrency architecture, and it decompiles
cleanly. Two routines are called by most handlers.

**`FUN_000140d4` — a 64-slot message-slot allocator** (published earlier as `FUN_000140d6`, which was the
2-byte offset — see the box above). Callers pass it `(length, type)` and it returns a pointer to an allocated
8-byte record; the body reads:

```c
int FUN_000140d4(int param_1)          /* callers pass (length, type) */
{
  uVar4 = _DAT_e180bdf0;
  iVar2 = DAT_00014140;                /* ring buffer base          */
  _DAT_e180bdf0 = 0xffffffff;          /* lock (interrupt/mutex)    */
  bVar1 = *DAT_00014138;               /* index, 64 entries         */
  *DAT_00014138 = *DAT_00014138 + 1 & 0x3f;
  puVar3 = DAT_00014144;               /* write cursor              */
  iVar5 = (uint)bVar1 * 8;             /* 8-byte records            */
  if (0x200 < *DAT_00014144) { *DAT_00014144 = 0; }     /* wrap at 0x200 */
  iVar6 = iVar2 + iVar5;
  *(uint *)(iVar6 + 4) = (int)DAT_00014148 + *puVar3;
  *puVar3 = param_1 + *puVar3;
  *DAT_00014148 = uVar4;               /* unlock (restore)          */
  *(char *)(iVar2 + iVar5) = (char)param_1;             /* ID at +0 */
  *(short *)(iVar6 + 2) = (short)param_1;               /* ID at +2 */
  *(undefined1 *)(iVar6 + 1) = 0;
  return iVar2 + iVar5;
}
```

Three things are worth reading off this:

1. **The message ID is stored twice**, as a byte at `+0` and a halfword at `+2` of each 8-byte record. Combined
   with the 8-byte stride, the record is `{u8 id; u8 flag; u16 id16; u32 payload}` — the same shape as the
   Blackfin's MIDI queue slot (doc `05` §5.7), which suggests TE used one message idiom across chips.
2. **Locking is a sentinel swap**: the old value is read, `0xffffffff` is written, and the old value is
   restored on the way out. That is a shared-memory flag rather than an RTOS mutex, so the handlers here run
   in contexts that must not preempt each other during a slot allocation.
3. **The write cursor has a `0x200` (512) wrap guard** independent of the 64-entry index — so the buffer can
   accumulate up to 512 units before the cursor resets.

**`FUN_00018a88` — a task primitive with a deliberate panic path** (published earlier as `FUN_00018a8a`; the
corrected decompile has *two* such branches). Its first branches are:

```c
if (param_1 == 0) {
  disableIRQinterrupts();
  do { /* WARNING: Do nothing block with infinite loop */ } while (true);
}
```

```c
if (param_1 == 0) { disableIRQinterrupts(); for (;;) { } }              /* bad handle */
if ((param_2 == 0) && (*(int *)(param_1 + 0x40) != 0)) { disableIRQinterrupts(); for (;;) { } }
```

A null handle — or a null second argument with a set flag at `+0x40` — enters an **infinite loop with
interrupts disabled**. That is an intentional firmware halt, the embedded equivalent of `assert(false)`, and
it is the behaviour to expect if this code is ever reached with a bad handle on real hardware.

Together with the dispatch table (§7.4c) this gives the PSoC message path end to end:

```
dispatch table @ flash 0x1aae4 (146 types: 0..0x91, 39 implemented)
      │  index = message[0]; type > 0x91 ignored
      ▼
  handler function (0x47f0 .. 0x155c6), tail-jumped with `mov pc,r3`
      │  message record: u16 length @ +2, payload pointer @ +4
      ├─ FUN_000140d4   allocate an 8-byte slot in a 64-entry ring
      │                 {u8 id; u8 flag; u16 id16; u32 payload}
      ├─ FUN_00018a88   task primitive; null handle => IRQ-off halt
      └─ FUN_000047b4   the default handler (60 B): retry an I2C read until it returns 1
```

### A second dispatch level: handler bodies dispatch again

Type `0` (`FUN_000057fa`) is worth reading in full because it shows the protocol is **two-level**. The handler
pulls the payload out of the record (`u16 length @ +2`, payload pointer `@ +4`), then dispatches a *second*
time on the payload's first byte, bound-checked at `5`:

```c
uVar1 = (uint)*pbVar2;                /* sub-command byte */
if (5 < uVar1) { FUN_000047b4(); }    /* out of range -> default handler */
(**(code **)(PTR_LAB_00005ab8 + uVar1 * 4))();
```

`PTR_LAB_00005ab8` is a literal holding `0x1adc0`, and that is a **6-entry table of handler entries**:
`0x58e0, 0x5926, 0x58b4, 0x584e, 0x583e, 0x5970`. So a type-`0` message carries a sub-command in its first
payload byte with 6 implementations, and the sub-handlers are themselves real functions (`FUN_00005840`,
`FUN_0000584e`, …).

**What those six sub-commands do, and the hardware helper they share.** The sub-handlers are entries inside
`FUN_000057fa` (they use its registers and return to its loop), and they all funnel into one helper:

```c
void FUN_00011010(uint index, uint value)      /* index <= 0x8f, value masked to 0x7ff */
{
  if (0x8f < index) return;                    /* 144 fields, 0..0x8f */
  uVar3 = (index & 0xf) * 0xc;                 /* bit position inside the word    */
  uVar4 = ((index >> 4) * 0x18 + 0xb) - ... ;  /* 16-bit word index               */
  FUN_00019888();                              /* interrupts off                  */
  do { *(short *)(DAT_00011104 + iVar2) = (short)uVar5; } while (uVar5 != *(ushort *)(DAT_00011104 + iVar2));
  ...
}
```

That is a **bit-field hardware register writer**: 144 addressable fields (index ≤ `0x8f`), each an **11-bit
value** (`& 0x7ff`) at a 12-bit stride inside a 16-bit register array, with a **read-back spin** that only
exits once the register reads back what was written, and a split path for fields that straddle a word
boundary. So the PSoC's register access here is a busy-wait-confirmed read-modify-write rather than a plain
store.

The value and register-index sources are two adjacent tables, and the raw instruction stream settles what
each is (the decompiler got the argument types tangled here):

```asm
0x58c0  ldrb r3,[r5,#0x2]     ; operand byte
0x58c2  ldr  r2,[0x5ac0]      ; = 0x1add8  -> the value table
0x58c4  lsls r3,r3,#0x1
0x58c6  ldrh r1,[r2,r3]       ; value = ((u16*)0x1add8)[operand]
0x58c8  ldr  r3,[0x5abc]      ; = 0x1afd8  -> the per-channel register-index table
0x58ca  lsls r4,r4,#0x2       ; channel * 4
0x58ce  add  r4,r12
0x58d0  ldrb r0,[r4,#0x3]     ; index = ((u8*)0x1afd8)[channel*4 + field]
0x58d2  bl   0x11010          ; write(index, value)
```

so the per-channel table at `0x1afd8` is **4 bytes per channel** giving the four field indices to write, in a
non-sequential order (`1a 18 19 1b  2a 28 29 2b  2e 2c 2d 2f  …`, i.e. `x+2, x, x+1, x+3` per group — an order
that looks like hardware channel wiring rather than a software choice).

**The payload is a script, and the six sub-commands are its opcodes.** The dispatch loop reads
`{opcode, channel}` from the front of each block and leaves a cursor (`r8`) at `block + 2`; each opcode then
consumes more operands and moves the cursor. Read from the instruction stream, the six opcodes are:

| sub | handler | channel byte | writes | value source | block length |
|---|---|---|---|---|---|
| `0` | `0x58e0` | `0x00`–`0x32` as-is | 4 fields `ch*4+0..3` | `((u16*)0x1add8)[op[2..5]]` | 6 |
| `1` | `0x5926` | `0x40`–`0x72`, minus `0x40` | 3 fields `ch*4+0..2` | `((u16*)0x1add8)[op[2..4]]` | 5 |
| `2` | `0x58b4` | `0x80`–`0xB2`, minus `0x80` | 1 field `ch*4+3` | `((u16*)0x1add8)[op[2]]` | 3 |
| `3` | `0x584e` | `0x00`–`0x32` as-is | 4 fields `ch*4+0..3` | explicit **16-bit big-endian** pairs `op[2]<<8|op[3]`, `op[4..5]`, `op[6..7]`, `op[8..9]` | 10 |
| `4` | `0x583e` | `0x40`–`0x72`, minus `0x40` | 3 fields, then an I2C apply/verify | explicit 16-bit pairs `op[2..7]`, then `FUN_00006174` | — |
| `5` | `0x5970` | `0x80`–`0xB2`, minus `0x80` | 1 field `ch*4+3` | explicit 16-bit big-endian pair `op[2]<<8|op[3]` | 4 |

Three channel banks of `0x33` (51) channels each are therefore addressable — `0x00`, `0x40` and `0x80` — and
each opcode names the bank it targets. Opcode `4` additionally **applies and verifies**: `FUN_00006174` writes
its three fields and then talks to the device at **I2C address `0x69`, register `0xB4`**
(`FUN_00017a24(0x69,0xb4,buf,1)`), waits (`FUN_00018d9c(...,100)`), and builds a reply — the same `0x69`
address family the charging path uses (§7.4d). Note that opcode `4` is the one branch that does **not** advance
the block cursor, which is either a deliberate alias or a firmware bug and is worth care if reimplementing.

So a PSoC type-`0` message is a **scripted bulk hardware-field writer**: a sequence of `{opcode, channel,
operands}` blocks, up to 51 channels per bank in three banks, values either given explicitly as 16-bit
big-endian pairs or looked up in a 512-byte table, and every write performed through a read-back-confirmed
11-bit field writer. That is the shape of pushing an LED or key-matrix driver's whole state from the host in
one message, and `leddriver.c` is in this image's source tree.

**The lookup table at `0x1add8` does read as a curve — I had concluded the opposite and was wrong.** An
earlier version of this section recorded that its contents "do not read as a monotonic brightness curve"
because the first values are `0x0000, 0xf883, 0xf884, …`. Dumping all **256** entries and looking at their
structure rather than the first three settles it: the table is a **piecewise-linear ramp**.

| index | value | masked to the 11-bit field the writer uses |
|---|---|---|
| `0` | `0x0000` | `0x000` — **off** |
| `1` … `18` | `0xf883` … `0xf894` | `0x083` … `0x094`, step **+1** |
| `19` | `0x0001` | **exception entry** (see below) |
| `20` … `145` | `0xf896` … `0xf93a`, step **+1** | |
| `147` | `0x0001` | **exception entry** |
| `148` … `254` | step **+3** per entry | |
| `255` | `0xfbff` | `0x3ff` — **full scale (10-bit maximum)** |

So: index `0` is off, the ramp runs from `0x083` to `0x3ff` in **two linear segments** (slope `1` then slope
`3`), and the top of the range is `0x3FF` — the maximum of a **10-bit** duty value, not the 11-bit mask the
writer applies. That is the shape of a **duty/brightness curve with a minimum floor** (`0x083`, so the LED
never goes fully dim at non-zero input) and a two-segment response, which is what the three lookup-driven
opcodes `0`–`2` need in order to write a field per channel from a raw input byte.

Two entries are `0x0001` and sit *inside* the ramp, with the ramp skipping the values they replace
(`0xf895` and the next one are absent). Those are **exception entries**, and I have not identified what they
mean — they are the one part of this table still unexplained.

**Still flagged, not claimed:** which peripheral owns the 144 fields (LED driver vs keypad matrix — the
`x+2, x, x+1, x+3` index order suggests hardware wiring, but that is an inference), and what the two `0x0001`
exceptions in the curve are for.

A second, useful detail from the same handler: **type `1` (`FUN_000057ee`) sets a flag then calls the default
handler** (`*(DAT_00005ab4 + 0x30) = 1; FUN_000047b4();`), and type `2` (`FUN_000055e6`) *builds replies*
rather than acting on the request — it allocates records with `FUN_000140d4(9,9)` and `FUN_000140d4(1,10)` and
fills a 9-byte status/reply payload byte by byte (bytes `0,1,0,2,0,0x1a,0,0,4`), then reads a device id from
flash (`DAT_00005784`, 0x13 = 19 bytes) and a 64-bit value assembled from byte globals, and finally calls
`FUN_000068f6`, which does not return.


### The PMIC reset-reason table is real

The reset-reason lookup at `0x18862` (found in the code region, not the pool) is a genuine code-side table of
pointers into the `Last PMIC reset reason: …` strings. It confirms that the §7.4 vocabulary is not merely a
set of printf formats: each reason is a **distinct runtime branch**, which is exactly what makes those strings
diagnostically useful in the field.

## 7.5 The engine modules (`.engine`): container and module ABI

The 21 factory engines are **Blackfin+ relocatable modules**, and they had never been opened — only their
export magic had been recorded. The container and the module ABI are now decoded, which matters for the MIDI
question (§7.6): this is where note events *end up*.

**Container layout**, read from all 21 files (the size in the header is `file size − 16` in every one of them,
which is what pins the header down):

| offset | field | evidence |
|---|---|---|
| `0x00` | `0x00 0x50` then a per-engine byte at `0x02` and the constant `0xAD` at `0x03` (byte view — see below) | `0x50` and `0xAD` constant in all 21 |
| `0x04` | `0x11a00000` — the **L1 instruction destination** | constant in all 21; this is the Blackfin's L1 code space |
| `0x08` | `0` | |
| `0x0c` | **payload length** = file size − 16 | exact in all 21 (e.g. `chord` `0xa60`, `ep` `0x3b34`, `organ` `0x276c`) |
| `0x10` | `0x00 0x00`, a per-engine byte at `0x12`, the constant `0xAD` at `0x13` | |
| `0x14` | the engine's **link-time payload address** (`0x81bxxxxx`) | `0x81be2400` for `chord`, `0x81b32000` for `ep` |
| `0x18` | `0x38` | |
| `0x1c` | `0` | |
| `0x20` | magic `0xfeed0ad1`, `0xad1facef` | present in all 21 |
| `0x28` … | **export table**: `(name_ptr, target)` `u32` pairs, terminated by a zero pair | 5 entries per engine |

**The module ABI is five exported functions.** Parsed across all 21 engines — `initModule` 21, `init` 21,
`onNoteOn` 21, `onNoteOff` 21, and `render` 13 / `renderFX` 8 — the union is exactly:

| export | meaning | notes |
|---|---|---|
| `initModule` | module/class initialiser | all 21 |
| `init` | per-voice/per-instance initialiser | all 21 |
| `render` / `renderFX` | the audio render entry | **13 engines export `render`, 8 export `renderFX`** (21 total) — two spellings of the same slot, not two different capabilities |
| `onNoteOn` | **note-on** entry point | all 21 |
| `onNoteOff` | **note-off** entry point | all 21 |

So an engine is loaded, initialised, rendered per audio block, and receives note events through
`onNoteOn`/`onNoteOff`. That is the **terminus of the MIDI/note path** — which is the concrete reason the
per-opcode semantics of the two ranged MIDI families are not in `opz.ldr`: what a message *does* downstream
is spread across 21 independently-built DSP modules behind this ABI, not in one command table.

**How to analyse an engine** (recipe, since the base is not obvious and getting it wrong is the same silent
failure as the BLE image):

```bash
# derive the base: find the "initModule" / "init" string in the file and subtract its offset
# from the name pointer in the export table at 0x28, e.g. for chord.engine:
#   name_ptr 0x81be2d90, "onNoteOff" at file 0x9f8  -> base 0x81be23c0
analyzeHeadless /tmp/eng-proj ENG -import chord.engine \
    -processor blackfinplus:LE:32:default -loader BinaryLoader -loader-baseAddr 0x81be23c0
```

Validation, not assumption: with that base **all five export name pointers land on their name strings** and
the five targets decode as Blackfin+ code. Example dump at the target of `onNoteOff`'s neighbour:

```asm
0x81be2444  Linkage UNLINK
0x81be2448  LdImmToReg R0 = 0x0 (X)
0x81be244a  Return RTS                 ; a "return 0" stub, i.e. an optional hook
0x81be2438  CompRegisters CC = R0 == R3   ; the real entry next door branches over it
```

and `onNoteOn` (`chord`, base `0x81be25dc`) decompiles into heavy fixed-point DSP arithmetic (64-bit
multiplies and saturation via helpers such as `FUN_81be2b3a`) — which is what a note-on in a synth module
should look like.

**The two `0xadXX` fields are not checksums — tested, and the test is what settles it.** Reading the header as
bytes rather than dwords changes the picture: across all 21 engines the bytes at `0x03` and `0x13` are
**exactly `0xAD` in every file**, while the bytes *before* them (`0x02`, `0x12`) vary per engine. So each
`0xadXX` pair is really `{varying byte, constant marker 0xAD}`, and a field whose high byte never changes
cannot be checksum data. The constants across all 21 files are:

| offset | value | |
|---|---|---|
| `0x00`, `0x01` | `0x00`, `0x50` | constant |
| `0x02` | varies per engine | unidentified |
| `0x03` | **`0xAD`** | constant marker |
| `0x12` | varies per engine | unidentified |
| `0x13` | **`0xAD`** | constant marker |

I then tested the two varying bytes against ~100 candidate derivations — 8-bit sum, XOR, five CRC-16 variants
(both bytes), CRC-32's four bytes, Adler-32's two bytes, and the region length — over eight regions of each
file (whole file, payload, header, export table, post-header code, first/last 4 KB, last 256 bytes). **No
function matched more than one engine**, so the 14 scattered coincidences are noise, not a scheme. Also ruled
out: the firmware's own metadata for these engines — `system/content/settings/plugs_patch.json` gives
`engine.version = 1` for all five engines it lists and plug versions `25/9/2/7/6`, none of which appear in the
header.

So they are **build/type identifiers, not integrity fields** — and one weak signal on their meaning: `chord`
and `cluster` are the only two engines sharing a `0x02` value (`0x26`), and both are chord-family instruments,
which suggests a **family/type code**. That is a hypothesis, not a finding, and is labelled as one.

**Further derivations tested and excluded** (all 21 engines): neither byte is the file size low or high byte,
the payload size in either half, the export count (5 for every engine), or a byte of the link-time address —
each candidate matched **0 of 21** except one incidental hit each for three of them, and the two bytes are never
equal to each other. A code-derived value (a build id or a hash over the module) now looks most likely, which
is exactly the kind of thing that cannot be confirmed without TE's build tooling.

**Honest limits.** The payload's file-offset-to-address offset is **not** a constant: it is `0x40` for 19
engines, `0x1C` for `ep.engine` and `0x14` for `organ.engine`, so the base must be derived from the name
pointers rather than computed from the header. The `0x18`/`0x1c` fields (`0x38`, `0`) are still uninterpreted.
And the export *bodies* are read only for `chord`; the other 20 engines decompile on demand at
`<base> + target_offset`.

## 7.6 Why this matters for the MIDI question

Doc `05` §5.7 records that the Blackfin OS's two MIDI ring buffers are **written but never drained** by any
code in `opz.ldr`, and that neither the engines nor the peripheral binaries reference the queue addresses.
This document closes off the peripheral binaries as candidates: the Nordic image is a self-contained ARM
Cortex-M4 with its own memory map (**SRAM at `0x20000000`**, vector table at `0x23000`), and the PSoC image is
likewise a separate Cortex-M3 at `0x20004000`/flash `0x19xx`. **Neither has any way to address the Blackfin's
`0x819cf64c` / `0x819d06a0`** — they are different chips with different address spaces.

That converts a suspicion into a closed question: the drain site for those two queues is **not** in
`opz.ldr`, **not** in the engines, and **not** in the companion processors. The remaining explanations are
that the queues are vestigial in 1.2.43, or that the drain is a further analyser-swallowed function — and
doc `05` §5.7 already shows such swallowed functions exist in exactly that region.

**And the engines cannot be the answer either, for a second reason now established in §7.5:** an engine's
interface is the five-function module ABI (`initModule`, `init`, `render`/`renderFX`, `onNoteOn`, `onNoteOff`),
with note events arriving as `onNoteOn`/`onNoteOff` calls — there is no per-opcode MIDI command table in an
engine to find. Whatever the ranged MIDI families mean, they mean it *before* this ABI, in code that is not in
the image. So doc `05`'s opcode map is the end of what static analysis can deliver, and that is a property of
the firmware, not of the effort spent.

## 7.7 What is not established here

- **The BLE image's message handler is read end to end** (§7.2b/§7.2c/§7.2d): the dispatcher
  `FUN_00028aa4`, the 129-entry table at `0x28af8`, all 20 populated types, both table-bypass side paths
  (type `4` → the BLE-OPZ channel; types `0x11`/`0x12` → raw staging/checksum), **and the installation chain**
  that calls it through the SRAM slot `0x20006320` (`FUN_00027688` → `FUN_00029bb4` → `FUN_0002894c` →
  `FUN_00027eb8` `blx`). What is **not** established: the per-field meaning of the 0x218-byte event records the
  state machine passes in. The transport layer below it (`FUN_00027eb8`) is documented in §7.2e in **both**
  directions — the SOF/escape framing, header layout and id allow-list on receive, and the 1 KB UART output
  ring, 255-byte chunking and four error strings on transmit.
- **The PSoC image is decompiled at the dispatch level and partly at the handler level** (§7.4c/§7.4d): the
  load-base bug is fixed (387 functions instead of 203), the table is walked (**146 types, 39 implemented**,
  real function pointers), the shared pipeline is read (`FUN_000140d4` slot allocator, `FUN_00018a88` task
  primitive, `FUN_000047b4` default handler). **All 39 handlers are now classified by the subsystem they
  drive** (power state / charger / PMIC / USB-PD / I2C recovery), **four bodies are read in full** (types `0`,
  `1`, `2`, `137`, including the nested 6-entry sub-command table at `0x1adc0`), and **three handlers are
  pinned by a literal string** (identity reply, I2C SDA unblock, character table). **Type `0`'s sub-command
  set is enumerated** (6 opcodes with their block format, banks, value sources and lengths). What is not done:
  reading the remaining 35 handler bodies line-detail.
- The `.cyacd` trailer algorithm is **not** identified (§7.4) — but the item is closed in the way that
  matters: the firmware verifies the **zip entry CRC** of each extracted file, and the CYACD parser (hex
  decoder `FUN_82803cf8`, 1536-byte line reader `FUN_82803e46`, per-record step `FUN_8280313a`) **decodes the
  trailer as text but never compares it**, taking the payload as a fixed 256 bytes. **Two exhaustive sweeps
  found no match**: 24 combinations first, then a 360-combination grid over all 445 rows (18 algorithms — the
  Cypress SUM, the Cypress reflected CRC-16/`0x8408` with every complement/byte-swap variant, CRC-16/`0x1021`
  likewise — × 5 byte scopes × 4 trailer alignments) produced only two single-row coincidences, **and a third
  sweep of ~50 arrangements of the vendor's own documented row-checksum rule (`2's complement of ArrayID +
  RowNum + Size + Data`, row number big-endian) matched no row at all**. So the trailer is Cypress-side and need
  not be reproduced to install a keyboard image; three independent formula families now fail on real data.
- **`.cyacd2` is an accepted second extension** (§7.4) with its own decode branch in `FUN_82803efc`; nothing in
  these four images uses it, so what it changes about the format is unknown.
- **The updater's letter-command dialect is structurally mapped but unnamed** (§7.4): five U32-argument commands
  driven by a second session implementation (`FUN_828031ee`/`FUN_8280341e`/`FUN_8280326c`) that requires replies
  to begin with the `@EIV:` banner. Whether that dialect targets the plug-in module is an inference.
- **The PSoC's `0x1add8` lookup table is a curve, not a mystery** (§7.4c): 256 entries, index 0 = off, then a
  piecewise-linear ramp `0x083`→`0x3ff` with slopes 1 and 3 — a duty/brightness curve with a floor. Two
  `0x0001` **exception entries sit inside the ramp and are unexplained**; that is all that remains of this
  item.
- **The PSoC message *semantics* are mapped per type, with bodies read for a subset.** All 39 types are
  classified by subsystem and their **reply types are read from the `FUN_000140d4(length, type)` call sites**
  (§7.4c), and eleven handler bodies are now read in enough detail to state their action (types `0`, `1`, `2`,
  `18`, `128`, `137`, `145`, plus the sub-command set of type `0`). The remaining bodies are at known
  addresses and decompile on demand; what is not established is the *content* of the replies whose source is
  runtime SRAM (e.g. the 8-byte blob at `0x200039b8`).
- The protobuf field semantics in §7.3 are **inferred from shape** (a 32-byte digest, a 64-byte signature),
  not from a schema. The field numbers are exact; their names are not.
- **Where the Blackfin consumes the PSoC's recorded power mode is unlocated** (§7.4c): the five writes are at
  known addresses and the two companion-triggered shutdowns are read, but no reader of `DAT_815c94ac` /
  `DAT_81004750` was found, and the byte-scan cross-check is invalid for Blackfin+ split constants.
- **The engine container is decoded but not fully interpreted** (§7.5): the export ABI and the payload
  length are verified and the two `0xadXX` fields are **shown not to be checksums** (the `0xAD` byte is
  constant across all 21 files while the preceding byte varies, and ~100 candidate checksums over eight
  regions matched at most one engine each). What the two varying bytes mean — probably a family/type code,
  since `chord` and `cluster` share one value — is **unidentified**, as are the `0x38` field and the varying
  payload file→address offset (`0x40`, `0x1C`, `0x14`).
  Engine export bodies are decompiled for `chord` alone; the other 20 are at known bases.
- The 128-bit value at `0x34bac` (file `0x11bac`) is a **candidate** BLE UUID, not a confirmed one (§7.2).

### What *is* now established, and worth not re-deriving

To be explicit about the boundary, since it moved substantially during this work:

| | Blackfin OS | Blackfin bootloader | BLE (nRF52832) | PSoC 5LP |
|---|---|---|---|---|
| container format | ✅ doc `01` | ✅ doc `01` | ✅ §7.2 | ✅ §7.4 |
| load base derived | ✅ | ✅ | ✅ `0x23000` | ✅ `0x1900` (2 bytes stripped first) |
| functions recovered | 1,995 | 1,389 | 342 | **387** |
| dispatch table mapped | ✅ doc `03` | ✅ doc `03` | ✅ §7.2b (129 entries) | ✅ §7.4c (146 types) |
| dispatch table kind | function pointers | function pointers | **`switch` jump table** (109-hit default = epilogue) | function pointers |
| decompiled case bodies | ✅ | ✅ | ✅ 20 of 20 types (2 side paths left) | ✅ 4 of 39 handlers (nested table included) |
| behaviour documented | ✅ | ✅ | ✅ decompiled handlers (§7.2b) | ✅ via strings + dispatch |

And the **load bases**, which are the thing that silently breaks a raw-binary import:

| image | load base | how it was derived |
|---|---|---|
| `opz.ldr` | loader-supplied | Blackfin+ boot-stream loader |
| `bootloader.ldr` | loader-supplied | same |
| `nrf52832_opz.bin` | **`0x23000`** | `Reset` vector and 47/48 vector entries land in the image; 129 stored words land on exact string starts (0 at `0x20000`, control max 25) |
| keyboard `kb_DVT2.bin` | **`0x1900`** after stripping the leading 2 bytes (raw: `0x18FE`) | `Reset` = `0x1911` lands on `push {r4,lr}`; literal pools become 4-aligned; functions recovered go 203 → 387 |
