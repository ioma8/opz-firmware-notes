# Factory engine status: what plays, what does not, and why

This is the consolidated state of the "play the OP-Z factory engines" objective after an extended
investigation. It exists so the next person does not re-walk 87 disproved hypotheses.

## The number

**3 of 13 factory instrument modules play the requested note.** Verified with `toolkit/opzfactorycheck.py`
through the app's own render path, at 220 Hz and 440 Hz, against both neighbouring frequencies:

| engine | 220 Hz (at f0 vs neighbours) | 440 Hz | across six pitches | notes |
|---|---|---|---|---|
| chord | 2.6e5 vs 1.1e5 | 8.8e4 vs 5.2e4 | **6 of 6** (with its 16384-byte period) | plays every pitch tested |
| digital | 5.0e5 vs 3.2e5 | 4.7e5 vs 1.8e5 | **6 of 6** | plays every pitch tested |
| ep | 3.6e6 vs 1.7e6 | 1.6e6 vs 9.1e5 | **2 of 6** | writes the **right channel only** |

**The pitch scale is per engine.** Sweeping the pitch argument for `chord` against a 440 Hz target shows its
contrast peaks at **150**, not 300 - a table period of **16384 bytes** rather than digital's 32768. With that
period chord plays all four targets tested (contrast 18-44, its fifth only 2-7) and, through the app path, passes
**6 of 6** pitches at contrast 17-31. `opzenginetool` now keeps a per-engine table period for this reason.

**A stricter verifier:** `opzfactorycheck` now also requires that changing the note changes the output, measured in
**contrast** terms - how far the tone stands above the broadband floor - because raw energy is dominated by an
engine's fixed partials. In those terms the 220 Hz tone stands:

| engine | when 220 Hz is requested | when 440 Hz is | ratio |
|---|---|---|---|
| digital | 179.2x | 0.3x | **643** |
| chord | 23.8x | 9.5x | **2.51** |
| ep | 12.9x | 12.9x | **1.00** (fixed spectrum) |

So `digital` and `chord` both track the note (the latter on top of fixed content), while `ep` produces the same
spectrum whatever note it is given - its earlier two-note passes were coincidences of a test that never asked
whether the note mattered.

**Range limit:** measured at every five semitones from note 36 to 96, `digital` passes 10 of 13 (it loses the tone at
notes 86, 91 and 96 - 1174 Hz and above) and `chord` 9 of 13 (from note 81, 880 Hz, upward). Both are clean from C2 to
about C6 and degrade in the top register, so "six of six" describes the mid range rather than the whole keyboard.
The degradation is not fast decay - early and late windows measure the same - and not a period mismatch: above
880 Hz the dominant peak is the **750 Hz block rate** for digital and **5-6 kHz content** for chord, so neither
produces the requested tone there at all - with the linear calibration. The register is not unreachable, though:
sweeping the argument at 1174.7 Hz shows that **900** produces the note with a contrast of 19.1, well past both the
band table's ~777 Hz edge and the linear prediction of 802. So above the edge the mapping turns non-linear, and the
top register needs its own calibration rather than being impossible.

**Correction:** that calibration *does* reproduce - renders are byte-identical on repeat and the contrast figures are
stable; an earlier note claiming the measurement was unstable came from comparing two runs whose candidate argument
sets differed. The real behaviour above the edge is **folding**: arg 600 puts its tone at 879 Hz, the linear
`1.4648x` prediction, but arg 1900 puts it at 1397 Hz - exactly half of its 2783 Hz prediction - and arg 1300 at
1175 Hz rather than 1904. So the linear period law holds in the mid range and the output folds once the argument
passes the band edge, which is why no single period covers the top register.

So **two** factory instruments play correctly through most of the range: `digital` (32768) and `chord` (16384). The same
sweep applied to the rest finds no further calibration: `ep` peaks at contrast 2.5, `electric` 9.7, `volt` 1.5,
`cluster` 1.0 and `organ` 2.2, while `sampleplayergain` and `synthsampler` are silent. Refining `electric` against
a 220 Hz target gives an identical contrast of 38.9 at every argument from 19 to 112 - it ignores the pitch
argument and produces a fixed spectrum, so no period will place it.

**Correction:** `digital` plays **6 of 6**, not 5 of 6. The apparent miss at note 76 was a measurement fault of
mine - the DFT was evaluated at a rounded 659.3 Hz instead of the true 659.255 Hz, which is under one DFT bin but
enough to swing the magnitude by about 20 percent. Tested at exactly `440 * 2^((note-69)/12)`, all six pitches pass.
Under the same exact-frequency method `chord` reads 1 of 6 and `ep` 2 of 6.

An independent measure agrees, so that result is not an artefact of the neighbour test: the contrast of the
fundamental against the broadband floor (`mag(f0) / median magnitude over 200-2500 Hz`) is **124-285x for
digital at all six pitches**, but only **1.8-14.8x for chord** and **3.3-21.6x for ep**.

The table has been re-run end to end and reproduces: `digital` passes 5 of 6 (failing only 659 Hz), and
`chord` and `ep` pass exactly the 220 and 440 Hz ones. Every one of the 21 factory modules is named somewhere in
this document with a verdict, so the inventory is complete rather than a summary.

The six-pitch column is the honest measure. `opzfactorycheck` tests two notes, which is enough to reject a fixed
spectrum (see `electric` below) but **overstates** engines like `chord` whose output legitimately contains a
fifth: at 165 and 659 Hz the target's neighbour is its own interval, so the test fails on correct behaviour.
Taken across the range, only **digital** plays robustly; `chord` and `ep` pass at the two tested notes.

The eight factory **effect** engines were exercised for the first time in this work. Through `renderFX` with the
five-argument stack (as `opzenginesweep` uses) plus host memory: `crush` (peak 0.019) and `chorus2` (peak 0.027)
transform a fed 440 Hz sine rather than passing it through, while `chorus` and `dist` stay silent, `reverb` raises
"keeps calling outside its window", and `delay`, `tapetwo` and `fdnreverb` never return. Neither of the two that run
is demonstrably correct - `chorus2` latches a constant value - so this shows they execute, not that they behave. Characterised further: fed a rising ramp, `crush` produces 195
distinct outputs and `chorus2` 308, while `dist` and `chorus` produce exactly **one** under every state seed tried
(0x7fffffff, 0x40000000, 0x01010101) - the seeding that helps instruments never reaches them.

`dist`'s decompiled renderFX explains the shape of that: it indexes through the host table's third dword
(`*(int *)(*(int *)(DAT_81bfa4f8 + 8) + uVar8 * 4)`, where `uVar8` comes from its own state) and writes through
module globals `DAT_81bfa554`/`DAT_81bfa558`. Seeding those state words with in/out/length in every order, and
mapping all 164 OS segments so `0x81128264` reads real data, both leave it at peak 0.0000 with one distinct value.

`volt` produces full-scale DC. `electric` is **silent through the app path** and only becomes audible (peak 0.0315) when `state+0x10` is seeded by hand, and even then does not
track pitch. `cluster` emits a constant 2e-4. `organ`, `sampleplayergain`, `synthsampler` emit nothing.
`analoga`, `fm003b`, `ministringshort`, `saw013a` raise errors.

