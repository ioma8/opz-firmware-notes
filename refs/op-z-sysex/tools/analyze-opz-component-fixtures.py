#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import welch


def midi_notes(root: Path, name: str, pitch: int | None = None) -> list[dict]:
    notes = []
    with (root / f"{name}-midi.jsonl").open() as source:
        for line in source:
            event = json.loads(line)
            if (
                event["kind"] == "midi"
                and 0x90 <= event["status"] < 0xA0
                and len(event["data"]) == 2
                and event["data"][1] > 0
                and (pitch is None or event["data"][0] == pitch)
            ):
                notes.append(
                    {
                        "time_ms": event["t_ms"],
                        "pitch": event["data"][0],
                        "velocity": event["data"][1],
                    }
                )
    return notes


def audio(root: Path, name: str) -> tuple[np.ndarray, int]:
    samples, sample_rate = sf.read(root / f"{name}.wav", always_2d=True)
    return samples.mean(axis=1), sample_rate


def spectral_metrics(samples: np.ndarray, sample_rate: int) -> dict:
    frequencies, power = welch(
        samples,
        sample_rate,
        nperseg=min(2048, len(samples)),
    )
    return {
        "rms": round(float(np.sqrt(np.mean(samples * samples))), 6),
        "centroid_hz": round(
            float(np.sum(frequencies * power) / max(np.sum(power), 1e-30)),
            1,
        ),
    }


def onset_metrics(root: Path, name: str) -> list[dict]:
    samples, sample_rate = audio(root, name)
    rows = []
    for note in midi_notes(root, name):
        start = int((note["time_ms"] / 1000 + 0.005) * sample_rate)
        end = int((note["time_ms"] / 1000 + 0.080) * sample_rate)
        rows.append({"time_ms": note["time_ms"], **spectral_metrics(samples[start:end], sample_rate)})
    return rows


def group_sizes(notes: list[dict], maximum_gap_ms: int = 150) -> list[int]:
    groups: list[list[dict]] = []
    for note in notes:
        if not groups or note["time_ms"] - groups[-1][-1]["time_ms"] > maximum_gap_ms:
            groups.append([note])
        else:
            groups[-1].append(note)
    return [len(group) for group in groups]


def sweep_curve(root: Path, name: str) -> list[float]:
    samples, sample_rate = audio(root, name)
    offsets = [0.02, 0.10, 0.20, 0.32]
    curves = []
    for note in midi_notes(root, name):
        values = []
        time = note["time_ms"] / 1000
        for offset in offsets:
            start = int((time + offset) * sample_rate)
            end = int((time + offset + 0.05) * sample_rate)
            values.append(spectral_metrics(samples[start:end], sample_rate)["centroid_hz"])
        curves.append(values)
    return np.median(curves, axis=0).round(1).tolist()


def glide_curve(root: Path, name: str) -> list[float]:
    samples, sample_rate = audio(root, name)
    curves = []
    for note in midi_notes(root, name, pitch=72):
        time = note["time_ms"] / 1000
        segment = samples[
            int((time - 0.03) * sample_rate) : int((time + 0.25) * sample_rate)
        ]
        curves.append(
            librosa.yin(
                segment,
                fmin=70,
                fmax=900,
                sr=sample_rate,
                frame_length=2048,
                hop_length=128,
            )
        )
    median = np.nanmedian(np.stack(curves), axis=0)
    times = librosa.frames_to_time(
        np.arange(len(median)),
        sr=sample_rate,
        hop_length=128,
    ) - 0.03
    return [
        round(float(median[np.argmin(np.abs(times - target))]), 1)
        for target in [0, 0.02, 0.05, 0.10, 0.15, 0.20]
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def readback_manifest(root: Path) -> dict:
    cases = {}
    suffix = "-expected-bank.bin"
    for expected_path in sorted(root.glob(f"*{suffix}")):
        name = expected_path.name.removesuffix(suffix)
        readback_path = root / f"{name}-readback-bank.bin"
        expected_hash = sha256(expected_path)
        readback_hash = sha256(readback_path)
        cases[name] = {
            "expected_sha256": expected_hash,
            "readback_sha256": readback_hash,
            "exact_match": expected_hash == readback_hash,
        }
    return cases


def capture_manifest(root: Path) -> dict:
    captures = {}
    suffix = "-midi.jsonl"
    for midi_path in sorted(root.glob(f"*{suffix}")):
        name = midi_path.name.removesuffix(suffix)
        captures[name] = {
            "midi_sha256": sha256(midi_path),
            "audio_sha256": sha256(root / f"{name}.wav"),
        }
    return captures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_directory", type=Path)
    parser.add_argument("--reset-directory", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    root = arguments.artifact_directory

    multiply_control = midi_notes(root, "component-spark-multiply-control")
    multiply_spark = midi_notes(root, "component-spark-multiply-pass-2")
    trigger = midi_notes(root, "trigger-spark-pass-2")
    reset_root = arguments.reset_directory or root
    trigger_reset = midi_notes(reset_root, "trigger-spark-pass-2-reset")

    summary = {
        "bank_sha256": {
            "before": sha256(root / "before-bank.bin"),
            "restored": sha256(root / "restored-bank.bin"),
            "exact_restoration": (
                sha256(root / "before-bank.bin")
                == sha256(root / "restored-bank.bin")
            ),
        },
        "readback_cases": {
            **readback_manifest(root),
            **readback_manifest(reset_root),
        },
        "capture_sha256": {
            **capture_manifest(root),
            **capture_manifest(reset_root),
        },
        "parameter_spark": {
            "control_onsets": onset_metrics(root, "parameter-spark-filter-control"),
            "pass_2_onsets": onset_metrics(root, "parameter-spark-filter-pass-2"),
        },
        "component_spark": {
            "multiply_control_group_sizes": group_sizes(multiply_control),
            "multiply_pass_2_group_sizes": group_sizes(multiply_spark),
        },
        "trigger_spark": {
            "pass_2_note_times_ms": [note["time_ms"] for note in trigger],
            "separate_reset_step_note_times_ms": [
                note["time_ms"] for note in trigger_reset if note["pitch"] == 60
            ],
            "reset_step_note_ons": [
                note for note in trigger_reset if note["pitch"] == 67
            ],
        },
        "glide": {
            "sample_offsets_ms": [0, 20, 50, 100, 150, 200],
            "control_f0_hz": glide_curve(root, "legato-control"),
            "glide_4_f0_hz": glide_curve(root, "legato-glide-4"),
        },
        "filter_sweep": {
            "sample_offsets_ms": [20, 100, 200, 320],
            "control_centroid_hz": sweep_curve(root, "filter-sweep-control"),
            "filter_up_centroid_hz": sweep_curve(root, "filter-sweep-up"),
        },
    }
    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
