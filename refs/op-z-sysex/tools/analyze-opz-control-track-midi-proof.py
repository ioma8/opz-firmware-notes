#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


TRACKS = [
    (9, "FX 1", 40, 80),
    (10, "FX 2", 41, 81),
    (11, "Tape", 42, 82),
    (12, "Master", 43, 83),
    (13, "Perform", 44, 84),
    (14, "Module", 45, 85),
    (15, "Lights", 46, 86),
    (16, "Motion", 47, 87),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def midi_events(path: Path) -> tuple[list[dict], list[dict]]:
    note_ons = []
    note_offs = []
    with path.open() as source:
        for line in source:
            event = json.loads(line)
            if event["kind"] != "midi" or len(event["data"]) != 2:
                continue
            status = event["status"] & 0xF0
            if status == 0x90 and event["data"][1] > 0:
                note_ons.append(event)
            elif status == 0x80 or (status == 0x90 and event["data"][1] == 0):
                note_offs.append(event)
    return note_ons, note_offs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_directory", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    root = arguments.artifact_directory
    note_ons, note_offs = midi_events(root / "control-tracks-midi.jsonl")
    enabled = (root / "enabled-config.bin").read_bytes()

    tracks = {}
    for track, name, note, velocity in TRACKS:
        ons = [
            event for event in note_ons
            if event["channel"] == track
            and event["data"] == [note, velocity]
        ]
        offs = [
            event for event in note_offs
            if event["channel"] == track and event["data"][0] == note
        ]
        gate_times = [
            off["t_ms"] - on["t_ms"]
            for on, off in zip(ons, offs)
        ]
        tracks[str(track)] = {
            "name": name,
            "configured_enabled": enabled[track - 1] == 1,
            "configured_channel": enabled[16 + track - 1] + 1,
            "expected_note": note,
            "expected_velocity": velocity,
            "note_on_times_ms": [event["t_ms"] for event in ons],
            "note_off_times_ms": [event["t_ms"] for event in offs],
            "gate_times_ms": gate_times,
            "exact_note_on_count": len(ons),
            "exact_note_off_count": len(offs),
        }

    before_bank = sha256(root / "before-bank.bin")
    restored_bank = sha256(root / "restored-bank.bin")
    before_config = sha256(root / "before-config.bin")
    restored_config = sha256(root / "restored-config.bin")
    emitting = [
        int(track) for track, values in tracks.items()
        if values["exact_note_on_count"] > 0
    ]
    summary = {
        "sha256": {
            "before_bank": before_bank,
            "restored_bank": restored_bank,
            "exact_bank_restoration": before_bank == restored_bank,
            "before_config": before_config,
            "restored_config": restored_config,
            "exact_config_restoration": before_config == restored_config,
        },
        "tracks": tracks,
        "conclusions": {
            "ordinary_midi_emitting_tracks": emitting,
            "ordinary_midi_silent_tracks": [
                track for track, _, _, _ in TRACKS if track not in emitting
            ],
            "all_emitting_tracks_preserved_note_velocity_channel": all(
                tracks[str(track)]["exact_note_on_count"] == 3
                and tracks[str(track)]["exact_note_off_count"] == 3
                for track in emitting
            ),
            "master_internal_only_in_fixture": (
                emitting == [9, 10, 11, 13, 14, 15, 16]
                and tracks["12"]["exact_note_on_count"] == 0
            ),
        },
    }
    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
