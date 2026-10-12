#!/usr/bin/env python3
"""Build and inspect an OP-Z file-transfer sync-job manifest offline."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opzsysex.fileprotocol import UploadState


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--device-path", action="append", default=[], help="target path matching each input file")
    parser.add_argument("--remove-plug", type=int, action="append", default=[])
    args = parser.parse_args()
    if len(args.files) != len(args.device_path):
        parser.error("provide one --device-path for each input file")
    state = UploadState([(target, path.read_bytes()) for path, target in zip(args.files, args.device_path)], args.remove_plug)
    print(json.dumps(json.loads(state.sync_job), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
