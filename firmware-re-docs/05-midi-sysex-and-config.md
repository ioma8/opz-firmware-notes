# 05 — MIDI: the SysEx command surface and configuration

The OP-Z speaks MIDI over USB and BLE, and — importantly for anyone writing a tool — it accepts
**SysEx commands** that are not part of the serial console command set at all. This document maps that
surface from the decrypted OS image.

## 5.1 MIDI subsystem source layout

Recovered source paths (`01-ldr-format-and-image-layout.md`) show the MIDI code is split across three
files, plus the platform layer:

```
src/sequencer/Midi.cpp              the SysEx command handler and MidiEntity management
src/sequencer/SequencerMidi.cpp     sequencer-side MIDI (notes, clock, transport)
src/sequencer/UsbMidi.cpp           USB MIDI transport
src/bf/command_handler_module.cpp   module (companion) MIDI endpoint registration
src/bf/ModuleControl.cpp            module connection state machine
```

Supporting string evidence:

```
MODULE_MIDI
registering module midi endpoint
Unregistering MODULE MIDI endpoint
MidiStreaming
USBH_AudioMIDIMutex
BLE midi
Audio/MIDI device %s: %d
MIDI rx packet too large!
unhandled usb midi packet %02x
MidiEntity list full!
[ Snakemidi ]   (section header in logs)
```

`MidiEntity list full!` indicates a **fixed-size MIDI entity table** — a hard cap on simultaneous MIDI
endpoints, which is the string to watch for if external gear is not appearing as expected.

## 5.2 The SysEx command frame

The handler is `FUN_80040922` in the OS image (base `0x80f5aad8`), which is `Midi.cpp`'s message
dispatcher. It is gated on `*(char *)(param_1 + 0xef4) != '\0'` — i.e. **MIDI input must be enabled for
the channel** before any of this is processed.

### Message classes

`param_2[4]` is the **sub-command selector**, and the two classes that matter are:

| `param_2[4]` | class |
|---|---|
| `0x01` | **identity request** (see below) — requires `param_2[3] == 0x06` |
| `0x02` | **the identity reply / configuration channel** — and this is the class that carries the text command set |

There is also an identity path keyed on `param_2[3] == 0x06` together with `param_2[4] == 0x01`, which
logs `Got identity request from <entity>, <channels>` and marks the entity record. Note this identity
handshake is a **separate message type from the configuration channel** — an earlier draft of this document
conflated them, and the `param_2[4]` values above are the correction.

In the configuration class (`param_2[4] == 0x02`), the handler stores `param_2[6]` and `param_2[7]` into
the entity record, sets a flag when `param_2[7] == 'v'`, and reads `param_2[8]` as a sub-flag. Replies
carry an 8-byte id copied from `param_2 + 9` and a 13-byte name from `param_2 + 0x11`, with a further byte
from `param_2[0x1f]` — that is the fixed-shape identity reply.

The SysEx text-command path is **not** the same class as the two above — it is the `else` arm of
`if (param_2[4] == '\x02')`, so it is reached when `param_2[4] != 0x02`. Its full condition, verbatim:

```c
else if ( (*param_2 == -0x10) && (param_2[1] == '\0') && (param_2[2] == ' ') &&
          (param_2[3] == 'v')    && (param_2[4] == '\x01') ) {
    bVar2 = param_2[5];   /* the opcode */
```

`-0x10` as a `char` is `0xF0`, so the frame is:

| byte | value | role |
|---|---|---|
| `[0]` | `0xF0` | SysEx start |
| `[1]` | `0x00` | manufacturer / group id |
| `[2]` | `0x20` (`' '`) | group / class discriminator |
| `[3]` | `0x76` (`'v'`) | version marker |
| `[4]` | `0x01` | sub-command selector |
| `[5]` | — | **opcode** (table below) |
| `[6..]` | — | payload |

So `[4] == 0x01` in *this* path and `[4] == 0x02` in the configuration-identity path — the same byte means
different things depending on which branch the message matches, which is exactly the kind of detail worth
being precise about when writing a client.

## 5.2b The MIDI input pipeline (how a byte becomes a command)

This document previously started at the SysEx dispatcher. The bytes arrive through a **standard MIDI stream
parser** one layer up, and reading it closes the front end. `FUN_80041048(ctx-related, data, len, ctx, …)` is
the per-byte driver, and the staging buffer lives inside the MIDI context:

| context offset | role |
|---|---|
| `+0` … `+0xFFF` | a **0x1000-byte (4 KB) staging buffer** — one MIDI message, SysEx included |
| `+0x1000` | bytes currently staged |
| `+0x1004` | expected total length for the message being staged |
| `+0x1008` | **"inside a SysEx"** flag |

Its dispatch on each incoming byte:

| byte | action |
|---|---|
| `< 0x80` (data) | append; if `count == 0x1000` the buffer is full → log `Midi message too big. Ignoring.` (`Midi.cpp` line `0x5b2`) and reset count + flag; when *not* inside SysEx and `count == expected` → `FUN_800403c4` (channel-message complete) |
| `0x80`–`0xF7` (status) | if inside SysEx and the byte is `0xF7` → append `0xF7` and call **`FUN_80040922`**, the SysEx dispatcher of §5.3; if inside SysEx with any other status byte → log `Sysex message interupted. Read %d` (line `0x5a9`), clear the flag, then re-handle the byte; otherwise → `FUN_80040614` |
| `≥ 0xF8` (real time) | `FUN_80040310` |

`FUN_80040614` is the status-byte handler and sets the expected length per status nibble — a plain MIDI
length table:

| status | expected | |
|---|---|---|
| `0x80`, `0x90`, `0xA0`, `0xB0` note-off/note-on/poly-AT/CC | **3** | `buffer[0] = status`, `count = 1` |
| `0xC0`, `0xD0` program-change/channel-AT | **2** | as above |
| `0xE0` pitch-bend | **3** | |
| `0xF0` | — | sets the **inside-SysEx** flag and stages `0xF0` as byte 0 |
| `0xF2`, `0xF3` song-position/select | **3**, **2** | |
| anything else | — | logs `unhandled common message 0x%02x` (line `0x5d5`) |

and `FUN_80040310` handles the real-time class:

```c
switch (b) {
  case 0xF8: case 0xFA: case 0xFB: case 0xFC:      /* clock, start, continue, stop */
      lock(); FUN_80022bf8(ctx + 0x2d0, &msg); unlock();   /* forwarded downstream as an 0xA0-tagged message */
      return;
  case 0xFE:  FUN_8003f756(ctx, FUN_800402b8(ctx, ...)); return;   /* active sensing */
  default:    log(Midi.cpp, 0x2ce, "unhandled real_time message 0x%02x", b); return;
}
```

**Two consequences worth recording.** First, the completed-message path and the SysEx path share the same
**MIDI-input gate**: `FUN_800403c4` returns immediately unless `*(char *)(ctx + 0xef4) != '\0'`, the same flag
the SysEx handler checks (§5.3) — so "MIDI input enabled" is one setting, not two. Second, **unlike opcodes,
unrecognised MIDI status bytes *are* logged**: `unhandled common message 0x%02x` and `unhandled real_time
message 0x%02x` fire for anything outside the tables above. So when probing this device over MIDI, an
unhandled *status byte* complains in the log while an unhandled *SysEx opcode* is silent (§5.3) — the two
silences mean different things.

## 5.2c The USB MIDI input path, named

The pipeline above is fed by `UsbMidi.cpp`, and the code that does it sits in a region Ghidra never turned
into functions (`0x8011a…`), which is why it was easy to miss. It is recognisable by its literals:

```
0x81112968  C:\snake-software\src\sequencer\UsbMidi.cpp
0x81112994  USB MIDI message size not multiple of 4: %d!
0x811129c4  USB MIDI SysEx message too large!
0x811129e8  sysex without first packet
0x81112a04  unhandled usb midi packet %02x
```

**The pump iterates USB-MIDI packets.** USB-MIDI transports MIDI as 4-byte packets (cable/CIN byte + three
data bytes), and the loop shows exactly that: a countdown in one register with the packet pointer advanced by
`AddImm P3 += 0x4` per iteration. Every packet is handed either to the stream parser or, when the packet
already completes a SysEx message, **straight to the SysEx dispatcher** — the pump calls `FUN_80040922`
directly at `0x8011ac12` and calls the parser `FUN_80041048` from five other sites
(`0x8011ac68`, `0x8011ac8e`, `0x8011aece`, `0x8011aeec`, `0x8011af40`).

**The five parser call sites all pass the same MIDI context**, `[0x81018320]` — so although there are several
entry points (normal packets, SysEx continuation, reassembled message), there is **one MIDI context and one
staging buffer** for USB input, and the 4 KB buffer of §5.2b is what bounds a SysEx message on this path
(`USB MIDI SysEx message too large!` when the reassembly would exceed it).

Two packet-level failure modes are handled explicitly and are worth knowing for anyone writing a USB-MIDI
driver against the unit:

