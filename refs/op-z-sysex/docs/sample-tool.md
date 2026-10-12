# Python sampler preparation tools

The repository includes cross-platform Python helpers for preparing OP-Z
sampler AIFF files and editing a user-supplied slot map. They do not contain or
download factory content.

## Supported inputs

- Mono 16-bit, 44.1 kHz WAV and AIFF use the Python standard library.
- Other user-owned formats optionally use the cross-platform `ffmpeg`
  executable.
- Melodic sampler output is capped at six seconds.
- Drum sampler output supports up to 24 slices and a twelve-second total.

## Prepare a melodic sampler

```sh
python3 tools/make-opz-synth-sample.py input.wav output.aif \
  --name MySample --base-frequency 440
```

The lower-level functions in `tools/opz_sample_format.py` also build drum kits,
read AIFF PCM, and inspect `APPL/op-1` metadata.

## Edit a slot map offline

```sh
python3 tools/opz-slot-map-edit.py before.json after.json \
  --track 4 --slot 3 --plug-id 60001
```

This operates only on files supplied by the user. It does not connect to the
device and does not prove that a slot was installed, activated, saved, or heard.

## Build the file-transfer manifest

```sh
python3 tools/file_manifest.py output.aif \
  --device-path samplepacks/MySample.aif
```

The manifest is only one input to the file protocol. Live orchestration and
fresh device readback remain required before claiming success.

## Public-data rule

Do not commit generated AIFFs, source audio, slot maps, project checkpoints,
backups, or factory/stock content. The test suite creates synthetic audio in a
temporary directory and removes it after each run.
