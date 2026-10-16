# 04 — Hidden features, debug hooks and undocumented commands

Everything here is recovered from the decrypted `opz.ldr` (OS 1.2.43) by decompilation. Addresses are
Ghidra addresses; the OS image maps with base `0x80f5aad8` for file-offset conversions.

## 4.1 The undocumented configuration command channel

There is an **undocumented text command channel** that is not part of the public serial console command
set and not exposed in the app. It is dispatched by a single function, **`FUN_80040922`**, which is
`Midi.cpp`'s MIDI-message handler. The commands ride inside a MIDI **SysEx-like** message and are
matched with `strcmp`.

### The carrier message

From the decompiled conditions, the command frame is:

| byte | value | meaning |
|---|---|---|
| `[0]` | `0xF0` | SysEx start (`*param_2 == -0x10`) |
| `[1]` | `0x00` | manufacturer / group |
| `[2]` | `0x20` | space — **the command-class discriminator** |
| `[3]` | `0x76` (`'v'`) | version marker |
| `[4]` | `0x01` | sub-command: **text command** |
| `[5]` | `0x62` (`'b'`) | sub-command: **configuration command** ← the hidden set |
| `[6]` | checksum | verified: `param_2[6] == (~len) & 0x7F` |
| `[7..]` | ASCII | the command name, NUL-terminated in a 32-byte stack buffer |

Three constraints the code enforces:

1. **`(~min(total-6, 0x20)) & 0x7F` must equal the byte at `[6]`.** So `[6]` is a
   **length-complement**, the command text is capped at **31 characters + NUL**, and the length used for
   the copy is the *clamped* value — so an over-long message is truncated rather than rejected. If the
   check fails the handler logs **`NOPE! %d != %d`** and does nothing.
2. The command name is `strcmp`'d against a fixed table — unmatched text is silently ignored (no log).
3. `0x61` (`'a'`) in `[5]` is a separate branch calling `FUN_80107b10`; `0x66` (`'f'`) is a
   `FUN_8011a528` path that stores `param_4` into `DAT_81018324` and calls through
   `*DAT_819c3ab4` — i.e. a **dispatch pointer**, the closest thing here to an indirect command hook.

### The command table

Each name sets one global flag. This is the full recovered table:

| command | line | effect | global |
|---|---|---|---|
| `enable-debug` | `0x4ca` | enable debug mode | `DAT_81113a60 = 1` |
| `disable-debug` | `0x4ce` | disable debug mode | `DAT_81113a60 = 0` |
| `enable-verbose-log` | `0x4d4` | verbose logging on | `DAT_815c8724 = 1` |
| `disable-verbose-log` | `0x4d8` | verbose logging off | `DAT_815c8724 = 0` |
| `enable-controller-mode` | `0x4dd` | controller mode on | `DAT_81018318 = 1` |
| `disable-controller-mode` | `0x4e2` | controller mode off | `DAT_81018318 = 0` |
| `enable-battery-log` | `0x4e8` | battery logging on; also calls `FUN_80129808(3, …)` | `DAT_81018319 = 1` |
| `disable-battery-log` | `0x4ed` | battery logging off | `DAT_81018319 = 0` |
| `enable-uart-log` | `0x4f2` | redirect log to UART via `FUN_8002c2c6(1)` | — |
| `disable-uart-log` | `0x4f9` | `FUN_8002c2c6(0)` | — |
| `debug-crash` | — | arm a deliberate crash (no log line) | `DAT_8101831a = 1` |
| `debug-save` | — | arm a debug save (no log line) | `DAT_8101831b = 1` |
| `restart-into-bootloader` | `0x50f` | logs `restarting into bootloader`, then reboots to the bootloader | `DAT_81003e81=1; DAT_81003e80=1` |
| `restart-into-content` | `0x517` | logs `restarting into content mode`, **creates `/yaffs2/contentmode.plz`** via `FUN_80128b50`, then restarts | `DAT_81003e82=1; DAT_81003e80=1` |
| `restart-into-synth` | `0x521` | logs `restarting into synth mode`, then restarts | `DAT_81003e82=1; DAT_81003e80=1` |