| condition | diagnostic |
|---|---|
| a packet run whose size is not a multiple of 4 | `USB MIDI message size not multiple of 4: %d!` |
| a SysEx *continuation* packet with no preceding start | `sysex without first packet` |
| a CIN value outside the handled set | `unhandled usb midi packet %02x` (already listed in doc `02`) |

So the input story end to end is: **USB-MIDI packets → packet pump (`UsbMidi.cpp`) → stream parser
(`FUN_80041048`, 4 KB buffer, status-length table, SysEx flag) → `FUN_80040922` (the TE SysEx dispatcher of
§5.3) → engine queue / file manager / text channel**, with the BLE path arriving through the Nordic chip's own
transport (doc `07` §7.2e) rather than this one.

## 5.3 The opcode map at `param_2[5]`

The dispatch branches the opcode into ranges and discrete values. This is the complete recovered set:

| opcode | branch | behaviour |
|---|---|---|
| `< 0x1C` | range 1 | → `FUN_80116f54`, which queues the message (see §5.3.1) |
| `0x2F < x < 0x61` | range 2 | → `FUN_80128f3c`, which queues toward the file manager under a `0x1e0`-offset lock, guarding at `0x138` (312) bytes — **the family is the file-transfer protocol and its opcodes are read in §5.3.2** (`0x33` client heartbeat, `0x34` client request, `0x51`/`0x52` sync + server heartbeat, `0x55` sync state) |
| `0x61` | discrete | increments a single byte counter at `param_1 + 0x39c0a0` — a **tick/heartbeat**, no payload and no reply |
| `0x62` | discrete | **the text/config command channel** — see `04-hidden-features-and-easter-eggs.md` §4.1 |
| `0x66` | discrete | `FUN_8011a528(payload, len, &DAT_81114798, len)`; on success stores the caller's id into `DAT_81018324` and calls through the stored pointer `*DAT_819c3ab4` — an **indirect dispatch hook** |
| everything else | **no branch** | **silently ignored** — no handler, no log, no reply (see below) |

**The map is now complete, which is a stronger statement than the table above.** The handler's control flow is
`if / if / if / else` and every branch ends in `return`, with a bare `return;` after the last one, so every
opcode value is accounted for:

| opcodes | disposition |
|---|---|
| `0x00`–`0x1B` | range 1 → engine queue (`FUN_80116f54`) |
| `0x1C`–`0x2F` | **silently ignored** (20 values) |
| `0x30`–`0x60` | range 2 → file manager (`FUN_80128f3c`) |
| `0x61` | heartbeat counter |
| `0x62` | text/config command channel |
| `0x63`–`0x65` | **silently ignored** (3 values) |
| `0x66` | indirect dispatch hook |
| `0x67`–`0x7F` | **silently ignored** (25 values) |
| `0x80`–`0xFF` | **silently ignored** (128 values; the framed branch is entered only via the `0xF0 00 20 76 01` prefix, and the opcode is still bounded by the comparisons above) |

So 80 of the 256 opcode values do something and 176 are ignored without a trace. That is worth knowing for
anyone probing the device with MIDI: **an unhandled opcode produces no error, no reply and no log line** — a
probe's silence is not evidence that the frame was malformed.

**Checked against the call sites, not just the function.** `FUN_80040922` is called from exactly two places:
`FUN_80041048` and `0x8011ac12` (inside the message loop of an unanalysed function). Disassembling the second
shows it loading a context pointer and a message pointer and calling the handler — `LdM32bitToDreg R0 =
[0x81018320]`, `LdImmToReg R1 = <context>`, `Call 0x80040922` — with **no further dispatch on any byte of the
frame**. So the disposition table above is the complete story for a framed message: nothing downstream
re-interprets `[5]`.

One asymmetry inside the `0x62` channel is the exception that proves the rule: an **unmatched command name is
silently ignored**, but a **length-complement mismatch does log** — `NOPE! %d != %d` at `Midi.cpp` line `0x4c5`,
comparing the expected `(~len) & 0x7f` with the byte at `param_2[6]`. So the only failure inside the text
channel that reports itself is the framing check.

`0x61` resolves to something very small and worth stating exactly, since it decompiles to three
instructions:

```c
void FUN_80107b10(int param_1)
{
  *(char *)(param_1 + 0x39c0a0) += 1;    /* one-byte counter, nothing else */
}
```

So `0x61` is a **one-byte heartbeat/tick counter** on the engine-host context — not a command.

### 5.3.1 Range 1 is split by payload SIZE, not by opcode

This is the correction to the natural first reading, and it took direct re-reading of the decompilation to
settle. `FUN_80116f54`'s first argument **is unused**; the function chooses its queue purely on
`param_4` (the payload length):

```c
void FUN_80116f54(undefined4 unused_ctx, undefined1 opcode, undefined4 payload, int len, undefined4 id)
{
  if (0x20 < len) {                      /* longer than 32 bytes  */
    memcpy(frame, payload, len);
    frame.id = id;  frame.len = (short)len;  frame.opcode = opcode;
    FUN_8011686c(&DAT_819cf64c, frame);   /* -> Queue A (520-byte slots) */
    return;
  }
  memcpy(frame, payload, len);
  frame.id = id;  frame.len = (short)len;  frame.opcode = opcode;
  FUN_80116df0(&DAT_819d06a0, frame);     /* -> Queue B (40-byte slots)  */
}
```

**Both queue bases are hard-coded absolute globals**, not derived from the caller's context. So the caller's
`DAT_81059d1c + 0x3463c0` (range 1) and `DAT_81125fc4` (range 2) are the *subsystem* objects, while the
queue choice inside range 1 depends only on **message length ≤ 32 bytes or not**. An earlier draft of this
document said the two ranges route to different destination objects *through this function*; that is wrong,
and the code above is the correct reading.

Range 2 is genuinely different: `FUN_80128f3c` takes a lock on `param_1 + 0x1e0`, refuses messages over
**312 bytes** with `File_manager_midi_message_too_big` (from `FileManager.cpp` line `0x43f`), and posts to
`DAT_81adff58`.

**The `0x62` path is the most valuable of these for a user**, because it is the only one whose commands are
pure text and directly verifiable — the 15 commands in `04-hidden-features-and-easter-eggs.md` §4.1.

## 5.3.2 Range 2 **is** the file-transfer protocol — opcodes read from its consumer

The range-2 family (`0x30`–`0x60`) was the half of the opcode map I had written off. It is now read, because the
queue's consumer was located (§5.7) and its two dispatch handlers decompile. **The family is the FileSync /
FileServer protocol**, and the "opcode" the map dispatches on is the protocol's message type:

| opcode | handler | name, from the handler's own logs |
|---|---|---|
| `0x33` | `FUN_8012b538` | **client heartbeat** — with `ctx[0xb4] == -1` (no client) and a **< 6000-unit** gap it logs `FileServer:: short disconnect detected` and runs the disconnect path; a malformed one logs `FileServer:: corrupt client heartbeat` |
| `0x34` | `FUN_8012b538` | **client request** — exempt from the client-id check; malformed → `FileServer:: corrupt client request` |
| `0x35` | `FUN_8012c7dc` | **file request** — needs an **8-byte** payload or logs `FileServer: corrupt file request`; carries a **32-bit file id** and a part number; an id `> 99` while `ctx[0xb0] == 0` logs `FileSync: ignore file request wh…`; otherwise logs `got new file request: %d, part: …` and latches `ctx[0x4f] = 1`, `ctx[0x44] = id`, `ctx[0x48] = part` |
| `0x51` | `FUN_80127338` | file-sync operation — runs `FUN_80126e4c(ctx, id, …)` |
| `0x52` | `FUN_80127338` | **server heartbeat** — malformed → `FileServer/Client: corrupt server heartbeat` |
| `0x53` | `FUN_8012c7dc` | **file part** (the data chunk) — needs ≥ 9 bytes or logs `FileServer: corrupt file part`; then calls `func_0x8012c4bc(ctx, fileId32, part, flag, payload + 0xa1, len − 9)` |
| `0x55` | `FUN_80127338` | file-sync state transition — runs `FUN_8012b7ea(ctx)` and clears `ctx[0xf4]` |

and the message routing rules are explicit in the code:

```c
/* client side, FUN_80127338 - FileSync.cpp */
if (!FUN_8011a528(payload, len, &DAT_81114798, len)) { log("corrupt file sync message"); return; }
uVar2 = (payload[0] << 8) | payload[1];                 /* a 16-bit session/server id */
if (uVar2 == 0x55 || opcode == 0x51 || opcode == 0x52 || uVar2 == *(u32 *)(ctx + 0xb8)) { ...dispatch... }
else log("FileClient: wrong server id: %d ...", uVar2, *(u32 *)(ctx + 0xb8), opcode);

/* server side, FUN_8012b538 - FileServer.cpp */
if (opcode != 0x34 && uVar3 != *(u32 *)(ctx + 0xb4)) { log("FileServer: wrong client id: %d ..."); return; }
```

**The dispatch itself is now read as well** (`FUN_80129c24`, a 2,270-byte function — the file-manager task loop),
and it is small enough to state exactly:

```c
iVar2 = func_0x801290c8(param_1, 0x81AE098C);          /* POP into a FIXED global record */
if (iVar2 != 0) {
  do {
    if (cRam81AE0AC8 == '`') {                          /* opcode 0x60 */
      copy the record's id fields out; FUN_800279d8(&DAT_0801fa74, buf);
    } else {
      if (*(char *)(param_1 + 0x1dc) != 0) FUN_8012b538(param_1, opcode, 0x81AE098C);         /* SERVER role */
      if (*(char *)(param_1 + 0x1dd) != 0) FUN_80127338(param_1 + 0xe4, opcode, 0x81AE098C);  /* CLIENT role */
    }
    iVar2 = func_0x801290c8(param_1, 0x81AE098C);       /* POP again */
  } while (iVar2 != 0);
}
if (*(char *)(param_1 + 0x1dc) != 0) func_0x8012abe4(param_1);        /* server upkeep */
if (*(char *)(param_1 + 0x1dd) != 0) func_0x8012712c(param_1 + 0xe4); /* client upkeep */
```

which pins four things:

- the dequeued record is a **fixed global at `0x81AE098C`** (the pop writes into it) and the opcode is read as the
  global **`0x81AE0AC8`** — i.e. `0x81AE098C + 0x13C`, confirming the `+0x13c` control-byte offset by arithmetic;
- **one task serves both roles**: `ctx+0x1dc` enables the **server** handler and `ctx+0x1dd` the **client**
  handler (with the client's sub-context at `ctx+0xe4`), and both can be live at once;
- **opcode `0x60` has its own arm** — it copies the record's id fields and calls `FUN_800279d8(&DAT_0801fa74, …)`
  rather than going through either file handler, so `0x60` is a distinct message class;
- each iteration ends with **per-role upkeep** (`func_0x8012abe4` server, `func_0x8012712c` client), which is where
  the timer-driven protocol state (the flag/deadline table at `0x81adff0c`, `…14`, `…1c`, `…24`, `…4c`) is serviced.

Three things follow, and they change what this document can claim:

- **the file-transfer protocol is now essentially enumerated**: the per-opcode worker `FUN_8012c7dc` (376 bytes)
  switches on the opcode and implements the request/part half (`0x35`, `0x53`) with the firmware's own log strings
  naming the failures (`FileServer: corrupt file request`, `FileSync: ignore file request wh…`,
  `got new file request: %d, part: …`, `FileServer: corrupt file part`), so the implemented range-2 set stands at
  **seven message types** — `0x33`, `0x34`, `0x35`, `0x51`, `0x52`, `0x53`, `0x55` — plus the distinct `0x60`
  class, with a **32-bit file id** and a part number on the request/part pair;
- **the range-2 "opcodes" are a session protocol, not commands**: every message carries a **16-bit id** that is
  validated against `ctx+0xb8` (the server id, client side) or `ctx+0xb4` (the client id, server side), so a
  message with the wrong id is *logged and dropped* — `FileClient: wrong server id` / `FileServer: wrong client
  id`. That is exactly the behaviour a file-sync protocol needs, and it is why these opcodes have no user-facing
  meaning;
- **the unpack helper is shared with the SysEx dispatcher**: both handlers validate the payload with
  `FUN_8011a528`, the same function MIDI opcode `0x66` calls (§5.3) — so the range-2 family and the `0x66` hook
  share one framing/unpack step;
- **the earlier "not a usable command reference" caveat is now withdrawn for this family**, replaced by a partial
  enumeration: `0x33`, `0x34`, `0x51`, `0x52`, `0x55` are named, and the rest of `0x30`–`0x60` is enumerable by
  reading the remaining arms of `0x80129c24` (the dispatch chain around `0x8012a500` and the two handlers above),
  with the same method.

The log source paths pin the containing files: `src/sequencer/FileSync.cpp` (0x811144a8) and
`src/sequencer/FileServer.cpp` (0x81126578), which is consistent with doc `01`'s source inventory.

## 5.4 The `0x62` command payload, precisely

Restating the wire construction because it is the part a tool has to get exactly right:

```c
uVar6 = param_3 - 6;                 /* total length minus the 6 header bytes */
if (uVar6 > 0x20) uVar6 = 0x20;      /* CLAMPED to 32, not rejected   */
uVar5 = (~uVar6) & 0x7F;             /* the expected length-complement */
bVar2  = param_2[6];                 /* the byte the caller put at [6] */
FUN_040201c4(auStack_28, param_2 + 7, uVar6 - 1);   /* copy len-1 text bytes from [7] */
*puVar7 = 0;                         /* NUL-terminate */
if (bVar2 != uVar5) { log("NOPE! %d != %d", uVar5, bVar2); return; }   /* else ignored */
```

So a conforming message is:

```
F0 00 20 76 01 62 <~n & 0x7F> <command text of n-1 bytes>
```

where `n` is the total message length minus 6, clamped to 32 — i.e. **at most 31 characters** of command
text. Getting the byte at `[6]` wrong means the device logs `NOPE!` and does nothing, which is a
debuggable failure rather than silence.

## 5.5 MIDI configuration keys (`config/midi.json`)

The `Midi.cpp` string pool defines the configuration vocabulary the app can set:

| key | meaning |
|---|---|
| `incoming_midi` | enable MIDI input |
| `outgoing_midi` | enable MIDI output |
| `midi_echo` | echo received MIDI back out |
| `track_channels` | map tracks to MIDI channels |
| `track_enable` | per-track enable over MIDI |
| `channel_one_to_active` | treat channel 1 as the active track |
| `timing_clock_in` | MIDI clock input |
| `timing_clock_out` | MIDI clock output |
| `alt_program_change` | alternate program-change handling |
| `enable_program_change` | enable program change |
| `parameter_cc_out` | send parameter changes as CC |

Values seen in the same block: `unknown`, `invalid`, `no serial`, `no version`, `snakemidi` (module name),
and `xcx0312p1.0.8` (a version/identifier string).

`config/midi.json` is the file the content-mode import writes, and `MidiSettings` is the in-memory
structure name.

## 5.6 Method note

The MIDI surface was found by the same route as the config channel: dump strings, spot the cluster of
`verb_noun` config keys sitting beside a source path (`…\src\sequencer\Midi.cpp`), derive the file→virtual
mapping, then search **function bodies** for the sign-extended immediate of those string addresses, which
lands you in the owning function. `FUN_80040922` came out of that search and decompiles cleanly.

## 5.7 The queue geometry, recovered

Both MIDI opcode ranges feed **ring buffers**, and their geometry is now fully recovered from the
accessor functions. This is the structural answer to how the MIDI protocol is delivered.

### Queue A — engine host, large slots (opcode `< 0x1C`)

| property | value |
|---|---|
| queue base (context) | `DAT_819cf64c` |
| slots | **8** (`index + 1 & 7`) |
| slot size | **0x208 (520) bytes** |
| tail index | `ctx + 0x1044` |
| head index | `ctx + 0x1040` |
| push lock flag | `ctx + 0x1051` |
| push | `FUN_8011686c` — variable-length copy up to `0x81` iterations (`130` dwords / 520 bytes), NUL-terminated |

It logs `WARNING: <name> Can't push, queue …` from `Queue.h` line `0x71`, and on overflow it **resets
both head and tail to 0** (`ctx+0x1040 = 0; ctx+0x1044 = 0`) rather than dropping a single entry — i.e.
the queue flushes itself on overflow. Both ends carry an `already pushing` / `already popping` guard that
logs from `Queue.h` line `0x6c`.

### Queue B — fixed 40-byte records (opcode `0x2F`–`0x60`)

| property | value |
|---|---|
| queue base (context) | `DAT_819d06a0` |
| slots | **32** (`index + 1 & 0x1f`) |
| slot size | **0x28 (40) bytes** |
| tail index | `ctx + 0x504` |
| head index | `ctx + 0x500` |
| lock flags | `ctx + 0x511` (push), `ctx + 0x510` (pop) |
| push | `FUN_80116df0` — copies exactly **10 dwords** |
| **pop** | **`FUN_80117000`** — checks `head == tail`, logs `Queue empty: %s`, advances head with `& 0x1f` |

The 40-byte slot exactly matches the MIDI frame the handler builds: 3 header words (id, length, opcode)
plus a 32-byte payload. So a Queue B slot **is** a MIDI message, and the `0x20`-byte cap on the payload
(`if (0x20 < param_4)`) exists precisely so the record fits the fixed slot.

### The queue accessors, and the `pop`

| queue | push | pop | pop's empty-test | advance |
|---|---|---|---|---|
| A | `FUN_8011686c` | **`FUN_80116a70`** (copy-out) + **`FUN_80116994`** (advance) | `head == tail` | `head = (head + 1) & 7` |
| B | `FUN_80116df0` | **`FUN_80117000`** | `head == tail` | `head = (head + 1) & 0x1f` |

`FUN_80116a70` decompiles to something readable and worth recording, because it shows the full
dequeue contract including its locking:

