# Exhaustive Pattern Proof Progress

Status: active device audit on firmware `1.2.45+`, 2026-07-26.

This document tracks completion against the full editor objective. It is
deliberately stricter than the representative demonstrations in
the private behavioral-proof ledger, which is not distributed here.

## Note Records

### All Track Layouts

The matrix wrote the maximum note allocation on step 1 of every track:

| Track | Slots | Stored pitches |
| --- | ---: | --- |
| Kick, Snare, Perc, Sample | 2 | 48, 52 |
| Bass, Lead, Chord, Master, Lights, Motion | 4 | 48, 52, 56, 60 |
| Arp | 8 | 48 through 76 in fourths |
| FX1, FX2, Tape | 1 | 48 |
| Perform, Module | 6 | 48 through 68 in fourths |

Every one of the 16 cases matched its complete pre-playback device readback
byte for byte. Audio tracks 1–8 produced USB audio according to their active
engine. FX and control tracks accepted the same records but require their
normal upstream/output context to have an audible effect.

Outgoing MIDI is project-configurable. The original project enabled only Lead,
so the first matrix saw Kick/Lead and Motion output but left most control
tracks silent. A later guarded `$10` + `$09` matrix temporarily enabled tracks
9-16 on channels 9-16 and programmed one distinct note per control track.
FX1, FX2, Tape, Perform, Module, Lights, and Motion each emitted three exact
note-on/off pairs with the stored pitch, velocity, approximately 60 ms gate,
and 1,935 ms loop. Master alone emitted no ordinary channel-12 note despite
being enabled and holding an exact-readback note; its sequence is consumed
internally for transpose/chord progression.

Lights matched exact readback before playback, then changed device state while
executing and failed the optional post-playback unchanged-bank gate. Motion
matched exact readback and emitted channel-16 notes.

Artifacts: local `run-29-note-track-0` through `run-29-note-track-15` and
control-track MIDI proof (private evidence; not distributed).

Contextual execution is now proven for two more control-track families:

- Perform lower B (59) executed Follow by suppressing every alternate Lead
  trig; upper B (71) executed Echo in USB audio while preserving source MIDI.
- FX1/FX2 source-send bytes drove factory Delay/Reverb, and stored FX notes 48
  versus 72 produced repeatable, different renders with identical source MIDI.

Native analysis now proves the complete Perform note/scope dispatch and the
factory Delay/FDN Reverb note normalization from `53...76` to `0...23`.
Millisecond FX transfer curves remain unmeasured. See
the private Perform/FX proof ledger and the
control-track internal audio proof (private evidence; not distributed).

### Pitch, Velocity, Duration, and Per-Note Microtiming

A Lead chord stored:

```text
note 60, velocity 45, duration 3100, microtiming -48
note 67, velocity 110, duration 12400, microtiming +48
```

The expected and readback banks share SHA-256:

```text
48af1e33ae5498117edaadd06ef719e368c99c9e59f490514e09ff2688863b59
```

On later complete cycles, outgoing MIDI showed:

- Notes 60 and 67 separated by about 61 ms, proving independent per-note
  microtiming inside one stored chord.
- Velocities 45 and 110 exactly.
- Note 60 gates about 61 ms and note 67 gates about 242 ms, matching 0.5 and
  2 stored steps at the measured tempo.

Artifact: local `run-28-chord-attributes`.

### Microtiming Domain and Scale

Genuine occupied notes across captured banks use every multiple of eight from
`-96` through `+88`, and no values outside that range. Isolated writes at:

```text
-96, -48, -8, 0, +8, +48, +88
```

all matched exact readback and moved outgoing note-on times monotonically.
Relative to the aligned zero-timing phase, `-96` was about 60 ms early, `-48`
about 32 ms early, `-8` about 3 ms early, `+48` about 26 ms late, and `+88`
about 58 ms late. This validates the app's displayed range `-12...+11`, stored
as displayed ticks multiplied by eight.

Artifacts: local `run-27-micro-raw-*`.

## Parameter Locks

The lock enable sentinel is `FF`. A physical Lead step-1 filter-lock diff
established:

