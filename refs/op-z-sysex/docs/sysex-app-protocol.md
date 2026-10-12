# OP-Z App SysEx Protocol

Teenage Engineering does not publish the OP-Z app's custom SysEx protocol. This
document summarizes the public reverse-engineering notes from
`MarkRdgOx/opzdoc` and should be treated as provisional.

## Transport

Confidence: Observed.

The custom protocol rides over MIDI SysEx on either USB MIDI or BLE MIDI. Public
notes and independent wire captures show that the official companion software
uses a native protocol layer rather than implementing the full exchange in its
visible UI code.

## Custom SysEx Frame

Confidence: Observed.

Common custom frame:

```text
F0 00 20 76 01 <message-id> ... F7
```

Fields:

| Bytes | Meaning |
| --- | --- |
| `F0` | SysEx start. |
| `00 20 76` | Teenage Engineering manufacturer ID. |
| `01` | Protocol version; `libopz` names it `OPZ_MAX_PROTOCOL_VERSION`. |
| `<message-id>` | OP-Z custom command/message number. |
| `...` | Message-specific payload. |
| `F7` | SysEx end. |

The app also sends standard universal device inquiry:

```text
F0 7E 7F 06 01 F7
```

The OP-Z replies with an extended identity response containing the Teenage
Engineering manufacturer ID plus ASCII serial/version fields.

## Live Handshake Capture

Confidence: Directly observed on 2026-07-26.

A connected OP-Z running firmware `1.2.45+` responded to:

```text
F0 7E 7F 06 01 F7
F0 00 20 76 01 00 01 4E 2E 06 F7
```

The first line is universal identity inquiry. The second is the exact heartbeat
used by the current public `libopz` implementation. Sending the heartbeat four
times at roughly one-second intervals produced four `$01` responses. The first
heartbeat also initiated this state burst:

| Message | Count | Observed role |
| --- | ---: | --- |
| `$11` | 1 | Serial/firmware |
| `$04` | 2 | Input, level, and battery state |
| `$07` | 1 | Sequencer/program state |
| `$1A` | 1 | Not yet mapped in the older public message table |
| `$03` | 1 | Selected track/octave |
| `$14` | 1 | Not yet mapped in the older public message table |
| `$0E` | 16 | One sound-state record per track |
| `$1B` | 1 | Not yet mapped in the older public message table |
| `$06` | 1 | Buttons/page/play state |
| `$12` | 1 | Mixer state |
| `$13` | 1 | Pattern runtime state |
| `$09` | 1 | Active pattern packet |
| `$0C` | 1 | Global data |

This confirms that identity plus heartbeat is enough to bootstrap a rich
read-only session on this firmware. No `$08` pattern query was needed.

## 7-Bit Packing

Confidence: Observed.

SysEx data bytes must stay below `0x80`, so OP-Z binary payloads are 7-bit
packed. Each chunk contains one prefix byte holding the high bits for the next
up-to-seven data bytes.

Decoding concept:

1. Split payload into 8-byte chunks.
2. In each chunk, byte 0 is the high-bit mask.
3. Bytes 1-7 are low 7-bit data bytes.
4. If bit N of the mask is set, add `0x80` to data byte N.

## Zlib Compression

Confidence: Observed.

Some decoded payloads are zlib-compressed. A normal zlib header such as
`78 9c` can appear as `78 1c` before 7-bit unpacking, because the high bit is
stored in the chunk mask.

## Message Map

Confidence: Observed unless noted.

