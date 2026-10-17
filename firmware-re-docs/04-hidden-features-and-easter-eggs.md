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
  features. §4.6b adds a **second, host-side route**: the Score context's `set mode %d %d %d %d` command builds
  the four DTM bytes itself (command, frequency, length, payload) and sends them as message type `0x21`, with its
  frequency selector clamped to exactly `[-1, 0x27]` — the last legal DTM channel.

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
`0x81113b70`, and the context's own state block in between (`0x81113a60`–`0x81113a97`). Everything below is gated
on `DAT_81113a60 != 0`, i.e. on the **Score context being the active one**, which is why none of it is reachable
from the documented UI.

**The state block, read out byte by byte.** Every field below was identified from a read or a write in the code,
and the two packed dwords at the end are what doc `08` §8.1b turns into slot colours:

| address | size | role | evidence |
|---|---|---|---|
| `0x81113a60` | byte | **the active gate** — every command returns immediately without it | 12 references, including `FUN_80040922` (the SysEx dispatcher) and `FUN_8010a29a` |
| `0x81113a62` | byte | the light-slot flag bits `1`/`2`/`4` → slots 8/9/10, **and** the value mirrored to the PSoC as debug flags | the panel's codes 8/9/10, and `FUN_80123828` |
| `0x81113a64` | byte | the signal generator's **enable** flag | set/cleared by code `0xc` |
| `0x81113a65` | byte | a second gate, on the slot writer and on the parameter adjuster | `FUN_80123568`, `FUN_8012320c` |
| `0x81113a68` | byte | the mode/index `1`–`3` that also picks the four-byte argument layout and colour selector | `FUN_80123064`, `FUN_80123568` |
| `0x81113a6c` | byte | a second index `0`–`2`, advanced **modulo 3** by code `1` | `FUN_801231d4` |
| `0x81113a70` | dword | the **DTM frequency** override, clamped to `[-1, 0x27]` | `FUN_8012320c` |
| `0x81113a74` | byte | set to `1` when an **8000-unit timer** expires; read by the `FUN_8002771c` service to decide a companion query | `FUN_8002771c` (SnakeSystem.cpp) |
| `0x81113a78` | byte | the audio-routing A/B state | code `0xe` |
| `0x81113a79` | byte | the signal generator's on/off latch | code `0xc` |
| `0x81113a7c` | signed byte | the signal generator's **gain in dB**, stepped by `-6` | code `0xc` |
| `0x81113a80` | dword | a **packed four-entry colour table** (`1f 0f 5f 2f`), indexed as bytes for slots `0xe`/`0xf` | doc `08` §8.1b |
| `0x81113a84` | dword | the last debug-flags value sent — the change detector | `FUN_80123828` |
| `0x81113a88` | 6 bytes | the name string **`Score`** | rodata |
| `0x81113a98` | 40 bytes | the **vtable**, ten slots | see the slot map below |
| `0x81113ac0` | dword | `0xBEBAFECA`, with no code reference anywhere in `opz.ldr` | §4.6 |
| `0x81113ac4` | dword | the same **packed four-entry colour table**, indexed for slots `0`/`1` | doc `08` §8.1b |
| `0x81113ac8` | 40 bytes | the ten-entry **digit → slot** table `39, 30, 31, … 38` | doc `08` §8.1b |
| `0x81113af0` | table | a jump table whose **every second entry is one shared target**, `0x80122b66` | below |

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
| `0x10` | a light-flush packet, up to `0x9a` bytes | `FUN_801313f4` via `FUN_8003d620` | **PSoC**, index `16` (`0x5818` inside `FUN_000057fa`) |
| `0x13` | one byte | `command_handler_ble.cpp` (codes 2/3/4 above) | **BLE** — index `19` is not implemented on the PSoC |
| `0x14` | two bytes `{1, value}` — the button debounce | `command_handler_kb.cpp` (`FUN_80131700`) | **PSoC**, index `20` (`0x55b4`) |
| `0x20` | two bytes `{3, value}`, `payload[0]` a sub-command | `FUN_801314d8`, right after the light ticker | **PSoC**, index `32` (`0x57ac`; `3` is one of its six populated sub-commands) |
| `0x21` | four bytes — the DTM command, above | `FUN_80123064` (`&DAT_81ae586c`) | **BLE** — index `33` is not implemented on the PSoC |
| `0x90` | two bytes — the debug flags | `FUN_80123828` (slot 9) | **PSoC**, index `144`, `"Set debug flags %d"` |