```text
step record = 7232 + (trackIndex * 16 + stepIndex) * 54
value byte  = record + 18 + parameterIndex
enable byte = record + 36 + parameterIndex
```

The corrected 16-step scan wrote lock slot `N` only on step `N` for slots
0–15. Its expected and readback banks were byte-identical. Raw value 8 produced
clear USB-audio differences for Attack, Release, Filter, Pan, and Level; other
slots need parameter-specific stimuli rather than one common low value.

Slots 16 and 17 were then written in an isolated fresh session and matched
exact readback. Therefore every one of the 18 value/enable pairs is
independently writable. Behavioral mapping still needs focused stimuli for
engine parameters, sends, portamento, and LFO controls.

Artifacts: local `run-24-lock-scan-correct-layout` and
`run-25-lock-tail-isolated`.

## Step Components

The mask/value layout and all 14 named bits independently roundtrip. Fourteen
fresh-process raw-4 cases each matched their complete pre-playback device
readback byte for byte. Against the same one-note Lead fixture:

| Component | Official key-4 meaning | Outgoing MIDI in nine seconds |
| --- | ---: | ---: |
| Pulse | Count 4 | 16 notes, grouped pulses |
| Parameter Spark | Pass 4 | 5 unchanged notes; no locks in fixture |
| Jump | Jump to 4/4 | 15 notes, shortened loop |
| Velocity | -1 | 5 notes, velocity 32 instead of 112 |
| Ramp Up | 5 steps / 1 octave | pitches 60, 64, 65, 67, 72 |
| Ramp Down | 5 steps / 1 octave | pitches 76, 72, 67, 65, 64 |
| Random | 5 steps / 1 octave | pitches 60, 65, 72 in this capture |
| Portamento | Glide 4 | 5 pitch-60 MIDI notes; audio-context effect |
| Multiply | x4 | 20 notes in four-note retrigger groups |
| Sweep | Synth down | 5 pitch-60 MIDI notes; audio-only modulation |
| Pulse Hold | Count 4 | 4 notes at a longer repeating interval |
| Tonality | Offset fifth | 5 pitch-67 notes |
| Trigger Spark | Pass 4 | 1 note in this counter phase |
| Component Spark | Pass 4 | 5 notes; no paired component in fixture |

The baseline fixture produced five pitch-60, velocity-112 notes. The MIDI
effects above agree with the official key-4 meanings wherever ordinary MIDI
can expose the result. A later paired/audio matrix directly proved Parameter
Spark gating a filter lock, Component Spark gating Multiply, Portamento's
pitch trajectory, and Sweep's spectral trajectory.