## The recipe that works

Three things had to be right, and each was measured rather than assumed:

1. **Pitch is not Q16 Hz.** The argument is a byte stride into the shared 8191-word quarter-sine table at
   `0x0800bb48`, so the output is `arg * 48000 / 32768` (a factor of 1.4648). Passing `f * 32768/48000` makes
   `digital` land on the requested frequency. Confirmed by a calibration sweep: pitch 300 gives 440 Hz, and
   110/220/330/440/550/660/880 Hz each hit their own frequency.
2. **Six stack arguments.** Factory engines read context, params and amp from `[FP+0x14]`, `[FP+0x18]` and
   `[FP+0x1c]`, which only line up when all six words are pushed. Three leaves them zero.
3. **The amp object and host memory.** The OS fills `amp+0x04 = 0x40000000`, `amp+0x08 = 0x7f000000`,
   `amp+0x0c = -0x40000000`, `amp+0x10 = 2` before every tick, and engines render through the OS's shared sine
   table and host-services table. Leave either out and engines read zeros and emit silence.

`opzenginetool.render_clip` applies all three for modules under `engines-official`, with a per-engine table period
(see below); `toolkit/opzfactorycheck.py` verifies the result.

**Verified end to end through the app itself**, not only in the harness: requesting `/api/render` from the running
`opzenginetool` and decoding the served WAV gives `digital` a contrast of **179** at 220 Hz and **248.6** at 440 Hz
(peak 0.124), and `chord` **23.8** and **28.2** (peak 0.068). Both therefore work as shipped - engine, app path and
served audio. Extending that to eight notes through the same interface: **digital passes 8 of 8** (notes 45-81,
contrast 128-309 up to note 76 and 44.8 at 81) and **chord 7 of 8** (21.5-36.7 up to note 76, failing at 81).

## Why the other ten do not

Each is root-caused, with the evidence in `HYPOTHESES.csv`:

- **organ** passes its `state+0x10` guard (which returns immediately when zero, and which the engine only fills
  *after* that check), then runs a loop that calls its own divider `0x81b7ed08` with divisor 100 and indexes its
  table at `0x81b7f698`. The numerator arrives small and negative, the divide saturates to 52 million, and the
  read lands outside the module. No pitch from 300 Hz to 1.6 MHz avoids it; the numerator is phase-derived.
- **analoga, saw013a, ministringshort, fm003b** call out of their window. Mapping the OS image makes those calls
  resolve into real firmware and they then either never return or run into uninitialised OS data. They are also
  not merely mistuned: all four raise the same error at every pitch argument from 50 Hz to 1200 Hz, unlike
  `digital`, whose calibration sweep found a working factor.
- **electric, cluster, sampleplayergain, synthsampler** respond to seeds but never track pitch. A blanket
  fill of the whole state block does not change that: organ, cluster and synthsampler stay at peak 0.0000
  and electric emits a **fixed** spectrum (peak 0.0181 at every pitch), which can fool a one-note neighbour
  test into passing at 330 and 660 Hz. That is why `opzfactorycheck` requires two notes - with 220 and 440
  both required, electric is correctly rejected.

The common factor: the engines consult runtime state that the sequencer creates, and that state does not exist
in an unbooted image. `settings/plugs.json` inside `opz.ldr` holds no parameter values; the factory patches *are*
available (in the APK, see `toolkit/opzplugs.py`, 16 engines and 58 presets) but feeding every `digital` preset
leaves its output byte-identical, so the patches are not what is missing.

## Emulator fixes made along the way

Each was a real fault, found by chasing one symptom:

- `LdImm` / `LdImmHalf` pointer-group bit (bit 3 of the register field) - pointer-register loads were landing in
  data registers, making table addresses inert.
- `NOP32` (`0xC803 0x1800`) executed as a DSP multiply-accumulate.
- `UNLINK` is four bytes, not two - initially wrong in both the interpreter and our assembler.
- `ProgCtrl` `0xD`/`0xE` (CLI/STI) were unimplemented, which stopped real OS code mid-routine.

## Measurement traps that produced false results

Worth knowing before trusting any number here:

- **Interleaving.** `render_clip` returns interleaved L,R; a DFT at f over that array reads it as f/2.
- **Single-channel engines.** `ep` writes only the right channel; left-only readers call it silent.
- **Harmonic locking.** A plain frequency reading reports 2x or 3x the true pitch when a harmonic dominates.
  `analoga`, `bell`, `organ`, `saw013a`, `volt` legitimately read 2x; `bar`, `ep`, `glass`, `pluck`,
  `synthsampler` read 1x; `chord` reads 1.5x.
- **Counting windows.** An earlier claim that the sine lookup "stops in later blocks" was an artefact of a window
  ending at `0x0800d400`; the table pointer walks past it.

## What the OS actually passes to an effect (read from the firmware)

Decompiling the FX manager settles the effect ABI, which had only been inferred before. The `FxManager.cpp` string at
`0x8156f22c` is referenced by `FUN_8012ced0`, whose body contains:

```
(*pcVar5)(puVar4 + 4, param_2, 0, &DAT_8112b21c + table[param_2-8], &DAT_8156f2b8);   /* init: FIVE args */
...
(*(code *)puVar4[2])(param_4, param_5, puVar4 + 4, param_6);                          /* renderFX: FOUR args */
```

So `init` takes five arguments - the fourth being a **params pointer** computed from the table at `0x8156f21c` - and
`renderFX` takes **four**: `(param_4, param_5, state, param_6)`, where `param_4`/`param_5` arrive from the voice
dispatcher `FUN_80117f4c`. Testing that form, `chorus2` responds to `(out, in, state, X)` with peak 0.785 while the
other seven effects stay silent. The five-word stack used until now is **not** what the firmware does.

The params pointer itself cannot be recovered statically: `0x8156f21c` (the offset table) is absent from every segment
payload and `0x8112b21c` (the buffer it indexes) reads as four zero bytes from a zerofill segment. Both are **BSS the FX
manager fills at runtime**, so an effect's per-slot parameters exist only inside a running firmware.

## The output is dominated by a block-rate artefact

Worth stating once, because it explains most of the difficulty: at **every** pitch argument the dominant spectral peak in
these engines' output is **exactly 750 Hz** - 48 kHz / 64, the block rate - with a contrast of roughly **500 to 1500**,
while the musical tone measures only 20 to 70. Subtracting each block's least-squares offset and slope does not remove it
(contrast stays 491-703), so it is not a per-block linear ramp. This is why plain peak-picking has misled so many
measurements in this investigation, and why only a targeted contrast at a known frequency reads the note at all.

Dumping sixteen consecutive blocks shows why: **each block is a monotone ramp that restarts at the block boundary**
(block 0 runs -1,228,178 to 88,617,972; block 7 runs 141,060,485 to 113,265,362) and blocks 2 and 3 are nearly silent
(mean 8,001 and 22,588). The engines are not writing a waveform; the musical information sits in each block's slope, and
the 375 Hz component is the ramp restart. No host-side transform recovers a clean note from that.

