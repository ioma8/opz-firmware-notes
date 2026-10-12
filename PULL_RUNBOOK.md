# Pulling files off the OP-Z over USB MIDI (read-only)

Current results: [STATUS.md](STATUS.md).

## Prerequisites

OP-Z in normal mode, attached over USB; mido exposes one input and output named `OP-Z`.
Use the existing uv-managed interpreter `/tmp/opzuv/bin/python`. Close other app/file-sync clients.
BLE activation is not needed.

## Verified command

```bash
/tmp/opzuv/bin/python -u ~/.opz-decode/toolkit/opzpull.py --wait 15 \
  settings/plugs.json settings/slotConfiguration.json
```

Expected: `$34`, client `26851`; `OK` for 4,423-byte plugs and 759-byte slot configuration on the
current unit. Files are saved under `~/.opz-decode/pulled/`, with SHA-256 printed.
These sizes/hashes describe this snapshot, not a universal firmware constant.

## Required handshake and keepalive

1. Send `$00` StateSync client hello, protocol version 6. This was the missing USB prerequisite.
2. Advertise `$51`; wait for device `$34`.
3. Send `$52` with sync-active 0, then `$35` reads.
4. Refresh both `$00` and `$52(active=0)` during the session and between short/unserved files.

The helper sends no master claim, `$52(active=1)`, upload manifest or host `$53` file data.
File IDs: CRC32 of lowercase relative path; reserved 0 = slot configuration, 1 = plugs, 2 = syncjob.
Only a contiguous transfer ending with the final-part flag is saved; incomplete cursors are retried.
The save is atomic. Exit 1 = no handshake; exit 3 = some requested paths unserved/incomplete.

## Limits and verification

`settings/plugPresets.dat` and tested audio/config/engine paths did not return part 0 in a live session.
The two known-readable settings files still succeeded after those probes: the transport was alive.
No response is not evidence that a file does not exist. `$35` is not proven to export arbitrary paths.

```bash
/tmp/opzuv/bin/python ~/.opz-decode/test_pull_paths.py
```

Offline checks cover the USB hello, both keepalives, assembly, foreign senders and missing final flags.
Live proof: repeated complete settings reads with identical SHA-256; `usb-pull-latest.log` includes a
long batch with successful controls at the end. The old BLE-only/USB-silent conclusion is superseded.
