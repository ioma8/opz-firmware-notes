# OP-Z SysEx documentation

This index is scoped to computer communication and reverse-engineered SysEx
behavior. References to the official companion software describe observed wire
behavior or provenance; no application code or platform-specific tooling is
included.

## Start here

- [coverage.md](coverage.md): evidence ledger, safety boundary, and open work.
- [sysex-app-protocol.md](sysex-app-protocol.md): envelope, handshake, message
  IDs, and StateSync overview.

## Project and live state

- [typed-pattern-editing.md](typed-pattern-editing.md)
- [project-global-format.md](project-global-format.md)
- [native-chain-writing.md](native-chain-writing.md)
- [native-state-sync-analysis.md](native-state-sync-analysis.md)
- [autosave-pattern-state.md](autosave-pattern-state.md)
- [live-position-and-chain-state.md](live-position-and-chain-state.md)
- [host-write-persistence.md](host-write-persistence.md)
- [midi-configuration-sysex.md](midi-configuration-sysex.md)
- [module-and-lights-control.md](module-and-lights-control.md)
- [exhaustive-pattern-proof-progress.md](exhaustive-pattern-proof-progress.md)

## File transfer and content

- [clean-room-file-transport.md](clean-room-file-transport.md)
- [normal-mode-sample-transfer.md](normal-mode-sample-transfer.md)
- [sample-tool.md](sample-tool.md)
- [user-plug-removal.md](user-plug-removal.md)

## Serial tunnel

- [battery-and-serial-tunnel.md](battery-and-serial-tunnel.md)

## Confidence key

- **Official:** documented by Teenage Engineering or a platform standard.
- **Device-proven:** confirmed by readback, captured output, or restoration.
- **Decoded:** parsed consistently, but not necessarily written field by field.
- **Observed:** recorded on the wire without complete semantic explanation.
- **Inferred:** supported by analysis but not isolated experimentally.
- **Unknown:** present but unresolved.