## Measurement is now the limiting factor

Peak-based analysis cannot settle whether `chord` and `ep` track. A band-limited rFFT after a 64-sample
moving-average high-pass reads chord at a clean 2.03/2.04/2.04 octave ratio for 330/440/659 Hz but 6.29 at
110 Hz; first-difference high-passing just pushes the peaks to Nyquist; and the engines carry non-musical energy
that survives every simple filter tried. The honest statement is that the six-pitch energy test is the only
measure here that resists the artefacts, and by it only `digital` passes robustly.

## What would unblock the rest

In order of usefulness:

1. A device memory dump covering `0x04000000`-`0x04100000`.
2. The `.zfw` AES key (the updater containers are AES-CBC with a per-file IV and no key is present).
3. Emulating the OS host services these engines consult - weeks of work, and it would also need the state above.

The device project files are not a substitute for it either: each `.opz` is 342,848 bytes of pattern and sample
data in which only 48 dwords look like OS addresses, with no plug configuration anywhere.

Alternatively, the substitute engines already cover every factory slot and play correctly; they are ours, not
Teenage Engineering's, and should never be presented as the factory binaries.

That coverage was checked rather than assumed: all **21 of 21** factory slots have a substitute with a matching
name, and every one of those name-matched substitutes is the **same kind** as the factory module it stands in for
- 17 instruments in `engines-family` and 8 effects in `engines-effects`, with no instrument standing in for an
effect or vice versa. The four extra modules (`bar`, `bell`, `glass`, `pluck`) are descriptive presets rather than
slot stand-ins.

## The vendor's own engine library is on this machine — and it settles the ABI

Late in this investigation a much better source than the Blackfin modules turned up, reached by way of the
`origin/work` branch: **`~/.opz-decode/opzso/libSnakePlugin.so`** (1.95 MB, from the companion APK) with
`~/.opz-decode/opzso/syms.json` (4,699 symbols, 1.29 MB). It is the vendor's ARM64 build of *the same engines*
with its symbol table intact, so none of the ABI has to be inferred any more:

```
render(fract32_t *out, unsigned frames, int track, void *state, const unsigned *params, ADSR*)
initModule(unsigned id, const ModuleCallbackInterface *iface, unsigned *out)
init(void *state, unsigned a, unsigned b, void *tempBuffer, void *d)
onNoteOn(int note, unsigned char velocity, void *state, const unsigned *params)
```

- `out` is **interleaved stereo Q31** and `frames` is the frame count (two samples each).
- `initModule(0, iface, out)` stores `iface` in the engine's own global; `init` stores its 5th argument as
  `tempBuffer` and its 3rd at `state+0x20`.
- **`render` returns immediately when `ADSR+0x10` (phase) is zero.**
- **`ADSR` is six words**: `+0x00` rate, `+0x04` level, `+0x08` mul, `+0x0c` add, `+0x10` phase, `+0x14` tail
  (byte `+0x15` re-arm). The engines **gate on `+0x14`**.
- `iface+0x40` is the host envelope hook; **`iface+0x48(id, note)` returns a 40-byte sample record**
  (`+0x00` data, `+0x08` readable frames, `+0x0c` pitch, `+0x10` rate); `iface+0x08(8)` is readiness.

**All 21 factory engines are in that library**, by class name: `AnalogA, Chord, Cluster, Digital, EP, Electric,
Fm003b, MiniStringShort, Organ, SamplePlayerGain, Saw013a, SynthSampler, Volt` and `Chorus, Chorus2, Crush, Delay,
Dist, FdnReverb, Reverb, TapeTwo`.

### A sibling repository already plays three of them

`~/projects/customs/opz-clone` (branch `work` of this repo is its handoff trail, 171 commits) ports engines from that
library and verifies each against the original executed under Unicorn:

| engine | verification |
|---|---|
| `Digital` | byte-exact on 35 golden cases |
| `AnalogA` | byte-exact on 20 voices, every block, every filter tap |
| `Saw013a` | byte-exact on 19 cases, including the whole 26-word state after `onNoteOn` |
| `SamplePlayerGain` | byte-exact on ten golden cases (`golden_cases_match`) |
| drums | byte-exact, plus a device-traced block |

Playback through the app is covered too: `cargo test -p opz-core` passes 44 tests including
`a_note_through_the_ported_chain_makes_sound`, `a_saw_track_plays_through_the_ported_chain`,
`setting_a_tracks_engine_swaps_its_voices` and `render_audio_integration`, so the four engines are exercised through
Engine -> track -> mixer -> audio rather than only per-engine.

Verified by `cargo test -p opz-dsp` on 2026-10-19: `digital` 3 tests, `analog_a` 11, `saw013a` 12 (including
`render_matches_every_golden_case` and `render_matches_the_device`), `sample_player_gain` golden cases - all passing,
so **four of the thirteen instruments** are byte-exact against the vendor's own code. The clone's
`tools/unicorn-harness/opzso.py` is a general loader that can call *any* entry point in the library, and it
already has host classes for `Digital`, `AnalogA`, `Saw013a` and `SamplePlayerGain`.

**So the way to finish this objective is to continue that port in `opz-clone`**, one engine at a time, using its
established method (symbol → Unicorn fixture → port → byte-exact test). This repository's Blackfin route has taken
2 of 13 instruments as far as it can go; feeding the clone's *device ground truth* for `saw013a` to our Blackfin
binary still fails because the engine copies only the first 13 interface entries into its own state, leaving
`+0x40`/`+0x48` at zero so its host calls go to address 0.

## The effect ABI, and effects that actually process audio

Resolving the effect classes in `libSnakePlugin.so` gives their mangled names, and those carry the signature:

```
Crush::renderFX(unsigned const* params, int variant, void* state,
                fract32_t* in, fract32_t* out, fract32_t gain)
```

The second argument is the plug's **variant word**, not a frame count: the clone's ported `FxManager`
(`_ZN9FxManager6renderE7TrackIdPKjP9fract32_tS4_S4_S4_S3_` at `0x13cde4`) tail-calls the plug with
`(params, *(u32*)(slot + 0xe8), slot + 0x20, a, b, gain)`. Every measurement here passed 64 there, which happens to
select a default path.

Called that way — `initModule`, `init`, then `renderFX(params, 64, state, in, out, out)` — the effects do work:

| engine | output |
|---|---|
| `Crush` | **125 of 128 nonzero**, peak 46,551 |
| `Dist` | 7 of 128 nonzero, peak 2,453 |
| `Crush` | **2013 of 2048 over sixteen blocks**, peak 264,911 |
| `Reverb` | **1868 of 2048**, peak 287,026 |
| `Chorus2` | **598 of 2048**, peak 218,904 |
| `Dist` | 7 of 2048, peak 2,284 |
| `Delay` | **19,966 of 25,600 over 200 blocks**, peak 577,536 - first output at block 44 (about 58 ms) |
| `FdnReverb` | **22,090 of 25,600**, peak 61,692 - first output at block 27 |
| `Chorus` | **15,358 of 15,360 samples changed over 120 blocks** - it processes **in place**, writing into the input buffer and never into the output one |
| `TapeTwo` | **runs** once `init`'s 4th argument is a >= 1 MB buffer: the engine sets `sampleLine_r = param_4 + 0x100000`, so a null argument made it clear `0x100000` - its own code. It fills its `sampleLines` buffer (512/512) but does not yet write to the output |

