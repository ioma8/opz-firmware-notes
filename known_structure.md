# OP-Z firmware — decoded structure (what is known from evidence)

Nothing here is guessed; each line cites the observation it came from.

## 1. Outer container (.zfw) — fully decoded from the file bytes
```
0x000  flags, 16 B        key index 0xff at +0x04
0x070  IV, 16 B           per-file random (7 distinct IVs recorded in archives.json)
0x080  length, u32 LE     plaintext payload length (e.g. 1 490 575 for 1.2.45)
0x084  zeros to 0x300
0x300  encrypted filename, 256 B  -> decrypts to "firmware_bin_only_with_bootloader.zip"
0x400  encrypted payload          -> the archive (CBC, chained with the filename field)
```
Verified by recovering the archive's own first payload block through the console oracle:
`50 4b 03 04 14 00 c0 1e 04 00 00 00 49 fb be 94 19 5b` then a NUL.

## 2. First zip local header — partially decoded (fields readable)
```
50 4b 03 04   version=0x0014 (20)   flags=0x1ec0   method=0x0004
              compressed size / uncompressed size start with 0x00 (small first entry)
name length = 0 -> the entries are NAMELESS ("bin_only" archive, as its own name says)
```

## 3. Component list and approximate uncompressed sizes
From the updater's own progress log during a genuine 1.2.45 upgrade (`[extract] progress N/2775623`,
whose cumulative jumps delimit the entries), cross-checked against what the updater reports:

| Component | Evidence |
|---|---|
| content | `[content] progress 1/18 ... 18/18`, `copied 18 files` -> 18 small files |
| os | `os: OK (0)` -> written every upgrade; the ~828 KB entry |
| bootloader | `bootloader: OK (0)`, `wrote bootloader to index 0/1` (256 348 / 257 644 B) -> A/B slots |
| ble | `ble: Already installed (-200)` in **all** upgrades incl. 1.1.12 -> identical across versions |
| keyboard | `keyboard: OK (0)`, `psoc upgrade row 25 ... row 511` -> PSoC firmware |
| (preset bank) | 351 200 B jump = 0x55be0, the plug-preset bank size |
| first entry | ~315 B (first progress jump) -> a small manifest-like file |

## 4. Boot/fault window (from the device crash logs + the app's matching code)
```
main: Read firmware 1.2.45+
... plug import, sample memory count ...
snakesystem: load general config /yaffs2/user/config/general.json
main: exception caught iid: 0x00130026, arg: 0x00000000
main: exc reason: ADI_EXC_DATA_CPLB_MISS
main: DCPLB_FAULT_ADDR: 0x00000000
callstack: RETX: 0x80117baa          (1.1.12: 0x8010ea52)
```
A null data read, immediately after the config load. The app is the same SnakeLib compiled for ARM64
(4 509 symbols retained in app_symbols.txt), which brackets the window; `RETX` resolves to its function
once the OS image is decoded.

## 5. Console protocol (for finishing the decode)
`C0 <routing> <type> <len:4 BE> <payload>`; routing 0x01 = Blackfin; replies use 0x1E, logs 0x2E
(11-byte log header: C0 2E 04 00 00 00 <tick:4> 01 <text NUL>). The decrypt oracle needs the bootloader
to read a file, i.e. the update medium must be present.