The app now exposes all ten official value-key meanings for each component,
while retaining an advanced raw-byte mode. The older
[`lrk/z-po-project` wiki](https://github.com/lrk/z-po-project/wiki/Project-file-format)
also documents Spark high-nibble modes, including `0x04`, `0x14`, and `0x24`.

Artifacts: local `run-30-component-0-4` through
`run-30-component-13-4`.

A later partial value sweep completed 53 exact full-bank readbacks and 52
MIDI/USB-audio captures before being intentionally stopped. It confirmed all
ten values for Pulse, Parameter Spark, Jump, Velocity, and Ramp Up, plus the
first two Ramp Down values. Particularly strong results include exact outgoing
Velocity values `4, 8, 16, 32, 64, 100, 112, 127`, mute for value 9, and
random velocity for value 10. Ramp Up produced the documented pitch sequences
for every two- through six-step, one- and three-octave setting.

The remaining ordinary value meanings are accepted from Teenage Engineering's
official chart rather than requiring redundant single-note enumeration.
Paired raw-2 fixtures additionally prove that Spark values `1...8` mean
**Pass N**, not a cumulative “passes 1 through N” range. Parameter Spark
alternated a filter lock, Component Spark changed Multiply group sizes from
`4,4,4,4,4` to `1,4,1,4,1`, and Trigger Spark fired on the second and fourth
passes. See the
partial sweep evidence (private evidence; not distributed)
and paired fixture proof (private evidence; not distributed).

A live raw-2/raw-3/raw-10 matrix then tested whether `$09` could resolve Reset
without stopping the experiment. It could not: a byte-identical raw-2 bank
apply caused a pass-2 target to fire before the third-loop marker, and all
three target phases converged after the next base upload. The untouched
sentinel stayed aligned within 23 ms, so this is a target Spark-state/cache
effect rather than trial drift. Exact raw-10 semantics now have a narrow
manual requirement: change the same physical step's component value without
uploading or reloading the pattern. See the
Spark reset boundary (private evidence; not distributed).

## Persistent Sound and Routing

All 18 persistent bytes on every track and both 16-bit routing masks match
exact device readback. A controlled Lead matrix then wrote raw `8` and `127`
for every parameter from the same known plug-10 preset. All 36 complete banks
matched pre-playback readback, every case emitted 11 outgoing Lead notes and
non-empty USB audio, and the final complete bank remained byte-identical.

Representative median 75 ms onset-window results:

| Parameter | Raw 8 | Raw 127 | Observable result |
| --- | --- | --- | --- |
| Parameter 1 | RMS `.0999`, centroid `324 Hz` | RMS `.0737`, `426 Hz` | engine timbre |
| Parameter 2 | RMS `.0860`, centroid `276 Hz` | RMS `.1064`, `503 Hz` | engine timbre |
| Attack | RMS `.0980`, peak `.204` | RMS `.1061`, peak `.239` | onset |
| Release | file RMS `.0444` | file RMS `.0711` | tail energy |
| Filter | RMS `.00263`, `134 Hz` | RMS `.0947`, `312 Hz` | cutoff |
| Resonance | peak `.246`, `321 Hz` | peak `.292`, `444 Hz` | resonant emphasis |
| Pan | L/R file RMS `.0896/.00563` | `.0896/.0893` | stereo position |
| Level | RMS `.00728` | RMS `.1193` | output level |

Decay and Sustain moved audio more subtly with this short gated fixture.
FX sends, Portamento, LFO fields, and Note Style all executed with exact
readback and valid audio, but their specific meanings require destination,
legato, or modulation-specific stimuli rather than whole-file RMS. Their byte
indexes and persistent-write behavior are proven; those specialized transfer
functions are not claimed here.

Routing has direct execution proof:

- Tape mask `0000` and Lead-only `0020` both emitted the same Lead/Tape MIDI
  events. With `0020`, the genuine Tape-track note produced later audio windows
  around RMS `.109-.114`, peak `.314-.316`, and centroid `1.54-1.63 kHz`;
  the zero-mask control stayed near RMS `.098`, peak `.240-.261`, and
  `1.23-1.33 kHz`.
- Master mask `0000` left all 11 Lead notes at MIDI 60. Master mask `0020`
  changed all 11 to MIDI 67 while preserving velocity and USB audio. The
  stored Master G note therefore transposed only the routed Lead track.
- All four routing fixtures matched both pre-playback and final full-bank
  readback.

Artifacts: local `run-38-tape-route-*`, `run-38-master-route-*`, and
`run-39-controlled-sound-matrix`.

### Active-Pattern Reload Rule

After a successful active-project upload and exact snapshot, reselect the same
project/pattern and wait before playback. Switching to another project first
can cause the old active runtime cache to autosave over the new bank. This was
the source of the earlier silent routing fixtures and post-playback mismatch;
same-pattern reload produced exact final banks and repeatable execution.

## External Baselines

- [`leddy231/libopz`](https://github.com/leddy231/libopz), commit
  `3204adfd859d67146a25e612f93e721a5f06b695`.
- [`lrk/z-po-project` wiki](https://github.com/lrk/z-po-project/wiki/Project-file-format),
  wiki commit `c7cb30c77dce76398d0dab3292a5eb4b05839a12`.
- [Teenage Engineering step-component chart](https://teenage.engineering/guides/op-z/step-components).

Neither third-party project implements a complete semantic component editor.
The local device matrix is therefore required to close the remaining gap.
