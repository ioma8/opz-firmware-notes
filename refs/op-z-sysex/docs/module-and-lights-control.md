# Module and Lights Control

This note maps the OP-Z expansion-module state and Lights/DMX execution path.
It distinguishes device-visible StateSync data from behavior simulated by the
official app's native sequencer replica.

## Evidence Snapshot

Confidence: analysis of official companion behavior, official manual evidence,
and prior device proof. Vendor binaries and their hashes are not distributed.

Managed classes and native symbols were inspected locally. Official binaries
and decompiled source are not committed. Relevant native symbols include
`StateSync::processMessage`, `StateSync::updateSlaveDevice`,
`Sequencer::externalCopyState`, `DmxController`, `DmxPlug`,
`LoadDMXConfig`, and `setDmxChannel`.

Primary and interoperable references:

- [Teenage Engineering Lights guide](https://teenage.engineering/guides/op-z/lights)
- [Teenage Engineering Line module guide](https://teenage.engineering/guides/op-z/modules/line)
- [Teenage Engineering Rumble guide](https://teenage.engineering/guides/op-z/modules/rumble)
- [Open Fixture Library OP-Z exporter at `19cd202`](https://github.com/OpenLightingProject/open-fixture-library/tree/19cd202052009a6f96d385b74bd4b870714a8534/plugins/op-z)

The attached OP-Z had no expansion module or USB DMX interface connected.
Its `$14` baseline was 24 zero bytes. The field layout and behavior below are
therefore statically proven against the official app, but the module-specific
status transitions have not been captured from physical accessories.

## `$14` ModuleInfo

StateSync message `$14` carries exactly 24 unpacked bytes. The native receiver
unpacks them directly into `g_moduleInfo`; the sender transmits the same
24-byte global when `g_moduleInfoDirty` is set.

| Bytes | Native/managed meaning | Confidence |
| --- | --- | --- |
| `0...3` | `moduleCaps`, little-endian `UInt32` | Exact |
| `4...7` | `moduleStatus`, little-endian `UInt32` | Exact |
| `8...17` | NUL-terminated module name | Exact |
| `18` | `moduleConnected`; nonzero means present | Exact |
| `19` | Unknown | Unknown |
| `20` | Enables module track-send read/write and a synth render path | Exact behavior; field name unknown |
| `21...23` | Unknown/padding | Unknown |

`Sequencer::externalCopyState` separately copies the name, capabilities,
status, and byte 18 into the managed `SequencerState` fields
`moduleName`, `moduleCaps`, `moduleStatus`, and `moduleConnected`. This proves
that bytes `0...7` are two 32-bit fields, not one generic 64-bit value.

The official UI recognizes these lowercase names:

| Wire name | UI kind |
| --- | --- |
| `oplab` | Oplab |
| `line` or `in-out` | Line |
| `rumble` | Rumble |

An unrecognized connected name gets the generic no-module panel.

### Status bits

The top status byte describes the physical MIDI/trigger switches on Oplab and
Line:

| Status bits | Meaning |
| --- | --- |
| `24...25 = 1` | Output switch: MIDI |
| `24...25 = 2` | Output switch: trigger |
| `24...25 = 3` | Output switch: PO sync |
| `24...25 = 0` | Unknown/unhandled by the official UI |
| `27 = 0` | Input switch: MIDI |
| `27 = 1` | Input switch: trigger |

For a Line module, bits in status byte 2 expose jack state:

| Status bit | Meaning |
| --- | --- |
| `20` | Line output connected/active |
| `21` | Line output mono when active |
| `22` | Line input connected/active |
| `23` | Line input mono when active |

This interpretation matches the official Line guide: stereo is the default,
and holding Screen while inserting a cable selects mono.

For Rumble, `moduleStatus & 0x0F` is the level. The official app renders four
bars and divides the value by four for animation weight, so the useful range is
`0...4`.

### What a host can do

A connected host can read `$14` in normal mode and display:

- presence, name, and recognized module kind;
- the raw capability and status words;
- Oplab/Line input and output switch positions;
- Line input/output connection and mono/stereo state;
- Rumble level;
- whether the native module-routing path is enabled.

StateSync accepts an inbound `$14` record, but this is a raw global-memory
write, not a documented module command. It may alter the peer's replicated
state; it is not evidence that the host can physically move switches, connect
jacks, or change Rumble hardware. OP-Z Lab therefore decodes `$14` but does not
offer a writer.

## Module Track Control

The Module track is human track 14 and zero-based track index 13.

- Its stored notes, velocity, gate, and loop timing are ordinary pattern data
  and can be edited through the proven `$09/$0A` bank writer.
- Its notes emit ordinary MIDI on the track's configured MIDI channel when
  output is enabled in `$10`; this is device-proven.
- Standard incoming notes and CCs can perform against the track through its
  configured MIDI channel.
- Line module audio-track assignment and send levels are stored in project
  pattern structures. The native app gates send access with `$14` byte 20.
- Physical Line/Oplab switch and jack state remains module telemetry, not
  pattern data.

## Lights Track Control

The Lights track is human track 15 and zero-based track index 14. Its built-in
plug ID is `146` (`DMX Basic`).

The official guide describes four primary controls. Native `DmxPlug` analysis
maps them and the second-page passthrough knobs to exact sound bytes:

| UI/DMX role | Sound byte | Incoming absolute CC |
| --- | ---: | ---: |
| Main color / `knob1` | 0 | 1 |
| Alternate color / `knob2` | 1 | 2 |
| Pattern speed / `knob3` | 8 | 3 |
| Intensity / `knob4` | 9 | 4 |
| `knob5` | 6 | 13 |
| `knob6` | 7 | 14 |
| `knob7` | 10 | 15 |
| `knob8` | 11 | 16 |

These values are available and writable in three ways:

1. `$0E` reads or writes the current 18-byte sound state.
2. `$09/$0A` reads or writes persistent sound bytes and parameter locks in a
   pattern.
3. Standard MIDI CCs provide low-latency performance control on the Lights
   track's configured MIDI channel.

The editor now names these fields according to their DMX function instead of
showing Filter, Resonance, FX send, Pan, and Level labels inherited from audio
tracks.

### Pattern and animation notes

Native lookup tables provide exact note mappings:

| Pattern | MIDI note |
| ---: | ---: |
| 1 | 54 |
| 2 | 56 |
| 3 | 58 |
| 4 | 61 |
| 5 | 63 |
| 6 | 66 |
| 7 | 68 |
| 8 | 70 |
| 9 | 73 |
| 10 | 75 |

| Animation | MIDI note |
| ---: | ---: |
| 1 | 53 |
| 2 | 55 |
| 3 | 57 |
| 4 | 59 |
| 5 | 60 |
| 6 | 62 |
| 7 | 64 |
| 8 | 65 |
| 9 | 67 |
| 10 | 69 |
| 11 | 71 |
| 12 | 72 |
| 13 | 74 |
| 14 | 76 |

Pattern notes set the Lights track's internal `FxTiming` selection `0...9`.
Animation notes gate 14 independent native `DmxAnimation` slots. Animation 14
also drives the `fog` channel type. The mappings are represented by
`OPZLightPatternShortcut` and `OPZLightAnimation`.

Because the Lights track's MIDI channel is configurable, callers should route
these notes to the current `$10` channel assignment rather than hard-code MIDI
channel 15. OP-Z Lab does this automatically and exposes the ten patterns and
fourteen animations as dedicated trigger grids.

## `dmx.json`

Actual fixture-channel layout is not carried by `$14`, `$0E`, or pattern
messages. It lives at `/config/dmx.json` in Content Mode.

The schema has two top-level arrays:

```json
{
  "profiles": [
    {
      "name": "rgb-dimmer",
      "channels": ["red", "green", "blue", "intensity"]
    }
  ],
  "config": [
    {
      "fixture": 1,
      "profile": "rgb-dimmer"
    }
  ]
}
```

The official limit is 128 total DMX channels. The native engine and official
app model 16 fixture units. Supported channel strings are:

- `red`, `green`, `blue`, `white`, `color`, `intensity`, and `fog`;
- `knob1` through `knob8`;
- `on`, `off`, or a decimal fixed value `0...255`.

The Open Fixture Library exporter is a useful third-party implementation of
this schema. It emits all selected fixture modes as profiles, assigns the first
mode of up to 16 fixtures, maps recognized color/intensity/fog channels, uses
the eight knobs for other coarse channels, and converts unsupported/fine
channels to fixed values or `off`.

Changing `dmx.json` still requires a file operation. The official route is
Content Mode. The clean-room normal-mode file transport may eventually support
it, but a guarded read/write/readback proof for this path has not been run and
OP-Z Lab does not currently expose a DMX-config writer.

## What the Official App Displays

The official app's `ShowDmxLeds` panel reads 48 bytes from its native
`SequencerState` mirror as 16 RGB triplets. Those bytes are generated by the
local `DmxController` replica after it runs the pattern, color, intensity, and
animation logic.

No standalone StateSync message carrying those 48 RGB bytes has been found.
They are not part of `$14`. A clean-room app can read the Lights pattern and
all controlling values, but exact real-time 16-fixture RGB preview requires
either:

- implementing the native DMX simulation rules;
- receiving actual DMX output through a separate interface; or
- finding a still-unknown telemetry source.

The official app's RGB preview is therefore not evidence that the OP-Z sends a
48-byte light-state stream over SysEx.

## Remaining Work

1. Capture `$14` differentials from physical Oplab, Line, and Rumble modules to
   validate every status transition and map capability bits.
2. Determine names for byte 19 and bytes `21...23`.
3. Guardedly read, write, read back, and restore `/config/dmx.json` through the
   clean-room normal-mode file transport.
4. Implement the 16-fixture DMX simulator if exact app-equivalent preview is
   worth the native behavior port.
5. Validate notes, CCs, pattern locks, and animation output against a connected
   USB DMX interface or loopback receiver.
