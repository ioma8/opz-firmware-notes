# 09 — The Ghidra harness and the process that worked

This document is the working method: how the four images were imported, the exact command form that runs a
query, **what each of the ten helper scripts answers and — more usefully — what it cannot answer**, the analysis
loop that produced the other eight documents, and the traps that cost real time. It is written so a later session
can start from a cold machine and reach a finding without rediscovering any of this.

Everything below was used on this firmware. Nothing here is aspirational.

## 9.1 The harness

| piece | value |
|---|---|
| Ghidra | **12.1.4** (`analyzeHeadless` is the only interface used — no GUI) |
| Blackfin support | **`Ghidra/Extensions/Ghidra-BlackFinPlus`**, installed separately |
| Java | Temurin 25 (whatever Ghidra ships with works) |

**The extension is not optional.** Standard Ghidra rejects the `Blackfin:LE:32:default` language id that
`opz.ldr`'s boot-stream header names, and the import fails with a language-not-found error. The two companion
ARM images need no extension.

The projects live outside the repository (they are large and regenerable), one per processor family:

```
/tmp/opz-fw/ghidra      project OPZ   program opz.ldr                 (Blackfin+ OS)
/tmp/opz-fw/ghidra      project OPZ   program bootloader.ldr          (same project, same language)
/tmp/opz-fw/ghidra-ble4 project BLE4  program nrf52832_opz.bin        (base 0x23000)
/tmp/opz-fw/ghidra-kb2  project KB2   program kb_DVT2_fixed.bin       (base 0x1900, 2 bytes stripped)
```

Load bases, and how each one was *derived* rather than guessed, are in the `## Load bases` table of doc `00`;
the short version is that getting `0x23000` and `0x1900` wrong produces code that decompiles confidently and
means nothing.

**The projects are regenerable, so treat them as scratch — but keep the *images* somewhere durable.** A
mid-session loss of the whole working tree (`/tmp/opz-fw`, holding the Ghidra projects, the expanded engine
images and every dump) cost a full re-import of `opz.ldr` before work could continue. The decrypted images live
in the repository's untracked `from-sergey/` tree and the scripts are committed, so nothing irreplaceable was
lost — but nothing derived should be stored only in a temporary directory either.

**Import once** (analysis runs during import, several minutes for the Blackfin images):

```bash
GH=/path/to/Ghidra_12.1.4/support/analyzeHeadless

# Blackfin: the loader and language are auto-detected from the .ldr signature
$GH /tmp/opz-proj OPZ -import /tmp/opz-fw/firmware/blackfin/bin/opz.ldr
$GH /tmp/opz-proj OPZ -import /tmp/opz-fw/firmware/blackfin/bin/bootloader.ldr

# BLE: base matters - 0x20000 gives confident nonsense
$GH /tmp/ble-proj BLE -import /tmp/opz-fw/firmware/nordic/bin/nrf52832_opz.bin \
    -processor "ARM:LE:32:Cortex" -loader BinaryLoader -loader-baseAddr 0x23000

# PSoC: assemble the .cyacd rows, then strip the leading 2 bytes of the 0x1900.. region
python3 - <<'EOF'
import pathlib
raw   = pathlib.Path('SnakeKeyboardModule_DVT2.cyacd').read_bytes()
lines = [l.strip() for l in raw.split(b'\n') if l.strip().startswith(b':')]
rows  = {int(l[1:7], 16): bytes.fromhex(l[7:7+512].decode()) for l in lines}
img   = bytearray(512*256)
for r, d in rows.items(): img[r*256:(r+1)*256] = d
pathlib.Path('kb_DVT2_fixed.bin').write_bytes(img[0x1900:0x20000][2:])
EOF
$GH /tmp/kb-proj KB -import kb_DVT2_fixed.bin \
    -processor "ARM:LE:32:Cortex" -loader BinaryLoader -loader-baseAddr 0x1900
```

**Query form — every script is used the same way:**

```bash
GH=/path/to/Ghidra_12.1.4/support/analyzeHeadless
S=$PWD/ghidra-scripts                       # see 9.2 for why this must be $PWD and not /tmp/...

$GH /tmp/opz-fw/ghidra OPZ -process opz.ldr -noanalysis -scriptPath "$S" \
    -postScript Decomp2.java   /tmp/out.c      0x8003ae20 0x8003d1e0 \
    -postScript DumpRange.java 0x8003ae20 60 \
    -postScript CallersOf.java /tmp/callers.txt 0x8003c5a4
```

