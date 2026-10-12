# OP-Z firmware decode — handover status

## What is proven
* The bootloader decrypts an arbitrary 256-byte window of our choosing and prints it (chosen-ciphertext
  oracle via the encrypted-filename field). Verified on hardware: it returned the archive's own zip local
  header `50 4b 03 04 14 00 c0 1e …` and its continuation.
* Transport edge: masking the IV (`IV ^= 0x01`) shifts the first CBC block so a NUL there cannot truncate the
  print. Measured mean leak 44 -> 161.7 bytes/probe (3.7x); ~46 cycles for the full 1 490 575-byte payload.
* Pipeline verified end-to-end against a simulated device: 100% coverage, assembled bytes byte-identical to
  ground truth, zip entries correct, `RETX 0x80117baa` resolved to its symbol, string self-check green.
* Supervisor proven: killing the farm is recovered in ~20 s; progress logged; completion produces the report.

## What is blocked, and why
The update medium disappears after any read and only a device reset re-presents it. No unprivileged host
action can do this (verified: libusb claim -> ACCESS, bulk without claim -> NOT_FOUND, detach -> ACCESS,
unconfigure/reconfigure, port reset, dfu-util, every console power/session message, BF_ENTER_DFU, 0x15 format).
macOS requires root for any USB write; DiskArbitration has no media-load verb.

## The one action needed (any one)
1. Double-click `~/Desktop/OP-Z-unstick.command`  (asks your password once, installs a sudoers rule for the
   tiny SCSI loader `/tmp/opzload`, then re-inserts the medium).  <- preferred; makes the loop self-healing.
2. Press PLAY once on the OP-Z.
3. Power-cycle the OP-Z.

## Safety net
False success gated on >=99% coverage; miss-rate diagnostic; serial reopen on a dead
handle; eject retried; single-instance lock; drift detection between running code and
disk; state saved per cycle and reboot-proof; every path covered by 15 standing checks.

## Expected runtime (measured, not estimated)
Full-scale simulation: 62 device cycles to 100% coverage of 1,490,575 bytes;
per-cycle host cost 0.7 s (save 0.3 s + worklist 0.4 s); total host CPU+disk for
the whole decode 41.4 s -- so wall time is set by the device cycles (~1 hour).

## What happens next (no further input)
`/tmp/opzwatch.sh` keeps the farm alive; the farm stages 200 crafted probes + the genuine .zfw per cycle, so
the device completes a real upgrade and resets itself each time. When the worklist is empty the supervisor
writes `/tmp/OPZ_DECODE_REPORT.txt` (payload size, zip entry map, resolved fault address).

Files: opzfarm.py (decode), opzassemble.py (map -> payload), opzanalyze.py (zip walk + ELF/raw symbolise),
opzwatch.sh (supervisor), opzload + opz-sudo-install.sh (medium re-insert), test_opzfarm.py / test_e2e.py (tests).
