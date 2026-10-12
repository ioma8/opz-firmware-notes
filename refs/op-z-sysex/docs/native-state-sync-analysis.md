# Native StateSync Analysis

Status: Clean-room companion-protocol analysis plus connected-device probes on OP-Z
firmware `1.2.45+`, 2026-07-26 through 2026-07-27.

## Method

The official companion software exposed useful native protocol symbols during
clean-room analysis. This document records protocol facts and behavior, not
copied implementation code or vendor binaries. Live claims were backed by raw captures in
the private evidence ledger (private evidence; not distributed).

The central receive switch is `StateSync::processMessage`; accepted state is
later applied by `StateSync::handleReceivedMessages`. The corresponding send
path is `StateSync::updateSlaveDevice`.

## Session Ownership and Direction

StateSync has asymmetric master and replica roles. The normal app connection is:

1. The app sends `$00` with a two-byte app session ID and protocol version `6`.
2. The OP-Z registers that MIDI sender, enters role `2`, and returns `$01`.
3. `$01` contains the OP-Z's random two-byte session ID followed by the app
   session ID it is acknowledging.
4. The app has already selected the physical MIDI port with the native
   `SetStateSyncEndpoint(portID)` API. It validates `$01`, enters role `1`, and
   becomes the synchronized replica.
5. The OP-Z sends `$02` deltas and larger state updates; the app applies them.

The first `$01` field is a StateSync session ID, not a host MIDI endpoint ID.
The native app keeps MIDI port identity separately in `ConnectedDevice` and
compares it against the app-local value configured by `SetStateSyncEndpoint`.
This native function is called by `UIPairingPanel.OnConnectTapped`; it is not a
SysEx command sent to the OP-Z.

The `$02` receive path executes only in role `1`. The hardware's normal USB
session is role `2`, so sending the acknowledged `$01` back to the device does
not reverse ownership. This is why an apparently well-formed next-sequence
delta can be silently discarded before sequence validation.

### Hardware role probe

A reversible probe on 2026-07-27:

- captured Project 1's complete pattern bank;
- derived the current `$02` sequence by muting and restoring Track 16;
- sent a correctly ordered `$01` using session IDs `CE2E` and `95F5`;
- sent the next `$02` against inactive Pattern 16;
- repeated the attempt while bounded by `$62 enable-controller-mode` and
  `$62 disable-controller-mode`;
- requested a fresh full-bank snapshot after each attempt.

Neither attempt produced the replica-role oracle or changed the target byte.
The pre-probe and post-probe banks had the same SHA-256:

```text
99895675d0a23f21a463cd8dbca2e49e65e94b46e9fa0692ea51b3b84fc6cd9b
```

Lead remained on factory plug `10`. Controller mode therefore does not provide
a remote StateSync role reversal on this firmware. Its other effects remain
unknown.

Conclusion: `$02` is a low-latency OP-Z-to-host telemetry format, not a
supported host-to-OP-Z surgical editor. Persistent host edits use the proven
flow-controlled `$09/$0A` pattern-bank transaction. Realtime performance
changes use ordinary MIDI and the separately proven writable live-state
messages.

## Short `$09` Project Prefixes

Static analysis of `StateSync::applyFullPattern` shows that the receiver masks
the transfer address with `0xFFF0`, multiplies the result by the 21,392-byte
pattern size, and inflates into a destination with 342,272 bytes of capacity.
The low nibble is therefore discarded: the destination is the selected
project's Pattern 1, not an individually addressed pattern. The receiver does
not reject a zlib stream whose actual inflated length is smaller than the
capacity.

Hardware proof on 2026-07-29 confirmed the practical result. A 21,392-byte
Pattern 1 member was accepted during playback, full-bank readback matched the
typed edit exactly, and the newly inserted Kick trig was emitted by the
sequencer before readback. No MIDI Stop was received during the write window.
The exact original full bank was then restored and verified.

This provides low-latency contiguous project-prefix replacement. It does not
provide arbitrary byte or arbitrary-pattern addressing: Pattern N requires an
unchanged prefix containing Patterns 1 through N.

## Typed Live State