Four things about that line are deliberate and each one cost a run to learn:

- **`-noanalysis`.** Without it every query re-runs the full analyser on the 828 KB image. With it a query is
  tens of seconds. Only the `-import` above analyses.
- **`-process <program> -noanalysis` is the read-only form.** No import, no re-analysis, no chance of mutating
  the project beyond the functions a script deliberately creates.
- **Several `-postScript` flags run in one JVM start.** Batch every question you can predict; the JVM start and
  project open dominate the runtime.
- **`-scriptPath` must be the resolved, symlink-free path.** On macOS `/tmp` is a symlink to `/private/tmp`;
  `analyzeHeadless` canonicalises the argument, then compares it against the script directories it printed, and
  fails with `Failed to find script in any script directory: /private/tmp/…` followed by
  `ClassNotFoundException`. `/tmp/opz-fw/ghidra` fails; `/private/tmp/opz-fw/ghidra` works. The same applies to
  `ghidra-scripts/` if the checkout is reached through a symlink.

## 9.2 The script inventory — and each tool's blind spot

Eleven scripts, all standalone `GhidraScript`s, all committed under `ghidra-scripts/`. They print to a file whose
name is the first argument.

| script | answers | **cannot** answer |
|---|---|---|
| `Decomp2.java` | decompiled C for a list of addresses; **creates the function if the region is unanalysed** | anything about callers; it will happily decompile a mid-function address if you aim badly |
| `DumpRange.java` | raw disassembly of `N` instructions from an address, following instruction lengths | nothing semantic — but it is the only tool that shows code a decompiler dropped |
| `FindXImm.java` | where a **materialised 32-bit constant** is built in code, plus the containing function | **never function calls** (Blackfin `CALL` is PC-relative), and its raw byte-pair fallback has false positives |
| `CallersOf.java` | Ghidra's reference database: every reference to an address, with its type (`CALL` vs `DATA`) | completeness — it only sees call sites that are already disassembled |
| `FnAt2.java` | which function contains an address | anything about reachability; `(none)` means *not analysed*, not *unreachable* |
| `ScanPro.java` | only the frame-establishing instructions (`LINK`, register pushes) in a range | which function an arbitrary address is in — but it is how a big function's entry is found among its own epilogues |
| `HexRange.java` | raw bytes of a range, hex + ASCII | meaning |
| `RangeStr.java` | printable strings in a range, with addresses | strings split across a non-printable byte |
| `FindDword.java` | every occurrence of a 4-byte value in every initialised block | Blackfin constants (they are split immediates — see `FindXImm`) |
| `LogMap.java` | `function → file:line → format` for a whole code range, by resolving backwards from log calls | functions that never log (many do not) |
| `EngineAsm.java` | assembles source lines with the program's own SLEIGH assembler and prints the resulting bytes | **on the Blackfin+ module it assembles nothing at all** — see the trap below; it is kept because it proves that negative and works for other languages |

**`LogMap` deserves its own paragraph**, because it is the highest-yield tool here and it is the one that is not
obvious. Every diagnostic log in this firmware goes through `FUN_8012f1e4(file, line, format, …)`, and all three
of those arguments are materialised at the call site. Walking a range, finding that call, and walking **backwards**
over the preceding instructions to resolve address-shaped scalars produces a source attribution for a region
without decompiling anything:

```
== call at 8003aefc  in FUN_8003ae20@8003ae20
   line argument (from R1): 620
   8003aef4  LdImmToReg R0 = -0x7efea420   -> "C:\snake-software\src\sequencer\DmxController.cpp"
   8003aee8  LdImmToReg R2 = -0x7efea334   -> "Failed to write dmx data"
```

Two details make it correct rather than plausible:

- **The line number is the value loaded into `R1` *immediately* before the call** — not the nearest small scalar.
  A nearest-scalar heuristic returned `3`, `12` and `24` for call sites whose real lines are `620`, `316`, `353`,
  `358` and `480`; it was picking up loop bounds. The `R1` rule reproduces the one line that had already been
  read by hand from the disassembly, which is what makes the rest of the map trustworthy.
- **Only the fused-immediate lines should be quoted.** The raw hi/lo byte-pair fallback exists for instructions
  the analyser did not pattern-match, and it also matches unrelated encodings, producing empty and
  single-character strings.