`DAT_81003e80` is the **reboot request** flag; `…e81`/`…e82` select the target mode. The `0x50f`/`0x517`/
`0x521` values are the **`Midi.cpp` source line numbers** passed to the logger. That reading is supported
by the sequence itself: the whole block's values rise monotonically (`0x4ca, 0x4ce, 0x4d4, 0x4d8, 0x4dd,
0x4e2, 0x4e8, 0x4ed, 0x4f2, 0x4f9, 0x50f, 0x517, 0x521`) with gaps of 4–10 lines between adjacent
commands, exactly as a single file's `switch`/`if`-chain would be arranged. So each command can be placed
at a specific line of `Midi.cpp`, and the two debug commands sit between them — `debug-crash` and
`debug-save` are handled at the tail of the table without a log line.

### Why this is significant

- **`restart-into-content` is a supported, documented-by-code way to enter content mode from the running
  OS**, and it does so by dropping the marker file `/yaffs2/contentmode.plz` — the same marker the
  bootloader checks. This is a *software* route into content mode, so it does not need the key combo,
  and (unlike the volume-eject path) it is not the import path that can strip `/yaffs2/user/engines/`.
- **`restart-into-bootloader` gives a software route into update mode** — directly relevant to the
  recovery work, since update mode is where the `0x19` file read-back and the zip-entry-path updater
  primitive live.
- **`enable-uart-log` / `disable-uart-log`** switch the log stream to UART. This is the switch that
  decides whether logs appear on the serial console at all, and it is the kind of flag that explains
  "the console is silent" symptoms.
- **`debug-crash` / `debug-save`** are deliberate fault-injection hooks used by the developers. They
  have no user-facing log line.

> ⚠️ **Never send `restart-into-bootloader` or `debug-crash` to a working unit casually.** The restarts
> change device mode mid-session, and `debug-crash` intentionally faults the OS. Both are recoverable
> in principle (the bootloader survives) but neither is a safe default. Treat this section as
> documentation of what the firmware *contains*, not as a to-do list.

## 4.2 Related MIDI configuration vocabulary

The same `Midi.cpp` region defines the `config/midi.json` keys, which the app can set but which are not
surfaced anywhere in the UI:

```
channel_one_to_active     timing_clock_in       timing_clock_out
alt_program_change        enable_program_change parameter_cc_out
incoming_midi             outgoing_midi         midi_echo
track_channels            track_enable
```

`snakemidi` is the module name. `xcx0312p1.0.8` is a stray version/identifier string.

## 4.3 Developer debug vocabulary found elsewhere

The `restart-into-*` commands are not the only developer hooks. The string pool also carries:

**`how_to_upgrade.txt` / `upgrade` / `battery` log targets** in the bootloader, plus these OS-internal
names that read as developer-only features (in the `Midi.cpp` / `ContentManager.cpp` neighbourhood):

```
profiles     config       channels      fixture     profile      ← DMX (DmxController.cpp)
userPresets.dat
/one_sample_pack_per_slot.plz
wav|aif|aiff|engine                                     ← the sample importer's extension filter
op1 synth patches are not supported                     ← see 4.4
```

## 4.4 Easter egg: OP-1 patch import is explicitly rejected

`ContentManager.cpp` contains the message:

```
op1 synth patches are not supported
```

Accompanied by a tight cluster of rejection strings:

```
unsupported file type
invalid meta data
invalid drum sample pack
invalid synth sample
unsupported sample rate
```

This is notable for two reasons. First, it confirms that somebody *tried* to import OP-1 synth patches
into an OP-Z — enough that the developers added an explicit, named rejection rather than a generic
parse failure. Second, it establishes the importer's validation gates in one place, which is exactly
what you need to know when building content: the device checks file type, metadata, a
drum-vs-synth pack distinction, and sample rate.

The importer's own working filter is `wav|aif|aiff|engine`, and it looks for
`/one_sample_pack_per_slot.plz` to enforce the one-pack-per-slot rule.

## 4.5 Internal naming: the project is called "snake"

Recovered source paths (see `01-ldr-format-and-image-layout.md`) show the internal codename:

```
C:\snake-software\...
C:\snake-software\snake-synth-bf\...
\snake-software\bootloader\...
SnakeKeyboardModule_EVT4.cyacd
SnakeKeyboardModule_DVT2.cyacd
```

`synaesthesia` (`SnakeSystem.cpp`) and `snakemidi` (`Midi.cpp`) continue the theme. The keyboard module
firmware ships in two builds, **EVT4** and **DVT2** — engineering-validation and design-validation
bring-up stages, which is why the `0x02` version reply on this unit reports `dsp hw revision: dvt2`.

## 4.5c A boot-triggered auto-install hook: `/yaffs2/firmware_auto.zip`

The bootloader installs an update **because a file exists**, not because a mode was entered. Decompiling the
tester (`FUN_82824d46`) shows the whole condition: open `/yaffs2/firmware_auto.zip`; if it is there, log
`found auto upgrade, upgrading`, run the upgrade, log `failed to upgrade` on failure, **delete the zip**, log
`Upgrade complete` and reset. There is no key combination, marker or version query in the trigger.

That makes it reachable from the update volume with the write primitive doc `03` §3.3 documents: entries are
extracted to `/yaffs2/upgrade/<name>`, so a single entry named **`../firmware_auto.zip`** places the file on the
hook. The practical consequence is that an update can be made **self-installing on the next boot** — which is
exactly how the OP-Z's own factory/OTA-style updates can be staged, and also why this is worth knowing when
reasoning about what a careless zip can do. The payload still faces the normal upgrade validation and
per-entry zip CRCs, and only the Nordic component carries a signature (doc `07` §7.3).

## 4.6 Hidden entry points on the *companion* chips

This document is written from the Blackfin OS, but the same class of finding exists on the other two CPUs.
They are listed here so that "hidden features" is not read as a Blackfin-only claim; the decompiled evidence
is in doc `07`.

| chip | hidden entry point | how it is reached | evidence |
|---|---|---|---|
| nRF52832 BLE | **factory mode**, enabled by the magic word **`0xBEBAFECA`** | message type `0x09` carries the 32-bit word in its payload; the handler sets the factory flag and logs `Enabling factory mode`. Type `0x80` then writes the factory configuration (`Not in factory mode.` when refused) | `FUN_00028aa4` case `9`, doc `07` §7.2b |
| nRF52832 BLE | **Bluetooth Direct Test Mode** over the normal message path | types `0x19` (enable) and `0x21` (command) drive `dtm_init` / `dtm_set_txpower` / `dtm_cmd(freq,length,payload)`; this is radio-test firmware normally reached only by a debugger | doc `07` §7.2b |
| nRF52832 BLE | **device-id / serial provisioning from a host string** | type `0x08` `strtok`s a `key:value;` payload on `;` and `:`, key `serial`; errors name the exact failure (`Serial %s of incorrect length (%d)`) | doc `07` §7.2b |
| nRF52832 BLE | **LED control and a setter into SRAM** | type `0x24` bit-reverses the low three bits of its payload into the LED driver; type `0x25` stores a byte at SRAM `0x20003d30` | doc `07` §7.2b |
| PSoC 5LP | **hardware field-write script** for 144 registers across three 51-channel banks | message type `0`, a sequence of `{opcode, channel, operands}` blocks; opcode `4` additionally applies/verifies over I2C at address `0x69` register `0xB4` | doc `07` §7.4c |
| PSoC 5LP | **I2C bus recovery** reachable as a message | type `6` calls the SDA-unblock escape hatch and logs `Can't unblock the SDA, something is hogging the line, and it's not a chips` | `FUN_000155c6`, doc `07` §7.4c |
| PSoC 5LP | **liveness/heartbeat** toward the host | type `145` answers `0x92 0x62 0x00`, stamps a `0xffffffff` sentinel and refreshes a timing window | `FUN_000047f0`, doc `07` §7.4c |
| PSoC 5LP | **system reset by magic word `0xDEADBEEF`** | message type `112` with a 4-byte payload `DE AD BE EF` writes `0x05FA0004` (VECTKEY \| SYSRESETREQ) to the Cortex-M `AIRCR` at `0xE000ED0C`, then replies `(8, 0x28)` — a software reset anyone who can send the frame can trigger | `FUN_00004f3c`, doc `07` §7.4c |
| PSoC 5LP | **debug flags setter** | type `144` stores a 16-bit value and logs through `FUN_0001006c(…, 0x280, "Set debug flags %d")` | `FUN_00004a92`, doc `07` §7.4c |

**A note on direction, because an earlier draft of this section got it wrong.** The Blackfin's own
`command_handler_kb.cpp` (the handler for PSoC messages) logs `PSOC requested SER_MSG_POWER_MODE_REQUEST_ACTIVE`
and four siblings, plus `Unknown power mode requested: 0x%02x`. So for that path the **PSoC originates** the
power-mode request and the Blackfin records it in `DAT_815c94ac`, while the PSoC's own type-`20` handler is a
*receive* path that sets its own state byte. The same `0x10`–`0x18` enum therefore travels in **both**
directions between the Blackfin and the PSoC, and the Nordic BLE image handles the same five codes in its type
`6`. What is shared is the enum and the 9-slot dispatch shape, not a one-way message. Details and the mirrored
tables are in doc `07` §7.4c.

**The companion that watches the power supply can shut the unit down.** `DAT_81003e80` — the OS's
restart/shutdown flag, the same one the hidden `restart-into-*` commands set (see the table in §4.1) — is also
raised when the **PSoC requests power-off or charging** over the companion protocol. So the power/USB-PD
controller can command the main CPU to power down and go to charging, using the OS's own shutdown flag, with no
target flag set (i.e. a plain shutdown rather than a restart into a specific mode). Evidence: the Blackfin's
`command_handler_kb.cpp` power-mode handlers at `0x80131d08` and `0x80131d38`, in doc `07` §7.4c.

That same file also documents the Blackfin→PSoC command vocabulary, which is the PSoC's own console:

| string | meaning |
|---|---|
| `Set button debounce: %d` | setter that sends a 2-byte message (byte `1`, then the value) via the L1 sender `FUN_11a01d24(ctx+4, 0x14, buf, 2, …)` |
| `psoc acc power mode` | the accessory power-mode command |
| `psoc enable ` | power-on/enable path |
| `failed to communicate with psoc` | the timeout path |
| `[%02d:%02d:%02d] charge: %d/100, temp: %dC, current: %dmA, voltage: %dmV` | the charger telemetry format |
| `battery status: removed.` | battery-removal notice |
| `ADC_VALUES` | an ADC dump label |

Two of the rows above are worth calling out as more than trivia:

- **`0xBEBAFECA` is a factory-mode backdoor that needs no key.** It is a magic constant in a message payload,
  not a signature or a challenge: whoever can send that frame can flip the BLE chip into factory mode and then
  write its configuration with type `0x80`. That is a materially different risk posture from the main `.zfw`
  container (AES) or the BLE component's own `.dat` descriptor (which carries a 64-byte signature, doc `07`
  §7.3). **Where the constant actually lives, exactly:** a 32-bit scan finds `0xBEBAFECA` **once per image** — at
  file offset `0x6998` in `nrf52832_opz.bin` (the BLE side that checks it) *and* once in `opz.ldr`, at
  `0x81113ac0`, immediately after the `ScoreContext.cpp` method table (`0x81113a98` + 10 slots), with **no code
  reference to it anywhere in the Blackfin image**. So the Blackfin copy is a data word with no located reader;
  whether it is the BLE magic relayed from the same constant pool or a table-guard value is **not established**,
  and this document does not claim the Blackfin ever sends it. See §4.6b.
- **Direct Test Mode is reachable over the same framing as ordinary messages**, so the radio's test interface
  is not gated behind a separate factory port. Treat both as documented factory surfaces, not as user
  features.

## 4.6b The Score context's hidden command panel: a signal generator and a routing switch

The `ScoreContext.cpp` translation unit installs a context vtable at **`0x81113a98`** — its constructor
`FUN_8012378e` writes that pointer into the object and zeroes the byte at `+4` — and two of its vtable slots are
thin thunks onto functions that are pure hidden-feature surface:

```asm
80123802  method -> FUN_80123274(player, code)     ; the command dispatcher
80123818  method -> FUN_80123568()                 ; the light-slot writer (doc 08)
801237e8  method -> FUN_8012320c(...)
801237aa  method -> if (B[0x81113a60] != 0) FUN_80117b82(0x802ee3c, 2, 0xff)
```

The vtable sits at `0x81113a98`, its `__FILE__` string (`…\src\sequencer\contexts\ScoreContext.cpp`) at
`0x81113b70`, and the context's own state block in between (`0x81113a60`–`0x81113ac8`). Everything below is gated
on `DAT_81113a60 != 0`, i.e. on the **Score context being the active one**, which is why none of it is reachable
from the documented UI.

**A signal generator with a 6 dB step attenuator** (command code `0xc`):

```c
if (code == 0xc) {
  if (DAT_81113a79 == 0) {                       /* off -> on, at 0 dB          */
    DAT_81113a7c = 0;  FUN_80023cc0(&DAT_0801fb40, 0);
    DAT_81113a64 = 1;  DAT_81113a79 = 1;
    LOG("…ScoreContext.cpp", 0x1b6, "Signal generator enabled, gain: 0dB");
  } else if ((int)DAT_81113a7c < -0x3b) {         /* below -59 dB -> off         */
    DAT_81113a64 = 0;  DAT_81113a79 = 0;
    FUN_80023cc0(&DAT_0801fb40, 0);
    LOG("…ScoreContext.cpp", 0x1c3, "Signal generator disabled");
  } else {                                        /* otherwise step down 6 dB    */
    DAT_81113a7c -= 6;
    FUN_80023cc0(&DAT_0801fb40);
    LOG("…ScoreContext.cpp", 0x1bc, "Signal generator enabled, gain: %ddB", DAT_81113a7c);
  }
}
```

So a repeated press steps the gain **down from 0 dB in 6 dB increments**, and past −59 dB the generator switches
itself off: `DAT_81113a7c` is a signed dB value, `DAT_81113a64` the enable flag, and `FUN_80023cc0(&DAT_0801fb40,
…)` reconfigures the audio graph whose context is `0x801fb40`. The three log strings
(`Signal generator enabled, gain: 0dB` at `0x81113bc4`, `… gain: %ddB` at `0x81113be8`, `Signal generator
disabled` at `0x81113c10`) sit in the same rodata window as the `__FILE__`, which is what identifies the owner.

**An audio-routing A/B switch** (command code `0xe`) rewrites four audio-graph connections and flips two GPIO
direction lines, then toggles its own state byte:

```c
if (code == 0xe) {
  FUN_80023a58(&DAT_0801fb40);
  if (DAT_81113a78 == 0) {
    FUN_80023bb8(&DAT_0801fb40, 0xc,  6, 0x80);   FUN_80023bb8(&DAT_0801fb40, 0xc,  7, 0x80);
    FUN_80023bb8(&DAT_0801fb40,   6, 10, 0x80);   FUN_80023bb8(&DAT_0801fb40,   7, 11, 0x80);
    FUN_8002544c(&DAT_0801fb40, 1);
    FUN_8002b3b6(DAT_0801ed7c, DAT_0801ed80);     /* GPIO direction set   */
    FUN_8002b388(DAT_0801ed84, DAT_0801ed88);     /* GPIO direction clear */
  } else {
    FUN_80023bb8(&DAT_0801fb40, 6, 6, 0x80);      FUN_80023bb8(&DAT_0801fb40, 7, 7, 0x80);
    FUN_80023bb8(&DAT_0801fb40, 0xc, 10, 0x80);   FUN_80023bb8(&DAT_0801fb40, 0xc, 0xb, 0x80);
    FUN_8002544c(&DAT_0801fb40, 0);
    FUN_8002b388(DAT_0801ed7c, DAT_0801ed80);     /* the same two, swapped */
    FUN_8002b3b6(DAT_0801ed84, DAT_0801ed88);
  }
  DAT_81113a78 ^= 1;
}
```

`FUN_80023bb8(ctx, from, to, 0x80)` is an audio-graph connection setter, so this is a **two-position routing
switch**: one position sends `0xc` to outputs `6` and `7` and takes `6`/`7` to inputs `10`/`11`, the other sends
`6` and `7` straight through and `0xc` to `10`/`11`. The GPIO pair is the hardware side of the same switch, and
it is the **same two helpers** (`FUN_8002b388`/`FUN_8002b3b6`) that doc `08` §8.5 found behind the light flush —
so "drive a pin" versus "release a pin" is a shared idiom in this image, not a light-specific one.

**The remaining codes**, all requiring the second argument to be `0xffffffff`:

| code | action |
|---|---|
| `0` | `FUN_801231a0()` — zeroes `DAT_81113a68` and `DAT_81113a6c`, then re-sends the mode message |
| `1` | `FUN_801231d4()` — advances `DAT_81113a6c` **modulo 3** and re-sends the mode message |
| `2`, `3`, `4` | `FUN_8012fed6` / `FUN_8012ff1c` / `FUN_8012ff98`, each with `&DAT_81ae5868` — see below |
| `8`, `9`, `10` | toggle bits `1`, `2`, `4` of the byte `DAT_81113a62` |
| `0xb` | toggle `DAT_81059d41` |
| `0xc` | the signal generator above |
| `0xe` | the routing switch above |

The `modulo 3` in code `1` is the compiler's divide-by-constant again (`× 0x55555556`, take the high word,
then subtract three times the quotient — the same idiom as the light engine's modulo-60 tick, doc `08` §8.5), and
`FUN_80123064` *uses* that byte: its argument block takes `uVar1 = 0`, or `0x14` (20) when `DAT_81113a6c == 1`, or
`0x27` (39) when it is `2` — unless `DAT_81113a70 != -1`, which overrides it.

**Codes 2, 3 and 4 are a companion abort/release family, and they identify the sender.** All three are in
**`command_handler_ble.cpp`** (the file that owns the `0x8012fe60` log site, immediately before them) and all
three have the same shape, gated on the state byte at `ctx + 0x3938`:

```c
void FUN_8012fed6(int ctx)                     /* code 2 : notify only          */
{ if (ctx[0x3938] == 0) return;
  FUN_11a01d24(ctx + 4, 0x13, &byte, 1, 0xffffffff, 0, 0xff, 0xff); }

