# Normal-mode sample transfer

Status: **device-proven upload; bounded download**.

The OP-Z companion protocol exposes a file server over ordinary MIDI SysEx. A
host can install a prepared melodic or drum sampler AIFF without switching the
device into Content or Sampling Mode.

## Proven transaction

1. Start the file-session handshake and obtain the session identifiers.
2. Read `settings/slotConfiguration.json` and `settings/plugs.json`.
3. Preserve both files as the rollback checkpoint.
4. Build a sync-job manifest describing the sampler AIFF and updated slot map.
5. Serve each requested file in 200-byte, zlib-compressed `$53` parts.
6. Observe the client's completion cursor and bound outstanding parts.
7. Read both settings files again through a new session.
8. Confirm the intended slot/plug assignment from fresh bytes.
9. If any step fails, push the checkpoint and verify the restoration.

The Python implementation provides the file framing and upload/download state
machines in `opzsysex.fileprotocol`. `tools/file_manifest.py` constructs the
sync-job manifest offline. Full live installation orchestration has not yet
been ported to the cross-platform Python device layer; do not describe a
generated manifest as an installed or verified sample.

## AIFF boundary

Sampler content uses mono 16-bit, 44.1 kHz AIFF with an `APPL` chunk beginning
with `op-1` and JSON metadata. The retained Python sample formatter can build
melodic and 24-slice drum files from user-owned audio. No sample audio or
factory content is stored in this repository.

## Download boundary

Advertised settings and manifest files can be requested through the clean-room
file session. Normal-mode download of arbitrary installed sampler audio was not
proven. Keep that distinct from the proven upload path.

## Safety

- Close any other process connected to the OP-Z MIDI endpoints.
- Never replace an occupied slot without explicit user authorization.
- Keep original settings bytes, not merely parsed JSON.
- Treat transport completion, slot-map readback, plug activation, persistence,
  and audible output as separate success states.
- Fail closed on unknown requests, part indexes, file IDs, or CRC mismatches.