## 9.3 The loop

The order below is what actually produced findings. It is deliberately data-first.

1. **Dump every printable string with its address.** Command vocabularies appear as clusters of `verb-noun`
   strings, and the source path of the file that uses them is normally in the same block. 75 original paths were
   recovered this way, which is what makes the architecture readable at all.
2. **Attribute functions to source files with `LogMap`** over a region, before trying to read the code. A
   `function → DmxController.cpp:620` line is cheap and enormously narrowing.
3. **Start from the data, not the code.** A table in rodata is ground truth that constrains every later reading:
   the 20-entry light palette, the 10-slot `ScoreContext` vtable, the 256-entry PSoC brightness curve, the
   129-entry BLE dispatch table. Reading the table first turns "what does this byte mean" into "which entry is
   this".
4. **Decompile the callee before naming the caller's argument.** Several readings in this document set were
   wrong until the callee was read: `FUN_8003c386`'s third argument is an *enable/clear*, not a range flag;
   `FUN_8003c60c` takes a mode number that is an *animation* number; `FUN_8003d56e`'s second argument is a
   *colour-wheel index*, not a channel byte; the Score panel's `set mode` is a *radio test command*.
5. **Then decompile the caller to see how it is driven**, and use `ScanPro` when the "function" turns out to have
   many epilogues — several identical epilogues and one prologue means **one large function with many early
   returns**, not many functions.
6. **Ask `CallersOf`, then ask `FindXImm`, then do not trust either.** The two answer different questions and
   their disagreement is informative (doc `05` §5.8c).
7. **Cross-check against the other CPUs.** The single strongest class of evidence available here. The companion
   protocols are shared source, so a type byte read on the Blackfin can be checked against the PSoC's dispatch
   table and the Nordic's, and the payload *width* is an independent second signal (doc `04` §4.6b verifies six
   message types that way, including one where the PSoC's own implemented-type list and the BLE's handler agree
   by absence and presence respectively).
