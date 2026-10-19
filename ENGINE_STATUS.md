# Factory engine status — one page

**The goal "all factory engines play correctly" is not met.** This page is the shortest accurate statement of
what is verified, what is not, and why.

## Verified today

| population | command | result |
|---|---|---|
| vendor ARM64 instruments, emit audio | `python3 toolkit/opzinstcheck.py --blocks 20` | **13 of 13** |
| vendor ARM64 instruments, play the requested note | `python3 toolkit/opzinstcheck.py --blocks 140 --note-check` | **11 of 13** at note 60 |
| … same, at notes 57 and 72 | `… --note 57` / `--note 72` | 9 of 13 / 10 of 13 |
| vendor ARM64 effects, process audio | `python3 toolkit/opzfxcheck.py --blocks 60` | **7 of 8** (`TapeTwo` silent) |
| device `.engine` instruments, emit audio | `python3 toolkit/opzfactoryaudible.py` | **5 of 13** (`analoga`, `electric`, `ep`, `organ`, `volt`) |
| device `.engine` effects, emit audio | `python3 toolkit/opzfactoryaudible.py` | **0 of 8** (harness-limited) |
| device `.engine` instruments, play the requested note | `python3 toolkit/opzfactorycheck.py` | **0 of 13** (the OSC-populated state above is what decides it) |
| everything above plus docs | `python3 toolkit/opzstatus.py --full` | all gates pass |

"Emits audio" is the weak criterion. "Plays the requested note" is the one that matches the goal, and it is
**9 of 13** across three tested pitches.

The device-instrument figure moved from 6 of 13 to 5 of 13 and the *set* changed when `opzsim` stopped
mis-executing two instruction classes (see the ledger rows for `LdStIIFP` and the 16-bit `LdStII` forms): the
old count included engines whose audio came out of reads from the wrong address, so the earlier figure was
partly an artifact. `analoga` moved the other way, from "keeps calling outside its window" to audible.

## Writing a new engine

Two layers, and the interesting one is the top. `toolkit/opzsynth.py` describes a **sound**, not code:

```python
K.build("cathedral", slot=74,
        partials=[(0.5, None), (1.0, None), (2.0, None), (3.0, None), (4.0, None), (6.0, None)],
        levels=[0.085, 0.145, 0.105, 0.070, 0.050, 0.035],
        gain="envelope*velocity",
        pitch="blend")
```

That is the whole cathedral engine (34 lines with its docstring): six undamped pipe ranks, pitch blended
between semitone rows, loudness from the OS envelope times the amp object's voice gain. Partials carry
their own decay time, `knob()` turns a preset knob into an eight-bucket decay control, `banks=` plus
`detune_cents=` splits a bank detuned and panned for ensemble width, and the voice machinery - the amp gate,
the strike, the zero/out-of-range pitch guard, the frame loop, the module header - is generated and
inherited. It refuses to build an engine whose seeds can clip, whose partials are all past Nyquist, or that
needs more state than the context layout documents.

The three authored engines are now declarations of this shape: `build_marimba.py` (46 lines),
`build_cathedral.py` (34), `build_strings.py` (36).

`toolkit/opzsdk.py` is the layer underneath, for DSP that is not a bank of rotators (a filter, FM, a sample
player): statements, registers, frame slots, branches and table symbols, compiled to this chip's
instructions with no assembly and no allocator to get wrong. It is the same DSL the generator emits, so the
two compose. `toolkit/opzsdktest.py` exercises every construct of both layers and checks the results in the
interpreter, so a change to either is gated the same way the engines are.

## What is not working, and where it is stuck

| gap | bounded to | evidence |
|---|---|---|
| `TapeTwo` (effect) | the tape-buffer mix inside `renderFX` | every caller-side cause excluded: readiness answer, host `sampleLine→tapeBuffer` transfer, scratch pointer, dispatch variant, sixth ("gain") argument, all eight exports |
| `Cluster` (instrument) | its band-add path (not judgeable by a pitched test) | output energy is invariant to the render increment, the note argument, `onNoteOn`'s note, `params[0..2]` and the record fields; the request-to-neighbour ratio is a constant ~0.59 at notes 40/48/55/65, i.e. it adds band content rather than a pitched tone, so the note test cannot judge it |
| 7 device instruments (`analoga`, `fm003b`, `ministringshort`, `saw013a`, `organ`, `SamplePlayerGain`, `SynthSampler`) | the OS per-voice tick | the tick does `CALL.A 0x04020a70` after 68 steps = ADSP-BF70x **L2 Bank 0 mask ROM** (0x04000000, 512 kB). `opz.ldr` maps only 0x11A / 0x08 / 0x80; 1,195 call sites name 51 ROM entries; the manual publishes no address table |
| 8 device effects | OS-populated buffer state | `dist` takes its scratch pointer from `module+0x554` (zeroed by `init`) and its output buffer from another OS-filled field |

Note: `SynthSampler` passes at note 60 (282.61 against 26.11/117.92) with the per-engine sampler host; an
earlier 6.67 reading for it came from a run that gave every sampler the pack host and is superseded. Sweeping
its record's declared pitch over four values does not change the result, so that is not its lever either.

`SamplePlayerGain` is no longer in the "frozen" category: driven with the host the sibling port's golden
fixtures document (2304-frame pack, 24 slices of 96, `slice = note − 36`, descriptor
`{data, 2304, 0x2000, 0x40000000}`) it writes **17920 of 17920** nonzero samples at note 43 and is silent at
note 60 **by design** (slice 24 clamps to 23, whose window runs past the pack). It is a slice/drum engine, so a
pitched test is the wrong instrument for it; `opzinstcheck` judges it at 43 via `DEFAULT_NOTE`.

## The two honest options

1. **Accept this deliverable as scoped**: 13 of 13 factory instruments emit audio, 9 of 13 play the requested
   note at every tested pitch, 7 of 8 factory effects, all reproducible by one command, with every remaining
   gap documented to a specific code site.
2. **Commission the reverse-engineering programme**: the four rows above, i.e. `TapeTwo`'s mix loop, `Cluster`'s
   rate source, 51 routines of unpublished mask ROM (plus the OS voice context), and the OS effect buffer state.

Details and history: `firmware-re-docs/13-factory-engine-status.md` (long form) and `HYPOTHESES.csv`
(307 recorded hypotheses, each with the experiment and verdict).