| Message | Name/status | Direction | Writable? | Notes |
| --- | --- | --- | --- | --- |
| `$00` | Client hello/heartbeat | App to OP-Z | yes | Carries the app session ID and protocol version. Must be sent roughly once per second for updates. |
| `$01` | Session acknowledgement | OP-Z to app | no | Carries the OP-Z session ID and echoes the app session ID. It does not carry a host MIDI endpoint ID. |
| `$02` | Ordered pattern delta | OP-Z to app | no | Low-latency memory telemetry for the app replica. The receive path is role-gated; controlled next-sequence hardware replays are ignored. |
| `$03` | Keyboard setting | both | yes | Selected octave and selected track. Sending updates values. |
| `$04` | Input/level state (`SynthState` natively) | both | yes, static | Battery, master volume, packed microphone FX/level, monitor/preview, input selector/context, and microphone mode/recording. |
| `$06` | UI/button state | both | yes, risky | Encoder mode, held buttons, and playing state. A three-second project+track hold remotely toggles autosave and is device-proven; other gestures are not implied. Held values can latch until released. |
| `$07` | Pattern-chain state | both | yes | Applies project, active pattern, packed active chain, length, and next-entry index. Direct recall is device-proven. |
| `$08` | Pattern query/rejection | both | query/status | Empty outbound frame requests `$09`; inbound `FF FF FF FF` rejects a malformed or out-of-order upload. |
| `$09` | Pattern packets | both | yes | Full 16-pattern bank, zlib-compressed and packetized. Host uploads require flow control. |
| `$0A` | Pattern terminator | both | yes | Carries the final compressed chunk and commits/applies the bank. |
| `$0B` | Pattern packet ACK | OP-Z to app | no | Success-only. Eight decoded bytes: `09 00 00 00`, transfer ID LE16, packet index LE16. Receive failures use one generic `$08 FF FF FF FF` rejection. |
| `$0C` | Global/project data | both | yes | One zlib-compressed 568-byte block. Saved chains and tempo writes are device-proven; all named scalar offsets are statically mapped. |
| `$0E` | Current sound parameters | both | yes | Track index plus all 18 8-bit sound bytes. Direct write, fresh bank readback, USB-audio effect, and exact rollback are device-proven. It does not select a plug or recall a preset. |
| `$0F` | MIDI configuration query | App to OP-Z | query | Empty frame requests a complete `$10`; device-proven. |
| `$10` | Compressed MIDI configuration | both | yes | 7-bit-packed zlib stream inflating to a 292-byte structure; direct write, fresh readback, and exact rollback are device-proven. |
| `$11` | Serial/version | OP-Z to app | no | Contains ASCII serial and firmware version. |
| `$12` | MixerState | both | yes | 16 track levels followed by a little-endian 16-bit mute mask. |
| `$13` | PatternState | both | yes, proven | Pattern/project copy flags, pattern-lift mode, chain mode, autosave, bounce state, and one reserved byte. Direct autosave write, fresh readback, and exact rollback are device-proven. |
| `$14` | ModuleInfo | both/raw | risky | Exactly 24 bytes: capability/status UInt32s, name, connection flag, routing flag, and unknown tail. Oplab/Line/Rumble status decoding is statically mapped. |
| `$15` | Full sample visualization request | App to OP-Z | query | Payloadless request for the current 8,192-value selected-sample display envelope. |
| `$16` | Sample visualization part | OP-Z to app | no | Part index plus exactly 180 zlib-stream bytes. |
| `$17` | Sample visualization ACK | App to OP-Z | yes | Echoes the accepted `$16` part index and advances the sender. |
| `$18` | Final sample visualization part | OP-Z to app | no | Part index plus 1...180 final zlib-stream bytes; no ACK follows. |
| `$19` | SamplerState | both | yes | Exactly 21 bytes: start/end/loop positions, pitch, gain, and two context bytes. Native receive/apply path is statically proven; a live write still needs a genuine Sampling Mode baseline. |
| `$1A` | SamplerUIState | both | yes | Five bytes: context, user-pack progress, sampling position, page, and flags. |
| `$1B` | AudioVisState | OP-Z to app | no apply path found | Four bytes; byte 0 contains two visualization nibbles. |
| `$33` | File-client status/progress | OP-Z to app | status | Client ID `u16`, status `u8`, overloaded value `u32`: state CRC, completed-part count, or completion. |
| `$34` | File-client hello/state | OP-Z to app | no | Response to `$51`: client ID `u16` plus client-state CRC `u32`. |
| `$35` | File request | App to OP-Z | query | Requests files to be sent in `$53` packets. |
| `$51` | File-server advertisement | App to OP-Z | yes | Host server ID `u16`; OP-Z answers with `$34`. |
| `$52` | File-server heartbeat | App to OP-Z | yes | Server ID `u16` plus sync-active byte; required during transfer. |
| `$53` | File data | both | yes | Sender ID `u16`, file ID `u32`, part `u16`, final flag, and one zlib-compressed part. |
| `$55` | File-server close | App to OP-Z | yes | Server ID `u16`; closes the normal-mode file session. |
| `$61` | Queue gate-sequencer step | App to OP-Z | realtime | Payload is ignored. Each frame increments a one-shot counter for track type `0A`; it does not edit pattern bytes. |
| `$62` | Text command | App to OP-Z | yes, internal/risky | UTF-8 command string. |
| `$66` | Packed serial tunnel | both | internal/risky | 7-bit-packed serial bytes are routed through `CommandHandlerMidi`; the app uses it only to answer type-0 pings with type 1. Power/factory/DFU constants exist but are not device-proven APIs. |

