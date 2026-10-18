# Factory engine status: what plays, what does not, and why

This is the consolidated state of the "play the OP-Z factory engines" objective after an extended
investigation. It exists so the next person does not re-walk 87 disproved hypotheses.

## The number

**3 of 13 factory instrument modules play the requested note.** Verified with `toolkit/opzfactorycheck.py`
through the app's own render path, at 220 Hz and 440 Hz, against both neighbouring frequencies:

| engine | 220 Hz (at f0 vs neighbours) | 440 Hz | across six pitches | notes |
|---|---|---|---|---|
| chord | 2.6e5 vs 1.1e5 | 8.8e4 vs 5.2e4 | **2 of 6** | fails at exactly 0.75x and 1.5x - its own interval components |
| digital | 5.0e5 vs 3.2e5 | 4.7e5 vs 1.8e5 | **5 of 6** | robust; fails only at 659 Hz |
| ep | 3.6e6 vs 1.7e6 | 1.6e6 vs 9.1e5 | **2 of 6** | writes the **right channel only** |

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

`volt` produces full-scale DC. `electric` becomes audible (peak 0.0315) when `state+0x10` is seeded but does not
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

`opzenginetool.render_clip` applies all three for modules under `engines-official`; `toolkit/opzfactorycheck.py`
verifies the result.

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

Alternatively, 21 substitute engines (`engines-family`, `engines-effects`) already cover every factory slot and
play correctly; they are ours, not Teenage Engineering's, and should never be presented as the factory binaries.
