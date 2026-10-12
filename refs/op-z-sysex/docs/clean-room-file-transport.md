# Clean-Room Normal-Mode File Transport

Status: device-proven on 2026-07-26 with OP-Z firmware `1.2.45+`.

The OP-Z's normal-mode file service is ordinary manufacturer SysEx over the
same USB or BLE MIDI connection used by the companion software. The public
Python implementation provides independent framing and upload/download state
machines without loading any vendor code.

`SnakePlugin` is the official app's native OP-Z simulator, engine host, and
file-transport bundle. It is unrelated to the OP-Z Snake game and is not a
downloadable synth engine. Static analysis of that bundle helped identify the
session model; the implementation described below is independent and does not
execute it.

This document covers the part already replaced. StateSync ownership, remote
plug-selection side effects, sampler UI writes, arbitrary content cleanup, and
the native engine host are tracked separately in
the separate clean-room engine plan.

## SysEx Envelope

Every file message uses:

```text
F0 00 20 76 01 <message-id> <7-bit-packed-payload> F7
```

Multibyte fields in the unpacked payload are little-endian.

| ID | Direction | Unpacked payload |
| --- | --- | --- |
| `$33` | client to server | client ID `u16`, status/progress `u8`, value `u32` |
| `$34` | client to server | client ID `u16`, client-state CRC `u32` |
| `$35` | requester to sender | requester ID `u16`, file ID `u32`, part index `u16` |
| `$51` | server to client | server ID `u16` |
| `$52` | server to client | server ID `u16`, sync-active `u8` |
| `$53` | sender to requester | sender ID `u16`, file ID `u32`, part index `u16`, last `u8`, zlib data |
| `$55` | server to client | server ID `u16` |

`$51` advertises an available server. The OP-Z answers with `$34`; both sides
then send heartbeats about once per second. `$55` closes the session. The
firmware times out a stale server after about six seconds.

The `$33` value field is overloaded:

- Status `255`: the value is the client-state CRC.
- Status `1...126`: the value is the completed non-final part count.
- Status `127`: the sync is complete.

## Files and Parts

Reserved file IDs are:

| ID | File |
| --- | --- |
| `0` | `settings/slotConfiguration.json` |
| `1` | `settings/plugs.json` |
| `2` | `syncjob.json` |

Other file IDs are:

```text
crc32(utf8(lowercase(relativePath)), initial: 0)
```

For example, `settings/slotConfiguration.json` hashes to `2873598156`.

Each `$53` body contains at most 200 uncompressed file bytes. That individual
part is a standard zlib stream. The receiver inflates it and appends it in part
order. One `$35` request seeds a file stream at the requested part; the sender
then advances part indices without waiting for another request. A 10 ms initial
send interval matches the native transport and completed a 2,648-part sample
transfer. `$33` completed-part feedback now adjusts pacing to 20 or 50 ms as
the receiver falls behind and pauses sending above 64 in-flight parts. The
final-part flag is one only for the last chunk.

## Upload Manifest

An active `$52` causes the OP-Z to request reserved file `2`. Its JSON shape is:

```json
{
  "files": [
    {
      "fileId": 2873598156,
      "path": "settings/slotConfiguration.json",
      "crc": 3469925004,
      "size": 5827
    }
  ]
}
```

The OP-Z skips a target whose current content CRC already matches. Otherwise it
requests every part, calculates the downloaded content CRC, and replaces the
destination only after the CRC matches. Manifest operations `write` and
`import` are recognized; an omitted operation is a normal write. The manifest
also supports remove entries for user plugs, but removal is not yet exposed by
the clean tools.

Paths containing `projects/project/` trigger project import/reload after a
successful write. A `patch.json` path triggers plug import. These post-write
effects are static-analysis findings; clean multi-file sample installation
directly proved the patch import path.

### Retransmission

`$35` is also a resume cursor. In a controlled hardware probe, the host omitted
slot-map part 3 but continued through part 9. The OP-Z reported `$33` value `3`,
then issued another `$35` for the same file at part 3. The clean sender sought
backward, resent parts 3–9, and received completion status `127`. Fresh readback
matched the intended file exactly; the original was then restored and its
original client-state CRC recovered.

The sender logs every requested cursor and accepts repeated or earlier part
indices. See
the private evidence ledger (private evidence; not distributed).

## Hardware Proof

The clean implementation performed this reversible sequence:

1. Advertised server `0x4242`.
2. Received client ID `21899` and state CRC `2E0B847D`.
3. Pulled `slotConfiguration.json` in 30 parts and `plugs.json` in 50 parts.
4. Re-serialized slot configuration to semantically identical but
   byte-different JSON.