| ID | Native type | Decoded bytes | Inbound apply path |
| --- | --- | --- | --- |
| `$03` | `PlayState` | 2 | yes |
| `$04` | native `SynthState` / input-level state | 4 | `applySynthState` |
| `$06` | `UiState` | 4 | yes |
| `$07` | chain state | 20 | `applyPatternChainState` |
| `$12` | `MixerState` | 18 | `applyMixerState` |
| `$13` | `PatternState` | 4 | `applyPatternState` |
| `$14` | `g_moduleInfo` | 24 | unpacked directly into global memory |
| `$15` | full sample visualization request | 0 | queues an 8,192-value transfer |
| `$16` | sample visualization part | 181 | receiver/replica only |
| `$17` | sample visualization ACK | 1 | advances sender to next part |
| `$18` | final sample visualization part | 2...181 | receiver/replica only |
| `$19` | `SamplerState` | 21 | `applySamplerState` |
| `$1A` | `SamplerUIState` | 5 | `applySamplerUIState` |
| `$1B` | `AudioVisState` | 4 | no inbound apply path found |

### `$12` MixerState

```text
0...15  one level byte per track
16...17 little-endian 16-bit mute mask
```

The firmware copies and applies the complete 18-byte structure. This is a
low-latency live mixer surface. Persistent project-level mixer edits should
still use the preserved `$0C` global block and readback.

### `$04` Input and Level State

The four bytes are treated as one little-endian packed word:

```text
bits 0...7    battery percentage
bits 8...15   master output volume
bits 16...19  microphone level minus one
bits 20...21  microphone effect
bit 22        input monitor, or input preview in sampler context
bits 24...27  input selector, or sampler-context value
bit 28        microphone mode, or recording in sampler context
```

The normal input-selector bits are microphone `1`, headset `2`, expansion
module `4`, and USB `8`. `copySynthState` subtracts one from the internal
microphone level before transmission; `applySynthState` adds one on receipt.
The current app decoder exposes both values.

The old working notes incorrectly assigned these fields to `$13`. Re-reading
the native send and apply call graph proves `$04` owns the input/level record
and `$13` owns `PatternState`. The prior `$13 00 00 40 08` experiment therefore
did not attempt USB selection and provides no routing evidence. See the
correction evidence (private evidence; not distributed).

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

The mapping is exact across `copyPatternState`, `applyPatternState`, and the
managed `SequencerState` field order. Inbound `$13` is a device-proven
live-state write. A reversible hardware proof changed only autosave bit 5,
obtained a fresh independent `$13` readback, then restored and reconfirmed the
exact original four bytes.

Autosave is the runtime-global `_g_autoSaveProject`, not a `$0C` project field.
The official native runtime initializes it to enabled and does not include it
in the 24-byte session save/load record. This proves reset-on-launch behavior
for the official runtime; physical hardware power-cycle persistence remains
unverified.

The same proof obtained otherwise change-driven `$13` telemetry by sending
`$06` project+track held state for about three seconds, releasing it, and
repeating to restore the toggle. This proves `$06` can execute this real
long-hold gesture. See
[Autosave and `$13` Pattern State](autosave-pattern-state.md).

### `$14` ModuleInfo

This is not battery state. It is the native replica global `g_moduleInfo`, exactly 24
bytes. The baseline connected device returned 24 zero bytes, consistent with no
expansion module attached. Static references now map:

```text
0...3    moduleCaps, UInt32 LE
4...7    moduleStatus, UInt32 LE
8...17   NUL-terminated module name
18       moduleConnected, nonzero when present
19       unknown
20       gates module track-send access and one synth render path
21...23  unknown/padding
```

The official app recognizes `oplab`, `line`/`in-out`, and `rumble`. Its module
panels further decode physical switch modes, Line input/output connection and
mono state, and Rumble level from `moduleStatus`.

Sending `$14` writes the global structure directly, so arbitrary probes are not
appropriate on a live device. A raw replicated-state write is not a physical
module-control API. See [Module and Lights Control](module-and-lights-control.md)
for the complete bit map and evidence boundary.

### `$19` SamplerState