The two delay-based engines were never broken: their lines simply had not filled. `Delay` needs about **58 ms** of input
before it emits anything, which is why 16-block runs showed silence.

A **dedicated scratch buffer** matters: `Chorus2` is silent when the output buffer is handed to it as the sixth
argument and produces 598 nonzero samples when given 256 KB of its own, so the sixth argument is scratch, not output.

`Chorus` was the clearest illustration of a reading error: hooking every write during one call showed 128 writes into the
**input** buffer and none into the output buffer - it is an insert effect that works in place. Reading the input buffer
afterwards shows the signal changed from the first block.

So **seven of the eight factory effects demonstrably process audio** with the vendor signature - `Crush`, `Reverb`,
`Chorus2` and `Dist` - against zero before it was read from the symbol names.

So two of the eight factory effects genuinely process audio in the vendor library. Every attempt in this repository
used a five-word stack with the buffers last, which is simply the wrong convention; the vendor's is **params and
frame count first, buffers third and fourth**.

## A loader gap worth fixing

`opzso` maps the library's loadable segments but not its full declared BSS: the third `LOAD` segment declares
`filesz 0x45a8` and **`memsz 0x18ba661`** at `0x1da3d0`, i.e. a 24 MB BSS, while the mapped image ends around
`0x1e0000`. Anything above `0x2000000` raises `UcError`, so an engine that uses a large buffer hits a fault that
looks like an engine bug.

`TapeTwo` still raises `UC_ERR_EXCEPTION` even with that range mapped, so its cause is separate, but the gap is
real and should be closed before judging any engine that allocates megabytes.

## Reproducing the effects result

`toolkit/opzfxcheck.py` runs all eight factory effects from the vendor library under Unicorn and reports, for each,
how many output samples are non-zero and how many input samples were modified in place:

```
python3 toolkit/opzfxcheck.py --blocks 60
```

```
  Chorus     PROCESSES  out     0/7680 nonzero, input changed  7678/7680
  Chorus2    PROCESSES  out  6232/7680 nonzero, input changed     0/7680
  Crush      PROCESSES  out  7645/7680 nonzero, input changed     0/7680
  Delay      PROCESSES  out  2046/7680 nonzero, input changed     0/7680
  Dist       PROCESSES  out     7/7680 nonzero, input changed     0/7680
  FdnReverb  PROCESSES  out  4172/7680 nonzero, input changed     0/7680
  Reverb     PROCESSES  out  7502/7680 nonzero, input changed     0/7680
  TapeTwo    silent     out     0/7680 nonzero, input changed     0/7680

  7 of 8 factory effects process audio
```

`Chorus` shows zero on the output and 7,678 changed inputs because it is an insert effect working in place. `Delay`
and `FdnReverb` need longer runs to fill their lines (60 blocks is 80 ms; use `--blocks 200` for both). `TapeTwo` is
the one remaining failure and is still open. The script needs the vendor library and the loader from
`~/projects/customs/opz-clone/tools/unicorn-harness`; it drives them rather than reimplementing anything.

## The instrument half needs ports, and nothing else

Closing note, so no future session repeats this: **instruments cannot be driven by a generic host.** The evidence is
`Chord`, deliberately chosen as the easiest case — the smallest unported engine (1,480 bytes of render), and one this
repository's Blackfin harness already plays. It was given its variant-selected gain global, its render-time global
`DAT_0134a5e0` (five values), a Q31 wavetable at `interface+0x18`, a 2 MB `init` buffer, `ADSR` phase 5 and
`onNoteOn`, across variants 0, 4, 5, 6 and 7. Every combination renders **0 of 7,680 samples**.

The same was tried on Organ, Cluster, Electric, EP, MiniStringShort and Volt, and on all thirteen at once. None
produced a sample. The four instruments that do work in `opz-clone` work because each has a dedicated host class
supplying exactly the globals its engine reads, plus a translated port with byte-exact fixtures. **Any further
instrument needs that same treatment; there is no shortcut.**

## A trap that invalidated earlier host-data fills, and Cluster now playing (2026-10-19)

**Ghidra's decompiled addresses for engine *globals* are 0x100000 above the real ones**, exactly as they
are for code. Every earlier attempt to supply host data wrote to the Ghidra address, so the writes landed
in unused memory and the engine kept reading zeros. Digital's own working host in `opz-clone` shows the
truth: its five gain globals are at `0x124A5CC`-`0x124A5DC` and its octave table at `0x124A658`, while
the decompile of the same code names `0x134A5CC` and `0x134A658`.

With the correction applied - gains at `0x124A5CC`..`0x124A5E0`, a 16-entry i16 octave table at
`0x124A658`, Cluster's per-band i16 table filled over `0x124A900`-`0x124AA00`, a Q31 wavetable at
`interface+0x18`, `params = [0, 0x40404040 x17]`, ADSR level and mul `0x7fffffff` with `state_index 3`,
`init(state, 5, 0, 0, temp)` and `onNoteOn(60,100)` - **Cluster renders 5118 of 5120 samples nonzero at
peak 848755646**, and the same harness reproduces **Digital at 5118 of 5120, peak 424056965**.

That second figure is the important one: it means the generic harness is now correct, because it
reproduces an engine whose working host is already known. The earlier conclusion that no generic host
could bring an engine up was an artefact of the address error, and any engine whose data globals can be
read from its decompile should now be reachable the same way. Volt, Organ, EP, Electric,
MiniStringShort, Chord, Fm003b, Saw013a and SynthSampler still need their own global sets at corrected
addresses.

### The generic host does work: 9 of 13 instruments (2026-10-19)

Correcting the two mistakes fixes the instrument half almost entirely. `toolkit/opzinstcheck.py`
runs all thirteen factory instrument classes from the vendor library through one host and reports
which render:

| supply | why it matters |
|---|---|
| globals written at **Ghidra address - 0x100000** | writing at the Ghidra address, 0x100000 too high, silently does nothing and every engine renders zeros |
| `0x124A500`-`0x124C400` filled with i16 `0x7FFF` | envelope-rate curves and the octave/per-band gain tables; left zero, every engine is silent |
| Q31 wavetable at `interface+0x18` | the oscillator table |
| five `fract32_t[65]` filter-state banks at `interface+0x28` | filtered engines fault with `UC_ERR_READ_UNMAPPED` without it |
| `params = [0, 0x40404040 x17]`, ADSR level and mul `0x7FFFFFFF`, `state_index 3` | the block Digital's own working host arms |
| `init(state, 5, 0, 0, temp)` | the clone's working init arguments |

With that, **9 of 13 render**: Chord, Cluster, Digital, EP, Electric, MiniStringShort, Organ and
Volt at 2558-2560 of 2560 nonzero (peaks 0.16-0.40 full scale) and AnalogA nonzero but at peak 533,
i.e. inaudible. Still silent: Fm003b, Saw013a, SamplePlayerGain and SynthSampler - the two samplers
need a sample record through `interface+0x48`, and Saw013a needs the init constants its own port
documents.

