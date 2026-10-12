#!/usr/bin/env python3
"""Compatibility wrapper for creating an OP-1/OP-Z melodic sampler AIFF."""

import argparse
from pathlib import Path

from opz_sample_format import create_synth_sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--base-frequency", type=float, default=440.0)
    parser.add_argument("--name", default="Sample")
    args = parser.parse_args()

    report = create_synth_sample(
        args.input,
        args.output,
        args.name,
        args.base_frequency,
    )
    print(
        f"Created {args.output} ({args.output.stat().st_size} bytes, "
        f"{report['duration_seconds']:.3f}s)"
    )


if __name__ == "__main__":
    main()
