#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import welch


def note_on_times(path: Path, note: int = 60) -> list[float]:
    times = []
    with path.open() as source:
        for line in source:
            event = json.loads(line)
            status = event["status"]
            data = event["data"]
            if (
                event["kind"] == "midi"
                and status & 0xF0 == 0x90
                and len(data) == 2
                and data[0] == note
                and data[1] > 0
            ):
                times.append(event["t_ms"] / 1000)
    return times


def analyze_variant(root: Path, name: str) -> None:
    audio, sample_rate = sf.read(root / f"{name}.wav", always_2d=True)
    mono = audio.mean(axis=1)
    times = note_on_times(root / f"{name}-midi.jsonl")
    rows = []
    for time in times:
        start = max(0, int((time + 0.005) * sample_rate))
        end = min(len(mono), int((time + 0.080) * sample_rate))
        window = mono[start:end]
        if not len(window):
            continue
        frequencies, power = welch(
            window,
            sample_rate,
            nperseg=min(2048, len(window)),
        )
        rows.append(
            (
                np.sqrt(np.mean(window * window)),
                np.max(np.abs(window)),
                np.sum(frequencies * power) / max(np.sum(power), 1e-30),
            )
        )
    values = np.asarray(rows)
    if not len(values):
        print(f"{name}: note-ons=0")
        return
    median = np.median(values, axis=0)
    print(
        f"{name}: note-ons={len(times)} "
        f"median-rms={median[0]:.6f} "
        f"median-peak={median[1]:.6f} "
        f"median-centroid-hz={median[2]:.1f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_directory", type=Path)
    parser.add_argument("variants", nargs="*")
    arguments = parser.parse_args()
    variants = arguments.variants or sorted(
        path.stem.removesuffix("-midi")
        for path in arguments.artifact_directory.glob("*-midi.jsonl")
    )
    for variant in variants:
        analyze_variant(arguments.artifact_directory, variant)


if __name__ == "__main__":
    main()
