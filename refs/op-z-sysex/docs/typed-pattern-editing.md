# Typed Pattern Editing

Status: Device-proven against firmware `1.2.45+` on 2026-07-26.

## Result

The complete `$09`/`$0A` pattern-bank writer now supports typed, independent
mutations for:

- Notes and chords on all 16 tracks.
- Pitch, velocity, duration, and microtiming.
- Parameter-lock values and enable masks.
- Step-component masks and value bytes.
- All 18 persistent sound parameters per track.
- Tape and Master routing masks.

These are direct pattern-memory edits. They do not simulate OP-Z controls and
do not require record mode.

Every operation starts from a fresh 342,272-byte snapshot, preserves unrelated
bytes, uploads with `$0B` flow control, requests another snapshot, and confirms
the requested values. OP-Z Lab attempts to restore the exact pre-edit bank if
the upload or confirmation fails.

## Pattern Layout

Each of 16 patterns occupies 21,392 bytes:

| Offset | Size | Contents |
| ---: | ---: | --- |
| `0` | 192 | 16 track records |
| `192` | 7,040 | 880 note records |
| `7,232` | 13,824 | 256 step records |
| `21,056` | 288 | 18 sound bytes x 16 tracks |
| `21,344` | 40 | 10 mute groups |
| `21,384` | 2 | Tape routing mask |
| `21,386` | 2 | Master routing mask |
| `21,388` | 1 | Active mute group |
| `21,389` | 3 | Unresolved/padding |

All multibyte values are little-endian.

## Notes and Chords

One note record is eight bytes:

```text
0...3  signed 32-bit duration
4      MIDI note; FF means unused
5      velocity
6      signed microtiming
7      age
```

Duration uses 6,200 units per OP-Z step. Current-firmware experiments in
`leddy231/libopz` observed microtiming moving in raw increments of eight, over
`-96...+88`, corresponding to displayed ticks `-12...+11`. OP-Z Lab therefore
accepts displayed ticks and stores `ticks * 8`.

Note records are interleaved by step. Every step contains 55 slots:

| Track | Offset | Slots per step |
| --- | ---: | ---: |
| Kick | 0 | 2 |
| Snare | 2 | 2 |
| Perc | 4 | 2 |
| Sample | 6 | 2 |
| Bass | 8 | 4 |
| Lead | 12 | 4 |
| Arp | 16 | 8 |
| Chord | 24 | 4 |
| FX1 | 28 | 1 |
| FX2 | 29 | 1 |
| Tape | 30 | 1 |
| Master | 31 | 4 |
| Perform | 35 | 6 |
| Module | 41 | 6 |
| Lights | 47 | 4 |
| Motion/Video | 51 | 4 |

The writer replaces the occupied note slots requested by the caller. For
remaining slots it changes only byte 4 to `FF`, preserving all other bytes.

## Parameter Locks

Each track/step has one 54-byte record:

```text
0...1   component mask
2...17  16 component values
18...35 18 locked parameter values
36...53 18 lock enable bytes
```

The records are track-major:

```text
7232 + (trackIndex * 16 + stepIndex) * 54
```

This ordering was confirmed by a physical Lead step-1 filter-lock diff. The
record begins at `11552`; filter value byte 8 is at `11578` and its enable byte
is at `11596`.

The parameter order is:

1. Parameter 1
2. Parameter 2
3. Attack
4. Decay
5. Sustain
6. Release
7. FX 1 send
8. FX 2 send
9. Filter
10. Resonance
11. Pan
12. Level
13. Portamento
14. LFO depth
15. LFO speed
16. LFO target/value
17. LFO shape
18. Note style

Setting a lock writes its value byte and sets the corresponding enable byte to
`FF`. Clearing it sets only the enable byte to `0` and preserves the last
value. All genuine locks observed on the connected OP-Z use `FF`.

## Step Components

The 16-bit mask and value-array indexes are:

| Index | Bit | Component |
| ---: | ---: | --- |
| 0 | `0001` | Pulse |
| 1 | `0002` | Parameter Spark |
| 2 | `0004` | Jump |
| 3 | `0008` | Velocity |
| 4 | `0010` | Ramp Up |
| 5 | `0020` | Ramp Down |
| 6 | `0040` | Random |
| 7 | `0080` | Glide |
| 8 | `0100` | Multiply |
| 9 | `0200` | Sweep |
| 10 | `0400` | Pulse Hold |
| 11 | `0800` | Tonality |
| 12 | `1000` | Trigger Spark |
| 13 | `2000` | Component Spark |
| 14 | `4000` | Reserved |
| 15 | `8000` | Reserved |

