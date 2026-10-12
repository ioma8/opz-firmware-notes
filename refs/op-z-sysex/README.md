# OP-Z SysEx

Unofficial, reverse-engineered documentation and cross-platform Python tooling
for communicating with the Teenage Engineering OP-Z over its app SysEx,
StateSync, serial-tunnel, and SysEx file-transfer protocols.

The core package uses only the Python standard library. Live MIDI access is optional and
uses `mido` plus `python-rtmidi` on desktop platforms.

The material was extracted from device-backed OP-Z research. Claims use a
consistent evidence vocabulary: **device-proven**, **decoded**, **observed**,
**inferred**, and **unknown**. Start with
[docs/coverage.md](docs/coverage.md) for the capability boundary.

> **Unofficial.** This project is not affiliated with or endorsed by Teenage
> Engineering. OP-Z is a trademark of Teenage Engineering. Writing malformed
> state can corrupt a project. Back up first, use a disposable project, verify
> every write by fresh readback, and preserve the original bytes for rollback.

## Documentation

| Document | Covers |
|---|---|
| [SysEx app protocol](docs/sysex-app-protocol.md) | Frame envelope, handshake, request/response IDs, and StateSync |
| [File transport](docs/clean-room-file-transport.md) | File-session framing, manifests, chunks, pull/push, verification, and rollback |
| [Project-global format](docs/project-global-format.md) | The 568-byte `$0C` state and saved-chain layout |
| [Pattern editing](docs/typed-pattern-editing.md) | Project-bank notes, locks, components, sound, and routing mutations |
| [MIDI configuration](docs/midi-configuration-sysex.md) | `$0F/$10` flow and the 292-byte settings map |
| [StateSync](docs/native-state-sync-analysis.md) | Live-state messages, sequencing, ACKs, and rejection boundaries |
| [Coverage](docs/coverage.md) | Evidence levels, safety boundary, public-data policy, and open questions |

See [docs/README.md](docs/README.md) for the full index.

## Install

```sh
python3 -m pip install .            # offline codecs and editors
python3 -m pip install ".[device]" # + cross-platform MIDI I/O
```

The `opzsysex` package includes:

- TE packed-7 framing, zlib payloads, and an incremental MIDI/SysEx parser;
- StateSync queries and bounded frame constructors;
- project-global and 16-pattern-bank editors that preserve untouched bytes;
- the 292-byte MIDI configuration codec;
- file-transfer upload/download state machines and sync-job manifests;
- guarded `$66` serial-tunnel framing;
- optional `mido` device transport with exact port matching and timeouts.

## Tools

```sh
# Decode one frame without touching a device
python3 tools/decode_sysex.py --hex "f0 00 20 76 01 0f f7"

# List MIDI ports or issue one documented read-only query
python3 tools/device_query.py --list-ports
python3 tools/device_query.py identity
python3 tools/device_query.py midi-config

# Apply bounded edits to a user-supplied checkpoint; never overwrites its input
python3 tools/edit_project.py --in global.bin --out changed.bin tempo 125
python3 tools/edit_project.py --in global.bin --out changed.bin chain 0 0 1 2 3

# Build a file-transfer manifest offline
python3 tools/file_manifest.py sample.aif \
  --device-path samplepacks/MySample.aif
```

Additional Python tools under `tools/` prepare OP-Z sampler AIFFs, edit slot
maps, and analyze synthetic or user-supplied evidence. WAV and AIFF preparation
is standard-library-only; other audio input formats optionally use `ffmpeg`.

## Tests

```sh
python3 -m unittest discover -s Tests -p 'test*.py'
python3 -m unittest discover -s Tests/ToolingTests -p 'test*.py'
```

All fixtures are generated during the tests. The repository contains no stock
projects, factory content, project backups, audio, firmware, app binaries, or
raw hardware captures.

## Public evidence policy

`evidence/` contains human-written summaries only. Machine-generated reports,
private paths, raw bytes, captured traffic, audio, samples, backups, and device
or firmware dumps are excluded. See [SOURCE_MANIFEST.md](SOURCE_MANIFEST.md).

## Acknowledgements

Special thanks to the OP-Z community researchers behind
[opzdoc](https://github.com/MarkRdgOx/opzdoc),
[z-po-project](https://github.com/lrk/z-po-project), and
[libopz](https://github.com/patriciogonzalezvivo/libopz), including
[leddy231's hardware-write fork](https://github.com/leddy231/libopz). Their
published observations and implementations established much of the public
baseline that this project verifies and extends.

See [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) for the complete source shoutout
and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for applicable notices.

## License

MIT — see [LICENSE](LICENSE).
