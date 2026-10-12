#!/usr/bin/env python3
"""Send one documented read-only OP-Z query and print the first response."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opzsysex.device import Device, list_ports
from opzsysex.sysex import IDENTITY_INQUIRY, MIDI_CONFIGURATION_QUERY, PATTERN_QUERY, SAMPLE_VISUALIZATION_QUERY


QUERIES = {
    "identity": IDENTITY_INQUIRY,
    "midi-config": MIDI_CONFIGURATION_QUERY,
    "pattern": PATTERN_QUERY,
    "sample-visualization": SAMPLE_VISUALIZATION_QUERY,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", choices=QUERIES)
    parser.add_argument("--match", default="OP-Z")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--list-ports", action="store_true")
    args = parser.parse_args()
    if args.list_ports:
        inputs, outputs = list_ports()
        print("Inputs:", *inputs, sep="\n  ")
        print("Outputs:", *outputs, sep="\n  ")
        return
    if args.query is None:
        parser.error("query is required unless --list-ports is used")
    with Device(args.match) as device:
        response = device.request(QUERIES[args.query], args.timeout)
    print(response.hex(" "))


if __name__ == "__main__":
    main()