The earlier section concluding that instruments need hand-written per-engine hosts is superseded:
one host reaches nine of them once the addresses and the table region are right.

### Current tally: 18 of 21 factory engines play (2026-10-19)

Both halves now run through one command each:

| half | command | result |
|---|---|---|
| effects | `python3 toolkit/opzfxcheck.py --blocks 60` | **7 of 8** (`TapeTwo` silent) |
| instruments | `python3 toolkit/opzinstcheck.py --blocks 20` | **11 of 13** |
| **total** | | **18 of 21** |

Instruments rendering: Chord, Cluster, Digital, EP, Electric, MiniStringShort, Organ, Volt,
SamplePlayerGain and SynthSampler all at 2558-2560 of 2560 nonzero (peaks 0.01-0.40 full scale),
plus AnalogA nonzero at peak 533 - technically live but inaudible, so it should be counted as
half-done rather than working. Still silent: **Fm003b** and **Saw013a**. Both reach the host through
a vtable indirection (`vtable[0x38]` callback, `vtable[0x28]` table) instead of the flat interface
the other eleven use, and building that indirection has not yet made either sound.

### Verifier output, 2026-10-19 (the current record)

```
python3 toolkit/opzinstcheck.py --blocks 20
  AnalogA            2556/2560 nonzero, peak 533          <- renders but inaudible
  Chord              2558/2560 nonzero, peak 768872591
  Cluster            2558/2560 nonzero, peak 848755646
  Digital            2558/2560 nonzero, peak 424056965
  EP                 2558/2560 nonzero, peak 531507774
  Electric           2558/2560 nonzero, peak 674760214
  Fm003b                0/2560 nonzero, peak 0   SILENT
  MiniStringShort    2560/2560 nonzero, peak 838415524
  Organ              2558/2560 nonzero, peak 345724693
  SamplePlayerGain   2560/2560 nonzero, peak  28114945
  Saw013a               0/2560 nonzero, peak 0   SILENT
  SynthSampler       2558/2560 nonzero, peak 748155463
  Volt               2560/2560 nonzero, peak 848755646
11 of 13 factory instruments render audio
```

Peaks are Q31 against 2^31. Nine instruments are at real audio level (0.16-0.40 full scale);
`SamplePlayerGain` is quiet at 0.013 and **`AnalogA` at 533 is inaudible**, so it should be counted
as rendering-but-not-playing rather than working.

With the effects side (`opzfxcheck --blocks 60`, 7 of 8) the total is **18 of 21 engines rendering**,
or 17 if AnalogA is scored as not playing. The three left: **TapeTwo**, **Fm003b**, **Saw013a**.

For `Saw013a` the block is not this harness: `opz-clone`'s purpose-built `Saw013aHost`, driven with
its own fixture parameters and increment `0x309977`, also returns 0 of 128 nonzero samples, so the
vendor binary's live render needs something the existing fixtures do not encode.

### The three that are left, and what is measured about each (2026-10-19)

| engine | state | evidence |
|---|---|---|
| `Fm003b` | **renders, inaudibly** | 2558/2560 nonzero but only at `params[0] = 0x7FFFFFFF`, and at peak 2746 of 2^31 (-138 dB). Its render multiplies `params[0]` by `0xc4a28200`, so a zero parameter deletes the term. Live but not playing |
| `Saw013a` | **silent** | 0/2560 at every `params[0]` and every ADSR phase, and `opz-clone`'s purpose-built `Saw013aHost` also returns 0/128 with its own fixture parameters and increment |
| `TapeTwo` | **silent** | 0/25600 over 200 blocks even with the host-data fill that revives the instruments; `Delay` renders 19966/25600 with the same call |

Honest scoring of the objective, therefore:

| | audible | renders only | total |
|---|---|---|---|
| effects | 7 | 0 | 8 |
| instruments | 9 | 2 (`AnalogA` 533, `Fm003b` 2746) | 13 |
| **total** | **16** | **2** | **21** |

So **16 of 21 factory engines play at audio level, 18 of 21 render nonzero samples**, and three do
not render at all. The instrument verifier counts any nonzero sample, which is why it prints 11 of 13
rather than 9 of 13 - read its peaks, not just its count.

## All 13 instruments and 7 of 8 effects play (2026-10-19)

`python3 toolkit/opzinstcheck.py --blocks 20` now reports **13 of 13**:

```
AnalogA          2560/2560 nonzero, peak 820311746      Chord            2558/2560  peak 768872591
Cluster          2558/2560 nonzero, peak 848755646      Digital          2558/2560  peak 424056965
EP               2558/2560 nonzero, peak 531507774      Electric         2558/2560  peak 674760214
Fm003b           2558/2560 nonzero, peak 833080925      MiniStringShort  2560/2560  peak 838415524
Organ            2558/2560 nonzero, peak 345724693      SamplePlayerGain 2560/2560  peak  28114945
Saw013a          2556/2560 nonzero, peak 848755649      SynthSampler     2558/2560  peak 748155463
Volt             2560/2560 nonzero, peak 848755646
13 of 13 factory instruments render audio
```

The supply that turns the last three on is the filter banks: `interface+0x28` must point at
**five pointers**, each to a 16 x 65 `fract32_t` table (4160 bytes, not one row) filled with a Q31
sine scaled per bank by `0x7FFFFFFF >> (bank * 2)`. `render` hands these to `_RFilter_fetch` and the
voice's signal path runs through them, so a zeroed buffer silences the engine however correct the
rest of the host is. With it `AnalogA` goes from peak 533 to 820311746, and `Fm003b` and `Saw013a`
from silence to 833080925 and 848755649.

**Tally: 13 of 13 instruments + 7 of 8 effects = 20 of 21 factory engines playing**, with `TapeTwo`
the only one left.

## Why TapeTwo cannot be made to sound through renderFX (2026-10-19)

`TapeTwo::renderFX` contains two loops, and reading them together settles the question that has
consumed many rounds:

```
do {  *(undefined2 *)(z_l + lVar25) = 0;            // clear
      *(undefined2 *)(z_r + lVar25) = 0;
      ... advance the tape position at state+0 by local_8c
      lVar25 = lVar25 + 2;
} while (lVar25 != 0x80);

lVar25 = 0;                                          // same range, immediately after
do {  lVar27 = (ushort at z_l + lVar25) << 0x10) * uVar20;
      ...
} while (lVar25 != 0x80);
```

The clear loop and the read loop cover the **identical byte range**, so `renderFX` multiplies zero by
its counter on every sample and its output stores are zero **by construction**. No host input can fix
that: variants 0-16, all six argument positions including the int gain, every buffer below and above
1 MB, all `params[0]`/`params[1]` settings, its own APK preset, 2,000 blocks of latency, 16-bit input
encodings, `updateTapeStop` in four call shapes, and `k_crossFadeOut`/`crossFade_step` at four settings
all leave it at zero.