```text
0...3    sample start, UInt32 LE
4...7    sample end, UInt32 LE
8...11   loop in, UInt32 LE
12...15  loop out, UInt32 LE
16...17  pitch, Int16 LE
18       gain
19...20  sampler-context bytes, exact names pending
```

OP-Z Lab has a lossless encoder for this record and a rollback-first hardware
probe.

Static analysis now proves the complete inbound write path:

1. `StateSync::processMessage` maps message ID `$19` to a branch that accepts
   exactly 21 unpacked bytes.
2. It stores those bytes in the pending `SamplerState` record and raises its
   apply flag.
3. `StateSync::handleReceivedMessages` consumes that flag and calls
   `Sequencer::applySamplerState`.
4. That function delegates directly to `SamplerContext::setSamplerState`.

The desktop simulator's final setter is only a 21-byte local structure copy,
because sample editing and DSP are stubbed in this build. The routing itself
is nevertheless symmetric with the real device protocol. `$19` is therefore
a genuine low-latency sampler-state write API, not a simulated key gesture.
The simulator cannot prove its real-device edit semantics: its outbound
start/end, loop, pitch, and gain getters are inert and reconstruct an all-zero
record even after the inbound setter stores a changed record.

Two connected-device runs requested StateSync outside Sampling Mode. Neither
produced `$19`, and both timed out before sending any `$19` mutation. The
second harness run selected Project 1, Pattern 6, Track 5 and waited 90 seconds
for a physical Sampling Mode transition. No transition arrived. A fresh
342,272-byte bank readback still had the exact baseline SHA-256
`99895675d0a23f21a463cd8dbca2e49e65e94b46e9fa0692ea51b3b84fc6cd9b`.

This confirms that the record is context-dependent and prevents using an
invented all-zero state as a write baseline. Reversible start/end, loop, pitch,
and gain writes remain live-unproven until a genuine Sampling Mode `$19`
baseline is captured.

### Sampling Mode entry boundary

The official manual documents only the physical `stop` + `rec` gesture. Static
analysis explains why common remote substitutions do not reproduce it:

- `DefaultContext::onCC` receives the simulator's internal panel-control IDs.
  Internal ID 15 is Record, 16 is Play, and 17 is Stop. A Record press while
  Stop is held calls `Sequencer::hasUserSamplePackActive`; a true result sets
  the sampler-context transition byte.
- The companion simulator implementation of `hasUserSamplePackActive()` is a
  two-instruction stub that always returns false. The call proves that the
  hardware has an active-pack gate, but the plugin cannot reveal the hardware
  predicate itself.
- These numbers are not MIDI controller numbers. Ordinary incoming MIDI CC 15
  is pan and CC 17 is portamento.
- `Sequencer::handleMidiMessage` routes `0xB0` messages to the normal CC engine,
  not to `DefaultContext::onCC`.
- Inbound `$06` applies a packed UI snapshot by copying held-button fields. It
  does not synthesize the required Record edge or call the context transition.
- The managed app only reads `samplingMode` from the native sequencer mirror.
  Its UI has no command that remotely enters Sampling Mode.

A local clean-room simulator experiment closed the desktop side of this path.
The unmodified plugin left the sampler request and `$1A` context byte at zero.
Changing only the private simulator stub's return value to true made the same
Stop+Record call set request byte `0x61`, and `updateActiveContext()` changed
`$1A` byte 4 from `0` to `1`. This proves the control path without claiming
that the simulator's stub describes the hardware predicate. See the
simulator oracle evidence (private evidence; not distributed).

A mistaken CC 15/17 probe changed normal sound parameters and was immediately
rolled back by uploading the exact pre-probe bank. A second independent device
readback matched the baseline byte-for-byte. The proof harness no longer emits
those CCs.

