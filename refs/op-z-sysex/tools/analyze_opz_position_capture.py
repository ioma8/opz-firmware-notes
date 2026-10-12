#!/usr/bin/env python3
"""Summarize $07 chain-position events from a user-supplied JSONL capture."""

import argparse
import json
from pathlib import Path


def analyze(path: Path) -> None:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selections = [event for event in events if event.get("kind") == "sysex" and event.get("id") == 7]
    clocks = [event for event in events if event.get("kind") == "clock"]
    first_time = selections[0].get("t_ms", 0) if selections else 0
    print(f"\n{path}\nselections={len(selections)} clocks={len(clocks)}")
    for event in selections:
        payload = bytes.fromhex(event["payload_hex"])
        if len(payload) < 20:
            print("malformed $07 payload")
            continue
        length = min(payload[16], 32)
        chain = [((payload[index // 2] & 0x0F) if index % 2 == 0 else (payload[index // 2] >> 4)) + 1 for index in range(length)]
        pattern = (payload[17] & 0x0F) + 1
        cursor = payload[18] % 10 if length else None
        project = (payload[19] & 0x0F) + 1
        elapsed = (event.get("t_ms", 0) - first_time) / 1000
        print(f"+{elapsed:.3f}s project={project} pattern={pattern} chain={chain} cursor_digit={cursor if cursor is not None else '-'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("captures", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.captures:
        analyze(path)


if __name__ == "__main__":
    main()