**The two chips separate cleanly by the PSoC's implemented-type list.** Of the six types, the four whose index
appears in doc `07` §7.4c's 39-entry list are the four the context object already pointed at the PSoC, and the two
whose index is **absent** from that list — `0x13` (19) and `0x21` (33) — are the two independently placed on the
BLE (the first by its source file, the second by the BLE's DTM handler). Two independent signals agreeing on all
six rows is what makes this table usable: **the type byte is a shared enum value looked up in each chip's own
dispatch, and the context object selects which chip**.

The two rows with a stated destination use *different* contexts, so the pair also shows the rule: **the context
object is the destination handle**, and the type is interpreted within it.
**The type byte is a shared enum value, verified on one type and disputed on another.** Type `0x90` is the
strongest cross-image match in this document set: the Blackfin sends a **two-byte** payload under the log string
`send debug flags to psoc: %d`, and the PSoC image's own handler for dispatch index **`144` = `0x90`** is
described in doc `07` §7.4c as *"set debug flags: stores the payload's 16-bit value and logs through
`FUN_0001006c(…, "Set debug flags %d")`"* — same name, same **16-bit** payload width, on the other CPU. So the
two sides number these messages identically, which is what a `src/shared/` header would produce (doc `07` §7.4c
already reaches the same conclusion from the power-mode table).

**The type byte *is* the PSoC's dispatch index — and the one apparent conflict sharpened doc `07` rather than
breaking it.** Three types now line up across the two images, each with the payload shape agreeing:

| Blackfin type | PSoC index | agreement |
|---|---|---|
| `0x90` | `144` = `0x4a92` | `send debug flags to psoc: %d` ↔ the PSoC's `"Set debug flags %d"`, both **16-bit** payloads |
| `0x20` | `32` = `0x57ac` | the Blackfin sends `{3, value}`; the PSoC's index-32 handler indexes a 19-entry table at `0x1ad74` by `payload[0]` and `3` is one of its six populated slots |
| `0x14` | `20` = `0x55b4` | the Blackfin sends `{1, value}`; the PSoC's index-20 handler reads **exactly two** payload bytes |

That third row is the one that looked wrong, because doc `07` §7.4c files index `20` under *"power-state
receive path — sets its own power-state byte and latches it"*. Decompiling it shows why both are true:

```c
void FUN_000055b4(void)                     /* PSoC, index 20 */
{
  _DAT_20000690 = (uint)**(byte **)(unr6 + 4);          /* payload[0]  -> dword at 0x20000690  */
  DAT_200000cd  = (*(byte **)(unr6 + 4))[1];            /* payload[1]  -> byte  at 0x200000cd  */
  FUN_000047b4();                                       /* the shared tail                    */
  uVar1 = **(byte **)(unr6 + 4) - 0x10 & 0xff;          /* payload[0] - 0x10                   */
  *(byte *)(unr7 + 0x58) = *(byte *)(unr6 + 1) >> 4;    /* the record's command nibble         */
  if (8 < uVar1) { FUN_000067cc(); uVar1 = ...; }        /* out of range -> default handler     */
  (**(code **)(DAT_0000577c + uVar1 * 4))();            /* else the 9-entry power table        */
}
```

**The two stores are unconditional**, and only *then* does it interpret `payload[0] - 0x10` as a power mode
through the 9-entry table at `0x577c`. So the handler is a **generic two-byte `{field, value}` setter with an
optional power-mode tail**, and doc `07`'s row described only the in-range case: a debounce payload of `{1,
value}` legitimately lands here, stores its two bytes, and falls to the default handler because `1 - 0x10` is out
of range. Nothing is mis-assigned; the row was incomplete.

**The light flush's receiver is therefore named as well.** Its type `0x10` is index `16`, whose entry is
`0x5818` — the **interior** offset `+0x1e` inside `FUN_000057fa` (one of the 11 shared-body entries doc `07`
§7.4c counts). That body reads `payload[0]` and dispatches through a table under a `5 < uVar1` guard, i.e. six
sub-commands, and the flush's first byte is the **constant `0x00`** that `FUN_8003d1e0` writes unconditionally
(doc `08` §8.4) — so every light update enters **sub-command 0**. That is the most economical explanation of the
otherwise-unexplained zero byte at the head of every flush record, and it is recorded as the reading it is: the
handler's *first* byte is a sub-command selector, which the flush always sets to zero.

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

**It also talks to the companion chips — and the “mode” it sets is a radio test mode.** `FUN_80123064` builds a
four-byte argument block from `DAT_81113a68` (values 1–3) plus an index (`0`, `0x14`, `0x27`, or
`DAT_81113a70`), logs `set mode %d %d %d %d` at `ScoreContext.cpp:326`, and sends it as message **type `0x21`**
over the same L1 sender doc `08` §8.5 describes:

```c
FUN_11a01d24(&DAT_81ae586c, 0x21, &uStack_c, 4, 0xffffffff, 0, 0xff, 0xff);
```

Type `0x21` = index `33`, which is **not** in the PSoC's implemented-type list (doc `07` §7.4c enumerates its 39
types) but *is* one of the **Nordic BLE** image's twenty handlers: *“**Bluetooth Direct Test Mode command** — 4
payload bytes drive `dtm_init()`, `dtm_set_txpower(4)`, `dtm_cmd()` setup-reset, then
`dtm_cmd(freq, length, payload)`”*. The black box's message is therefore a **DTM command**, and every one of its
four bytes lands inside the Bluetooth test parameters:

| byte | what the panel puts there | DTM parameter and legal range |
|---|---|---|
| 0 | `1` or `2` | the DTM command — receive test / transmit test |
| 1 | `0`, `0x14` (20), `0x27` (39), or `DAT_81113a70` clamped to **`[-1, 0x27]`** | **frequency**, `0x00`–`0x27` — the 40 BLE RF channels |
| 2 | `0` or `0x17` (23) | **length**, `0x00`–`0x25` |
| 3 | `3` or `0` | **payload**, `0x00`–`0x07` |

**The frequency field is what proves it.** `FUN_8012320c` (vtable slot 2) clamps `DAT_81113a70` to exactly
`[-1, 0x27]`, and `0x27` = 39 is the *last* legal DTM channel — a bound with no other reason to exist. The panel's
other codes read as the rest of the control: code `1` advances `DAT_81113a6c` **modulo 3**, choosing frequency `0`,
`20` or `39` (the bottom, middle and top of the band), code `0` resets both selectors, and the `0x26`/`0x27` keys
step the frequency up and down one channel at a time.

That makes this a **second, independent route to the radio's test interface**. Doc `04` §4.6 already notes that
DTM is reachable over the ordinary BLE framing; here the *Blackfin itself* computes the four DTM bytes, so the
test surface is exposed on the host side as well, from a context panel whose commands are otherwise about signal
generation and audio routing. And the same file carries the string **`send debug flags to psoc: %d`**
(`0x81113c2c`) and sends it as type `0x90` from slot 9, so this context is a Blackfin→companion command source in
its own right. Two further strings in the same window — `SoloMute` (`0x81113c4c`) and `StepComponent`
(`0x81113d18`) — name UI components of the same translation unit.

**Why this counts as hidden.** Nothing in the official product documentation exposes a signal generator, a 6 dB
attenuator, an audio routing A/B switch or a `set mode` companion message. The whole vocabulary lives in one
rodata window whose `__FILE__` is `ScoreContext.cpp`, the entry points are vtable slots rather than named
commands, and every one of them is additionally gated on the Score context being active.

## 4.6c Songs, chains and bounces are three different things

The word "song" appears in three unrelated places in `opz.ldr`, and separating them matters because only one
of them is the feature the word suggests.

**`RenderSongContext.cpp` is the bounce renderer, not an arrangement engine.** Its rodata block is a WAV
writer end to end: `init bounce: %s` (`0x8111371c`), `RIFF----WAVEfmt ` (`0x81113730`), `finalize bounce,
written %u` (`0x81113744`), `%sbounces/bounce0%d/` (`0x8111377c`), `done writing %llu bytes`
(`0x811137b8`) and `Failed to find available bounce folder. Aborting bounce operation.` (`0x811137d4`), next
to `bounce.wav` (`0x8111363c`), `bounces` (`0x81113660`) and the file modes `rb`/`ab`/`r+b`/`w+b`
(`0x81113610`–`0x8111361c`). The context's own name string `RenderSong` (`0x811135d4`) and its source path
(`0x811136dc`) sit in the same 700-byte window with `Start rendering song` (`0x81113764`) and `Done rendering
song. Writing %s.` (`0x81113794`). So "song" inside that translation unit means **the performance currently
playing**, rendered offline to a RIFF file in a numbered bounce folder — which is the documented "up to five
bounces" feature, not pattern chaining.

**A chain is a first-class synced state.** `ChainState has wrong size.` (`0x8110f29c`) sits inside the
state-synchronisation block `0x8110f1c0`–`0x8110f320`, which is a wall of fixed-size state guards in the same
shape — `PlayState`, `SynthState`, `MixerState`, `PatternState`, `PositionState`, `UiState`, `SamplerState`,
`SamplerUIState`, plus `persistent data has wrong size` and `failed to read global data message`. That is the
companion-sync protocol: each named state is a blob whose size must match between the two ends. So a chain is
a modelled object the device can exchange with its host, even though nothing in this analysis shows it being
edited or played from the device's own UI.

**The sequencer understands MIDI song position.** `received song position pointer %d ` (`0x81059f98`) follows
the `Sequencer.cpp` path string (`0x81059f3c`) immediately after `reset global tick: %d` (`0x81059f80`), so
`Sequencer.cpp` parses Song Position Pointer and reacts to it. A song-position message is meaningless without a
linear timeline to point into, which is independent corroboration that a song timeline exists.

`selectSong %d` (`0x81113394`) is the one string that most suggests a *selectable* song: it sits at the head of
the sequencer-context rodata block that also holds `Pattern` (`0x8111335c`), and that block begins with the
`DefaultContext.cpp` path (`0x8111322c`) whose `set additative record mode` strings follow — so the caller of
`selectSong` is a sequencer context, not the bounce renderer.

**What this does and does not establish.** It establishes that chaining, song selection and MIDI song position
are all modelled in the firmware, and that offline rendering is the bounce path rather than a song-arrangement
path. It does **not** establish a user-reachable song mode: no string here is a UI label, and none of the three
was traced to a key or menu. An earlier reading of this session's own notes treated `RenderSongContext` as a
possible dormant arrangement engine; the WAV-writer block above supersedes that.

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
