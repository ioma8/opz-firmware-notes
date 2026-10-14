# Handoff: the clone's end-to-end output level

Found while adding a `--project` file to the TUI: **the whole clone plays about 78–90 dB down**, which
is why nobody has ever heard it. Nothing below is fixed; this records the measurements so the next
session starts from evidence.

## Measurements (44 100 Hz, the real packs in `samplepacks/`)

| path | peak, Q31 |
|---|---|
| `DrumEngine` alone, pack.bin-equivalent real pack, `level` 0x7fffffff, note 36, velocity 200, 64 blocks | **301 010 069** |
| the same hit through `opz_core::engine::Engine` (the whole ported chain), track level 255 | **32 419** |
| the demo pattern's offline render (`--render`), all six tracks | **69 894** |
| one synth track alone through `Engine` (track 5, note 60, every parameter 255) | **8 401** |

The engine's own output is Q31 and near full scale; the chain hands back roughly the raw i16
magnitude. That is a ~2^13–2^15 cut.

The two output conversions then make it inaudible:

- `crates/opz-tui/src/render.rs`'s `write_wav` writes `sample >> 16`, so a peak of 69 894 becomes
  **1 LSB of i16** (the recorded "non-silent, peak 69894" evidence is true and useless).
- `crates/opz-tui/src/audio.rs` converts Q31 to `f32` by dividing by 2^31, so the live path is the
  same ~-90 dB.

## Why 105 green tests did not catch it

The mixer-level fixtures are inert at the level that matters:

- every `voice` case in `crates/opz-dsp/tests/golden/host/host.json` has `out` **all zero** (73 cases);
- all 14 `synth_render` cases have `outputs` peaking at **13 654** — they pin the scratch, the LFOs,
  the counters and the ramps, not a voice's audio;
- the `synth_render_tracks_match_the_original` comment already notes the master bus at 0x12288a0 is
  4.5 % off for its "filled" case, at a magnitude of ~2e6.

So the per-voice gain domain (the ported `Voice` / `TrackFilter` / group-gain path) has never been
compared against the device with an engine producing real audio. The engine-level fixtures pin the
engine alone (1.04e9 for a full-scale pack, byte-exact), and the mixer fixtures pin a mix of silence.

## What would settle it

1. A Unicorn trace of the device's `Voice::render` (and the mix-down after it) with a **full-scale**
   voice input, reading the voice's `out` buffer and the master buffer — the same register-oracle
   method that ported `Saw013a::render`. The open question is which domain the device's per-voice
   gain multiplies run in (`>>15` over Q15, or `>>31` over Q31), and whether the framework scales
   the master buffer up before the DAC.
2. A `synth_render` fixture case whose engine input is a full-scale drum `noteOn` rather than
   silence, added to `tools/unicorn-harness` and `host.json`.
3. Only then decide where the fix belongs: the ported `Voice`/mixer gain math, or `Engine::render`'s
   hand-off to the output stage (the `master[frame*2] >> 1` fold plus the two output conversions).

Until that lands, the plan's Phase 5 "playable check" stays open for a second reason: not only has
nobody listened, the app as it stands cannot be heard.