5. Uploaded the manifest and all ten target parts.
6. Received progress through `127`.
7. Reconnected and pulled the file; SHA-256 exactly matched the upload:
   `403a114ead55c2c65f1400ffe8db9680c4d6f3d80c65b16edac29cf48329f4c7`.
8. Uploaded the original 5,891-byte file and pulled it again.
9. Original SHA-256
   `1764d7c3bd44c1b57736ac6364acf061a3cc802332082ff4cf61c16b97cd394c`
   and state CRC `2E0B847D` were restored exactly.

A second proof used one manifest for a 529,600-byte melodic sample,
`settings/patch.json`, and `settings/slotConfiguration.json`. The OP-Z requested
the byte-different sample and patch, accepted 2,654 served parts in one
transaction, reported status `127`, and exposed the requested slot on a fresh
settings pull. An acknowledged pattern-bank write then selected plug `60001`
on Pattern 6 Bass and a new bank query read back `60001`.

### Transport integration

Two details proved necessary in a live host implementation:

1. After the OP-Z replies with `$34`, send `$52` with sync-active `0` before
   the first `$35` file request. Requesting the file first leaves the session
   alive and exchanging `$33` heartbeats, but the device sends no `$53` parts.
2. Serialize access to the streaming MIDI parser. MIDI backends can deliver one
   SysEx frame in multiple callback chunks.

Pause ordinary StateSync ownership for the bounded file session, then reconnect
and request a fresh project snapshot. This avoids two host clients trying to
own the same OP-Z file-server session.

Evidence is under
the private evidence ledger (private evidence; not distributed).
A second reversible proof directly exercised the extracted shared-core upload
and download cursors; see
the private evidence ledger (private evidence; not distributed).

## Tools

Build the clean pull tool:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Pull the two readable settings files:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Probe an explicit relative path:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Reserved settings paths map to IDs `0...2`; other paths use the lowercase-path
CRC32 ID. This command is useful for read-only protocol research and returns a
nonzero status with explicit metadata when the device does not serve a file.

Build and run the push tool:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

The push command intentionally requires an explicit root and relative path.
For destructive or semantic changes, capture a fresh pull first and verify
with a second independent pull afterward.

The client can emit progress `0x7F` while the final advertised file part is
still in flight. The clean uploader therefore does not terminate on that
signal alone: it also requires proof that an `isLast` frame was sent for every
hosted file. This guard was hardware-proven with a 30-part slot map where the
unguarded tool stopped after part 28 and the guarded tool sent part 29 before
fresh readback confirmed the edit. See the
render-ABI proof (private evidence; not distributed).

The sample installer makes at most two clean transfer attempts. It waits seven
seconds before retrying so the firmware can expire the interrupted server
session. If both attempts fail, or the fresh slot readback does not match, it
resends the original slot configuration and requires another clean readback
before reporting rollback. A sample or patch that completed earlier in a failed
multi-file job may remain in storage, but the original slot map is restored so
that content is not selected.

## Remaining Work

- Search for any separate content-read command or mode. Direct `$35` requests
  for the installed synthetic test-sample path ID and imported
  `settings/patch.json` path ID each produced zero parts, while reserved ID `0`
  returned the complete slot map through the same generic command.
- A direct request for installed `engines/saw013a.engine` likewise returned
  zero parts during a healthy session. The known `$35` service is therefore
  whitelist/virtual-table based rather than a general filesystem export API.

## Native Transaction

`OPZFilePushSession` and `OPZContentInstaller` now place the complete transfer
inside shared `OPZCore`. The native transaction:

1. Pulls and journals the original slot map and plug catalog.
2. Validates OP-1 sampler metadata and track compatibility.
3. Rejects occupied slots and plug-ID collisions unless replacement is
   explicit.
4. Uploads the sampler AIFF, patch, and updated slot map with bounded retry.
5. Pulls both settings files again and requires the target assignment.
6. Restores and independently verifies the original slot map after failure.

The standalone rollback form is:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

A non-deduplicated hardware proof served 2,152 parts for a 423,392-byte sample,
confirmed temporary plug `60003`, and restored the exact original slot-map
SHA-256. See
the private evidence ledger (private evidence; not distributed).

Rollback does not delete an imported but unassigned sample or plug. Import and
removal semantics are now decoded separately; see
[user-plug-removal.md](user-plug-removal.md).

## External References

- [leddy231/libopz](https://github.com/leddy231/libopz)
- [MarkRdgOx/opzdoc](https://github.com/MarkRdgOx/opzdoc)
- [schollz/teoperator](https://github.com/schollz/teoperator)
- [romangarms/opz-sample-manager](https://github.com/romangarms/opz-sample-manager)
