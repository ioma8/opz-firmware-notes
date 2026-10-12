# MIDI Configuration over StateSync

This document maps the OP-Z app's complete MIDI-configuration exchange. It is
based on analysis of the official companion protocol and a reversible
read/write/readback experiment against firmware `1.2.45`.

Confidence: Device-proven for reading, writing one parameter-CC assignment,
fresh readback, and exact rollback. Static analysis plus device evidence for
the complete structure. Persistence across a physical power cycle is not yet
proven.

## Result

The app does not simulate buttons to configure MIDI. It uses a compact,
bidirectional StateSync API:

```text
Read request:
F0 00 20 76 01 0F F7

Read response or complete write:
F0 00 20 76 01 10 <7-bit-packed zlib stream> F7
```

Inflating the `$10` body must produce exactly 292 bytes. Sending a compressed
292-byte structure in `$10` replaces the MIDI configuration. The OP-Z reports
the applied structure back through `$10`; an explicit `$0F` then provides an
independent fresh read.

## Decoded Layout

| Offset | Size | Field | Encoding |
| ---: | ---: | --- | --- |
| `0` | 16 | Track MIDI enable | One byte per track; zero is off, nonzero is on. |
| `16` | 16 | Track channel | One zero-based channel per track, `0...15`. |
| `32` | 256 | Parameter CC output | Track-major `16 tracks * 16 parameters`; values `0...127`. |
| `288` | 1 | Global settings | Eight bit flags below. |
| `289` | 3 | Padding/reserved | Preserve exactly when editing. |

Parameter address:

```text
offset = 32 + track * 16 + parameter
```

Both `track` and `parameter` are zero-based. The 16 parameter positions follow
the OP-Z's four parameter pages, four controls per page. These are outgoing CC
assignments; they do not replace the fixed incoming parameter CC map.

### Settings Byte

| Bit | JSON/app name | Meaning when set |
| ---: | --- | --- |
| `0` | `channel_one_to_active` | Route incoming channel 1 to the active track. |
| `1` | `incoming_midi` | Enable incoming MIDI. |
| `2` | `outgoing_midi` | Enable outgoing MIDI. |
| `3` | `timing_clock_in` | Enable incoming MIDI clock. |
| `4` | `timing_clock_out` | Enable outgoing MIDI clock. |
| `5` | `alt_program_change` | Use alternate program-change behavior. |
| `6` | `midi_echo` | Enable MIDI echo. |
| `7` | `enable_program_change` | Enable program change. |

The official native JSON importer initializes this byte to `0x97`, then
overwrites each named bit. The current connected device returned `0x95`.

## Official App Evidence

The managed `OPZ.MidiConfig` type in `Assembly-CSharp.dll` has
`StructLayout(Pack = 1)` and these exact fields:

```text
byte channelEnable[16]
byte trackToChannel[16]
byte parameterToCC[256]
byte settings
byte padding1
byte padding2
byte padding3
```

`UIMidiPanel` calls native `SetMidiConfigChannel`,
`SetMidiConfigCC`, and `SetMidiConfigSettings`, then calls
`CommitMidiConfig()` on a one-second UI timer while dirty.

The arm64 `SnakePlugin` binary proves the transport:

- `StateSync::update()` sends an empty message ID `$0F` after about 2 seconds
  when it needs the current config.
- The `$10` receive arm 7-bit-unpacks into a 512-byte temporary buffer.
- `StateSync::applyMidiConfig()` inflates it and accepts only `0x124` (292)
  output bytes.
- `StateSync::sendMidiConfig()` queues the 292-byte global structure as
  compressed message ID `$10`.
- `CommitMidiConfig()` calls that sender when connected to an OP-Z.

The installed binary exports all relevant symbols, including
`_CommitMidiConfig`, `_SetMidiConfigChannel`, `_SetMidiConfigCC`,
`_SetMidiConfigSettings`, `StateSync::sendMidiConfig`, and
`StateSync::applyMidiConfig`.

## Connected-Device Proof

The proof changed only Track 16, parameter 16's outgoing CC assignment:

```text
offset 287: 16 -> 17
```

Sequence:

1. Send StateSync hello and empty `$0F`.
2. Save and decode the returned `$10`.
3. Send the one-byte-modified full config as `$10`.
4. Wait for the device's `$10` applied-state report.
5. Send a new `$0F`; verify a second `$10` equals the complete modified config.
6. Send the original full config as `$10`.
7. Wait for the applied-state report, query again, and verify all 292 bytes.
8. Perform one additional independent query.

Hashes:

```text
original  00dd0ad6b640208d601f6af8be62770446b1dd478d885adf2d57ae0f2dd710f8
modified  29677fe08fe5bf563a539a51b86e4a07070bc35de49df8e2896865263e6d7bf9
restored  00dd0ad6b640208d601f6af8be62770446b1dd478d885adf2d57ae0f2dd710f8
final     00dd0ad6b640208d601f6af8be62770446b1dd478d885adf2d57ae0f2dd710f8
```

The mutation's applied-state report arrived in 29 ms and its explicit read
response arrived 6 ms after `$0F`. The rollback report was delayed by roughly
2 seconds in this run, after which explicit reads completed in 9 ms. A client
must therefore wait for matching content, not assume a fixed low latency.

Evidence:

- proof summary (private evidence; not distributed)
- wire capture (private evidence; not distributed)
- manifest (private evidence; not distributed)

## Tool and API

Shared `OPZCore` now provides:

- `OPZMIDIConfiguration` typed decode/encode.
- Validated typed setters for all flags, track enables, channels, and CCs.
- `OPZProtocolEngine.midiConfigurationQuery`.
- `$10` read parsing and a cached current configuration.
- Complete compressed `$10` frame generation.
- A guarded app transaction that obtains a fresh baseline, writes, explicitly
  queries, compares all 292 bytes, and restores the baseline on failure.

The Device workspace includes an editor for all eight global flags, all 16
track enable/channel pairs, and all 256 parameter CC assignments. A live UI
proof changed disabled Kick parameter 16 from CC `16` to `17`, showed the
fresh `$10` readback, then restored `16` through the same editor and confirmed
the restored device state. The editor retains the three reserved bytes from
the fresh baseline rather than synthesizing them. If that baseline changed
while the editor was open, the transaction aborts before writing instead of
overwriting concurrent hardware or official-app changes.

`opzsysex.midi_config.MIDIConfiguration` decodes, validates, edits, and rebuilds
the complete structure. `tools/device_query.py midi-config` performs a read-only
query. The historical reversible write harness is not distributed.

Production editing should always preserve the three reserved bytes, retain a
fresh baseline, compare the complete reported structure after every write, and
restore the baseline on any mismatch.

## Public Repository Boundary

The public
[`leddy231/libopz`](https://github.com/leddy231/libopz)
protocol notes correctly identify `$0F` as a configurator command and `$10` as
zlib-compressed MIDI configuration. As of the inspected `main` branch, they
describe `$10` only as device-to-host and do not map the 292-byte structure or
implement writes. The
[`MarkRdgOx/opzdoc`](https://github.com/MarkRdgOx/opzdoc)
and
[`lrk/z-po-project`](https://github.com/lrk/z-po-project)
repositories likewise do not provide this bidirectional field map.

This proof therefore closes a previously documented gap in the public
reverse-engineering record.