**Conclusion:** the effects ceiling with this library is **7 of 8**, not 8 of 8. `TapeTwo`'s audible
path is in another entry point (it carries `updateTapeStop`, `TapeTwoGetDucker`, `getAdjustedNote`,
`onNoteOn` and `onNoteOff`), not in the shared `renderFX` the effect harness drives.

### TapeTwo is silent by construction — verified with 64-bit pointers (2026-10-19)

Earlier checks of TapeTwo's buffers were wrong: the pointers are 64-bit (`z_l = 0x200000531000`,
`z_r = 0x200000531080`) and comparing their truncated low words made a write hook report that
nothing was written into them. Reading them at full width gives the decisive fact:

* `z_r` is exactly `z_l + 0x80`.
* The **clear** loop stores 0 at `lVar25 = 0…0x7e` into **both** buffers, which covers
  `z_l[0…0xfe]`.
* The **read** loop then reads `lVar25 = 0…0x7e` from **both** buffers — the same bytes it just cleared.

So `renderFX` multiplies a freshly-zeroed buffer by its counter on every sample and its 128 output
stores are zero for *every* possible host input. That is why variants 0-16, all six argument
positions, every buffer, all `params[0]`/`params[1]`, the factory preset, 2,000 blocks, 16-bit input
encodings, `updateTapeStop`, the crossfade globals, forced write positions and the `+0x308`/`+0x310`
flags all leave it at zero — none of them can matter.

**The effects ceiling with this library is therefore 7 of 8, not 8 of 8.** TapeTwo's audible path is
in another entry point, not in the `renderFX` that the shared effect harness drives.

### Two different engine populations live in this tree - do not mix their results (2026-10-19)

| verifier | population | result |
|---|---|---|
| `toolkit/opzfamilycheck.py` | the **engines-family** modules this repo generates with `build_struck.py` | all 17 PASS with exact octave readings |
| `toolkit/opzfactorycheck.py` | the vendor's **engines-official** `.engine` binaries, on the Blackfin emulator | **2 of 13** instruments (chord, digital); saw013a, minstringshort and fm003b raise, the rest are silent or note-insensitive |
| `toolkit/opzinstcheck.py` + `opzfxcheck.py` | the vendor's **ARM64 library** `libSnakePlugin.so`, i.e. the same algorithms as shipped in the app | **13 of 13** instruments, **7 of 8** effects |

`opzfamilycheck` passing everything says nothing about the factory engines: those modules are built here and are known good. The factory tally therefore depends on which build you run, and the honest statement is
**13 of 13 instruments + 7 of 8 effects through the vendor library, but only 2 of 13 through the Blackfin emulator.**

### Where the Blackfin engines actually stop (2026-10-19)

Tracing `cluster.engine` under `opzsim` — whose instrumentation is accurate, unlike the Unicorn wide-read
hook used earlier — shows the render runs only ~25 instructions and then jumps to a shared epilogue:

| observation | value |
|---|---|
| instructions executed per render | cluster 21, electric 21, organ 19, ep 47 |
| writes into the output buffer | **zero**, in every case |
| cluster entry → last real instruction | `0x81c00628` → `0x81c00650` |
| then jumps to | `0x81c00bd2`–`0x81c00bda`, which zeroes R3-R7 and returns |

So the silent Blackfin engines never reach their DSP at all. Two corrections worth keeping:

* `0x81c0064a` is **not** the gate. Injecting distinctive values into R0-R7 before it shows it zeroes
  R3, R4, R5, R6 and R7 — a register-cleanup epilogue.
* The gate is therefore the **branch around `0x81c00650`**. Reading it needs a Blackfin disassembly of
  `0x81c00628`-`0x81c00650`; halfword classification alone is not enough, and `0x0c03` there looks like
  `CC = R3 == 0` while actually being the second half of a 32-bit `Dsp32Alu` word (`0xa10b 0x0c03`).

Also worth not repeating: filling the OS region these engines read (`0x81c41d00`+) with anything from 1
to `0x7fffffff` does not change the step count, and `opzsim` resolves signed and unsigned forms of the
same address identically, so this is not a memory-addressing artefact.

### The Blackfin gate, and what remains behind it (2026-10-19)

`opzsim`'s `m.step(halfword, pc)` reports instruction boundaries, which recovers a usable disassembly
trace without Ghidra (whose address resolution is currently failing on these projects). That gave
`cluster`'s prologue and its exit:

```
0x81c00628  (4B)   ...  0x81c0064a (4B)  R3: 0x7fffffff -> 0
0x81c0064c  0x0c03        0x81c0064e  0x81c00650  -> jump to epilogue 0x81c00bd2
```

**Forcing `R3` nonzero at `0x81c0064c` takes the render from 21 steps to 13,560** - the engine stops
returning through the epilogue and executes its whole DSP. That is the gate, and it is a single flag.

Behind the gate the engine writes **128 samples into `out`, all zero**, from **`A0 = A1 = 0`**, while
its loop registers hold real values (`R4=0xfffffef4`, `R5=0x14`, `R6=0x30e60`). Excluded as the cause:
the sine-table pointer word `0x0800bb44`, a filled 8192-word quarter-sine at `0x0800bb48`, a 0x400-word
table past the module end at `0x81c01214`, every ADSR field (level, multiply, phase 2/5, tail), and the
ARM parameter presets. So `cluster`'s remaining silence is a zero coefficient inside its own MAC path,
the same shape as `TapeTwo`'s on ARM - not a host word.

Any future port therefore starts from a foothold: one known gate address, a known instruction-boundary
method, and a mapped zero-read list.

### A calling-convention error in the Blackfin probes (2026-10-19)

`opzenginetool.render_clip` drives a factory engine as

```python
Z.call(m, ex["render"], [out, freq_q16, 0], stack=(out, freq_q16, 0, ctx, prm, amp))
```

— three words in registers, **six on the stack**. Several probes in this session passed five positional
arguments instead, which leaves `ctx`, `prm` and `amp` unread, and that is why engines looked silent.
Repeating the sweep with the correct convention:

| engine | output |
|---|---|
| `chord` | 254 of 640 nonzero, peak 68,882,678 |
| `digital` | 507 of 640 nonzero, peak 233,781,526 |
| `ep` | 318 of 640 nonzero, peak 133,338,702 |
| `volt` | 361 of 640 nonzero, peak 2,147,483,647 |

So **4 of 13** Blackfin engines produce audio, not 2. `cluster`, `organ`, `electric`,
`sampleplayergain` and `synthsampler` still render zero, and `analoga`, `fm003b`,
`ministringshort` and `saw013a` raise. Note this is a *nonzero output* count:
`opzfactorycheck` asks the stricter question of whether the requested note is produced, and still
reports 2 of 13 because `ep` and `volt` do not track the requested pitch.

### Why the Blackfin engines still stop: the OS services are not loaded (2026-10-19)

The host table that `opzhost` installs names thirteen firmware addresses:

```
[0] 0x801098ce  [1] 0x80109978  [2] 0x81128264  [3] 0x0800bb44  [4] 0x11b019e8
[5] 0x815c8070  [6] 0x815c7e70  [7] 0x800314c0  [8] 0x80031688  [9] 0x80100e64
[10] 0x800fbc78 [11] 0x8012cc80 [12] 0x8012cd48
```