```c
undefined4 FUN_80116a70(int param_1, undefined4 *out)
{
  FUN_8012e50c(param_1 + 4);                     /* lock */
  uVar2 = 0;                                     /* 0 = queue was empty */
  if (DAT_819d068c != DAT_819d0690) {            /* not empty */
    puVar1 = &DAT_819cf64c + (*(int*)(&DAT_819cf64c + 0x1040) * 0x208);   /* slot = base + head*520 */
    /* copy 0x81 dwords out to `out` */
    func_0x80116994();                           /* advance head */
    uVar2 = 1;
  }
  FUN_8012e530(param_1 + 4);                     /* unlock */
  return uVar2;
}
```

### A Ghidra analysis defect worth knowing about

The Queue A pop was **not** found by the analyser: it had been merged into `FUN_80116b00`, which Ghidra
reported as **`size=1`** (a single bad instruction). A bad instruction broke the linear sweep and swallowed
the surrounding functions. I recovered them by disassembling the region directly. Two wasted hours of
"the pop does not exist" reasoning came from trusting `getFunctionCount()` and the reference manager as if
they were complete.

**Lesson for this codebase:** the Blackfin+ mixed 16/32-bit ISA produces `size=1` stubs and
`halt_baddata()` bodies where the sweep loses alignment. Grep the function list for `size=1`, and do not
treat "0 references" as proof of dead code without also testing for raw constants with the
split-immediate search.

### Both queues are written but never drained in this image — hypothesis tested and refuted

A careful reference audit produced a genuinely surprising result:

| object | references in the OS image |
|---|---|
| Queue A context `0x819cf64c` | push, one inline `memset`, plus the pop's own hard-coded uses |
| Queue B context `0x819d06a0` | push, one inline `memset` |
| `pop` A (`FUN_80116a70`) | **no caller** |
| `pop` B (`FUN_80117000`) | **no caller** |

A range query over `0x80116f00`–`0x80117400` returns 7 references, and the single *external* one is
`FUN_80040922` calling the **push** forwarder. So in `opz.ldr` both queues are initialised and written,
and both pops exist as unreferenced code.

**The natural hypothesis — that the engines drain the queues through shared memory — is refuted.** Because
the queue bases are hard-coded absolute addresses, any code could reach them without being passed a
pointer, so I tested for the constants directly (raw LE32, BE32, and the split 16-bit halves Blackfin uses
to materialise constants) across:

- all **21 engine binaries** in `engines-official/` — **no hit**;
- `nrf52832_opz.bin` (BLE) — **no hit**;
- both `SnakeKeyboardModule_*.cyacd` (keyboard PSoC) — **no hit**.

So the "engines read it" explanation is gone, and there is no evidence the peripherals do either.

The pops also have **different ABIs** — Queue A's context is hard-coded inside its own body, while Queue
B takes it in register `P5` — so they are not two entries of one common dispatch table either.

**What remains, stated without overclaiming:** the ring buffers are a one-way channel in every binary I
have examined, or their drain sites are further analyser-swallowed functions of the kind documented above.
The second is credible precisely *because* I already found one such function, so this is a lead rather
than a dead end: sweep the `0x80116xxx`–`0x80118xxx` region for further `size=1` stubs and disassemble them
by hand. A negative result with a refuted hypothesis and a named next step is worth more than a plausible
mechanism asserted without one.

**I did sweep, and here is the result.** The OS contains only **47** `size=1` stubs, and 46 of them are in
the `0x0401xxxx`/`0x0402xxxx` **L2 ROM library** (`memcpy` at `0x04022ea8`, `memset`, and friends) — normal
library code, not defects. Exactly **one** is in the queue region: `0x80116b00`, the stub whose swallowed
body turned out to be the Queue A pop. So the "swallowed function" explanation has been tested rather than
merely hoped for, and it did not yield a further caller.

I also re-tested the split-immediate search **with a control group**, because `0x1180` is the high half of
every `0x8011xxxx` address and therefore a false-positive magnet:

> For a target lo-half the search gave **1** proximate pair; five *random* lo-halves with the same high
> half gave **0, 2, 0, 0, 0**. So 1 is inside the noise floor and the reference is **not** real. I briefly
> mis-read this as 16 hits before adding the control — the control is what caught it.

That closes the question within `opz.ldr`: the pops are not called from anywhere in the analysed image, and
not by coincidence-looking byte patterns either.

**The file-manager queue *does* have a pop — my earlier "write-only" claim for it was wrong, and the
split-immediate search is what caught it.** I first checked the address `0x81ADFF58` with Ghidra's reference
manager and got **two** references (the pusher and the initialiser), concluding no consumer existed. Scanning the
image for the **split-immediate form** of the same constant — the method that this project has now needed three
times, after the Queue A pop was swallowed by a `size=1` stub — returns **six** sites:

| site | what it is |
|---|---|
| `0x80128fb6` | the pusher, in `FUN_80128f3c` (already documented) |
| `0x8012a9cc`, `0x8012a9e2` | the initialiser (head/tail and the `memset`) |
| `0x801290e0`, `0x80129144`, `0x80129168` | **an unanalysed function at `0x801290c8` — the pop** |

and disassembling it gives the queue's real geometry:

```asm
0x801290c8  push {R7:6, P5:3} ; R7 = ctx + 0x1e0          ; the lock offset from §5.7
0x801290da  Call 0x8012e50c                               ; LOCK
0x801290de  P3 = 0x81ADFF58                               ; queue base
0x801290ee  R0 = [P3 + 0xa20] ; R1 = [P3 + 0xa24]         ; head, tail
0x80129108  if (head == tail) { unlock; return 0; }       ; EMPTY
0x80129142  R0 = 0x81ADFF58 ; R1 = 0x144                  ; slot stride
0x80129164  R1 *= R0                                      ; slot = index * 0x144
0x80129172  copy the slot out (LC0 = 0x50 words) ; Call 0x80128fe8 ; unlock
```

So the file-manager ring is **324-byte (0x144) slots** with head/tail at `+0xa20`/`+0xa24` and the `ctx+0x1e0`
lock — and `324 = 312 + 12` matches the record the pusher builds (a 312-byte payload behind a 12-byte header).
**The earlier claim that this queue is written but never drained is therefore retracted.**

**And the consumer is now located too** — two callers of the pop, at `0x80129c36` and `0x80129c8c`, inside an
unanalysed function starting at `0x80129c24`. It is a **drain loop**, and it dispatches on the record:

```asm
0x80129c24  LINK 0x250 ; push {R7:4, P5:3}        ; a deep frame, so this is a real work function
0x80129c2c  R1 = 0x81AE098C                         ; the dequeue destination record
0x80129c36  Call 0x801290c8                         ; POP
0x80129c3a  if (result == 0) -> exit                ; the queue was empty
0x80129c3e  P4 = 0x81AE098C                         ; the dequeued record
0x80129c58  R1 = B[P4 + 0x13c]                      ; a byte near the end of the 324-byte record
0x80129c5c  if (R1 != 0x60) -> 0x8012a500           ; *** the dispatch chain ***
0x80129c68  R0 = B[P4 + 2]                          ; the message's opcode/id byte
...         call with a constant (0x801fa74) ... then
0x80129c8c  Call 0x801290c8                         ; POP again
0x80129c90  if (result != 0) -> 0x80129c58           ; keep draining while messages remain
```

Three things fall out of that, all of them new:

- **the record shape is confirmed from the consumer side**: the message's opcode/id byte is at **`+2`** — the same
  offset the PSoC's record allocator writes (`{u8 id; u8 flag; u16 id16; …}`, §7.4c of doc `07`) — and the
  dispatching control byte is at **`+0x13c`**, near the end of the 324-byte slot;
- **the dispatch is a comparison chain, and the first arm handles `0x60`**; the code for every other value starts
  at **`0x8012a500`**, which is where the range-2 opcode semantics are to be read;
- the loop re-pops until the queue is empty, so this is the file manager's message pump, i.e. the **range-2
  consumer exists** and the family's per-opcode semantics are **recoverable** — the earlier, closed negative is
  fully withdrawn for this family.

