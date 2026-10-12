# Native Pattern-Chain Writing

Status: Proven against a connected OP-Z on firmware `1.2.45+`, 2026-07-26.

## Result

The OP-Z's saved pattern chains can be read and written directly through the
companion-app SysEx protocol. This is not MIDI CC pattern selection and does not
simulate OP-Z button presses.

The project-global payload is exactly 568 bytes after 7-bit unpacking and zlib
inflation. Its first 512 bytes contain 16 chain records:

```text
chain offset = chain_index * 32
chain size   = 32 bytes
entry        = zero-based pattern index, 00...0F
unused       = FF
```

Records 1 through 15 are saved-chain slots. Record 16 is the live active-chain
buffer: recalling chain 1 copied its contents there, and selecting one pattern
over MIDI replaced it with a one-entry chain. Each record has 32 bytes, but
firmware `1.2.45+` executes at most 31 references because it clamps the active
length to 31 and reserves the following byte for `FF`.

## Wire Format

An upload is one custom SysEx frame:

```text
F0 00 20 76 01 0C <7-bit-packed zlib(global[568])> F7
```

Unlike the much larger pattern bank, this compressed block does not need the
`$09`/`$0A` packet sequence or `$0B` flow-control acknowledgements. There is no
separate observed `$0C` acknowledgement. Confirmation must come from a fresh
global-state readback.

The safe mutation sequence is:

1. Establish an app session with `$00` heartbeat and capture `$0C`.
2. Preserve all 568 bytes.
3. Replace only the selected chain's 32-byte range.
4. Deflate, 7-bit pack, and send the complete block as `$0C`.
5. Start a fresh heartbeat session and compare its returned `$0C`.

Do not construct the rest of the global block from defaults. It contains mixer,
tempo, swing, mute, routing, and other project state that must survive the edit.

## Live Proof

The proof used empty chain slot 15:

```text
before:   (empty)
written:  1 2 1
readback: 1 2 1
restored: (empty)
```

Only offsets `448`, `449`, and `450` changed in the device readback. These are
the first three bytes of chain 15 (`14 * 32`). A subsequent upload restored the
original block; the independently captured restoration matched all 568 original
bytes.

Artifacts are in
the private evidence ledger (private evidence; not distributed):

| File | SHA-256 |
| --- | --- |
| `before-global.bin` | `099bbe39f53dcaa856181489e55c2425b684220ad87797749da5a8a8f5a7aced` |
| `written-global.bin` | `f0e7888b135d2712e91bf8956418627f39fbb21c8d467e5140b25cfc8b5d7267` |
| `readback-global.bin` | `f0e7888b135d2712e91bf8956418627f39fbb21c8d467e5140b25cfc8b5d7267` |
| `restored-global.bin` | `099bbe39f53dcaa856181489e55c2425b684220ad87797749da5a8a8f5a7aced` |

The matching written/readback hashes prove device acceptance. The matching
before/restored hashes prove exact restoration.

## Reproduce

Build:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Read-only inventory:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Reversible write/readback/restore proof:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Reversible mapped scalar write/readback/restore proof:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Clear one chain record and retain exact before/write/readback artifacts:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Saved-chain arguments are user-facing numbers `1...15`; pattern numbers are
`1...16`. The low-level `clear` command also accepts record 16 for active-buffer
recovery. The proof command always restores the exact initially captured block.

## App Support

OP-Z Lab's Project workspace lists all 15 saved-chain slots and provides an
editor. Enter up to 31 pattern numbers, separated by spaces or commas. A blank
value clears the selected chain. The app reports success only after rotating its
heartbeat session token and receiving a fresh `$0C` whose decoded chain matches.

## Song Implications

Native chains provide a saved arrangement layer inside one project:

- 15 saved-chain slots plus one active-chain buffer per project.
- 32 storage bytes, with 31 executable pattern references on firmware 1.2.45+.
- Repetition is represented by repeated pattern numbers.
- The chain references patterns; it does not duplicate pattern content.

This makes programmatic song assembly viable when combined with the proven
full-bank `$09`/`$0A` pattern writer. A host can construct or edit the 16
patterns, write them, and write chain order without touching the OP-Z controls.

It is not an unlimited arranger. Longer or cross-project performances still
need host-driven pattern/project changes over MIDI, multiple prepared projects,
or further reverse engineering of how chain selection/playback is controlled.

## Reverse-Engineering Basis

Public groundwork:

- [`MarkRdgOx/opzdoc`](https://github.com/MarkRdgOx/opzdoc) documents the custom
  frame, app handshake, 7-bit packing, and message inventory.
- [`leddy231/libopz`](https://github.com/leddy231/libopz) provides a working
  protocol implementation and the proven full pattern-bank write path.
- [`lrk/z-po-project`](https://github.com/lrk/z-po-project) documents OP-Z
  project structures used to interpret pattern and global data.

Additional local analysis of Teenage Engineering's companion protocol found
symbols `StateSync::sendGlobalData`, `StateSync::applyGlobalData`, and
`Sequencer::applyPatternChainState`. Disassembly showed a 568-byte global-state
buffer sent through the compressed SysEx path and an inbound path that inflates
and applies the same state. The live proof above validates that interpretation.
