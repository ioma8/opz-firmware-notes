# OP-Z User-Plug and Sample Removal

Status: protocol decoded and hardware-proven on 2026-07-26 against firmware
`1.2.45+`.

## Protocol

Removal is a normal file-server sync job. The host serves `syncjob.json` as
reserved file ID `2`; its `files` array contains:

```json
{
  "operation": "remove",
  "plugId": 60003
}
```

No sample path or separate delete message is sent. The usual clean-room
`$51/$52/$34/$35/$53/$33/$55` session carries the one-part manifest.

## Evidence for the Shape

Clean-room analysis of the official companion protocol exposed these operation
names:

- `AddSyncRemoveUserPlug`
- `FileServer::addRemoveUserPlug(unsigned int)`
- `PlugManager::removeUserPlugAndSample(unsigned int, bool)`

Disassembly of `FileServer::addRemoveUserPlug` shows it constructing an object
with string value `remove` under key `operation`, the unsigned argument under
key `plugId`, appending it to the sync job's `files` array, and writing
`syncjob.json`.

The clean implementation reproduces only this observed data contract. It does
not load or link the official bundle.

## Hardware Proof

A temporary test plug referenced a user-owned synthetic sample and was no
longer assigned to any slot.

1. The clean remover sent one manifest part.
2. Fresh `plugs.json` readback changed the count for ID `60003` from one to
   zero.
3. The identical 423,392-byte AIFF was then reinstalled at the identical path
   and CRC.
4. Firmware requested the full sample again; the sender served 2,150 parts.
   This proves removal deleted the underlying sample bytes, not only the plug
   catalog entry.
5. The slot map was restored exactly.
6. Plug `60003` was removed again and final readback contained no matching
   plug. Client-state CRC returned to `01287F2B`.

Evidence is in
the private evidence ledger (private evidence; not distributed).

## Safety Rule

Before removal, pull both reserved settings files and refuse to transmit if any
slot still references the plug ID. `opzsysex.fileprotocol.UploadState` can build
the remove operation in a sync-job manifest, but the public Python layer does
not yet orchestrate or verify the live transaction. Removal is irreversible
through the known protocol because arbitrary installed sample bytes cannot be
downloaded. Preserve the original source before removal.

Fresh readback must confirm that the plug ID is gone. Firmware `1.2.45+`
deletes an associated user sample, but retains a unique custom engine
definition after its last plug reference is removed. The removal report and
`remove-report.json` expose that condition as `orphanEnginePaths`; it is not a
failed plug removal. Shared factory engines are not reported as orphans while
another installed plug references them.

Command:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

The journal captures before/after catalogs and the exact request cursor.

## Custom-Engine Removal Proof

The connected device was power-cycled after removing custom plug `60006`.
Fresh normal-mode readback showed:

```text
plug 60006 count:       0
slot references:        0
clean-tone.engine count: 1
client-state CRC:       D6D34300
```

An earlier independent removal of plug `60002` produced the same result for
`engines/researchmute.engine`. This is persistent firmware behavior, not a
stale host cache. The known remove manifest has no engine path, and no
normal-mode arbitrary-file delete operation has been identified.

## Remaining Questions

- Whether lower-numbered third-party user plugs have a reliable user flag that
  can be exposed as a safe remove affordance.
- Whether removal also clears every preset record associated with the plug.
- Whether a separate garbage-collection operation exists for orphan engine
  files that have no plug definition. Content mode is the known fallback, but
  it interrupts normal MIDI/audio operation.
