#!/usr/bin/env python3
"""opzstatus.py - one command that runs every engine gate and prints the tallies.

The project reports three engine populations plus a documentation gate, and each lived in a different
script. This runs them all, prints the line that carries the number, and fails if any gate fails - so
"20 of 21" is something a reader can reproduce in one step instead of trusting a summary.

Usage:
    python3 toolkit/opzstatus.py
"""
import pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TK = ROOT / "toolkit"

# (label, argv, pattern whose first match is the number worth showing, known gap?)
GATES = (
    ("interpreter selftest", [sys.executable, str(TK / "opzsim.py"), "selftest"], r"all checks passed", None),
    ("ARM64 instruments", [sys.executable, str(TK / "opzinstcheck.py"), "--blocks", "20"], r"\d+ of \d+ .*", None),
    # TapeTwo is documented as silent by construction, so its exit 1 is a known gap rather than a regression;
    # the tally line still prints, so the gap stays visible instead of being hidden behind a green tick.
    ("ARM64 effects", [sys.executable, str(TK / "opzfxcheck.py"), "--blocks", "60"],
     r"\d+ of \d+ factory effects.*", "not processing: TapeTwo"),
    ("Blackfin any audio", [sys.executable, str(TK / "opzfactoryaudible.py")],
     r"(instruments|effects):\s+\d+ of \d+.*", None),
    ("Blackfin requested note", [sys.executable, str(TK / "opzfactorycheck.py")], r"plays the requested note.*", None),
    ("docs gate", [sys.executable, str(ROOT / "firmware-re-docs" / "check_docs.py")], r".*", None),
)


def main():
    failed = []
    for label, argv, pattern, known in GATES:
        p = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
        out = p.stdout + p.stderr
        hits = [m.group(0).strip() for m in re.finditer(pattern, out) if m.group(0).strip()]
        for hit in hits:
            print(f"  {label:24s} {hit}")
        ok = p.returncode == 0
        if not ok and known and known in out:
            print(f"  {label:24s} known gap: {known}")
            ok = True
        if not hits:
            print(f"  {label:24s} {'ok' if ok else 'FAILED'} (no summary line)")
        if not ok:
            failed.append(label)
    rows = sum(1 for _ in (ROOT / "HYPOTHESES.csv").read_text().splitlines()) - 1
    print(f"  {'ledger rows':24s} {rows}")
    if failed:
        print(f"\n  FAILED: {', '.join(failed)}")
        return 1
    print("\n  all gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
