#!/usr/bin/env python3
"""Edit one OP-Z slotConfiguration.json assignment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def edit_slot(
    document: dict, track_index: int, slot: int, plug_id: int
) -> int | None:
    tracks = document.get("tracks")
    if not isinstance(tracks, list):
        raise ValueError("slot map has no tracks array")
    track = next(
        (
            candidate
            for candidate in tracks
            if isinstance(candidate, dict)
            and candidate.get("index") == track_index
        ),
        None,
    )
    if track is None or not isinstance(track.get("packs"), list):
        raise ValueError(f"slot map has no track {track_index}")

    packs = track["packs"]
    prior = next(
        (
            pack
            for pack in packs
            if isinstance(pack, dict) and pack.get("slot") == slot
        ),
        None,
    )
    prior_id = prior.get("id") if prior else None
    if prior is None:
        packs.append({"id": plug_id, "slot": slot})
    else:
        prior["id"] = plug_id
    packs.sort(key=lambda pack: pack["slot"])
    return prior_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--track", type=int, required=True, help="zero-based track")
    parser.add_argument("--slot", type=int, required=True, help="one-based slot")
    parser.add_argument("--plug-id", type=int, required=True)
    args = parser.parse_args()
    if not 0 <= args.track < 16:
        parser.error("--track must be in 0...15")
    if not 1 <= args.slot <= 10:
        parser.error("--slot must be in 1...10")
    if not 0 < args.plug_id <= 0xFFFFFFFF:
        parser.error("--plug-id must be a non-zero UInt32")

    document = json.loads(args.input.read_text(encoding="utf-8"))
    try:
        prior_id = edit_slot(document, args.track, args.slot, args.plug_id)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"track={args.track} slot={args.slot} "
        f"prior={prior_id} plug={args.plug_id}"
    )


if __name__ == "__main__":
    main()
