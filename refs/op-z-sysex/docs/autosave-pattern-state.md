# Autosave and `$13` Pattern State

Status: direct `$13` autosave write and exact rollback device-proven on
2026-07-27 with OP-Z firmware `1.2.45+`. Remote project+track long-hold through
`$06` is also device-proven.

## Conclusions

- `$13` is a real bidirectional four-byte live-state message on the OP-Z.
- Bit 5 of byte 2 controls autosave immediately.
- Autosave is one runtime-global flag, not a per-project value and not part of
  the 568-byte `$0C` project-global block.
- The project+track long-hold can be invoked remotely through `$06`; it is not
  limited to physical panel input.
- `$13` is change-driven and may be absent from an otherwise complete initial
  StateSync burst. A client must not invent a baseline.
- The official native runtime initializes autosave to enabled and does not
  serialize it in its session file. This proves reset-on-launch behavior for
  the official runtime. Hardware power-cycle persistence still needs a
  controlled physical test.

## Four-Byte Layout

```text
0           pattern-copied value
1           project-copied value
2 bits 0-3  pattern-lift mode
2 bit 4     chain-edit mode
2 bit 5     autosave enabled
2 bit 6     bounce in progress
3           reserved
```

The connected device's restored baseline was:

```text
10 10 20 00
```

Changing only autosave produced:

```text
10 10 00 00
```

The XOR is exactly `0x00200000`.

## Direct Hardware Proof

The proof used three independent StateSync sessions:

1. Obtain a live `$13` baseline and save all four bytes.
2. Send `$13` with only byte-2 bit 5 changed.
3. Let the roughly five-second StateSync lease expire.
4. Start a new session and force a new device-originated `$13`.
5. Require `10 10 00 00`.
6. Send the exact original `10 10 20 00`.
7. Repeat the independent readback and require the exact original.

The device reported:

```text
before             10 10 20 00  autosave on
changed readback   10 10 00 00  autosave off
restored readback  10 10 20 00  autosave on
```

Evidence is in
the private evidence ledger (private evidence; not distributed).

## Remote Long-Hold Through `$06`

The proof also resolves an important `$06` boundary. These decoded UI payloads
were sent:

```text
released  00 1F 1F 00
held      00 1F 1F 03
```

Byte 3 bits 0 and 1 are track and project held. While the held frame remained
active, the host maintained the normal StateSync heartbeat. The OP-Z emitted
17 `$06` progress frames whose byte 0 advanced `1...16` and returned to `0`.
After about 3.02 seconds it toggled autosave and emitted `$13`.

Repeating release, hold, and release toggled autosave back. In the baseline
acquisition, the two returned `$13` values differed only by
`0x00200000`. Release is always sent in a deferred cleanup path so held keys
cannot remain latched after a timeout.

This is device proof that `$06` can drive at least one real long-hold gesture.
It does not establish that every button combination is remotely equivalent to
physical input. Copy, clear, sampling, and other destructive or
context-sensitive gestures need separate bounded tests.

## Native Scope and Persistence

The installed official `SnakePlugin` provides a clean scope map:

- `_g_autoSaveProject` is a one-byte global initialized to `1`.
- `PatternContext::fixedUpdate` toggles it for the project+track hold.
- `PatternContext::updateLeds` reads it for the manual-save indicator.
- `Sequencer::copyPatternState` writes it into `$13` byte-2 bit 5.
- `Sequencer::applyPatternState` writes bit 5 back into the global.
- No `$0C` field references this global.

All direct references to `_g_autoSaveProject` are accounted for. The native
`saveSession` function writes version `7` followed by 24 bytes: project,
pattern, active track, 16 per-track values, and two 16-bit fields.
`loadSession` restores exactly those values. Neither function reads or writes
the autosave global.

Therefore:

- scope is device/runtime global rather than per project;
- changing projects does not select a different autosave preference; and
- the official runtime starts with autosave enabled on every launch.

The native app is strong evidence for firmware behavior but is not a physical
power-cycle test. Do not yet claim that the hardware forgets manual-save mode
across reboot.

## StateSync Role Boundary

Native receive tracing explains why `$13` works while `$02` does not:

- `$02` has an explicit role-1/replica check before pattern deltas are applied.
- `$06`, `$12`, `$13`, and `$19` unpack into pending records without that
  check.
- `StateSync::handleReceivedMessages` applies those pending records directly.

The normal OP-Z remains StateSync master, but these typed live-state messages
are not blocked by the `$02` replica guard.

## Tool

Build:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Read and restore the current state through two remote long holds:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Run the direct `$13` change/readback/rollback proof:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

The proof deliberately takes tens of seconds because each confirmation waits
for the old StateSync lease to expire before opening a fresh observer session.

## External References

- [`leddy231/libopz`](https://github.com/leddy231/libopz) implements the public
  StateSync transport but does not document this autosave write proof.
- [`MarkRdgOx/opzdoc`](https://github.com/MarkRdgOx/opzdoc) catalogs the
  manufacturer SysEx protocol but does not map this runtime-global behavior.
- [`lrk/z-po-project`](https://github.com/lrk/z-po-project) documents project
  files; autosave is not a project-file field.
