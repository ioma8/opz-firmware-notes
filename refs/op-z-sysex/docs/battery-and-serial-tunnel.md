# Battery, Charging, and the `$66` Serial Tunnel

## What the app can read

Ordinary StateSync `$04` exposes battery percentage as decoded byte 0. The
connected OP-Z repeatedly reported `100`. The same message contains master
volume, microphone level/effect/mode, and input selector/monitor state.

No charging flag or battery voltage has been found in:

- the four-byte `$04` payload;
- the official app's 22,820-byte `SequencerState` exchange structure;
- `$13` `PatternState`;
- `$14` `ModuleInfo`;
- the managed app's battery UI, which consumes only an integer percentage.

A USB host reported a 500 mA power allocation for the attached OP-Z. That is an
allocation, not measured current and not proof that charging is enabled.

The official native simulator exports a separate boolean named
`g_usbChargingEnabled`, initialized to `1`. It is not part of the StateSync
exchange structure, and the current simulator's battery key handlers are
stubs. This is evidence that charging is firmware-local state, not evidence of
a readable or writable MIDI field.

The documented hardware gesture remains:

```text
hold screen + press the rightmost piano key
```

It toggles USB charging. Repeat it to toggle charging back. See the official
[hardware and battery guide](https://teenage.engineering/guides/op-z/hardware-overview).

## What `$66` actually is

`$66` is not a regular StateSync state message. Static analysis of the official
app's `SnakePlugin` proves a bidirectional serial byte tunnel:

```text
F0 00 20 76 01 66 <7-bit-packed serial bytes> F7
```

The decoded non-CRC serial framing is:

```text
C0 routing type length_be32 payload...
```

The official app has a 4,096-byte outer receive buffer and 256-byte serial
message payload. Inner `C0` and `7D` values are escaped with `7D` and XOR `20`.

The managed companion app only uses the tunnel to answer device-originated
serial pings. It receives type `00` and replies with type `01` carrying the
same payload.

The assembly also defines these serial message families:

| Type | Name |
|---:|---|
| `0` / `1` | ping / pong |
| `2` / `3` | version request / reply |
| `4` / `5` | log / log level |
| `6` / `14` | power-mode request / reply |
| `7` / `8` | metadata request / reply |
| `9` / `10` | factory-mode request / reply |
| `11` / `12` | greeting request / reply |
| `13` | error |
| `16` / `17` | profile / control-profile data |
| `41` | Blackfin DFU entry |

Power-mode payload values include active `16`, standby `18`, power-off `20`,
charging `22`, and low-battery `24`.

These names and values come from shared serial-library constants. The official
companion app does not call them. They must not be treated as a supported OP-Z
MIDI API without device responses and rollback behavior. Power-off, factory
mode, and DFU are specifically unsafe to probe speculatively.

## Hardware proof boundary

A direct clean-room serial ping and a ping sent through the official
`SendSerialMessage` pipeline both timed out without a device pong. StateSync
and file transport were connected during the official-path test.

This does not disprove `$66`; the static bidirectional transport is conclusive,
and the app only answers incoming pings. It does establish that a host cannot
currently use type `00` as a health-check request to this OP-Z.

Current product behavior should therefore be:

- display `$04` battery percentage;
- label charging state and voltage unavailable;
- parse and log `$66` defensively when observed;
- do not expose power-mode writes;
- retain raw serial frames for future device-originated differentials.

Detailed evidence is in
the private evidence ledger (private evidence; not distributed).
