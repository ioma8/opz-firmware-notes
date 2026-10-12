#!/usr/bin/env python3
"""Decode one OP-Z SysEx frame from hexadecimal text or a binary file."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opzsysex.sysex import decode_frame


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--hex", help="space-separated or contiguous hexadecimal frame")
    source.add_argument("--in", dest="input_path", type=Path, help="binary file containing one frame")
    args = parser.parse_args()
    data = args.input_path.read_bytes() if args.input_path else bytes.fromhex(args.hex)
    decoded = decode_frame(data)
    print(json.dumps({"messageId": decoded.message_id, "payloadSize": len(decoded.payload), "payloadHex": decoded.payload.hex(" ")}, indent=2))


if __name__ == "__main__":
    main()