### `$66` Serial Tunnel

Static analysis of the official plugin proves this outer frame:

```text
F0 00 20 76 01 66 <7-bit-packed serial bytes> F7
```

The decoded non-CRC serial framing is `C0`, routing byte, message type,
big-endian 32-bit payload length, then payload. The official app accepts up to
4,096 unpacked bytes and its managed parser supports 256 payload bytes.

The app only handles a device-originated type-0 ping and sends a type-1 pong.
Two read-only connected-device host-to-device ping attempts, including one
through the official `SendSerialMessage` path, received no response. See
[Battery, Charging, and the `$66` Serial Tunnel](battery-and-serial-tunnel.md).

### Full Selected-Sample Visualization

`$15...$18` transfer an 8-bit, 8,192-value display envelope without Content
Mode or Sampling Mode:

1. Send payloadless `$15`.
2. Accept zero-based `$16` parts in strict order and append their bytes after
   the part index.
3. Reply to each `$16` with `$17` carrying the accepted index.
4. Append the final `$18` body but do not acknowledge it.
5. Inflate the complete zlib stream and require exactly 8,192 output bytes.

The connected-device proof completed twice in 18 parts and returned identical,
nonempty data. This does not expose the underlying PCM sample.

`$19` is not part of a normal-context StateSync burst on the connected OP-Z.
The first rollback-first write proof therefore stopped before mutation because
there was no genuine baseline to modify and restore. Its encoder and safe
probe are implemented, but sampler-context entry and an echoed, audible write
remain open.

### `$04` LevelState

Device-proven decoded layout:

```text
0  battery percentage, 0...100
1  master output volume, 0...255
2  bits 0...3: microphone level minus one; bits 4...5: microphone FX;
   bit 6: input monitor or sampler preview
3  bits 0...3: input selector or sampler context; bit 4: microphone mode
   or sampler recording
```

On 2026-07-26 the attached OP-Z sent decoded payload `64 6E 05 00`. The
official app ABI changed from its disconnected default of `50` to `100` when
that frame arrived. The same snapshot reported master volume `110`,
encoded microphone level `5` (internal/UI level `6`), microphone FX `0`, and
microphone mode `0`. This
cross-check proves that byte 0 is live device battery telemetry, not a plugin
placeholder.

### `$13` PatternState

```text
0           pattern-copied flag
1           project-copied flag
2 bits 0-3  pattern-lift mode
2 bit 4     chain mode
2 bit 5     autosave enabled
2 bit 6     bounce in progress
3           reserved/padding
```

Earlier repository notes incorrectly assigned input selector and monitor bits
to `$13`. Native send/apply symmetry and managed ABI field order prove those
bits belong to `$04`.

### Verified Full-Bank Write