Enabling a component sets its bit and writes its value at
`step[2 + componentIndex]`. Disabling clears only the bit and preserves the
value. The device accepted and returned all 14 named bits independently.

USB MIDI/audio playback additionally proves Pulse raw `4`, Multiply raw `4`,
and Trigger Spark raw `2`: an otherwise identical one-step sequence produced
5, 16, 20, and 2 note-ons respectively for baseline, Pulse, Multiply, and
Trigger Spark.

Teenage Engineering documents components only for audio tracks 1-8 and provides
the musical meaning of value keys 1-0 in the
[official component chart](https://teenage.engineering/guides/op-z/step-components).
The app represents those ten settings as raw values `1...10`, with an advanced
raw-byte mode. A fresh-process raw-4 matrix matched exact readback for all 14
named bits and produced the official key-4 behavior wherever outgoing MIDI
could expose it. Spark high-nibble modes `0x04`, `0x14`, and `0x24` are also
decoded from the third-party project-format research.

Paired connected-device fixtures prove that ordinary Spark raw values `1...8`
mean **Pass N**. Raw `2` gated a filter lock, Multiply, and a note trigger on
the same alternating second-pass phase. It does not mean cumulative passes
1 through 2. Glide 4 and Filter Up Sweep also have direct USB-audio trajectory
proof. See
component-fixtures-2026-07-27 (private evidence; not distributed).

Raw `10` remains intentionally labeled **Reset counter**, but its exact local
scope is not yet claimed. A live one-byte matrix proved that full-bank `$09`
application perturbs a Spark counter even when the uploaded byte is unchanged;
the writer therefore cannot serve as a transparent runtime mutation for this
question. See the
Spark reset live-state boundary (private evidence; not distributed).

## Sound Parameters

Each track has 18 persistent bytes at:

```text
21056 + track * 18 + parameter
```

Their order is identical to the parameter-lock order above. This differs from
live MIDI only in persistence: a full-bank edit changes the stored pattern
value directly instead of performing a CC gesture.

## Routing

Tape and Master each use a little-endian 16-bit mask. Bit zero is Kick and bit
15 is Motion/Video:

```text
trackMask = 1 << trackIndex
```

The writer can replace either complete mask or independently set/clear the
selected track's bit.

USB MIDI/audio fixtures prove both words execute. Tape bit 5 changed the
audio-domain tape treatment of Lead without changing its MIDI notes. Master
bit 5 changed all routed Lead notes from C to G under a stored Master G note,
while the zero-mask control left them at C.

## Live Proof

The comprehensive proof targeted empty, inactive Pattern 16 in Project 3:

- 336 typed mutations.
- 609 changed byte offsets.
- Maximum chord allocation on every track.
- One independent parameter lock on every track.
- All 14 named component bits and values on tracks 1-8.
- All 288 sound-parameter bytes.
- Tape mask `A55A` and Master mask `5AA5`.
- 45-packet acknowledged upload.
- Exact 342,272-byte device readback.
- 40-packet restoration.
- Exact original-bank readback from the device and a separate process.

See the
proof artifacts (private evidence; not distributed).

Control-track storage also has direct output proof. With temporary exact-
readback `$10` enables, tracks 9, 10, 11, 13, 14, 15, and 16 emitted their
stored pitch, velocity, gate, and loop timing on their configured MIDI
channels. Master track 12 remained internal-only in the same fixture. See the
control-track MIDI proof (private evidence; not distributed).

## Remaining Behavioral Proof

The storage API and representative runtime behavior are proven. These narrower
questions remain:

- Resolve Spark Reset raw `10` with one same-step physical value change that
  does not invoke `$09` or reload the pattern.
- Complete the useful note ranges and transfer curves for FX and Perform.
  Follow/Echo, FX sends, and note-dependent Delay/Reverb audio are proven.
- Characterize Module, Lights, and Motion against their peripheral/app
  destinations. Ordinary MIDI output is proven.
- Confirm host-written pattern state after an OP-Z power cycle.
- Determine whether `$61` offers a lower-latency single-gate write.

## Implementation

- `opzsysex.project.PatternBankEditor`: typed, validated byte mutations.
- `opzsysex.sysex.pattern_upload_frames`: lossless prefix/bank packetization.
- `tools/edit_project.py`: bounded offline editing of user-supplied checkpoints.
- `Tests/test_protocol.py`: generated-fixture offset and round-trip tests.

The public Python package does not yet orchestrate live pattern writes,
readback, and rollback; the documented hardware results predate this extraction.
