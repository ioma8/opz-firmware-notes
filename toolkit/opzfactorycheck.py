#!/usr/bin/env python3
"""opzfactorycheck.py - do the OP-Z factory engines play the requested note?

Runs each factory module through the app's own render path (`opzenginetool.render_clip`, which knows about the
scaled pitch argument, the amp object and the host memory) and asks a question a harmonic cannot fake:

    energy at the requested frequency must beat both its 0.75x and its 1.5x neighbour

Two measurement traps are handled here, both of which produced false failures before:

  interleaving  `render_clip` returns interleaved L,R. A DFT at f over that array reads it as f/2, so each
                channel is measured separately and the stronger one is used.
  channels      some engines write one channel only - `ep` writes the right channel and nothing on the left -
                so a left-only reader calls them silent.

Two notes is enough to reject a fixed spectrum (an engine whose peak never moves passes one note by luck,
as `electric` does at 330 and 660 Hz) but it OVERSTATES interval engines: `chord` legitimately puts energy a
fifth above the root, so its 0.75x and 1.5x neighbours are its own intervals and the test fails on correct
behaviour. Measured across six pitches, only `digital` is robust (5 of 6); `chord` and `ep` pass 2 of 6.
Read a PASS here as "this engine reaches the requested note at these two notes", not as "it tracks pitch".

Usage:
    python3 toolkit/opzfactorycheck.py            # every instrument module in engines-official
"""
import cmath, math, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzenginetool as T

FS = 48000.0
NOTES = ((57, 220.0), (69, 440.0))
PARAMS = [int(0.5 * (1 << 28))] * 8


def mag(samples, freq):
    n = len(samples)
    if not n:
        return 0.0
    return abs(sum(samples[i] * cmath.exp(-2j * math.pi * freq * i / FS) for i in range(n))) / n


def energy(samples, freq):
    """Stronger of the two channels, measured after de-interleaving."""
    return max(mag(samples[0::2], freq), mag(samples[1::2], freq))


def check(path):
    info = T.describe(path)
    if info["kind"] != "instrument":
        return None, "effect module"
    peak, detail = 0.0, []
    rendered = {}
    for note, target in NOTES:
        samples, _ = T.render_clip(info, note, 0.8, PARAMS)
        rendered[note] = (samples, target)
        peak = max(peak, max((abs(v) for v in samples), default=0) / 2 ** 31)
        at = energy(samples, target)
        near = max(energy(samples, target * 0.75), energy(samples, target * 1.5))
        if at <= near or at <= 1e-6:
            return False, f"{target:.0f} Hz: energy {at:.1e} vs neighbours {near:.1e}"
        detail.append(f"{target:.0f} Hz ok ({at:.1e} vs {near:.1e})")
    if peak <= 1e-3:
        return False, "silent"
    # Pitch dependence: a fixed-spectrum engine passes a two-note energy test by coincidence - `ep` does
    # exactly that, producing the same contrast at every pitch argument. Require that the tone at note A's
    # frequency is markedly stronger in note A's render than in note B's.
    (a_samples, a_target), (b_samples, _) = (rendered[n] for n in sorted(rendered))
    here, there = energy(a_samples, a_target), energy(b_samples, a_target)
    if there and here < 1.5 * there:
        return False, (f"does not depend on the note: {a_target:.0f} Hz energy is {here:.1e} when requested "
                       f"and {there:.1e} when a different note is")
    return True, "; ".join(detail)


def main(argv):
    root = pathlib.Path(argv[0] if argv else "engines-official")
    playing, audible, failing = [], [], []
    for path in sorted(root.glob("*.engine")):
        try:
            ok, why = check(path)
        except Exception as e:                                 # noqa: BLE001 - report, never abort
            print(f"  {path.stem:20s} ERROR  {type(e).__name__}: {str(e)[:60]}")
            failing.append(path.stem)
            continue
        if ok is None:
            continue
        print(f"  {path.stem:20s} {'PLAYS' if ok else 'no   '}  {why}")
        (playing if ok else failing).append(path.stem)
    print(f"\n  plays the requested note: {len(playing)} of {len(playing) + len(failing)} instrument modules")
    if playing:
        print("   ", ", ".join(playing))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
