# Host-Write Persistence

Status: save/project-reload proven on OP-Z firmware `1.2.45+`, 2026-07-26.
Persistence across physical power loss remains to be tested.

## Result

Host-written pattern and project-global data survive an explicit firmware save
and a project reload:

1. Stop playback and select Project 1, Pattern 1.
2. Capture the complete 342,272-byte pattern bank and 568-byte global block.
3. Write a sound-parameter sentinel to Pattern 16 through `$09/$0A`.
4. Write saved chain 15 as `16 15 16` through `$0C`.
5. Establish a fresh StateSync session and verify exact immediate readback.
6. Send `$62` with the UTF-8 command `debug-save`.
7. Select Project 2, then reselect Project 1.
8. Establish another fresh StateSync session and verify persisted data.
9. Restore both original blocks, issue `debug-save`, reload, and verify again.

The pattern bank matched the sentinel byte for byte after reload. The saved
global data also matched. The only `$0C` differences were offsets `481...495`,
inside chain record 16, which is the live active-chain buffer. Selecting a
pattern rebuilds that runtime buffer; it is not a stable saved-project
invariant.

## Evidence

The successful run is in
the private evidence ledger (private evidence; not distributed).

| Comparison | Result |
| --- | --- |
| sentinel pattern vs immediate readback | exact, `e2f278a5...f93b` |
| sentinel pattern vs post-reload readback | exact, `e2f278a5...f93b` |
| original pattern vs restored readback | exact, `b04676ac...132c` |
| sentinel global vs immediate readback | exact, `1a9b419b...bd1e` |
| post-reload stable global bytes | exact outside live buffer `480..<512` |
| restored stable global bytes | exact outside live buffer `480..<512` |

The complete MIDI/SysEx exchange is retained in `wire.jsonl`.

## StateSync Session Rule

`$0C` is sent once per StateSync session, not in response to every heartbeat.
A readback is independent only after the previous session has expired. On the
tested firmware, waiting 6.25 seconds without heartbeats reliably exceeds the
roughly five-second timeout before the next heartbeat and `$08` pattern query.

Repeated queries inside one session can return a fresh pattern bank while
leaving the prior global block cached. Tools must not report that combination
as a fresh two-block snapshot.

## Tool

Build:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Run the reversible proof:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Emergency restoration from a proof directory:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

The recovery command uploads `original-pattern.bin` and
`original-global.bin`, then sends `debug-save`.

Stage a sentinel for a real power cycle:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

After turning the OP-Z fully off and on, verify and restore:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

The first stage captures originals, writes and saves the sentinels, confirms a
project reload, and deliberately exits with the sentinels installed. The
second requires exact post-boot pattern bytes and stable global bytes, then
restores the originals, saves, reloads, and verifies restoration. Separate
`wire-prepare-reboot.jsonl` and `wire-verify-reboot.jsonl` logs prevent the
second process from overwriting first-stage evidence.

## What Is Not Yet Proven

Project reload proves that the firmware's project storage path retained both
host writes. It does not prove behavior after complete power loss. The final
power-cycle test should:

1. Write and save the same reversible sentinels.
2. Disconnect all host sessions.
3. Physically power the OP-Z off and on.
4. Reconnect and verify the sentinel pattern and stable global bytes.
5. Restore, save, power-cycle again, and verify the originals.

No safe software reboot command has been established. `debug-crash` is not an
acceptable substitute for a controlled power cycle.

TODO: Determine the scope and persistence of manual-save/autosave mode. Current
manual wording suggests an on-device mode rather than a per-project field, but
we have not proven whether the toggle is device-wide, session-only, persisted
across boots, or visible in any StateSync/project-global bytes.

## References

- [Teenage Engineering project guide](https://teenage.engineering/guides/op-z/project)
- [MarkRdgOx/opzdoc MIDI protocol notes](https://github.com/MarkRdgOx/opzdoc/wiki/MIDI-Protocol)
- [leddy231/libopz write notes](https://github.com/leddy231/libopz/blob/main/WRITE_NOTES_PLAN.md)
