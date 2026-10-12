# Recorded sample-pack substitutes

These 19 files contain **real drum-machine recordings**, processed into OP-Z-style AIFF sample packs. They are substitutes, not the original OP-Z factory sounds, and their filenames only match the missing assets so they can be assigned to corresponding slots.

Source recordings come from [`fluid-music/open-drums`](https://github.com/fluid-music/open-drums), pinned at commit `475cc3314fe06f6d1af02e9790ad9707c1f2b26b`. Its TR-707 `README.txt` states those samples are public domain. Its TR-808 README says the source files have no licensing restrictions; `TR808.TXT` credits Michael Fischer/Technopolis and describes the set as free. The source notes are kept in `sources/`.

The packs draw on 24 recorded hits each (the auxiliary `CuckooC_keypawn.aif` has 22 distinct hits because its source pool is smaller), with modest pitch, filtering, gain, limiting and fade processing. `zVinyl.aif` uses processed cymbal/percussion recordings, not a vinyl recording. Files are mono 44.1 kHz / 16-bit AIFF with `APPL`/`op-1` slice metadata created by MIT-licensed [`schollz/teoperator`](https://github.com/schollz/teoperator), commit `ddc6ef3`.

Regenerate with Python 3, `ffmpeg`, and `teoperator` installed:

```sh
python3 generate.py --tool /path/to/teoperator
```

All outputs passed AIFF, metadata, non-silent audio, and macOS `afinfo` checks. SHA-256 hashes and per-pack source filenames are in `MANIFEST.json`. They have **not** been imported or playback-tested on the OP-Z; nothing was written to the device.
