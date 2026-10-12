#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


PITCHES = {
    "marker": 48,
    "target": 60,
    "sentinel": 72,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def note_times(path: Path) -> dict[str, list[int]]:
    times = {name: [] for name in PITCHES}
    with path.open() as source:
        for line in source:
            event = json.loads(line)
            if (
                event["kind"] != "midi"
                or not 0x90 <= event["status"] < 0xA0
                or len(event["data"]) != 2
                or event["data"][1] == 0
            ):
                continue
            for name, pitch in PITCHES.items():
                if event["data"][0] == pitch:
                    times[name].append(event["t_ms"])
    return times


def aligned_spreads(rows: list[list[int]]) -> list[int]:
    width = min(map(len, rows))
    return [max(row[index] for row in rows) - min(row[index] for row in rows)
            for index in range(width)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_directory", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    root = arguments.artifact_directory
    manifest = json.loads((root / "manifest.json").read_text())

    trials = {}
    for trial in manifest["trials"]:
        name = trial["trial"]
        times = note_times(root / f"{name}-midi.jsonl")
        intervention_window = [
            value for value in times["target"]
            if trial["intervention_upload_finished_ms"]
            <= value
            < trial["base_upload_started_ms"]
        ]
        post_base = [
            value for value in times["target"]
            if value >= trial["base_upload_finished_ms"]
        ]
        trials[name] = {
            "intervention_value": trial["intervention_value"],
            "marker_times_ms": times["marker"],
            "target_times_ms": times["target"],
            "sentinel_times_ms": times["sentinel"],
            "intervention_window_target_times_ms": intervention_window,
            "post_base_target_times_ms": post_base,
        }

    marker_spreads = aligned_spreads([
        trials[name]["marker_times_ms"] for name in ("no-op", "pass-3", "reset")
    ])
    sentinel_spreads = aligned_spreads([
        trials[name]["sentinel_times_ms"] for name in ("no-op", "pass-3", "reset")
    ])
    post_base_spreads = aligned_spreads([
        trials[name]["post_base_target_times_ms"]
        for name in ("no-op", "pass-3", "reset")
    ])

    offset = manifest["base_to_reset_changed_offsets"][0]
    base = (root / "base-bank.bin").read_bytes()
    pass3 = (root / "pass-3-bank.bin").read_bytes()
    reset = (root / "reset-bank.bin").read_bytes()
    before_hash = sha256(root / "before-bank.bin")
    restored_hash = sha256(root / "restored-bank.bin")

    no_op_before_third_marker = [
        value for value in trials["no-op"]["intervention_window_target_times_ms"]
        if value < trials["no-op"]["marker_times_ms"][2]
    ]
    summary = {
        "bank_sha256": {
            "before": before_hash,
            "restored": restored_hash,
            "exact_restoration": before_hash == restored_hash,
        },
        "single_changed_offset": {
            "absolute": offset,
            "base_raw": base[offset],
            "pass_3_raw": pass3[offset],
            "reset_raw": reset[offset],
        },
        "trials": trials,
        "cross_trial_alignment": {
            "marker_spreads_ms": marker_spreads,
            "maximum_marker_spread_ms": max(marker_spreads),
            "sentinel_spreads_ms": sentinel_spreads,
            "maximum_sentinel_spread_ms": max(sentinel_spreads),
            "post_base_target_spreads_ms": post_base_spreads,
            "maximum_post_base_target_spread_ms": max(post_base_spreads),
        },
        "conclusions": {
            "intervention_value_effect_observed": (
                trials["no-op"]["intervention_window_target_times_ms"]
                != trials["pass-3"]["intervention_window_target_times_ms"]
                and not trials["reset"]["intervention_window_target_times_ms"]
            ),
            "byte_identical_upload_perturbed_target_phase": bool(
                no_op_before_third_marker
            ),
            "untouched_sentinel_remained_aligned": max(sentinel_spreads) <= 25,
            "target_phase_converged_after_base_upload": (
                max(post_base_spreads) <= 25
            ),
            "reset_semantics_isolated": False,
            "boundary": (
                "A full-bank upload perturbs Spark phase even when the target "
                "byte is unchanged, so $09 cannot isolate raw 10 counter-reset "
                "semantics. Use a same-step physical value change without a "
                "pattern upload or reload."
            ),
        },
    }
    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
