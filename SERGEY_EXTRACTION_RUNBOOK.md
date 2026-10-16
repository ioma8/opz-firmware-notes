# OP-Z factory content extraction — request for a healthy unit

Read-only. Nothing here writes to the device, changes firmware, or needs the firmware key.
Two separate things are wanted, and they come from two different places:

| what | where it lives | route |
|---|---|---|
| factory **sample packs** (~24 `.aif`) | the content/slot tree | **Route 0** (one script) |
| 8 factory **engines** (`.engine`) | system content | **Route 0** (one script) |

Background: the target unit was bricked by a NAND format and no longer boots normally. It boots to *update
mode* only, and everything below is what is missing. The eight engines and the factory packs are **not** in any
firmware package — checking the released `.zfw` files and a decrypted 1.2.45 tree, the packages carry 13 engines
and a single `UserSampler.aif`, nothing else.

---

## Route 0 — run one script (recommended; replaces Routes 1 and 2)

The console in update mode has a **file-read command**, so both groups can be fetched the same way, with no
disk copying and no SysEx. `opzget.py` in this folder does all of it.

**What you need:** the OP-Z in **update mode** ("OP-Z Boot" — the mode where an `OP-Z` disk appears with a
`systeminfo` folder), USB connected, and the OP-Z app closed so nothing else holds the port.

```
uv run --script opzget.py                     # macOS, Linux and Windows, if you have uv
pip3 install pyserial && python3 opzget.py    # macOS / Linux without uv
py -3 -m pip install pyserial && py -3 opzget.py   # Windows without uv
python3 opzget.py --dry-run                   # show what it would ask for, send nothing
python3 opzget.py --limit 1                   # quick 20-second trial
```

The serial port is found automatically — COM ports on Windows, `/dev/cu.usbmodem*` on macOS, `/dev/ttyACM*`
or `/dev/ttyUSB*` on Linux. It prefers a port that describes itself as a USB device, so a Bluetooth or virtual
port will not be picked over the OP-Z. `--list` shows every port with its description, and `--port COM5` (or the
full `/dev/...` path) forces a specific one.

**It is read-only.** It sends exactly one command, type `0x19`, which opens a file, reads it and streams it
back. It cannot write, move, rename or delete anything on the device. Nothing of yours is touched — results
land in an `opz-dump` folder **created next to the script**, so it does not matter which directory you run it
from.

**Please do not send any other type byte.** The same console dispatches seven destructive commands, and several
would not look dangerous from the number alone:

| type | what it does |
|---|---|
| `0x10` | writes SPI flash |
| `0x14` | formats SPI flash |
| `0x15` | **formats NAND** — this is what destroyed our unit |
| `0x23` | firmware upgrade by filename |
| `0x29` | path-based filesystem operation |
| `0x31` | **loads code into RAM and executes it** |
| `0x34` | SPI flash operation |
| `0x37` | moves/renames a file (not a copy — it relocates it) |
| `0x3b` | sets the device clock |

`0x31` is the one to respect most: a RAM-load-and-execute primitive needs no file and no power cycle to do
something arbitrary. `opzget.py` constructs only `0x19`, and nothing else in this runbook needs a type byte, so
there is no reason to send any other value. If you write your own tool, the read-only types are `0x00`, `0x02`,
`0x07`, `0x17`, `0x19`, `0x21`, `0x27`, `0x35` and `0x39`, and nothing outside that list.

`0x31` is the one to respect most: a RAM-load-and-execute primitive needs no file and no power cycle to do
something arbitrary. `opzget.py` constructs only `0x19`, and nothing else in this runbook needs a type byte, so
there is no reason to send any other value.

**What it does:** for each wanted name it tries several plausible paths, stops at the first that answers,
remembers which path form worked and uses that first for the rest. A name that is not found anywhere is
reported MISSING and the run continues. It prints a moving byte counter while a file streams and an elapsed
counter while nothing arrives, so a slow or absent file never looks like a hang. Interrupting is safe —
re-running resumes and skips what it already has.

**Expect 20-40 minutes** if most packs are present: a sample pack is about 890 kB and this is a serial link.

It first reads an engine that must exist as a **control check**, so if the command does not work on your unit
you find out in seconds rather than after half an hour.

