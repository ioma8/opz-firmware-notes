# OP-Z SysEx coverage and evidence

This is the canonical scope and confidence ledger for the standalone
`op-z-sysex` extraction. It records what the included code and tools support
without turning protocol evidence into broader application claims.

## Evidence vocabulary

- **Official:** documented by Teenage Engineering or a platform standard.
- **Device-proven:** exercised on OP-Z hardware and confirmed by fresh readback,
  captured output, or exact restoration.
- **Decoded:** parsed consistently from device/project bytes, but not necessarily
  written field by field.
- **Observed:** captured on the wire without a complete semantic explanation.
- **Inferred:** supported by symbols, disassembly, or behavior but not isolated
  in a controlled experiment.
- **Unknown:** a message, field, or transport exists but its semantics are open.

## Current coverage

| Area | Status | Evidence and boundary |
|---|---|---|
| TE SysEx envelope and 7-bit packing | Device-proven | Framing, packing, zlib payloads, request/response parsing, and realtime-byte tolerance have offline and hardware evidence. See [sysex-app-protocol.md](sysex-app-protocol.md). |
| App handshake and StateSync | Device-proven/decoded | Session handshake, telemetry, sequence numbers, delta recovery, ACK/rejection behavior, and snapshot recovery are implemented. Not every field is semantically named. See [native-state-sync-analysis.md](native-state-sync-analysis.md). |
| Project pattern banks (`$08/$09/$0A`) | Device-proven | Full-bank and bounded-prefix writes, notes/chords, velocity, duration, microtiming, locks, components, sound bytes, routing, mutes, length, and plug IDs have readback/rollback evidence. See [typed-pattern-editing.md](typed-pattern-editing.md). |
| Project-global state (`$0B/$0C`) | Device-proven/decoded | The 568-byte payload, tempo, selected chain, and 15 saved chains are mapped; unknown bytes remain preserve-only. See [project-global-format.md](project-global-format.md). |
| Active-chain state (`$07`) | Device-proven | Chain recall payload and repeated-entry cursor behavior are covered; no beat-resolution playhead was found. See [live-position-and-chain-state.md](live-position-and-chain-state.md). |
| MIDI configuration (`$0F/$10`) | Device-proven | The 292-byte layout, typed settings, query/write framing, readback, and rollback are covered. Preserve unknown bytes. See [midi-configuration-sysex.md](midi-configuration-sysex.md). |
| Autosave state (`$13`) | Device-proven | Runtime-global autosave behavior and the related project/track hold path are documented with rollback-first tooling. See [autosave-pattern-state.md](autosave-pattern-state.md). |
| Module state (`$14`) | Device-proven/decoded | Module layout and Oplab/Line/Rumble status parsing are covered; some peripheral semantics remain unresolved. See [module-and-lights-control.md](module-and-lights-control.md). |
| Serial tunnel (`$66`) | Device-proven/guarded | Framing and ping/pong are covered. Potential power commands remain guarded. See [battery-and-serial-tunnel.md](battery-and-serial-tunnel.md). |
| SysEx file server | Device-proven | Handshake, manifest, chunking, retransmission, pull/push, inventory, sample install, readback, and rollback are implemented. See [clean-room-file-transport.md](clean-room-file-transport.md). |
| User sample/content install | Device-proven | Prepared sampler AIFF installation and slot-map verification work over normal USB MIDI. Normal-mode download remains bounded. See [normal-mode-sample-transfer.md](normal-mode-sample-transfer.md). |
| User plug removal | Device-proven | An unassigned user plug and sample can be removed through the decoded sync-job path with before/after verification. See [user-plug-removal.md](user-plug-removal.md). |
| Host-write persistence | Device-proven | Pattern/global writes survived the documented save/reload flow. Persistence remains a separate claim from an ACK. See [host-write-persistence.md](host-write-persistence.md). |

## Safety invariants

1. Use a disposable project or slot and take a fresh checkpoint first.
2. Serialize device access; never overlap file or StateSync sessions.
3. Treat `sent`, `acknowledged`, `saved`, `read back`, and `heard` as distinct.
4. Preserve opaque bytes and untouched project regions exactly.
5. Verify every write using a new device read, not the outbound buffer.
6. Restore the checkpoint and verify the restoration by readback.
7. Fail closed on malformed frames, missing snapshots, sequence gaps,
   unexpected sizes, unknown firmware layouts, or unsolicited debug frames.

## Offline verification

```sh
python3 -m unittest discover -s Tests -p 'test*.py'
python3 -m unittest discover -s Tests/ToolingTests -p 'test*.py'
```

The suites cover packing, zlib, file-transfer state machines, StateSync,
project/global decoding, typed pattern edits, MIDI configuration, serial
framing, sample preparation, slot-map edits, and validation failures.

## Public evidence policy

The [`evidence/`](../evidence/) directory contains human-written experiment
summaries only. It intentionally excludes firmware and app binaries, factory or
stock projects, backups, raw project banks, audio and samples, wire captures,
logs, and machine reports that may expose content metadata or private paths.

## Open questions

- Complete the semantic map of unknown StateSync and project/global bytes.
- Reconfirm write paths after firmware changes.
- Determine whether a higher-resolution playhead exists beyond the chain cursor.
- Establish save cadence and atomicity under sustained live writes and faults.
- Prove inferred peripheral or serial commands with reversible readback before
  exposing them as writable API.
- Keep normal-mode sample download claims separate from proven upload and
  advertised-file reads.