No host-callable Sampling Mode entry command is currently known. Synchronized
hardware captures proved that a physical `stop` + `rec` gesture alone is not
sufficient after selecting an imported `flags: 2` pack through pattern recall.
Physically selecting that pack first produced a `$1A` load-progress transition,
then the correctly captured `stop` + `rec` edges still did not enter sampler
context. An attempted empty-slot creation produced a full `$1A` progress ramp
but no durable slot-map change and no sampler context. The exact active-pack
predicate therefore remains open. Pressing `stop` exits a context once entered,
as documented by Teenage Engineering's
[sampling guide](https://teenage.engineering/guides/op-z/sampling).

### `$15...$18` Full Sample Visualization

This is a separate bulk protocol from `$1B`. Payloadless `$15` asks the master
to compress its current 8,192-byte selected-sample visualization. The sender
uses:

```text
$16  part index, 180 compressed bytes
$17  acknowledged part index
$18  final part index, 1...180 compressed bytes
```

Parts are zero-based and strictly ordered. The sender transmits part zero,
waits for `$17 00`, then sends part one. It accepts at most 93 parts
(`0...92`). The final `$18` is not acknowledged. Concatenating bytes after
each part index and inflating the resulting zlib stream yields exactly 8,192
unsigned visualization values.

Two independent clean-room requests to the connected OP-Z completed in 18
parts and produced the same nonempty visualization: 3,844 nonzero values,
range `0...221`, SHA-256
`049eddf9a30146827aef35b9ff1ebad17e89a6e00b7714178e4d1a9d000c0abf`.
No Sampling Mode, Content Mode, or device-state mutation was required.

The values are a display envelope, not source PCM and not a sample-file export.
OP-Z Lab now assembles and renders this waveform directly. See
the private evidence ledger (private evidence; not distributed).

### `$1A` SamplerUIState

```text
0  sampler context
1  create-user-pack progress
2  current sampling position, zero or one-based position while sampling
3  sampler page
4  flags: bit 0 context-active, bit 1 reference tone
```

Connected-device differentials establish byte 1 more precisely. Physical
selection of imported Bass slot 10 emitted `1 -> 0`. Holding Track with empty
Sample slot 9 emitted `1 -> 2 -> 3 -> 4 -> 3 -> 2 -> 1 -> 0`. In both cases
the other bytes remained `FF 00 00 00 18` at rest, context-active bit 0 stayed
clear, and a fresh settings pull showed no slot-map or plug-table change.
Byte 1 is therefore the user-pack operation progress animation/state, not proof
that creation committed.

### `$1B` AudioVisState

Only byte 0 is populated by the current send path. Its low and high nibbles are
two visualization values. Bytes 1–3 remain reserved in the observed firmware.

## `$04` Battery Cross-Check

The four decoded bytes are:

```text
0  battery percentage, 0...100
1  master output volume, 0...255
2  bits 0...3: microphone level minus one; bits 4...5: microphone FX;
   bit 6: input monitor or sampler preview
3  bits 0...3: input selector or sampler context; bit 4: microphone mode
   or sampler recording
```

The official plugin's 22,820-byte `SequencerState` ABI places battery at offset
`22804`. Static disassembly showed a disconnected initialization value of
`50`. A read-only live probe then observed the field change to `100` at the
same instant StateSync connected and received decoded `$04` payload
`64 6E 05 00`. The adjacent ABI fields also matched that payload: master
volume `110`, encoded microphone level `5` (internal/UI level `6`),
microphone FX `0`, and mode `0`.

Battery percentage is therefore available over ordinary USB or BLE MIDI
StateSync. The same message also carries input routing and monitoring state.
Charging state and battery voltage are not present in the mapped exchange
structure. The plugin separately exports `g_usbChargingEnabled`, but that
firmware-local boolean is neither copied into `SequencerState` nor proven
writable over MIDI. `$66` is a packed serial tunnel with unused power-mode
library constants, not proof of a charging-state API. See
[battery-and-serial-tunnel.md](battery-and-serial-tunnel.md).

## `$0E` Current Sound Parameters

Decoded payload:

```text
0       zero-based track index
1...18  the track's 18 sound-parameter bytes
```

The inbound handler accepts exactly 19 decoded bytes. It writes all 18
parameters into the active pattern's sound block and mirrors them into the
current-parameter buffer used by the running engine. It does not select a plug,
recall plug-specific parameter memory, reset the engine, or apply a preset.

A direct connected-device proof on 2026-07-27 changed Pattern 1 Lead Filter
from `127` to `255`. Fresh pattern-bank readback contained that exact byte.
With transport running, matched five-second USB-audio captures measured:

| Filter | Peak | RMS |
| ---: | ---: | ---: |
| `127` | `0.344104290` | `0.103034453` |
| `255` | `0.363564610` | `0.023902284` |

The original `$0E` record was then sent and a fresh complete bank matched the
pre-test SHA-256
`99895675d0a23f21a463cd8dbca2e49e65e94b46e9fa0692ea51b3b84fc6cd9b`.
This proves `$0E` as an immediate, 8-bit, all-parameter sound editor. It is
lower latency and higher resolution than individual 7-bit MIDI CCs, but it
still targets only the active pattern.

The `$0E` frame can be constructed with `opzsysex.sysex.frame`. The historical
live proof harness is not distributed; the public Python device layer does not
yet automate this reversible write/readback experiment.

## No Hidden Preset Recall

Neither `$04` input/level state nor `$13` pattern runtime state calls
`TrackContext::applyPreset` or `TrackContext::selectPlug`. Neither is a hidden
plug or preset recall command.

## `$61` Gate Sequencer

The SysEx dispatcher checks only the message ID. For `$61`, it does not read or
validate any payload and calls `Sequencer::addGateSequencerStep`.

That method increments one byte. `Sequencer::stepGateSequencer` consumes one
count, scans all 16 tracks, and steps only tracks whose type byte equals `0A`.
It then decrements the count. Consequences:

- one `$61` frame queues one gate-sequencer pass;
- payload bytes have no meaning;
- it is realtime/ephemeral;
- it does not mutate persistent pattern gate bytes;
- it is not a lower-latency surgical drum-step editor.

A payloadless `$61` was accepted during the live cursor probe and produced no
state response. Persistent note-trig edits continue to require the proven
flow-controlled `$09`/`$0A` bank path.

## Upload ACK and Rejection

`$0B` is an eight-byte success ACK:

```text
09 00 00 00 <transfer-id LE16> <packet-index LE16>
```

The sender builds it from the current `$09` packet header. The receiver accepts
it only when both values match its pending transfer and expected prior packet.

Pattern receive failures use a different message:

```text
F0 00 20 76 01 08 <packed FF FF FF FF> F7
```

The rejection covers malformed unpacking/size, transfer-ID changes, and
non-consecutive packet indexes. A harmless empty `$09` probe produced this
rejection in 4 ms. OP-Z Lab now:

1. validates each ACK's transfer ID and packet index;
2. fails immediately on `$08 FF FF FF FF`;
3. retains the complete pre-edit bank;
4. reuploads it after failure;
5. requests a fresh snapshot and requires byte equality.

A later no-op hardware matrix proved that skipped and duplicate packet indexes,
a changed transfer ID, and a premature `$0A` all return the exact same generic
rejection in 7-8 ms. There is no `$0B` error-detail variant: `$0B` is strictly
the success ACK. Restarting at packet 0 worked after every rejection and after
silently abandoning two acknowledged packets. Each recovery ended with an
exact 342,272-byte readback. See
pattern-fault-proof-2026-07-27 (private evidence; not distributed).

## Latency

Timestamped USB-MIDI measurements:

| Operation | Observed response |
| --- | ---: |
| MIDI note echo | 1–2 ms |
| CC 1 to `$0E` sound state | 2 ms |
| mute CC to `$02` delta | 4–5 ms |
| inbound `$07` to echoed `$07` | 6–11 ms |
| malformed `$09` to `$08` rejection | 4 ms |

These are single-machine observations, not scheduling guarantees. They show
that realtime MIDI and small StateSync messages are suitable for interactive
control; full compressed pattern-bank writes remain a larger transaction.

## External References

- [`MarkRdgOx/opzdoc`](https://github.com/MarkRdgOx/opzdoc)
- [`leddy231/libopz`](https://github.com/leddy231/libopz)
- [`lrk/z-po-project`](https://github.com/lrk/z-po-project)
- [`patriciogonzalezvivo/libopz`](https://github.com/patriciogonzalezvivo/libopz)
