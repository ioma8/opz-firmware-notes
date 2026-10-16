#!/usr/bin/env python3
"""Mechanical consistency + privacy check for the firmware-re-docs document set.

Run from anywhere:  python3 firmware-re-docs/check_docs.py
Exit code 0 = all checks pass, 1 = at least one failure.

Covers the invariants that are worth re-checking after every editing session:

  1. code fences balanced in every document
  2. the index's findings table lists exactly the documents present
  3. every headline item in 00-INDEX carries a `doc NN §x.y` pointer, and both
     the document and the section it names exist
  4. no duplicate headline item numbers
  5. no private device data (unit serial, quoted private material, 64-hex strings)

Section references *inside* the prose (§x.y in the middle of a paragraph) are
deliberately **not** machine-checked: they appear as `doc 07 §7.4`, `` `07` §7.4``,
`§7.4c of doc 07` and as series (`doc 07 §7.1, §7.2, §7.4`), and a resolver that
guesses between two documents named in one sentence produced false alarms in both
directions. They were verified by hand; the rule that worked is "the §x.y belongs
to the document whose token is nearest it in the same sentence or table cell".
"""
import re, sys, shutil, tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent

SERIAL    = "X3CJN79E"                      # unit serial, must never appear
FORBIDDEN = ["from-sergey", "chat.txt"]     # quoted private material
NOTE_ONLY = ["opz.key"]                     # only ever a path, reported as a note
HEX64     = re.compile(r"\b[0-9a-fA-F]{64}\b")
H2        = re.compile(r"(?m)^#{2,4}\s+([0-9]+\.[0-9]+[a-z]?)\b")

fails, notes = [], []


def run(docs=DOCS):
    """Return (fails, notes, files, text) for a documentation directory."""
    global fails, notes
    fails, notes = [], []
    files = sorted(docs.glob("*.md"))
    text = {p.name: p.read_text() for p in files}
    if "00-INDEX.md" not in text:
        fails.append("00-INDEX.md missing")
        return fails, notes, files, text

    # 1. fences
    for name, t in text.items():
        n = len(re.findall(r"(?m)^```", t))
        if n % 2:
            fails.append(f"{name}: unbalanced code fences ({n})")

    # sections per document, for the headline-pointer check
    heads = {n: set(H2.findall(t)) for n, t in text.items()}

    idx = text["00-INDEX.md"]

    # 2. findings table vs files present
    listed = set(re.findall(r"`(\d\d-[a-z0-9-]+\.md)`", idx))
    present = set(text) - {"00-INDEX.md"}
    for missing in sorted(present - listed):
        fails.append(f"00-INDEX table does not list {missing}")
    for absent in sorted(listed - present):
        fails.append(f"00-INDEX table lists missing file {absent}")

    # 3 + 4. headline items
    marks = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^(\d+)\. \*\*", idx)]
    if not marks:
        fails.append("00-INDEX has no headline items")
    else:
        marks.append((idx.index("## Confidence levels"), "X"))
        for i in range(len(marks) - 1):
            num = marks[i][1]
            block = idx[marks[i][0]:marks[i + 1][0]]
            refs = list(re.finditer(r"doc\s+`(\d\d)`\s*§([0-9]+\.[0-9]+[a-z]?)", block))
            if not refs:
                fails.append(f"00-INDEX item {num}: no 'doc NN §x.y' pointer")
                continue
            for r in refs:
                cand = [k for k in heads if k.startswith(r.group(1) + "-")]
                if not cand:
                    fails.append(f"00-INDEX item {num}: doc {r.group(1)} absent")
                elif r.group(2) not in heads[cand[0]]:
                    fails.append(
                        f"00-INDEX item {num}: §{r.group(2)} not in {cand[0]}")
        nums = [m[1] for m in marks[:-1]]
        dupes = sorted({n for n in nums if nums.count(n) > 1})
        if dupes:
            fails.append(f"00-INDEX: duplicate headline item numbers {dupes}")

    # 5. privacy
    for name, t in text.items():
        if SERIAL in t:
            fails.append(f"{name}: contains the unit serial")
        for bad in FORBIDDEN:
            if bad in t:
                fails.append(f"{name}: contains {bad!r}")
        for m in HEX64.finditer(t):
            fails.append(f"{name}: 64-hex string {m.group(0)[:16]}…")
        for soft in NOTE_ONLY:
            if soft in t:
                notes.append(f"{name}: mentions the {soft} path (a path, not key material)")

    return fails, notes, files, text


def report(docs=DOCS):
    files, text = sorted(docs.glob("*.md")), {p.name: p.read_text() for p in docs.glob("*.md")}
    fails, notes, _, _ = run(docs)
    print(f"documents: {len(files)}  lines: {sum(len(t.splitlines()) for t in text.values())}")
    for n in notes:
        print(f"  note: {n}")
    if fails:
        print(f"\nFAIL ({len(fails)}):")
        for f in fails:
            print("  " + f)
        return 1
    print("\nOK — fences balanced, index table complete, every headline item "
          "points at a real section, no duplicate items, privacy clean")
    return 0


def self_test():
    """Prove the checks have teeth: seed one fault at a time into a throwaway copy."""
    seeds = {
        "unbalanced fence":      lambda d: (d / "05-midi-sysex-and-config.md").write_text(
                                     (d / "05-midi-sysex-and-config.md").read_text() + "\n```\n"),
        "64-hex string":         lambda d: (d / "03-serial-commands.md").write_text(
                                     (d / "03-serial-commands.md").read_text()
                                     + "\n" + "ab" * 32 + "\n"),
        "unit serial":           lambda d: (d / "04-hidden-features-and-easter-eggs.md").write_text(
                                     (d / "04-hidden-features-and-easter-eggs.md").read_text()
                                     + "\nX3CJN79E\n"),
        "index table missing":   lambda d: (d / "00-INDEX.md").write_text(
                                     (d / "00-INDEX.md").read_text().replace("`06-rtos", "`xx-rtos")),
    }
    bad = 0
    for label, seed in seeds.items():
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "docs"
            shutil.copytree(DOCS, dst)
            seed(dst)
            fails, _, _, _ = run(dst)
        if fails:
            print(f"  PASS  {label}: caught")
        else:
            print(f"  FAIL  {label}: NOT caught")
            bad += 1
    print("self-test: " + ("all seeds caught" if not bad else f"{bad} seed(s) missed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else report())
