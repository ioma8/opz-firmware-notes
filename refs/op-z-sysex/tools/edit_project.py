#!/usr/bin/env python3
"""Apply one bounded offline edit to a user-supplied OP-Z project block."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opzsysex.project import GlobalEditor, Note, PatternBankEditor


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline only; this tool never opens a MIDI device")
    parser.add_argument("--in", dest="input_path", required=True, type=Path)
    parser.add_argument("--out", dest="output_path", required=True, type=Path)
    sub = parser.add_subparsers(dest="operation", required=True)
    tempo = sub.add_parser("tempo")
    tempo.add_argument("bpm", type=int)
    chain = sub.add_parser("chain")
    chain.add_argument("slot", type=int)
    chain.add_argument("patterns", nargs="*", type=int)
    note = sub.add_parser("notes")
    note.add_argument("pattern", type=int)
    note.add_argument("track", type=int)
    note.add_argument("step", type=int)
    note.add_argument("midi_notes", nargs="*", type=int)
    note.add_argument("--velocity", type=int, default=100)
    args = parser.parse_args()

    source = args.input_path.read_bytes()
    if args.operation in ("tempo", "chain"):
        editor = GlobalEditor(source)
        if args.operation == "tempo":
            editor.set_tempo(args.bpm)
        else:
            editor.set_chain(args.slot, args.patterns)
    else:
        editor = PatternBankEditor(source)
        editor.set_notes(args.pattern, args.track, args.step, [Note(value, args.velocity) for value in args.midi_notes])
    if args.output_path.exists():
        parser.error(f"refusing to overwrite existing output: {args.output_path}")
    args.output_path.write_bytes(editor.bytes())


if __name__ == "__main__":
    main()