void FUN_8012ff1c(int ctx)                     /* code 3 : + release the buffer */
{ if (ctx[0x3938] == 0) return;
  FUN_11a01d24(ctx + 4, 0x13, &byte, 1, 0xffffffff, 0, 0xff, 0xff);
  if (ctx[0x393c] != 0) { FUN_80040220(DAT_81018320, buf[4], buf[8]); ctx[0x393c] = 0; } }

void FUN_8012ff98(int ctx)                     /* code 4 : + clear ctx[0x4952]  */
{ ... the same, then ctx[0x4952] = 0; }
```

So each sends a **one-byte message of companion type `0x13`**, and codes 3 and 4 additionally hand the pending
message buffer at `ctx[0x393c]` to `FUN_80040220` — the MIDI/SysEx transmitter whose context is
`DAT_81018320` — before dropping the pointer, which is what a transfer **abort** looks like.

That also corrects a reading in doc `08` §8.5: `FUN_11a01d24` is **not** the PSoC's private sender but the
**shared L1-overlay companion sender**, used by both companion handlers — `command_handler_kb.cpp` for the PSoC
(`0x14`, the button debounce) and `command_handler_ble.cpp` here (`0x13`). So a call site alone does not say
which chip receives a message; the **context object** does — see the debug-flag sender below for the case that
settles it, and doc `08` §8.5 for the light flush.

### The command bus, read from the slot map

`FUN_8012378e` is the context's **constructor** (it writes the vtable pointer and zeroes the byte at `+4`), and
`FindXImm` confirms it is the **only** code reference to `0x81113a98` in the image — so the object's method table
can be read straight out of rodata. It is ten slots, and the last three are the hidden surface above:

| slot | address | method |
|---|---|---|
| 0 | `0x81113a98` | `0x801237aa` — the `if (B[0x81113a60] != 0) FUN_80117b82(0x802ee3c, 2, 0xff)` gate |
| 1 | `0x81113a9c` | `0x80122b30` |
| 2 | `0x81113aa0` | `0x801237e8` → `FUN_8012320c(a, b, c)`, the parameter adjuster (`b == 0x26`/`0x27` steps `DAT_81113a70` down/up, clamped to `[-1, 0x27]`) |
| 3 | `0x81113aa4` | `0x80123802` → **`FUN_80123274`, the command dispatcher** |
| 4 | `0x81113aa8` | `0x80122b24` |
| 5 | `0x81113aac` | `0x8011cc04` |
| 6 | `0x81113ab0` | `0x8011cbf8` |
| 7 | `0x81113ab4` | `0x80123818` → **`FUN_80123568`, the light-slot writer** |
| 8 | `0x81113ab8` | `0x80122b10` |
| 9 | `0x81113abc` | `0x80123828` → **the PSoC debug-flag sender** (below) |

**How much of this table is shared, measured.** Counting each slot's pointer across the whole image with a
dword scan: slots **5 (`0x8011cc04`) and 6 (`0x8011cbf8`) appear in 15 tables each** — they are base-class methods
every context's table carries — while slots **0, 1, 3, 4 and 8 occur exactly once each**, i.e. they belong to
this context alone. So the ten-slot table is mostly context-specific, and only the `0x8011cbxx` pair is the shared
layer. Two of the single-occurrence slots (1 and 4) point into the `0x8011cxxx`/`0x80122xxx` cluster that also
holds the shared pair — being *near* a shared method does not make a method shared, and an earlier draft of this
section claimed exactly that before the scan was run.

That count is also what makes the panel *hidden* rather than merely undocumented: **slot 3's wrapper
(`0x80123802`) is the only reference to `FUN_80123274` in the image**, and it sits in exactly one vtable, so the
dispatcher has no other entry point. Reaching it requires the Score context to be the active one and its method
table to be used.

**Slot 9 is the message that names its destination, and it is the anchor for the whole companion bus.**

```c
void FUN_80123828(void)                            /* ScoreContext.cpp, line 640 */
{
  if (DAT_81113a62 == DAT_81113a84) return;        /* unchanged -> send nothing     */
  LOG("…ScoreContext.cpp", 0x280, "send debug flags to psoc: %d", DAT_81113a62);
  uStack_c = (byte)DAT_81113a62;
  uStack_b = (byte)(DAT_81113a62 >> 8);
  FUN_11a01d24(&DAT_0801fb94, 0x90, &uStack_c, 2, 0xffffffff, 0, 0xff, 0xff);
  DAT_81113a84 = DAT_81113a62;
}
```

Three things come out of that. The byte the panel toggles with codes 8/9/10 (`DAT_81113a62`) is mirrored to the
PSoC as a **two-byte word** — `0x90` is the debug-flags message type — but only when it **changes**, tracked
against `DAT_81113a84`. The destination is stated by the file's own log string, so `0x90` is a **PSoC** type
rather than an inference. And the sending context is `&DAT_0801fb94`, which is `0x0801fb90 + 4` — the **same
context the light engine's ticker sends its type-`0x10` flush on** (`FUN_801313f4(&DAT_0801fb90, …)`, doc `08`
§8.5), which is what makes the light flush a PSoC message too.

**The Blackfin→companion message types read so far**, all sent through `FUN_11a01d24(ctx, type, buf, len, -1, 0,
0xff, 0xff)`:

| type | payload | sender | destination |
|---|---|---|---|
| `0x10` | a light-flush packet, up to `0x9a` bytes | `FUN_801313f4` via `FUN_8003d620` | **PSoC** (same context as `0x90`) |
| `0x13` | one byte | `command_handler_ble.cpp` (codes 2/3/4 above) | BLE |
| `0x14` | two bytes `{1, value}` — the button debounce | `command_handler_kb.cpp` | PSoC |
| `0x20` | two bytes `{3, value}` | `FUN_801314d8`, right after the light ticker | not established |
| `0x21` | four bytes — `set mode`, above | `FUN_80123064` (`&DAT_81ae586c`) | not established |
| `0x90` | two bytes — the debug flags | `FUN_80123828` (slot 9) | **PSoC** (named by its own log string) |

The two rows with a stated destination use *different* contexts, so the pair also shows the rule: **the context
object is the destination handle**, and the type is interpreted within it.

**One data constant worth recording, because it corrects a scope.** Immediately after slot 9 sits
`0x81113ac0 = 0xBEBAFECA`, and a `FindDword` over the whole `opz.ldr` finds that value **exactly once** — at that
address, with no split-immediate reference to it anywhere in the Blackfin image. The same 32-bit value occurs
exactly once in the Nordic image as well (file offset `0x6998`), which is consistent with §4.6's factory-mode
magic, but on the Blackfin it is a **data word with no located reader**, and it is adjacent to a vtable. So §4.6
should be read as "the magic the *BLE* side checks": this document does not claim the Blackfin ever sends it, and
whether the Blackfin copy is the BLE magic relayed from here or a vtable-guard constant is **not established**.

The dwords after it are the tail of an array based at `0x81113ac8` and read by the light writer with indices
derived from `DAT_81113a70`: ten consecutive values `0x27` then `0x1e`–`0x26`, i.e. the contiguous run **30–39
with 39 written first**. `DAT_81113a70`'s own clamp maximum is `0x27`, which matches that run's last value, and
`FUN_80123568` uses the **quotient and remainder of `DAT_81113a70 / 10`** as two separate indices into the array
before passing the results to the slot setters as their slot argument. The arithmetic is read; what the run is *for*
(a two-digit display index, a step-key map, something else) is **not established**, and the quotient/remainder
indices would run past the run's start for some inputs, which is one more reason not to name it.

`DAT_81113a62` is the same per-bit flag set the light writer reads — `FUN_80123568` lights slots 8, 9 and 10 when
bits `1`, `2` and `4` are set (doc `08` §8.1's slot API) — so commands 8/9/10 drive three light slots directly.
The slot setters themselves have ~200 call sites across the sequencer (doc `08` §8.7), so this panel is one
contributor among many rather than the reason they exist.

**It also talks to the companion chips.** `FUN_80123064` builds a four-byte argument block from
`DAT_81113a68` (values 1–3) plus an index (`0`, `0x14`, `0x27`, or `DAT_81113a70`), logs `set mode %d %d %d %d` at
`ScoreContext.cpp:326`, and sends it as message **type `0x21`** over the same L1 sender doc `08` §8.5 describes:

```c
FUN_11a01d24(&DAT_81ae586c, 0x21, &uStack_c, 4, 0xffffffff, 0, 0xff, 0xff);
```

and the same file carries the string **`send debug flags to psoc: %d`** (`0x81113c2c`), so this context is a
Blackfin→companion command source in its own right. Two further strings in the same window — `SoloMute`
(`0x81113c4c`) and `StepComponent` (`0x81113d18`) — name UI components of the same translation unit.

**Why this counts as hidden.** Nothing in the official product documentation exposes a signal generator, a 6 dB
attenuator, an audio routing A/B switch or a `set mode` companion message. The whole vocabulary lives in one
rodata window whose `__FILE__` is `ScoreContext.cpp`, the entry points are vtable slots rather than named
commands, and every one of them is additionally gated on the Score context being active.

## 4.7 Method note: how these commands were found

For anyone continuing this work, the technique that worked:

1. **Dump all printable strings** from the imported image, with their Ghidra addresses.
2. Command vocabularies show up as **clusters of `verb-noun` strings** in a region that also contains
   the source path of the file that uses them (`…\src\sequencer\Midi.cpp` sits immediately after the
   `restart-into-*` block). The source-path string is the giveaway.
3. Derive the **linear file→virtual mapping** by anchoring two strings whose addresses are known
   independently (`base = 0x80f5aad8` for `opz.ldr`) and verifying on a third.
4. Search **within function bodies** for the sign-extended immediate of the string address
   (`restart-into-synth` → `-0x7efe7540` at `0x80040de4`). A whole-program instruction walk that
   compares each scalar operand to the target is what finds these; scanning raw bytes for pointers does
   **not** work, because Blackfin+ is a mixed 16/32-bit ISA and these constants are materialised by
   `LdImmToReg` rather than stored as a 32-bit pointer.
5. Decompile the owning function — the dispatch table then reads almost like source.

Step 4 is the one that took the longest to get right, and step 5 is what makes this document possible.