**What to send back:** the whole `opz-dump` folder (or a zip), which the script creates **next to itself** —
you do not need to `cd` anywhere first. `opz-dump/manifest.json` alone is also genuinely useful if sending
~20 MB of audio is awkward — and a MISSING result is useful information too, because it says the content is not
on your unit either.

If you would rather not run a script from a stranger, Routes 1 and 2 below do the same job manually and are
still perfectly good. Route 3 covers everything else.

---

## Route 1 — content mode (sample packs). 5 minutes, settles most of it.

1. Put the OP-Z in **content / disk mode** (the mode where it mounts as a USB disk with `projects/`,
   `bounces/`, `samplepacks/` on it). *Not* update mode.
2. Send us a **recursive listing with file sizes** first — before copying anything:

   ```bash
   # macOS / Linux
   find /Volumes/OP-Z -type f -not -path '*/.fseventsd/*' -exec stat -f '%z %N' {} + | sort -rn
   # Linux
   find /Volumes/OP-Z -type f -printf '%s %p\n' | sort -rn
   ```

   On the broken unit this listing showed `samplepacks/<track>/<slot>/` folders that were almost all empty, with
   a handful of **0-byte `~`-prefixed** files. Those `~` files are *duplicate references* — by the shipped
   readme the `~` prefix means "same pack as one stored elsewhere" and carries no audio. So a healthy unit
   should instead show the real packs as **non-zero** files.

3. If the listing shows non-zero `.aif` files, copy the whole thing:

   ```bash
   rsync -a --exclude '.fseventsd' /Volumes/OP-Z/ ./opz-content-disk/
   ```

   Then **eject properly** so any pending import commits.

**If the factory packs appear as non-zero `.aif` files, this route alone is enough** and Route 2 only needs to
cover the engines.

**If they appear only as 0-byte `~` references**, or the `samplepacks/` tree does not contain them at all, the
audio is not on the content surface and we fall through to Route 2/3.

---

## Route 2 — MIDI SysEx pull (engines + system packs). ~10 minutes.

The OP-Z exposes a read-only file service over USB MIDI. We already pulled `settings/plugs.json` and
`settings/slotConfiguration.json` from a unit this way. File IDs are `crc32(lowercase(path))`, so a wrong path
just returns "unserved" — probing is harmless and read-only.

1. Connect the OP-Z over USB and put it in **normal mode** (not update mode, not content mode).
2. Close the OP-Z app and any other MIDI or file-sync client, so nothing competes for the port.
3. Get the tooling:

   ```bash
   git clone https://github.com/ioma8/opz-firmware-notes
   cd opz-firmware-notes
   ```

4. Confirm it sees the device, then run the probe. `PATHS.txt` holds 254 candidate paths — engine path
   variants, pack path variants, and the slot-tree forms seen on the broken unit's disk:

   ```bash
   # list MIDI ports; the OP-Z should appear by name
   uv run --with mido --with python-rtmidi python -c "import mido; print(mido.get_output_names())"

   # probe all candidate paths in ONE session (~10 min; nothing is written)
   uv run --with mido --with python-rtmidi python toolkit/opzpull.py --probe --wait 60 \
     $(grep -v '^#' sergey-extraction/PATHS.txt)
   ```

   Lines are printed as `OK <path> <bytes>` or `MISSING <path> (reason)`.

5. **Re-run without `--probe`**, restricted to whatever came back `OK`, to actually save the files:

   ```bash
   uv run --with mido --with python-rtmidi python toolkit/opzpull.py --wait 60 \
     engines/saw013a.engine engines/chord.engine          # <- replace with the OK lines
   ```

   Files land under `pulled/`.

6. Meanwhile, paste us the raw output of the `--probe` run — even an all-`MISSING` result is informative,
   because it tells us whether the service is whitelisted.

**Known caveat:** in an earlier session on the broken unit, `settings/plugPresets.dat` and several
audio/engine paths did not return part 0 while the two settings files kept working. That may mean the service
only serves a known file table, or that those earlier paths were simply wrong. The candidate list above exists
precisely to distinguish those two cases. A `MISSING` result is *not* proof a file is absent.

---

## Route 3 — if Routes 1 and 2 both fail

Neither route is destructive, so trying them costs nothing. If they fail, the remaining options need either
firmware work from us or hardware:

