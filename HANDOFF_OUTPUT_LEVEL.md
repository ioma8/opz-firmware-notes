# Handoff: why the clone was inaudible, and what fixed it

Found while adding `--project` to the TUI and reported by ear ("I do not hear anything"): the whole
clone played about **80 dB down**, and the second half of every bar was silent. Both causes were host
programming gaps in `crates/opz-core/src/chain.rs`, not port bugs. Fixed, with a regression test.

## What was wrong

**1. The master bus's parameters were never programmed.** The device's mixer renders *twelve* tracks:
the UI drives six, and tracks 8..11 are the three FX tracks and the master bus. Their parameters are
the library's to *read* and the app's to write, and the clone wrote none of them, so track 11's
filter row sat at zero - and that row **is** the master filter. Zero cutoff is row zero of the
coefficient table, i.e. a closed lowpass. Measured, one full-scale kick through the whole chain:

| master filter word | master-bus peak (Q31) |
|---|---|
| 0 (what the clone had) | 1.5e5 |
| 0x40000000 (centre) | 1.6e8 |

The filter's response is symmetric around the centre, so the clone latches `0x40000000` into the
filter's two words (track 11 parameters 8 and 9) - the same "centre" convention `pan` already uses.
`Chain::new` now calls `program_mixer_tracks`, which sets all four mixer-only tracks with a transparent
parameter vector (filter centred, FX sends silent, limiter dry) and latches them so the first half
second of a session is not 30 dB quiet while the smoothed block glides in.

**2. `set_master_volume` set only half of the pair.** `interpolateParameters` glides the smoothed
volume (`+0x6860`) a sixty-fourth of the way toward its target (`+0x685c`) every block, and the clone
wrote only the smoothed word - so the volume walked down to silence in about half a second. That is
the "first hit is loud and the rest are ducked into nothing" symptom. Both words are now set.

## Measured, `opz-tui --render` (i16 peak, one bar demo / two bar project)

| | demo | project |
|---|---|---|
| before | 69894 Q31 -> **1 LSB, -90 dBFS**, bar 2 silent | 91036 Q31 -> **2 LSB** |
| after | 309499830 Q31 -> **4723, -16.8 dBFS** | 389469850 Q31 -> **5943, -14.8 dBFS** |

The fixed render's per-step peaks repeat every bar (the pattern loops), where before everything after
step 5 was zero. Two runs are byte-identical. 106 tests green, including a new
`chain::tests::the_master_bus_keeps_the_mix_audible`, which asserts the level a listener needs rather
than merely a non-zero sample (the old tests all passed with the bug live: the whole-mixer fixtures
are inert at audio level - every `voice` case's `out` is all zero and all 14 `synth_render` cases'
`outputs` peak at 13654, so nothing pinned the master bus's level).

`engine::tests::render_audio_integration` had to change with it: it counted `0 -> non-zero` edges to
prove the kicks on steps 4/8/12 fired, and those edges only existed while the master volume decayed to
silence between hits. It now watches the host's own note bookkeeping as the transport reaches each
step, plus an audio check per step window.

## What is still open, and how it would be closed

* **The app's real values.** The clone's mixer-track parameters are a *stand-in* (the transparent
  setting), because the device's app data for the master filter, the FX sends and the compressor's
  references is not in replay. On the device the app writes them; a trace of the app's
  `setTargetParameters`/`latchParameters` calls for tracks 8..11 would pin them exactly.
* **The compressor's references.** `Chain::set_compressor_references` is still dead code: it writes
  `+0x6854`, which `render_setup` refolds from `HostValues::master_params` every block, so it cannot
  take effect that way. With track 11's parameters at their stand-in the compressor's `gain_scale`
  (`+0x6298`, track 11 parameter 14) is zero, which makes it transparent - fine for now, but it means
  the master compressor is effectively not exercised by the live path.
* **Listening.** Still nobody has heard it. This round went from "inaudible" to "-15 dBFS, pattern
  loops" by measurement only; the ear check belongs to whoever has the speaker.
