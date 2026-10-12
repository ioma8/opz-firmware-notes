# Acknowledgements

This project stands on years of OP-Z community research. Thank you to the
people behind the following projects for publishing protocol observations,
format maps, experiments, and tools that made independent verification and
further research possible.

## Core protocol and project research

- [MarkRdgOx/opzdoc](https://github.com/MarkRdgOx/opzdoc) for the early OP-Z
  app-SysEx catalog, heartbeat, packed-7, compressed-message, file-protocol,
  and filesystem observations.
- [lrk/z-po-project](https://github.com/lrk/z-po-project) for the foundational
  project-file, pattern, track, note, step-component, parameter-lock, plug, and
  engine maps. The repository is licensed under Apache-2.0.
- [patriciogonzalezvivo/libopz](https://github.com/patriciogonzalezvivo/libopz)
  for turning much of the early format and SysEx research into an executable
  C++ model and parser.
- [leddy231/libopz](https://github.com/leddy231/libopz) for the first public,
  hardware-backed, flow-controlled full pattern-bank writer found during this
  research, its write notes, and its controlled `$02` experiments.

The two `libopz` repositories use the Prosperity/Patron licensing model. They
were used as protocol references and comparison baselines; no upstream C++
source files are vendored here. This repository's Python implementation is
organized independently around documented wire behavior and additional
device-backed observations.

## Sample and content tooling

- [schollz/teoperator](https://github.com/schollz/teoperator) for practical
  OP-1/OP-Z AIFF sample construction and metadata examples. It is MIT-licensed;
  see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- [romangarms/opz-sample-manager](https://github.com/romangarms/opz-sample-manager)
  for prior OP-Z sample-management workflows and interoperability context.

## Lights and official references

- [Open Fixture Library's OP-Z exporter](https://github.com/OpenLightingProject/open-fixture-library/tree/19cd202052009a6f96d385b74bd4b870714a8534/plugins/op-z)
  for a useful public implementation of the OP-Z `dmx.json` fixture schema.
- [Teenage Engineering's official OP-Z guides](https://teenage.engineering/guides/op-z)
  for the documented device behavior, limits, MIDI settings, sampling model,
  project workflow, modules, Lights, and step-component meanings used as the
  primary behavioral reference.

Inline links throughout `docs/` identify which sources informed each topic and
where this repository corrects, extends, or independently verifies earlier
findings. All trademarks remain the property of their respective owners.

## Research snapshot

The source research recorded these upstream revisions on 2026-07-26:

| Project | Revision reviewed |
| --- | --- |
| `leddy231/libopz` | [`3204adf`](https://github.com/leddy231/libopz/commit/3204adfd859d67146a25e612f93e721a5f06b695) |
| `MarkRdgOx/opzdoc` | [`06947e4`](https://github.com/MarkRdgOx/opzdoc/commit/06947e4927495cab47af468ed2c7b11334132e98) |
| `lrk/z-po-project` | [`c846a78`](https://github.com/lrk/z-po-project/commit/c846a78267d7ab2dc31c5eb54fe99173abeba802) |
| `patriciogonzalezvivo/libopz` | [`0f78266`](https://github.com/patriciogonzalezvivo/libopz/commit/0f78266e01b3f5487f9e109c073d96f5a916ea98) |
| `schollz/teoperator` | [`ddc6ef3`](https://github.com/schollz/teoperator/commit/ddc6ef3beee166dc14de7b69f8c3899aa69e7d96) |
| `romangarms/opz-sample-manager` | [`1f2bbec`](https://github.com/romangarms/opz-sample-manager/commit/1f2bbec91f0d243c01267b264d5a334de4c092b1) |
| Open Fixture Library OP-Z exporter | [`19cd202`](https://github.com/OpenLightingProject/open-fixture-library/commit/19cd202052009a6f96d385b74bd4b870714a8534) |