- **Console file READ — WORKING. This is now the cheapest route, and it needs no content mode and no SysEx.**
  The update-mode console does have a file-read command. It was previously written off here as "CLOSED, no route"
  on the strength of a type sweep that sent *empty* payloads — but a command that needs a filename argument stays
  silent when sent an empty payload, which is exactly what happened. The command is:

  | | |
  |---|---|
  | request type | `0x19` |
  | reply type | `0x20`, payload = the file contents |
  | payload | one NUL-terminated path, **relative to `/yaffs2/`** |

  So `/yaffs2/system/content/engines/chord.engine` is requested as the string
  `system/content/engines/chord.engine`. The file comes back as a sequence of `0x20` frames; concatenating their
  payloads in arrival order reproduces the file exactly. Verified byte-exact against files we already held, from
  1,428 bytes up to 706,990 bytes, so the reassembly is trustworthy at any size.

  **It is read-only.** It opens the file, reads it, streams it, closes it. It cannot write, move or delete
  anything, so it is safe to send repeatedly and safe to batch across many paths.

  **Send ONLY type `0x19`.** Blind probing of neighbouring type bytes is how our own unit was bricked, and the
  console is far more dangerous than one format command. Nine type bytes write or execute: `0x10` writes SPI
  flash, `0x14` formats SPI flash, `0x15` formats NAND (this is what destroyed our unit), `0x23` is the upgrade
  path, `0x29` is a filesystem operation, `0x34` is a flash operation, `0x37` relocates a file, `0x3b` sets the
  clock, and **`0x31` loads code into RAM and executes it** — a general code-execution channel needing no file
  and no power cycle. The read-only types are `0x00`, `0x02`, `0x07`, `0x17`, `0x19`, `0x21`, `0x27`, `0x35` and
  `0x39`, and nothing outside that list is safe to send. `0x19` specifically is not a NAND command; the earlier
  guess that it belonged to a "NAND family, do not send" set was wrong, but that set was also incomplete and
  must not be used as a guide to what is safe.

  Two practical notes for whoever runs it: opening the serial port resets it and **the first frame written is
  lost**, so send a `0x00` PING first and only then the read command; and a wrong path produces **no reply at
  all**, just an `ENOENT` line in the console's log frames (routing `0x1E`, type `0x04`).

  Known state on the broken unit: `system/content/engines/{chord,digital,electric,fm003b,ministringshort,
  saw013a,tapetwo,volt}.engine` all return nothing, so those eight are **measured absent** from that unit's
  `/yaffs2/system/content/engines/`. A control request for `crush.engine` returns 1,212 bytes, so the path form
  and the command are both working — the eight are genuinely not there. Running the same eight read requests on
  a **healthy** unit is the single most informative test available and takes about a minute.
- **A directory listing.** The read command needs an exact path, so unknown filenames still need either a listing
  primitive or a path guess. Several console handlers remain unread (`0x10`, `0x14`, `0x17`, `0x31`, `0x23`,
  `0x27`, `0x32`, `0x34`) and one of them may enumerate; failing that, candidate paths can simply be tried with
  `0x19`, which is free because it writes nothing.
- **A repacked firmware that exports the system content into the user area.** The firmware is unsigned and can
  be repacked and re-encrypted, so we can build an image whose only job is to copy
  `/yaffs2/system/content/{engines,samplepacks}` into the user tree — after which a normal content-mode copy
  retrieves it. Needs work on our side, then one flash on yours. Largely superseded by the read command above.
- **JTAG on the 3x2 pad array.** Reads the whole NAND and therefore everything, but needs the debug port wired
  up and the I/O rail voltage measured first.

**Warning about the other console command you may see mentioned: `0x37`.** It looks like a file copy and it is
not — it is a **move/rename** inside `/yaffs2`, with source and target both taken from the payload. Using it
moves a file out of its real location, and if the unit is powered off before it is moved back, the file can be
lost. It has no copy mode. Do not use it for extraction now that `0x19` exists.

---

## Please don't send

Anything personal. The content disk also holds your own projects, bounces and imported samples — strip those,
we only need factory content. Also please don't paste anything from a private conversation; the pack and engine
*names* and the listing output are all we need.

## What to send back

1. The **recursive listing with sizes** (Route 1, step 2) — needed regardless.
2. The **`--probe` output** (Route 2, step 4).
3. Any files that came back `OK`, or the content-disk copy if Route 1 worked.
4. Your **firmware version** and whether the unit is factory-untouched, so the packs are known to match
   1.2.40/1.2.45.