The pop itself has no decoded caller for the same reason it was invisible to the reference manager: the
surrounding region is not analysed and an undecoded `Call` produces no reference. The immediate next step is
therefore precise: read the dispatch chain at **`0x8012a500`** (and the `0x80129c24` function's other arms),
which is where each range-2 opcode's behaviour is written.

The engineering lesson, worth stating because it has now cost three misses: on this image, **the reference
manager is not a completeness test**. Any "no consumer/no reference" conclusion must be re-tested with the
split-immediate scan against a control group.

**For the engine queues, the same stronger method was then applied — and the negative holds.** Because the
reference manager had just been wrong about the file-manager queue, I re-ran the split-immediate scan on both
engine queue contexts, and every site it finds is inside a routine already documented:

| queue context | sites found | what they are |
|---|---|---|
| Queue A `0x819cf64c` | `0x80116a86`, `0x80116aec`, `0x80116b10` | inside `FUN_80116a70`, the **pop** |
| | `0x80116f94` | inside `FUN_80116f54`, the **push** |
| | `0x80117748`, `0x8011775e` | the **initialiser** (`FUN_80117740`) |
| Queue B `0x819d06a0` | `0x80116fce` | the **push** |
| | `0x801170d6`, `0x8011713e`, `0x8011715a` | inside `FUN_80117000`, the **pop** |
| | `0x80117776`, `0x8011778c` | the **initialiser** |

Six sites per queue, each attributable, and no unidentified function among them — so unlike the file-manager
ring there is **no hidden consumer** for either engine queue. The internal control is that the scan *does* find
the documented pop, push and init in every case; the range-1 negative therefore now rests on the method that
overturned the range-2 one, not on the reference manager alone.

**What follows remains true for them:**

```asm
; 0x80128fb4 - the pusher (inside FUN_80128f3c, already documented)
; 0x8012a9e0 - the INITIALISER
0x8012a9d2  P5 = 0x81ADFF58 ; [P5+0xa20] = 0 ; [P5+0xa24] = 0   ; head and tail
0x8012a9e8  memset(0x81ADFF58, 0, 0xa20)                          ; the 2592-byte queue body
0x8012a9f0  B[P5+0xa30] = 0 ; B[P5+0xa31] = 0                     ; the two lock/enable bytes
```

so the file-manager ring has **the same shape as the engine queues**: a body zeroed wholesale, head and tail at
`+0xa20`/`+0xa24`, lock bytes at `+0xa30`/`+0xa31` — and **no consumer**. That extends the earlier negative from
the engine queues to the file-manager queue: *both* ranged MIDI families end in a ring whose drain site is not in
the analysed image, which is why neither family's per-opcode semantics can be enumerated from `opz.ldr`.

**The sweep now covers every artifact in the extracted set, including the bootloader.** `bootloader.ldr` is a
separate 253 KB image and had never been checked for these ring addresses. On this ISA the constants are
materialised as **split immediates** (high half then low half within a few bytes), so a plain 32-bit word scan
finds nothing — my own control run proved that by returning 0 hits in `opz.ldr` where the constants
*provably* exist. Using the split-immediate scan with a control group:

| image | `0x819cf64c` | `0x819d06a0` | `0x81adff58` | control (5 random low halves) |
|---|---|---|---|---|
| `opz.ldr` | **6** | **6** | **6** | **0, 0, 0, 0, 0** |
| `bootloader.ldr` | **0** | **0** | **0** | **0, 0, 0, 0, 0** |

so the scanner has real signal (6 versus 0) and the **bootloader contains none of the three queue addresses**.
With that, the negative covers all six artifacts in the recoverable set: `opz.ldr` (both pops uncalled, plus the
8.4 KB gap swept by hand), the file-manager ring (init and push only), the 21 engine modules, the nRF52832 BLE
image, both PSoC keyboard images, and now the bootloader.

**And the engines have now been opened, which closes it from the other side** (doc `07` §7.5). All 21
`.engine` modules are Blackfin+ relocatable modules exporting exactly five functions — `initModule`, `init`,
`render` or `renderFX`, `onNoteOn`, `onNoteOff` — with note events arriving as `onNoteOn`/`onNoteOff` calls.
There is therefore **no per-opcode MIDI command table inside an engine** for this document to recover: what a
ranged opcode *means* is decided before the module ABI, in code that is not present in the image. This opcode
map is the end of the statically reachable chain, and that is a property of the firmware rather than a gap in
the search.

## 5.8 The DMX / lighting output path, decompiled

Doc `02` §2.7 lists a DMX vocabulary (`DmxController.cpp`, `config/dmx.json`, `profiles`, `profile`, `fixture`,
`channels`, `rgb`) and nothing else. The path is now read, and the headline is: **DMX is a track, and you play
it like an instrument.**

**How it is reached.** The sequencer's note dispatcher `FUN_8010c894` (the one that logs `max notes reached -
can't play note` at its line `0x710`) calls, for every played note:

```c
FUN_8003b108(seq_ctx + 0x345d54,   /* the track/voice context */
             param_2,              /* the TRACK index      */
             param_5,              /* the NOTE number      */
             (param_11 & 1) != 0); /* a flag               */
```

**Track `14` is the DMX track.** `FUN_8003b108` branches on the track argument:

```c
if ((flag != 0) || *(char *)(DAT_81059d1c + 0x22) == 0) {
  if (track == 0x0e) {                     /* 14 -> lighting */
    iVar1 = 0;
    switch (note - 0x36) {                 /* note -> fixture index */
      case 2:  iVar1 = 1; break;           /* 0x38 */
      case 4:  iVar1 = 2; break;           /* 0x3A */
      case 7:  iVar1 = 3; break;           /* 0x3D */
      case 9:  iVar1 = 4; break;           /* 0x3F */
      case 0xc: iVar1 = 5; break;          /* 0x42 */
      case 0xe: iVar1 = 6; break;          /* 0x44 */
      case 0x10: iVar1 = 7; break;         /* 0x46 */
      case 0x13: iVar1 = 8; break;         /* 0x49 */
      case 0x15: iVar1 = 9;               /* 0x4B */
      ...  /* twelve other note values map to -1 = ignored */
    }
    if (iVar1 != -1) {
      FUN_80107890(DAT_81059d1c, 0xe, 1);      /* ctx[0x39c0c3 + 14] = 1        */
      FUN_8010988c(DAT_81059d1c, 0xe, uVar2);  /* current-track record[n] = idx */
      return;
    }
  }
  else FUN_8003b09e();                          /* every other track */
}
```

So the **nine lighting slots are addressed by nine scale-spaced notes** — `56, 58, 61, 63, 66, 68, 70, 73,
75` (G#3, A#3, C#4, D#4, F#4, G#4, A#4, C#5, D#5; intervals 2-3-2-3-2-2-3-2), and the twelve notes in between
(`55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72, 74`) are explicitly **ignored** — they are the only values that
map to the `-1` sentinel. A DMX fixture or colour is selected by *playing its note* on track 14, which is why
the pattern is a scale rather than a contiguous range: it is meant to be played by hand.

**Read the sentinel direction carefully, because the default is not "ignore".** Both switches initialise their
result to **`0`** *before* the case list, so any note that is not one of the twelve ignored values — including
`0x36` (54, one semitone below the first mapped note) and **anything above `0x4B`** — falls through to the
default and selects **index `0`**. The `-1` list is therefore an ignore list of exactly twelve values, and
everything else on track 14 selects a slot. That is easy to misread from the switch alone, and it is the kind
of detail that decides whether an errant note lights the rig or does nothing. **One correction, made in
§5.8c:** those twelve notes are ignored *as fixture selectors* only — the same twelve values are what the
preview-LED flag builder arms, so on the preview table they are slots 1–12, not dead values.

**The two writes are byte-array stores, and they are the track's state:**

| call | effect |
|---|---|
| `FUN_80107890(ctx, i, v)` | `*(u8 *)(ctx + 0x39c0c3 + i) = v` — a flat per-index byte array. Note that the MIDI `0x61` heartbeat writes `*(char *)(ctx + 0x39c0a0)`, so **`0x39c0a0` is a per-track byte block** with the heartbeat at `+0` and the DMX flag here at `+0x23`. |
| `FUN_8010988c(ctx, i, v)` | indexes the **current-track record** at `ctx + 0x690 + *(int *)(ctx + 0x44) * 8`, keeps **bit 7** of the existing byte, and stores `v \| (old & 0x80)` through `FUN_80043990` — i.e. a flag-preserving field set, which is what a "held/modulated" bit would be. |

**The firmware also *ships* the DMX manual, which answers the config-model question.** The decrypted tree
contains `firmware/blackfin/system/content/readme/how_to_dmx.txt` — 6,671 bytes of vendor documentation, in the
image, that the official product documentation does not surface:

> OP-Z can transform sequencer data to DMX channel data and send it out using a **USB DMX interface**. use the
> dmx.json file to configure the outgoing channel data to correspond to your DMX fixture setup.

Its supported **channel types** are exactly the vocabulary the decompiled code needs:

| channel | range | meaning |
|---|---|---|
| `red`, `green`, `blue`, `white` | 0–255 | colour components |
| `color` | 0–255 | colour wheel |
| `intensity` | 0–255 | dimmer |
| `fog` | 0, 255 | **triggered by animation 14** |
| `knob1`…`knob8` | 0–255 | the four OP-Z knobs across **two pages** (green/blue/yellow/red knob LEDs) |
| a literal `0`–`255` | — | a custom fixed value |
| `on` / `off` | 255 / 0 | always on / always off |

and the file has the two blocks doc `02` §2.7 saw as bare strings: **`profiles`** (named fixture profiles,
each listing the channels for the selected mode of that fixture) and **`config`** (assign a profile to each
fixture — *"OP-Z supports up to 16 fixtures. each of them corresponds to a LED on the DMX preview on your
OP-Z"*).

Two things follow directly. First, my note→fixture map above is the **note-addressable subset**: nine notes
select nine of the **up to 16** configured fixtures, so fixtures 10–16 exist in the config and are not
reachable from the keyboard. Second, **the DMX output leaves through the USB host port**, which is what makes
doc `06`'s `USBH_FTDI232Mutex` and FTDI host support meaningful rather than speculative — USB DMX interfaces
are FTDI-based, so that mutex is the DMX output path.

**The controller itself** is a singleton: `FUN_8003c5a4` initialises it and publishes the pointer to the global
**`DAT_81015e9c`** — sentinel-filled fields (`0xffffffff`), two fixed values `0x4f` (79) and `0x1f` (31), and
an **18-byte region at `+0x28` zeroed with the L2 `memset`**. `FUN_8003c3e4(value, &a, &b, &c, &d)` decomposes
a packed colour value into **up to four output channel bytes** by switching on the *mode* bits
(`value >> 0xd`) and taking one 8-bit component from `value >> 5` — a classic **fixture colour-mode encoder**
(RGB / RGBW / wheel), which is exactly what the `rgb` key in the config vocabulary is for.
`FUN_80039cb0(fixture)` switches on `fixture+0x10` and clears a state byte at `+0x17` for most modes (returning
early for modes `4` and `8`), i.e. a per-fixture state reset.

**Config vocabulary and diagnostics** (all in the `DmxController.cpp` string block):

| string | meaning |
|---|---|
| `config/dmx.json`, `load dmx config %s`, `dmx config not found: %s`, `failed to read dmx config: %s` | the profile file and its load path |
| `Invalid dmx config json: %s` | parse failure |
| `failed to find dmx fixture mode %s` | a fixture mode named in the config is missing |
| `profiles`, `profile`, `fixture`, `channels`, `name`, `rgb`, `config`, `%s%s` | the config's own key vocabulary |
| `Failed to write dmx data` | the **output** write failure |

**The whole `DmxController.cpp` is mapped by its own log call sites.** A log-call resolver over
`0x8003a000`–`0x8003d800` finds exactly **six** calls to the `(file, line, format)` logger in that
2400-byte region, and every one of them names the same file with a line number:

| call site | file and line | format |
|---|---|---|
| `0x8003b7ea` | `DmxController.cpp:316` | `dmx config not found: %s` |
| `0x8003b82e` | `DmxController.cpp:324` | `failed to read dmx config: %s` |
| `0x8003b9f4` | `DmxController.cpp:353` | `load dmx config %s` |
| `0x8003bfbc` | `DmxController.cpp:358` | `Invalid dmx config json: %s` |
| `0x8003c086` | `DmxController.cpp:480` | `failed to find dmx fixture mode %s` |
| `0x8003aefc` | `DmxController.cpp:620` | `Failed to write dmx data` |

Three things follow. The **config loader is lines ~316–358** — read, parse and the two failure paths sit
within 42 lines of each other; the **fixture-mode lookup is line 480**; and the **wire write failure is line
620**, which was already the one hand-verified line. So `DmxController.cpp` is at least 620 lines long, and the
separation of 480 → 620 between the mode lookup and the frame send is the room the animation and packing code
lives in.

**The fixture-mode registry is a 14-entry table at `0x810159e0`.** The routine that logs line 480 resolves a
configured mode **by name** in a loop whose bound is the literal `0xe` — `LSETUP … LC0 = 0xe` from
`0x8003c052` — and stores a pointer per iteration with `StDregToM32bit [0x810159e0] = P5`. So there are **14
fixture modes** in the controller's registry, and `0x810159e0` is the table base. That also places the
controller's state words (`0x810159d4`, `0x810159d8`, `0x810159dc`, `0x810159e0`, `0x810159e4`, `0x810159e5`) in
one contiguous run just before the file's `__FILE__` string, with the light palette of doc `08` at
`0x81015fec` further along in the same region — see doc `08` §8.8 for what that contiguity is and is not
evidence for.

**The wire-side packing is read too** (the frame sender, the transport and the pump: §5.8b) — the per-fixture
encoders that turn sequencer state into channel bytes are `FUN_8003a34a`, `FUN_8003a46e`, `FUN_8003a5d6`,
`FUN_8003a718` and `FUN_8003ab0e`, and they are **mode-driven**:

| routine | what it does |
|---|---|
| `FUN_8003a34a(fixture)` | resets a fixture record (`+2 = 0x7fff`, `+4 = 0`, `+8 = 0`, `+0xc = 0`, `+0x17 = 1`) and switches on the **fixture mode** at `+0x10` (modes 1–3 fall through, others return) |
| `FUN_8003a46e(fixture, src)` | **mode 0: a 16-bit pack with the bit order reversed** — it walks `iVar5` down from `0xf` while `iVar4` counts up, so source bit *i* lands in output bit `15 − i` |
| `FUN_8003a5d6(fixture, src)` | **mode 4: a 15-channel encoder** (`iVar4 = 0xe` down to 0), walking source words into channel slots |
| `FUN_8003a718(ctx, …)` | reads the **selected lighting slot** with `FUN_8010994e(DAT_81059d1c, 0xe)` and branches on it (`> 9` takes the other arm) — the *getter* that pairs with the `FUN_80107890`/`FUN_8010988c` setters above, using the same `0xe` track index |
| `FUN_8003ab0e(fixture)` | carries a **fade/interpolation counter at `+0xcc`**, decremented by `0x14` per call — the per-frame ramp |

So the shape is: **mode-specific encoders** (a reversed-bit 16-bit pack, a 15-channel walk, and early-out
modes) driven by the selected slot and a fade counter.

**And the controller's API surface is now located by its call sites.** The DMX singletons users are mostly in
the image's **unanalysed tail** — exactly where the sequencer→DMX pump lives — and two of them show the API
directly:

```asm
; 0x8011f214 - apply a value to the controller, with a range flag
0x8011f200  R0 = 0x7b ; R6 < 0x85 ; R2 = whether the value is inside that window
0x8011f214  R0 = [0x81015e9c]        ; the DMX controller
0x8011f21c  Call 0x8003c386          ; controller <- value (range-flagged)

; 0x8011eda4 - a controller operation with argument 3, then return 0
0x8011eda4  R0 = [0x81015e9c]
0x8011edac  Call 0x8003c60c          ; controller op (3)
```

so the DMX controller API is `FUN_8003c5a4` (initialise), `FUN_8003c386` (apply a value, range-flagged),
`FUN_8003c60c` (a mode/commit operation taking `3` here) and `FUN_8003c3e4` (the colour-mode encoder), with the
per-fixture state in `FUN_80039cb0`/`FUN_8003a34a`/`FUN_8003a718` and the fade in `FUN_8003ab0e`.

**A first look into the pump's immediate neighbourhood (disassembly only — the region has no Ghidra functions,
so this is provisional).** The code around those call sites shows how the controller is fed:

```asm
; 0x8011f1a6
R1 = 0xf ; Call 0x8003c60c          ; controller operation, selector 15   (3 was used at 0x8011edac)
; 0x8011f1be..0x8011f1da  - two gates before anything happens
B[0x8110e52a] == 0 ? -> early exit           ; a global enable flag
B[[0x81059d1c] + 0x14] == 0 ? -> early exit  ; the main context's own enable flag
; 0x8011f1e0..0x8011f1ee
push args (0, 6, P5, P5, 0) ; Call 0x801094a2 ; return 0
; 0x8011f200 (the value path)
R0 = 0x7b ; R2 = (R6 > 0x7b) && (R6 < 0x85)   ; the window is 124..132
R0 = [0x81015e9c] ; Call 0x8003c386            ; controller <- value, range-flagged
```

**Both of those readings have since been checked by decompiling the two callees, and one needed correcting.**

```c
void FUN_8003c386(int ctrl, int value, int enable)
{
  if (enable == 0) { *(u32 *)(ctrl + 0x30) = 0xffffffff; }        /* CLEAR the slot */
  else if (value != *(int *)(ctrl + 0x30)) {                     /* edge-triggered  */
    *(u32 *)(ctrl + 0x20) = 0x1f;   /* 31  */
    *(u32 *)(ctrl + 0x24) = 0xff;   /* 255 */
    *(int *)(ctrl + 0x30) = value;
    *(u32 *)(ctrl + 0x34) = 0x60;   /* 96  */
  }
}
```

So the third argument is **not a range flag on the value** — it is an **enable/clear**: `0` blanks the slot
(`ctrl[0x30] = 0xffffffff`) and non-zero *sets* it, and the write is **edge-triggered** (it only fires when the
value actually changes). The contrast constants written with it (`0x1f` = 31, `0xff` = 255, `0x60` = 96) are the
rate/depth fields of that fixture. The window check I saw in the caller (`124–132`) is therefore what *decides*
enable versus clear, and the applied value is a **slot/target**, not a channel byte.

```c
void FUN_8003c60c(int *ctrl, int mode, int a, int b, ...)
{
  if (mode == 0xf && b == 0xff) {                    /* 15 = "go to mode 16, timeout 200" */
    if (*ctrl != 0x10) { FUN_8003c60c(ctrl, 0x10, 200, 0, ...); return; }
  }
  else if (mode != 0xf && ctrl[mode + 0x10] < 1) {   /* per-mode gate */
    ctrl[3] = a;  ctrl[4] = b;  ctrl[7] = ...;  ctrl[0xe] = ...;  ctrl[0xf] = ...;
    *ctrl = mode;  ctrl[1] = 0;
    if (mode == 1)  { ctrl[0x11] = 5;    return; }   /* per-mode extras */
    if (mode == 0x10) { ctrl[0x20] = 0x14; return; } /* 0x14 = 20 */
    ctrl[mode + 0x10] = 0;
  }
}
```

so this is the DMX **mode/state setter**: a mode number plus its parameters, a per-mode gate
(`ctrl[mode + 0x10] < 1`), and special cases — **mode `15` re-enters itself as mode `16` with a `200` timeout**,
mode `16` sets `ctrl[0x20] = 0x14`, mode `1` sets `ctrl[0x11] = 5`. My "it is a mode operation" reading was
right; the parameter meanings are now concrete.

**And the modes are the lighting *animations*.** A second pump call site (`0x8011f2b6`) builds the mode call
twice, and the arguments line up with the setter's parameter slots:

```asm
0x8011f26e  push param_6 = 0 ; push param_7 = 0 ; push param_5 = 0x4f (79) ; push param_4 = <index>
0x8011f280  R1 = 0xd (13)     ; mode 13
0x8011f282  R2 = 0x1f4 (500)  ; duration 500
0x8011f286  Call 0x8003c60c   ; mode setter
```

so `FUN_8003c60c` is invoked as **(mode 13, duration 500, index, 79, 0, 0)**. That mapping is verified
rather than assumed: the setter stores `param_1[3] = param_3`, `[4] = param_4`, `[7] = param_5`,
`[0xe] = param_6`, `[0xf] = param_7`, `*param_1 = param_2`, and on this ABI the first three arguments arrive in
`R0/R1/R2` with the rest on the stack in order — which is exactly the `SP+0xc` (value), `SP+0x10` (`0x4f`),
`SP+0x14`/`SP+0x18` (`0`) layout the call site builds, alongside `R1 = 13` and `R2 = 500`. So it is a numbered
effect with a duration and an index, which is what an **animation** is. That ties straight to the vendor readme's one
behavioural note, *"`fog` … triggered by animation 14"*: the controller's mode numbers are animation numbers,
and the per-mode extras in the setter (`mode 1 → ctrl[0x11] = 5`, `mode 16 → ctrl[0x20] = 0x14`) are that
animation's own parameters. The earlier two were entered by the pump as modes `3` and `15`, so the DMX feature
has at least animations `1`, `3`, `13`, `14` (inferred from the readme), `15` and `16` reachable.

The remaining hypothesis is unchanged and still labelled as one: the window check feeding enable/clear is what
suggests the controller is driven by the **plug/parameter system** (matching the vendor readme's
`knob1`–`knob8` channel types) rather than by raw channel numbers.

### 5.8b The wire-side frame, decompiled

§5.8 ended on the claim that the routine which frames the fixtures onto the USB interface was *located by its
callers rather than read*, and that `Failed to write dmx data` had **no resolved scalar reference**. Both are now
closed, and the second one is a **retraction**: a reference exists, and the `FindXImm` split-immediate scan (the
same method that retracted the file-manager write-only verdict in §5.7) finds it at **`0x8003aee8`**, inside
`FUN_8003ae20`:

| address | instruction |
|---|---|
| `0x8003aee8` | `R2 = 0x81015ccc` — the split immediate `-0x7efea334` is `"Failed to write dmx data"` |
| `0x8003aef0` | `R1 = 0x26c` (**620**) |
| `0x8003aef4` | `R0 = 0x81015be0` — `"C:\snake-software\src\sequencer\DmxController.cpp"` |
| `0x8003aefc` | `Call 0x8012f1e4` — the shared `(file, line, format)` logger |

So the failure site is **`DmxController.cpp:620`**, and the routine that reaches it is the **frame sender**.

**`FUN_8003ae20(fixture)` — one DMX frame, end to end:**

```c
void FUN_8003ae20(int fixture)
{
  if (cRam810159dc != 0) *(u32 *)(fixture + 0xc8) = 0x80;   /* forced 128 channels */
  B[0x802d190] = 0x00;                   /* the frame buffer is ONE fixed global */
  B[0x802d191] = 0x06;
  B[0x802d192] =  (byte)(*(u32 *)(fixture + 0xc8));        /* channel count, LE16 */
  B[0x802d193] =  (byte)(*(u32 *)(fixture + 0xc8) >> 8);
  B[0x802d194] = 0x00;
  if (cRam810159dc == 0) func_0x8003a268(0x802d195);       /* fill the channel payload */
  FUN_8000aff4(0, &status0, &status1);   /* read the interface's status byte pair */
  if ((status & 0x9e) != 0) {
    LOG("C:\\snake-software\\src\\sequencer\\DmxController.cpp", 620, "Failed to write dmx data");
    return 0;
  }
  n = (byte)(*(byte *)(fixture + 0xc8) + 5);               /* payload + a 5-byte header */
  for (i = 0; i <= (n - 1) / 56; i++)                      /* 0x38-byte blocks */
    FUN_8000b55c(0, 0x802d190 + i * 56, MIN(n - i * 56, 56));
  return 1;
}
```

Three things fall out of that.

**The wire frame has a five-byte header: `00 06 <count LE16> 00`.** The `0x06` and the leading `0x00` are bare
literals with no string or constant cross-reference anywhere in the image, so they are recorded as **unknown**
rather than guessed at — the only thing that can be said is that the third and fourth bytes carry the fixture's
channel count in little-endian order, which is what the block loop then reads back out of `fixture+0xc8`.

**The frame is cut into 56-byte (`0x38`) blocks on purpose.** `FUN_8000b55c(0, buf, len)` is a generic
block-chunking submitter, and its own chunk size is **64**:

```c
int FUN_8000b55c(int chan, int buf, int len)
{
  if (chan != 0 || DAT_080198b8 == 0) return 0;
  desc = DAT_080198b8[3];
  for (blocks = (len + 0x3f) >> 6; blocks != 0; blocks--) {   /* 0x40-byte blocks */
    n = MIN(len, 0x40);
    *(int *)(desc + 0x14) = n;            /* length   */
    *(int *)(desc + 0x30) = buf;          /* buffer   */
    *(u32 *)(desc + 0x4c) = *DAT_080198b8;
    if (FUN_8000ab5c(desc) != 0) return sent;
    if (FUN_0803aaf2(desc + 0x48, 0x1e) == 0) FUN_8000abc0(desc);  /* completion, 0x1e-tick wait */
    else { sent += n; len += -0x40; }
    buf += 0x40;
  }
  return sent;
}
```

so the DMX caller's `56` is deliberately *smaller* than the transport's own maximum: a 56-byte block plus its
header still fits a single 64-byte USB packet, which is exactly the constant one expects for the FTDI-based USB
DMX interface doc `06`'s `USBH_FTDI232Mutex` exists for. The descriptor at `DAT_080198b8` is the USB endpoint
object (`+0x14` length, `+0x30` buffer, `+0x48`/`+0x4c` the completion and ownership fields).

**The pump is a tick-driven timer, `FUN_8003af18`.** Two bytes of the `DmxController.cpp` data block are its
state:

```c
void FUN_8003af18(int ctx)
{
  if (DAT_0801fa75 != 0x10) return;           /* the GATE */
  if (FUN_8000afca(0) == 0) { cRam810159e4 = 0; return; }   /* interface not ready */
  if (cRam810159e4 == 0) {                    /* arm on first ready tick */
    cRam810159e4 = (FUN_8000b494(0) == 0);
    cRam810159e5 = 100;                       /* 100-tick first period */
  }
  if (cRam810159e4 != 0 && --cRam810159e5 == 0) {
    FUN_8003ae20(ctx);                        /* one frame */
    cRam810159e5 = 10;                        /* then every 10 ticks */
  }
}
```

`DAT_0801fa75` is not a DMX field — it is **byte 1 of a small state block at `0x801fa74`** whose exact meaning is
an open item (§5.8c), and `FUN_8003ab0e` (the fade routine of §5.8) gates on the identical comparison, so **DMX
output only runs at level `0x10` (16)** and is completely silent at the other three values the same byte takes
elsewhere in the image — **`0`, `8` and `0x4f` (79)**.

### 5.8c The preview flags, the fixture table and the idle animation

The three remaining questions about this path — *who feeds the fixtures, what the table at `0x802cdec` is, and
what the fade routine animates* — resolve into one small group of routines.

**`FUN_8003a418(fixture, flag)` is the per-fixture edge detector.** It is the only caller of the two encoders
`FUN_80039cb0` and `FUN_8003a34a` from this side:

```c
void FUN_8003a418(int fixture, int flag)
{
  if (fixture[0x16] != 0 && flag == 0) { FUN_80039cb0(fixture); fixture[0x16] = 0; return; }  /* off  */
  if (fixture[0x16] == 0 && flag != 0) { FUN_8003a34a(fixture); fixture[0x16] = flag; return; } /* on  */
  fixture[0x16] = flag;                                                  /* edge not taken */
}
```

**`FUN_8003ac64(ctx)` builds that flag array from the lighting track's note records**, and it is where the
§5.8 note→fixture map is confirmed a *second* time — with one correction to §5.8's reading. It walks the
0x1c-stride track records at `ctx+0x114+0x124`, skips everything whose controller byte is not `0x0e` (14 = the
lighting track), and switches on the record's **note byte**, with the case labels being the ASCII characters of
the note numbers. There are **two** switches, and the guard between them inverts the meaning:

```c
int iVar2 = 0;                       /* 0 by default */
switch (rec.note) {                  /* first switch: the 9 fixture notes */
  case '8': case ':': case '=': case '?': case 'B':
  case 'D': case 'F': case 'I': case 'K':  iVar2 = 1..9; break;
  case '7': case '9': case ';': case '<': case '>': case '@':
  case 'A': case 'C': case 'E': case 'G': case 'H': case 'J':  iVar2 = -1; break;
}
if (iVar2 == -1) {                   /* ONLY the twelve in-between notes get here */
  switch (rec.note) {
    case '7': uVar3 = 1;  case '9': uVar3 = 2;  case ';': uVar3 = 3;  case '<': uVar3 = 4;
    case '>': uVar3 = 5;  case '@': uVar3 = 6;  case 'A': uVar3 = 7;  case 'C': uVar3 = 8;
    case 'E': uVar3 = 9;  case 'G': uVar3 = 10; case 'H': uVar3 = 11; case 'J': uVar3 = 12;
    case 'L': uVar3 = 13;
    case '6': case '8': case ':': case '=': case '?': case 'B':
    case 'D': case 'F': case 'I': case 'K': uVar3 = 0xe;
  }
  if (0xd < uVar3) uVar3 = 0xd;
  auStack_24[uVar3] = 1;             /* the flag */
}
```

| note | second switch | sets a flag? |
|---|---|---|
| **55, 57, 59, 60, 62, 64, 65, 67, 69, 71, 72, 74** (the twelve §5.8 called *ignored*) | `1` … `12` | **yes** — preview slots 1–12 |
| 56, 58, 61, 63, 66, 68, 70, 73, 75 (the nine fixture notes) | `0xe` → clamped `0xd` | **no** — `iVar2 != -1`, so the whole second switch is skipped |
| 54, 76 (`'6'`, `'L'`) | `0xe` / `0xd` | **no** — `iVar2` stays `0`, not `-1` |
| anything else | — | no (the flag array is zeroed first) |

So **§5.8's "ignore sentinel" is only half the story and the half that was read is the wrong way round.** The
twelve notes are ignored *as fixture selectors* — they never reach the fixture path — but they are the **preview
LED slots 1–12**, which is precisely the vendor readme's "each fixture corresponds to an OP-Z DMX preview LED".
The nine fixture notes light nothing on the preview table: they select the fixture and are routed through
§5.8's `FUN_80107890`/`FUN_8010988c` instead. The `0xe` arms and the `> 0xd` clamp are therefore **unreachable
in practice**, because every note that would take them has `iVar2 != -1`; recording them as "slot 14" would be
wrong. The flags land in a 14-byte stack array (`FUN_04022ea8(auStack_24, 0, 0xe)`) which is then handed to the
table:

```asm
8003ad66  R7 = 0x802cdec          ; the fixture table, 0x18 (24) bytes per entry
8003ad6e  LSETUP ... LC0 = 0xe    ; 14 entries
8003ad76  R1 = B[P5++]            ; one preview flag
8003ad7a  Call 0x8003a418         ; -> FUN_8003a418(table, flag)
8003ad7e  R7 += 0x18
```

so `0x802cdec` is the **fixture table** — 24-byte records, 14 of them driven here — and the follow-up block
(`FUN_8003a718`, `FUN_8003ac08`, `FUN_8003a814`, `FUN_8003ac34`) builds a scratch record from `ctx+0xb4`/`+0xb8`/
`+0xbc` and commits it against the second table at `0x802d0fc`, ending with `fixture[0xd4] = 1`. The
split-immediate scan puts `0x802cdec` in **six** places: this loop plus `FUN_8003ab0e`, `FUN_8003ac08`,
`FUN_8003ac34` and two sites in the controller API region — the same table, shared by the whole subsystem.

**And the fade routine `FUN_8003ab0e` is the idle animation plus a filter ramp.** Beyond the `+0xcc` counter
already documented in §5.8, it multiplies a 6+-entry block at `0x802cdd0` and the two words that follow by
`0xf334` (62308) with 16-bit saturation — a fixed-point filter — and then, **only when the current track is 14
and 5000 timer units have elapsed** since `DAT_810159d4`:

```c
if (FUN_80107b90(DAT_81059d1c) == 0x0e &&          /* the lighting track is selected */
    TimeSince(DAT_810159d4) > 5000) {
  int level = 0x0f;                                 /* dim */
  if (DAT_0801fa75 == 0x10) level = 0x1f;           /* bright, and the interface is up */
  FUN_8003c60c(DAT_81015e9c, 1, 200, 0, level, 0, 0);
  TimeMark(&DAT_810159d4);
}
```

That is the **idle animation**: animation `1`, duration `200`, restarted every 5000 units of lighting-track
inactivity, with its parameter set to `0x1f` when the device is at level `0x10` and `0x0f` otherwise. It also
explains the `mode 1 → ctrl[0x11] = 5` special case §5.8 recorded in the mode setter without knowing its caller.

**Method note.** `FindXImm` finds *materialised addresses*; it can never find a function *call*, because the
Blackfin `CALL` encodes a PC-relative displacement and not an absolute immediate. All five routines above are
called that way — `FindXImm` returns nothing for `0x8003ab0e`, `0x8003a418`, `0x8003ac64`, `0x8003ae20` and
`0x8003af18`, while `Ghidra`'s reference database does resolve the one call site that lies in decoded code
(`0x8003af70` → `FUN_8003ae20`). So a missing `FindXImm` hit on a *function address* means nothing at all, and
the pump `FUN_8003af18` keeps **no decoded caller** — its invoker sits in the still-undecoded tick region, which
is a coverage gap and not a statement that the routine is dead.

**One open item, stated rather than resolved: what `0x801fa74` is.** The DMX gate byte is *not* owned by the DMX
subsystem. `0x801fa74` is a **small byte block** (`param_1[0]`, `[1]`, `[2]`), and the two places it is touched
from are unrelated to lighting:

- `FUN_800279d8(0x801fa74, record)` is called from the file-manager task loop's `0x60` arm, and it is a **USB
  connection-event handler** — `UsbControl.cpp` line `0xa2` (162), logging
  `connection event: %s 0x%02x 0x%02x …` with the `attached`/`detached` strings of `0x81002d28`/`0x81002d34`,
  and clearing the `param_1` block when the event is a detach.
- `FUN_80123568` reads `0x801fa75`, `0x801fa76` and `0x801fa78` as levels/indexes while writing slot values
  `0x4f`/`0x1f`/`0xf`/`0x7f` through `FUN_8003d56e(slot, value, 0xff)` for slots `0`–`0xf`.

So the DMX pump is gated on a byte that a **USB connection event** also clears, and on the value `0x10` of a set
`{0, 8, 0x10, 0x4f}` that is neither boolean nor a plain level. The honest reading is that `0x801fa74` is a
**shared device-state block** whose individual fields have not been named yet; it is deliberately **not** guessed
at here.

**Three of its bytes are now identified by their readers**, which is progress without guessing at the block's
owner. `FUN_80123568` (the `ScoreContext.cpp` light-slot writer, doc `08` §8.1b) reads `0x801fa75`, `0x801fa76`
and `0x801fa78` as light levels and selectors, and the third of those is an **index into a packed four-entry
colour table** that colours slots `0xe`/`0xf` — while the DMX pump reads `0x801fa75` as the `== 0x10` gate. So the
block holds at least one byte the DMX path treats as a mode and three the light path treats as a level and two
colour indices; what writes them is still open, and that is the item to resolve.

**`FUN_8003d56e` itself is no longer a guess.** It is a **light-slot setter**, not an output writer: it writes a
5-byte record into one global slot table at `0x802d3a4`, and its second argument is a **colour-wheel index**
(`value >> 4`) into a palette — which is why the values above select palette entry 4 (black, i.e. *off*) and
entry 1 (green). The whole engine behind it — the slot records, the two-variant palette, the change-only flush
and the Blackfin→PSoC transport the packet leaves on — is doc `08`. The `+0xc8`/`+0xcc` offsets this section
uses are tied up with that table's ownership, which doc `08` §8.6 states as a bounded open item rather than
resolving.

