# Live Song and Beat Position

Status: Device-proven against a connected OP-Z on firmware `1.2.45+`,
2026-07-26.

## Result

The companion-app `$07` message reports substantially more than project and
pattern selection. While a pattern chain is active, its decoded 20-byte payload
contains:

```text
bytes 0...15  active chain, two zero-based pattern nibbles per byte
byte 16       active chain length, 0...31 on firmware 1.2.45+
byte 17       pattern address; low nibble is active zero-based pattern
byte 18       zero-based index of the next chain entry
byte 19       zero-based project
```

Nibble order is low, then high. For saved chain `1 2 2 3 4 5 6 6 7 8`, the
first five payload bytes are:

```text
10 21 43 55 76
```

Decoding low nibble first produces `0 1 1 2 3 4 5 5 6 7`, exactly matching
the chain stored in the current project's `$0C` global block.

This corrects the public `libopz`/`opzdoc` interpretation that byte 0 is always
the active pattern. Byte 0 only resembles a pattern number when no chain is
active. The active pattern is the low nibble of byte 17.

## Live Cursor Proof

The attached OP-Z was in project 3. Chain 1 contained:

```text
1 2 2 3 4 5 6 6 7 8
```

MIDI Start without recalling the chain looped pattern 1 and emitted this state
every 15 seconds:

```text
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 20 00 02
```

After physically recalling chain 1 with `project` plus the leftmost white piano
key, `$07` changed at each chain boundary:

| Chain entry | Pattern | Byte 17 | Byte 18 |
| ---: | ---: | ---: | ---: |
| 1 | 1 | `20` | `01` |
| 2 | 2 | `21` | `02` |
| 3 | 2 | `21` | `03` |
| 4 | 3 | `22` | `04` |
| 5 | 4 | `23` | `05` |
| 6 | 5 | `24` | `06` |
| 7 | 6 | `25` | `07` |
| 8 | 6 | `25` | `08` |
| 9 | 7 | `26` | `09` |
| 10 | 8 | `27` | `00` |
| loop | 1 | `20` | `01` |

The repeated `2 -> 2` and `6 -> 6` entries are the important controls. Byte 18
advanced even though byte 17 and the active pattern did not change. This proves
that `$07` exposes a real chain cursor, not a cursor inferred from pattern
changes.

Byte 18 is the next entry's zero-based index. Thus while entries 1–9 play it is
`01...09`; while entry 10 plays it wraps to `00`. The same rule covers the
whole executable chain:

```text
current position = next_index == 0 ? chain_length : next_index
```

A reversible host probe sent next indices `00...1F`. The OP-Z accepted and
echoed each in 6–11 ms, including `0A...1F`, then accepted an exact restore of
the original one-entry state. The same probe revealed that sending length 32 is
clamped to 31. Disassembly agrees: `applyPatternChainState` selects
`min(length, 31)` and writes `FF` at that offset. Therefore firmware `1.2.45+`
executes at most 31 entries through this path; a nominal 32nd storage byte is
reserved for the terminator.

The physical recall also revealed that `$0C` chain record 16 is the live active
chain buffer, not a sixteenth saved-chain slot. It changed from empty to an
exact copy of chain 1. Selecting pattern 1 over MIDI later replaced it with a
single `0` entry. Two exact readback cleanups returned that active buffer to its
original empty state while preserving chain 1 and all non-chain globals.

## Direct Recall and Start

`$07` is a real bidirectional state API, not just telemetry. Sending a packed
saved chain invokes the firmware's `Sequencer::applyPatternChainState`.

On project 1, saved chain 1 contained patterns `1...16`. The host sent that
chain as `$07`; 10 ms later the OP-Z echoed the exact 16-entry active chain.
The host then sent standard MIDI Start (`FA`). The device:

- echoed Start in 2 ms;
- emitted pattern-1 notes immediately;
- emitted Program Changes `1`, `2`, `3`, `4`;
- emitted matching `$07` positions `2`, `3`, `4`, `5` at each boundary.

This proves direct saved-chain recall and playback without button simulation
and without rewriting the saved `$0C` chain slot.

## Beat Inside a Pattern

There is no identified SysEx field carrying the current beat or step. The
normal timing surface is standard MIDI Clock:

- `F8` arrives 24 times per quarter note when `timing_clock_out` is enabled.
- Six clock ticks equal one sixteenth note.
- A track step advances every `step_length * 6` clocks.
- The app can combine clock phase with each decoded track's step count and step
  length to display independent playheads.

During this chain experiment, outgoing clock was disabled: the OP-Z emitted
notes and `$07` boundaries but zero `F8` messages. The observed chain boundary
interval was 15.000 seconds at 128 BPM, or 32 quarter notes. This permits a
wall-clock estimate after a boundary, but it is not as authoritative as MIDI
Clock and can drift.

The safe UI distinction is:

- **Exact chain entry:** device-proven from `$07` for the tested ten-entry
  chain.
- **Exact clock phase:** available when outgoing MIDI Clock is enabled.
- **Per-track step:** derived from clock, track length, and multiplier.
- **Without clock:** estimated from the host timestamp of the last `$07`
  boundary, not directly reported by the OP-Z.

Teenage Engineering documents the `tempo` + `screen`, key `5` toggle for
outgoing clock in the
[MIDI guide](https://teenage.engineering/guides/op-z/midi). The same guide says
song pointer is not used, so MIDI Song Position Pointer is not an alternative.

## Reproduce

Build the timestamped capture tool:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Capture passive state:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Capture while the host starts and later stops transport:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Recall saved chain 1 directly and start it:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Analyze one or more captures:

```sh
python3 tools/analyze_opz_position_capture.py capture.jsonl
```

The original proof captures and hashes are in
the private evidence ledger (private evidence; not distributed).
The cursor and direct-recall captures are in
the private evidence ledger (private evidence; not distributed).

## External Reverse-Engineering References

- [`MarkRdgOx/opzdoc`](https://github.com/MarkRdgOx/opzdoc) first cataloged
  `$07` as sequencer settings and noted that sending it causes the OP-Z to
  resend current state.
- [`leddy231/libopz`](https://github.com/leddy231/libopz) decodes byte 17 as a
  pattern address but previously treated byte 0 as the pattern.
- [`lrk/z-po-project`](https://github.com/lrk/z-po-project) documents the
  persistent project and chain structures.
- The official [project guide](https://teenage.engineering/guides/op-z/project)
  describes a nominal 32-pattern chain; the firmware `1.2.45+` `$07` path
  device-tested here clamps the executable representation to 31.