8. **Cross-check against the vendor's own material.** Two vendor manuals ship inside the image
   (`readme/how_to_dmx.txt`, `readme/how_to_import.txt`), and published chip specs name protocol bytes that the
   decompiler cannot (Infineon AN60317 for the PSoC bootloader's numeric command set). When spec and code
   disagree, the code wins and the disagreement is recorded.
9. **Write it down in the same session, with the address.** A claim without an address is not checkable, and
   the next session will re-derive it.

## 9.4 Rules for making a claim

These are the rules that kept the document set from accumulating confident nonsense. Each is here because
breaking it produced a wrong entry that had to be retracted.

- **A failed reference search is not proof of absence.** Ghidra's reference manager and `CallersOf` missed a
  queue pop that exists (it is swallowed by a size-1 stub) and an entire message consumer. Before recording
  "never read" or "no caller", re-test with the **split-immediate scan** and a control group.
- **Always run a positive control with a negative result.** Every "the scan finds nothing here" claim in these
  documents is paired with a case where the same scan *does* find the known thing (the pop/push/initialiser of a
  queue; 6 hits in `opz.ldr` for the queue constants against 0 in `bootloader.ldr`, which proves the scan is
  discriminating rather than broken).
- **A raw 32-bit dword scan is invalid for Blackfin constants.** They are materialised in two 16-bit halves
  (high half first), so a dword scan returns **0 hits for an address that demonstrably appears in the code**.
  Use `FindXImm`. Conversely, `FindDword` *is* correct for genuine data (vtable slots, magic constants) — the two
  tools are for different things and swapping them silently loses findings.
- **A missing `FindXImm` hit on a function address means nothing at all.** Function calls are PC-relative. Only
  `CallersOf` speaks to call sites, and only where the site is disassembled.
- **`FnAt2` returning `(none)` is coverage information, not a reachability conclusion.** Large regions of this
  image have no Ghidra functions at all; `Decomp2` reads them anyway.
- **A decompiler's "unreachable block" can contain the payload.** Ghidra dropped the send half of the light
  ticker as *Removing unreachable block (ram,0x801314b2)* — the send is **at** `0x801314b2`. When a decompiled
  function looks incomplete, read the raw range with `DumpRange`.
- **Register-carried arguments look like missing parameters.** Calls decompile as `FUN_8003d48a(idx, 1)` with the
  third argument "gone" because it is still in `R2` from the caller. Count arguments in the disassembly before
  concluding a callee takes fewer.
- **A Ghidra function boundary can be wrong for thunks**, and a scalar search for an offset can match a
  source-line number (a yaffs2 assert's line `0x1044` matched a queue-offset search and made an unrelated
  function look exactly like a queue consumer). Require *both* halves of a signature — for a queue, the head
  **and** the tail offset in one function.
- **Module proximity to a `__FILE__` string is a hint, not a binding.** The hypothesis that a translation unit's
  globals sit beside its own path string was tested and **rejected** (doc `08` §8.8): the PSoC power-mode byte and
  the light ticker's state sit between `command_handler_ble.cpp`'s path string and
  `command_handler_kb.cpp`'s, yet are written by the `kb` handlers.
- **Record the retraction at the claim.** Three verdicts in this set were overturned by better methods (the
  file-manager queue is not write-only; the `.cyacd` trailer is decoded but never compared; the `0x1add8` table
  *is* a brightness curve). Each is marked where it was originally asserted, because a reader diffing two
  sessions needs to see which one is current.

## 9.5 Traps and their cost

| trap | symptom | fix |
|---|---|---|
| symlinked `-scriptPath` | `Failed to find script in any script directory: /private/tmp/…`, then `ClassNotFoundException` | pass the canonical path |
| missing `-noanalysis` | every query takes minutes | always pass it after the initial import |
| script compile error | same `ClassNotFoundException`, one line earlier says `error: cannot find symbol` | read the compile line; the class error is a symptom, not the cause |
| wrong load base | code that decompiles plausibly and means nothing | derive the base (doc `01` §1.4); `0x23000` not `0x20000`, `0x1900` not `0x18FE` |
| raw dword scan for a Blackfin constant | zero hits for an address you can see in the listing | `FindXImm` |
| `SweepAll`-style whole-image sweeps | budget exhausted before reaching the target — the L1 image spanned 2.1 MB of mostly zeros | rebuild as **tight per-cluster images** (a 28 KB and a 54 KB slice instead of 2.1 MB) |
| decompiler misnames created functions | every new function is called `ble_dispatch` | cosmetic, but it corrupts call-graph reading — fix the helper's naming |
| building a doc from memory | plausible statement, wrong address | every claim carries an address; `check_docs.py` then guards the set mechanically |
| SLEIGH assembly assumed to work | `Assemblers.getAssembler` returns a `SleighAssembler`, but every line fails, including `NOP` and `RTS` — the Blackfin+ module's constructors expose display templates, not a usable assembly grammar | the assembler existing is not the assembler working: probe with a no-operand mnemonic first. To author engine code, transcribe the encodings from the module's own `.sinc` (each instruction file carries the bit-field diagram) and round-trip the result through the disassembler |
| `.engine` described as a flat image | a legal-looking dump, and a parser that desynchronises at the fill segment of `ep`/`organ` | the module is a segment list and a fill segment carries **no** payload (doc `11` §11.1); verify any parser by byte-exact repack of all 21 factory engines |

## 9.6 Verifying the document set itself

The last piece of the harness is not a Ghidra script. `firmware-re-docs/check_docs.py` is a dependency-free
verifier for these documents and runs in under a second:

```bash
python3 firmware-re-docs/check_docs.py              # exits non-zero on failure
python3 firmware-re-docs/check_docs.py --self-test  # seeds one fault of each kind, fails if any goes undetected
```

It checks **code-fence parity per file**, **the findings table matching exactly the documents present**, a
**resolvable `doc NN §x.y` pointer on every headline item**, **duplicate headline numbers**, and the **privacy
invariants** (no unit serial, no private-material references, no 64-hex strings). The `--self-test` exists
because a checker that has never failed is unproven: it copies the documents to a scratch directory, injects one
fault of each kind, and asserts each one is caught.

Two honest boundaries, stated in the script as well as here:

- **Prose `§x.y` references are not machine-checked.** They are written four ways in these documents and a
  resolver that guesses between two documents named in one sentence fails in both directions; an earlier version
  reported 93 false failures. The manual rule that works is recorded in the script's docstring: *the § belongs to
  the document whose token is nearest it in the same sentence or table cell*.
- **A clean run means no recorded gap, not completeness.** The verifier guards against regressions in the
  mechanical properties. It cannot tell whether a claim is *correct* — only an address, a decompile and a
  cross-check do that.