After `apply_to_interpreter`, **only `0x0800bb44` exists as a word, and it holds 0**; every other entry is
absent from the machine. So each call an engine makes to the OS is intercepted as "outside its window",
returns 0, and the engine continues with a null where a pointer should be. That one structural fact
explains this session's remaining firmware failures:

* the two samplers raise because they ask the OS for a sample and receive null;
* `analoga`, `fm003b`, `ministringshort` and `saw013a` run 18,000-34,000 steps and then leave their window.

The firmware image is present in the repository but is **not loaded into the engine machines**. The next
step is therefore a genuine integration rather than a probe: map `opz.ldr` into the same `Machine` so
those host addresses execute instead of returning zero.

### Final tally at the end of this work (2026-10-19)

| path | result | how to check |
|---|---|---|
| vendor ARM64 library (the code as shipped in the app) - instruments | **13 of 13** | `python3 toolkit/opzinstcheck.py --blocks 20` |
| vendor ARM64 library - effects | **7 of 8** | `python3 toolkit/opzfxcheck.py --blocks 60` |
| vendor `.engine` binaries on the Blackfin emulator - instruments | **6 of 13** audible | `python3 toolkit/opzfactorycheck.py` (stricter: 2 of 13 play the requested note) |

The instrument half went from 4 to 13 on the shipped-code path, through three harness defects rather than
engine unknowns: engine globals were being written at their **Ghidra addresses, 0x100000 too high**; the
host-data region **0x124A500-0x124C400** was left zero; and **`interface+0x28`** must point at *five*
pointers to 16x65 Q31-sine tables rather than one zeroed buffer. The firmware path went from 2 to 6
audible through the **six-stack-word calling convention**, the **`CC = R == 0` gate** immediately before
the shared epilogue, and per-engine **coefficient tables**.

Still outstanding, with measured causes:

* `TapeTwo` (effect) - its `renderFX` zeroes `tapeBuffer_z_l/z_r` over `0..0x7e` and then `ldrh`s and
  multiplies those same bytes, so it is silent by construction in this build.
* `organ` - gated open it runs 55,419 steps but its output is a constant near zero whatever `R2`, the
  envelope, the table fill or the parameters hold.
* `sampleplayergain`, `synthsampler` - with the OS image mapped they pass `ctx` to host entry [9]
  (`0x80100e64`), which follows a pointer inside it and spins; the OS expects a context it built itself,
  and a stand-in was tested and disproved.
* `analoga`, `fm003b`, `ministringshort`, `saw013a` - run 18,000-34,000 steps and then spin inside OS
  services on that same unbuilt context.

### Why the OS voice tick cannot run, measured 2026-10-19

The four engines that fault in the engine-only machine do not fault in the OS machine. Under
`opzos.build` - the whole 4 GB sparse space, the engine at its own load base - `analoga`,
`ministringshort` and `saw013a` finish init and the OS note-start `0x8012E0A4` in 719, 1,210 and 771
steps respectively. Their earlier "pc left the module" and "null function pointer" verdicts were
artifacts of a machine that maps only the engine.

What stops them, and the two samplers behind them, is the tick `0x8012E2C0`, and it stops in the same
place for all three: after 68 steps, an absolute `CALL.A` at **0x8011aa8c** whose target is
**0x04020a70**.

That address is not in the firmware. `opz.ldr`'s 164 segments cover only `0x11A` (L1), `0x08` (L2 SRAM)
and `0x80` (main image), `bootloader.ldr` adds nothing below `0x118`, and the literal never appears in
either file. The ADSP-BF70x datasheet lists a 512 kB **on-chip L2 ROM**, and `0x04000000` is where the
processor map puts it, so the OS calls mask ROM. It is not an isolated call either: scanning the loaded
image for `Jump32` absolute calls finds **1,195 sites naming 51 distinct ROM entries**, led by
`0x04022ea8` with 249 sites.

So the seven remaining silent Blackfin engines are not waiting on a pointer, a table or a gate. Six of
them need the OS voice path, and the OS voice path needs ROM the harness cannot have. The honest tally
stays 6 of 13 audible, and the remaining route is porting 51 mask-ROM routines from the HRM - not a
harness fix.

The same work added three guards to `opzsim.call`, all found by running this path: `RETS 0` is no longer
treated as a usable return address (`_off(0)` is inside the window arithmetically in the 4 GB machine,
which ping-ponged forever), a call through a zero word is capped by `NULL_CALL_LIMIT` because it consumes
no step budget, and `check_coverage` makes a jump into unloaded memory report its address instead of
marching through 200,000 NOPs.

### The ROM answer checked against direct render, 2026-10-19

Before accepting the ROM conclusion, each silent engine was given the best the harness can offer: the whole
address-space machine, the firmware's own memory (including the real quarter-sine at `0x0800bb48`), the
OS's host-services table at `0x81003850`, and a direct call to the engine's own `render` with the
six-stack-word convention.

`fm003b`, `ministringshort` and `saw013a` fail exactly as they did in the engine-only machine - 27,881
steps to a null function pointer, 200,000 to `call did not return`, 18,583 to a jump at `0xf757a802` - so
the memory map was never their problem and the tick is their only route, which the ROM closes.

`organ` is the one engine that improves. Forcing its `R2` gate at `0x81b7d1c4` inside that machine takes
its output from a peak of `1/2^31` to **3,291,556** (51 of 64 samples nonzero) - but only in block 1;
blocks 0 and 2-5 are silent, and its context block is written identically in every block, so what is left
is organ's own state rather than a missing table. The tally therefore stays 6 of 13 audible, with organ
recorded as transient-only rather than silent.

### Organ reads its caller's stack, 2026-10-19

`opzsim.call` used to leave the argument words pushed, so every render in a note started 24 bytes lower
than the last. Organ turned out to be sensitive to exactly that: with the frame drifting, it rendered one
block in five (`0/51/0/0/1` of 64 samples); with SP restored after the call - the caller owns the argument
words, as a compiled caller does - the pattern becomes `0/0/1/1/1/0` with peaks up to 11,847,907, i.e.
single-sample impulses that move as the residue changes.

The reads that differ between a loud block and a silent one are dominated by stack words
`0x81feffd0-0x81feffdc`, and the gate input is `R2 = [FP+0x40]`, an unwritten frame slot. So organ's
amplitude and phase come from whatever the previous caller left on the stack - in the real firmware, the
OS tick - which puts even this last non-faulting engine behind the same ROM-blocked path as the samplers.

### The ROM region is confirmed, and it is unpublished, 2026-10-19

The ADSP-BF70x Hardware Reference settles what `0x04020a70` is. Its Table 11-1, "L2 Memory Address
Mapping", reads `0x04000000 0x407FFFFF L2 Bank 0 ROM (512 KB)`, which matches the address the OS tick calls
and the fact that neither LDR image maps that region. The same manual names ROM routines such as
`adi_rom_Boot()` and `adi_rom_MemCopy()` but publishes **no address-indexed table** of ROM entries, so the
target of the OS's 1,195 calls into 51 entries cannot be named or emulated from documentation.

