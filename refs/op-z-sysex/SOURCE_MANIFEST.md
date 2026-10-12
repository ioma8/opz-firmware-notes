# Source manifest

This repository was initially extracted on 2026-08-28 from private research in
`kmorrill/op-z` at commit `0f080c1`. The implementation was ported to Python so
the public toolkit has no dependency on Swift, Objective-C, CoreMIDI, Xcode, or
other Apple-only frameworks.

## Included

- Cross-platform Python implementations of packed-7 SysEx framing, StateSync
  constructors, file-transfer state machines, serial tunneling, MIDI
  configuration, and lossless project/global editors.
- Optional live MIDI transport through `mido` and `python-rtmidi`.
- Python offline utilities and generated-fixture tests.
- Documentation covering SysEx, StateSync, serial tunneling, project/global
  formats, file transfer, and the evidence boundary for those paths.
- Human-written experiment summaries that contain no raw payload dumps.

## Deliberately excluded

- All macOS/iOS application code and all Swift, Objective-C, C, Xcode, CoreMIDI,
  and Apple-framework tooling.
- Firmware extraction, firmware images, custom-engine binaries, app binaries,
  boot/eject experiments, and simulator-oracle code.
- Factory or stock projects, project backups, raw project banks, MIDI captures,
  logs, audio, samples, device dumps, private filesystem paths, and machine
  reports that may expose content metadata.

Small protocol constants, field offsets, synthetic fixtures, and human-written
observations are retained for interoperability. No third-party application or
library source files and no copyrighted Teenage Engineering content are
included. The sampler metadata provenance and applicable MIT notice are
recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); the research
sources are credited in [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).