As of July 2026, [`leddy231/libopz`](https://github.com/leddy231/libopz)
demonstrates and documents a working live pattern write:

1. Fresh-sync with `$08` and retain the decoded 16-pattern bank plus the
   transfer address and two-byte ID from `$09`.
2. Modify the raw 342,272-byte bank.
3. Compress the bank as one zlib member.
4. Split the compressed stream into 178-byte chunks.
5. Prefix each decoded packet with
   `[address, 0, id_lo, id_hi, packet_lo, packet_hi]`.
6. Send every non-final packet as `$09`, waiting for the `$0B` carrying the
   exact transfer ID and packet index.
7. Send the final packet as `$0A`; firmware may not acknowledge this terminator.
8. Request a new `$08` dump and compare the returned bytes or decoded state.

The receiver rejects an invalid decoded size, transfer-ID change, skipped
packet, or unexpected packet ordering with `$08 FF FF FF FF`. The OP-Z Lab
uploader now aborts immediately on that frame, validates every `$0B` identity,
then uses its preserved pre-edit bank for rollback and readback verification.

A connected-device no-op fault matrix additionally proved that empty packets,
skipped and duplicate indexes, transfer-ID changes, and premature `$0A`
terminators all produce that same generic rejection in 7-8 ms. `$0B` contains
no error detail. After each rejection, a packet-zero restart completed with
normal ACK flow and exact full-bank readback. A packet-zero restart also
recovered directly after abandoning an acknowledged two-packet prefix, without
waiting for a timeout or reconnecting. See
pattern upload fault proof (private evidence; not distributed).

### Live project-prefix writes

Connected-device and official-app receiver analysis on 2026-07-29 established
a narrower form of the same `$09`/`$0A` transaction. The receiver masks the
low pattern nibble from the transfer address, chooses the start of that
project's pattern bank, and gives zlib a 342,272-byte output capacity. It does
not require the inflated member to fill that capacity. A shorter zlib member
therefore replaces only a contiguous prefix of the project bank.

A reversible Pattern 1 proof sent 21,392 inflated bytes while the sequencer was
running. Fresh full-bank readback changed exactly the four expected note-record
bytes, and the OP-Z emitted the newly written Kick note at velocity 127 during
the transfer window. No MIDI Stop was observed. A subsequent full-bank rollback
matched the pre-edit bank exactly. The reusable packetizer is now
`opzsysex.sysex.pattern_upload_frames`; live write/readback orchestration is not
yet part of the public Python tools.

This is a project-prefix write, not random-access addressing:

- one-pattern transfers can edit Pattern 1 only;
- editing Pattern N requires sending Patterns 1 through N, preserving all
  preceding bytes;
- the low nibble in the transfer address does not select the destination
  pattern;
- `$0B` flow control and the final `$0A` behavior are unchanged.

`OPZProtocolEngine.projectPatternPrefixUploadFrames` exposes the raw transport.
`makeProjectPatternPrefixUpload` additionally applies typed mutations and
rejects any mutation that falls outside the included prefix.

The transfer ID is not a recognized standard checksum and tested firmware
accepts it unchanged after bank contents are modified. `$02` remains
telemetry-only in controlled replay tests. See the fork's
[`WRITE_NOTES_PLAN.md`](https://github.com/leddy231/libopz/blob/main/WRITE_NOTES_PLAN.md)
and
[`opz_rtmidi.cpp`](https://github.com/leddy231/libopz/blob/main/src/opz_rtmidi.cpp).

## Known App-SysEx Writable State

Confidence: mix of observed and inferred.

The app protocol can apparently change:

- Selected track and octave via `$03`.
- Some button/UI/encoder state via `$06`.
- Complete live pattern banks via flow-controlled `$09` packets plus `$0A`.
- Project-global state, including saved pattern chains, via `$0C`.
- Sound parameter state via `$0E`.
- Complete MIDI setup through `$0F`/`$10`: track enables, track channels, all
  256 outgoing parameter-CC assignments, and eight global flags. Direct write,
  fresh readback, and exact rollback are device-proven; see
  [MIDI Configuration over StateSync](midi-configuration-sysex.md).
- Plug slot/configurator setup through `$51`/`$52`/`$35`/`$53` workflows and
  app commit behavior.
- Internal debug/controller/log settings through `$62` text commands.

## Pattern and Project Editing Status

Confidence: High for reading core pattern structures and flow-controlled live
pattern-bank writes.

The protocol exposes pattern/project/global blobs:

- `$09` carries the 16-pattern bank.
- `$0C` carries the 568-byte project-global block.
- `$35` can request `project01.opz` through later project files.
- `$53` carries file data packets.

### `$07` Live Sequencer State

Device-proven decoded layout:

```text
0...15  active chain, two zero-based pattern nibbles per byte, low first
16      active chain length; firmware 1.2.45+ clamps 32 to 31
17      pattern address; low nibble is active pattern
18      zero-based index of the next chain entry
19      project
```

A live ten-entry chain `1 2 2 3 4 5 6 6 7 8` produced byte-18 values
`1 2 3 4 5 6 7 8 9 0`, because the next index wraps to zero while the final
entry is playing. A reversible live probe sent all values `00...1F`; the device
echoed each exact value in 6–11 ms. A requested length of 32 echoed as 31,
matching the firmware's explicit clamp and terminator write. See
[live-position-and-chain-state.md](live-position-and-chain-state.md).

The `z-po-project` documentation and `libopz` implementation substantially map:

- Note records, allocation, velocity, duration, and micro-timing.
- Track timing and note settings.
- Step-component bitmasks and values.
- Parameter-lock values and masks.
- Sound parameters, mutes, routing, chains, and global settings.

`libopz` receives `$09`, performs packet reassembly, 7-bit decoding and zlib
inflation, and exposes the result as structured pattern state.

The full-bank write sequence, typed pattern mutations, note add/delete round
trips, and `$0C` saved-chain writes are proven on firmware `1.2.45+`.
Typed pattern writes now include all track-specific chord slots, note
attributes, parameter locks, named step-component bits/value bytes, all stored
sound parameters, and Tape/Master routing. See
[typed-pattern-editing.md](typed-pattern-editing.md).

The 54-byte step records are track-major:

```text
7232 + (trackIndex * 16 + stepIndex) * 54
```

A physical Lead step-1 filter-lock diff established the ordering and the `FF`
lock-enable sentinel. Corrected host writes then produced distinct outgoing
MIDI behavior for Pulse, Multiply, and Trigger Spark and alternating filter
effects in direct USB audio. See
the private behavioral-proof ledger, which is not distributed here.

For the chain proof, the host:

1. Captured the current 568-byte `$0C` block.
2. Changed chain slot 15 from empty to patterns `1 2 1`.
3. Deflated the complete block, 7-bit packed it, and sent it as message `$0C`.
4. Opened a fresh heartbeat session and captured the OP-Z's new `$0C`.
5. Confirmed that only raw offsets `448`, `449`, and `450` changed.
6. Sent the exact original block and confirmed byte-for-byte restoration from
   another device readback.

This is a real project-state editor API, not simulated panel input. See
[native-chain-writing.md](native-chain-writing.md) for the executable proof and
artifact hashes.

Remaining risk and research areas include:

- Mapping and independently proving the writable semantics of every non-chain
  field in `$0C`.
- The stateful, apparently local scope of Spark reset raw `10`. A controlled
  live matrix proves `$09` is not transparent enough to isolate it: even a
  byte-identical bank apply perturbs Spark phase.
- Compatibility and malformed-write recovery on older firmware versions.
- More musical interpretation for the payloadless `$61` gate-sequencer tick.

See [coverage.md](coverage.md) for the current proven/decoded/
unknown matrix and the separate application feasibility notes
for the app architecture and remaining editor roadmap.

## Debug/Text Commands

Confidence: observed; `debug-save` device-proven. Controller mode was tested
only for StateSync role effects; other commands remain risky.

Known `$62` UTF-8 command strings from public notes:

- `enable-debug`
- `disable-debug`
- `enable-verbose-log`
- `disable-verbose-log`
- `enable-controller-mode`
- `disable-controller-mode`
- `enable-battery-log`
- `disable-battery-log`
- `enable-uart-log`
- `disable-uart-log`
- `debug-crash`
- `debug-save`

These should not be sent casually. Some are explicitly diagnostic or crash/update
paths. The persistence proof sent `debug-save` after reversible `$09/$0A` and
`$0C` sentinels; both survived a project switch/reload and were then restored.
The command does not emit a dedicated acknowledgement, so confirmation still
requires a fresh StateSync session and readback. See
[host-write-persistence.md](host-write-persistence.md).

A bounded 2026-07-27 test sent `enable-controller-mode`, attempted a valid
next-sequence StateSync role claim and delta, then sent
`disable-controller-mode`. It did not make the hardware accept inbound `$02`
and did not change the pattern bank. This rules out controller mode as the
missing StateSync ownership switch; it does not establish what controller mode
does elsewhere.