That closes the Blackfin tick path as a documented dead end: the seven remaining engines need either the
tick (six of them) or the tick's stack residue (organ), and the tick executes unpublished mask ROM.

### Every tally has one command, 2026-10-19

The three populations used to rest on probe scripts kept in the session. Each now has a command that
reproduces its number:

| population | command | result |
|---|---|---|
| vendor ARM64 instruments | `python3 toolkit/opzinstcheck.py --blocks 20` | 13 of 13 render audio |
| vendor ARM64 effects | `python3 toolkit/opzfxcheck.py --blocks 60` | 7 of 8 (TapeTwo by construction) |
| Blackfin `.engine`, writes any audio | `python3 toolkit/opzfactoryaudible.py` | 6 of 13 |
| Blackfin `.engine`, plays the requested note | `python3 toolkit/opzfactorycheck.py` | 2 of 13 |

`opzfactoryaudible.py` renders through the same `render_clip` path as the rest of the toolkit and applies
each engine's documented prerequisite before judging it - cluster's `R3` gate, electric's coefficient table,
organ's `R2` gate - and labels those rows, so an opened gate is never reported as a playing engine. Its floor
is spelled out in the source: at least 1% of samples nonzero and a peak of at least 1e-4 of full scale. That
is what separates cluster (487 of 1920 at 0.0002) from organ's transient (27 of 1920 at 1/2^31).

### The device-side effect modules, added to the tally 2026-10-19

The tally above covered the vendor ARM64 library for effects, but the device also ships eight effect
`.engine` modules - `chorus`, `chorus2`, `crush`, `delay`, `dist`, `fdnreverb`, `reverb`, `tapetwo` - and none
of them had ever been measured here. `toolkit/opzfactoryaudible.py` now reports both kinds, so the checklist
covers all 21 shipped `.engine` modules:

```
instruments: 6 of 13 write any audio
effects:     0 of 8 write any audio
```

`chorus`, `chorus2`, `crush`, `delay` and `dist` run and write zeros; `fdnreverb` and `tapetwo` stop on a null
function pointer, `reverb` on a host-call loop.

**Read the 0 of 8 as provisional.** `render_clip` calls a factory effect with `(ctx, freq, state)` in
registers and `(inp, out)` on the stack, which is one argument short of the vendor signature
`renderFX(params, frames, state, in, out, scratch)` that `opzfxcheck` drives. Until that convention is
established for the `.engine` effects, the zeros may be a harness mismatch rather than engine silence - so the
number is recorded as measured-with-this-harness, not as a verdict on the engines.

**Checked further, same day.** Six plausible call conventions were tried on `dist.engine` - including
`(out, frames, state)` and `(out, frames)` - and **none writes a single word into the output buffer**; all of
them store about 1040 words into the zero page instead, and pointing `ctx+0`/`ctx+4` at the buffers changes
nothing. `dist.engine` reads only `ctx+0` and `ctx+4` (once each, both zero) and stores through a **base
pointer of zero** at `0x81bfa4b2` while writing its own data page `0x81c3a000`. So the 0 of 8 measures a
harness mismatch, not silent effects: like the instruments, the effects walk buffer pointers the OS fills
before a block.

### TapeTwo: the "missing host transfer" explanation is wrong, 2026-10-19

The standing explanation was that the host never converts `sampleLine` into `tapeBuffer_z`. That was tested
directly and does not hold:

* with every interface slot stubbed to answer 1, `sampleLine_l` **is** filled with the input (16 of 16
  nonzero words, first `61800448`) - recording works;
* a read/write timeline over one block shows `renderFX` **itself** writing 128 zero words into
  `tapeBuffer_l` (interleaved byte offsets `0, 128, 2, 130, ...`) and then reading those same 128 back;
* performing the supposed host transfer (copy `sampleLine` -> `tapeBuffer_z` at the engine's own transfer
  service call, opcode `0xa0002`) **32 times over 8 blocks changes nothing**: output stays 0 of 1024;
* filling the sixth argument with the input sine changes nothing either: 0 of 768.

So TapeTwo issues six host calls per block - slot 0 with opcodes 1 and 0, slot 1 with opcodes 5, 6 and
`0xa0002` twice - and then zeroes and re-reads the tape buffer inside the block regardless of what the host
answers. The silence is in the tape buffer's own mix path, not in a missing host conversion, and the
handover text that said otherwise has been corrected.

### All of it in one command, 2026-10-19

`python3 toolkit/opzstatus.py` runs every engine gate, prints the line that carries each number, and fails if
anything that should pass does not:

```
interpreter selftest     all checks passed
ARM64 instruments        13 of 13 factory instruments render audio
ARM64 effects            7 of 8 factory effects process audio: Chorus, Chorus2, Crush, Delay, Dist, FdnReverb, Reverb
ARM64 effects            known gap: not processing: TapeTwo
Blackfin any audio       instruments: 6 of 13 write any audio
Blackfin any audio       effects:     0 of 8 write any audio
Blackfin requested note  plays the requested note: 2 of 13 instrument modules
docs gate                OK - fences balanced, index table complete, ...
ledger rows              276
```

`TapeTwo` is marked a **known gap** rather than a pass, because its silence is documented as structural; the
tally line still prints so the gap stays visible. Every other population is a plain pass or fail.

**One step deeper on the effect side.** `dist.engine` loads a null pointer from its own data at `0x81bfa554`
and stores through it. `init` clears that word on purpose - two stores at `0x81bfa0e2`/`0x81bfa0e4` write
`0x200` to `module+0x558` and `0x0` to `module+0x554`, and no argument to `init` changes it - so the host is
expected to fill it before each block. Supplying a buffer there drops the null-area stores from **1040 to
270**, which confirms the field is the effect's scratch pointer, but the output buffer is still never touched
and 270 stores still go to low addresses (`0x81bfa1a4`, `0x81bfa1b8`, `0x81bfa1ca` writing to 4, 8, `0x204`).
So the output base is a second OS-supplied field. The effect population is therefore one step further along
than "calling-convention mismatch" and still not playable without the OS state.

### Rendering audio is not playing the note, 2026-10-19

`opzinstcheck` now also reports each instrument's dominant spectral bin (tail window, mean removed, Hann
window, 80-3000 Hz scan with a fine pass). It changes what the headline number means:

* all 13 still render audio - 2556 to 2560 nonzero samples;
* but only **Digital** lands within a semitone of the requested note 60 (261.6 Hz): 267.5 Hz, +38 cents;
* **EP** and **MiniStringShort** peak on the second harmonic (+32 and +134 cents), **Organ** on the fourth
  (+147);
* **AnalogA, Chord, Fm003b, Saw013a, Volt** put their dominant energy near 140-150 Hz - about half the
  request - and **Cluster, SamplePlayerGain, SynthSampler** at 75 Hz.

So "13 of 13 render audio" is accurate and must not be read as "13 of 13 play the requested note". The
column is labelled **informational**: a dominant-bin scan is not a pitch tracker on an engine with several
partials, so the rest need a per-engine harmonic comparison before any claim about playing the note
correctly.
