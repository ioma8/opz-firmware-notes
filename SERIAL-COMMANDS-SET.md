 The complete command set

 ┌──────┬───────────┬────────────────────────────────────────────────────────┬─────────────┐
 │ type │ reply     │ command                                                │ class       │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x00 │ 0x01      │ PING                                                   │ read        │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x02 │ 0x03      │ version block                                          │ read        │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x06 │ —         │ hardware self-test (CRC engine, SPI info, stored time) │ benign      │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x07 │ 0x08      │ identity / metadata                                    │ read        │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x10 │ 0x12,0x13 │ write SPI flash                                        │ write       │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x14 │ 0x16      │ format SPI flash                                       │ write       │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x15 │ —         │ format NAND                                            │ write       │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x17 │ 0x18      │ READ SPI FLASH (offset, length) and stream             │ read        │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x19 │ 0x20      │ read file under /yaffs2/ and stream                    │ read        │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x21 │ 0x22      │ read the log and stream                                │ read        │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x23 │ 0x24      │ firmware upgrade by filename                           │ write       │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x27 │ 0x28      │ read via the yaffs2/NAND layer (≤32 KB) and stream     │ read        │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x29 │ 0x30,0x16 │ path-based filesystem operation                        │ write       │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x31 │ 0x12,0x13 │ load code into RAM and execute it                      │ execute     │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x32 │ 0x33      │ companion-module comms (BLE/Nordic/keyboard)           │ config      │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x34 │ —         │ SPI flash operation                                    │ write       │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x35 │ 0x36      │ chip / firmware version info                           │ read        │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x37 │ 0x38      │ move / rename in /yaffs2                               │ write       │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x39 │ 0x3a      │ monotonic clock read                                   │ read        │
 ├──────┼───────────┼────────────────────────────────────────────────────────┼─────────────┤
 │ 0x3b │ 0x3c      │ set the clock (0x8283dfd0 + /yaffs2/time.txt)          │ minor write │
 └──────┴───────────┴────────────────────────────────────────────────────────┴─────────────┘

## Using this set: framing, replies, and the one trap

**Frame:** `C0 <routing> <type> <len_be32> <payload>` — routing `0x01` host→device, `0x1e` device→host.
The header goes out **raw** and only the **payload** is escaped (`C0`/`7D` → `7D` followed by `byte ^ 0x20`).

> **The trap, measured 2026-10-16.** Escaping the frame's **leading `C0`** makes the device answer *nothing at
> all* — no PONG, no reply, no log frame — in every mode, at every baud, both DTR states, through cable replug and
> power cycle. It reads exactly like a dead console and cost a day of misdiagnosis. Build frames with
> `toolkit/opzcopyprobe.py::encode` or `sergey-extraction/opzget.py::encode`; never hand-roll the escaping.
> Detail: `FIRMWARE_ANALYSIS.md` §71.1.

**Replies:** the reply type is the one in the table above (`0x00`→`0x01`, `0x02`→`0x03`, `0x07`→`0x08`,
`0x35`→`0x36`, `0x19`→`0x20`, …). Log frames are type **`0x04`** — routing `0x1e` from the bootloader, `0x2e`
from the OS — and a PONG is routing `0x1e` **type `0x01`**, the same routing as bootloader logs. Classify by
**type**, not routing, or a log frame reads as an answer. `toolkit/opzframe.py::frames()` discards length-0 frames,
so a PONG has to be found in the raw bytes.

**Discipline:** send `0x00` PING for liveness before and after anything; keep payloads empty unless the command
documentedly needs one; never enumerate unknown types (the upgrade-mode console is a root shell — see the brick
warning in `README.md`). A wrong or absent path for `0x19` draws **no reply**, which is not evidence that a file is
absent.

**Measured working set (2026-10-16, update mode, read-only):** `0x00` → PONG; `0x02` → `dsp hw revision: dvt2…`;
`0x07` → `serial:…;hardware…`; `0x35` → `bf_os_ver:1.2.43;bf_bl_ver:1.1.35;…`; `0x19` streams whole files by path
relative to `/yaffs2`; `0x2b` is one-shot and no longer answers. `0x06` (hardware self-test, benign) and `0x34`
were not exercised in this set.
