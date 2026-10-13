# Automate OP-Z bootloader oracle capture with an Arduino relay

## Context

`toolkit/opzbootprobe.py` stages one bounded probe, captures and decodes the console leak, persists range state, and waits for the update volume. The device accepts only one probe per boot; after a read, a genuine power cycle is needed to restore the volume. The user reports that interrupting OP-Z power through the relay turns it fully off even with USB connected. The full off/on, update-mode return, and cycle timing still need an end-to-end check.

Goal: automate resumable recovery of the compressed `bootloader.ldr` stream, targeting a complete probe-to-next-volume cycle of at most 20 seconds. This plan authorizes no device action by itself.

## Steps

- [x] Confirmed by the user: the proposed relay power cut turns the OP-Z off even while USB is connected.
- [ ] Confirm the relay can restore power and the device returns as `OP-Z Boot` with a fresh update volume; record off-time and boot/remount time. Use a current-rated, isolated control interface and keep the Arduino powered independently.
- [ ] Add an opt-in Arduino relay control to `toolkit/opzbootprobe.py`; preserve current manual behavior by default. Trigger one power cycle only after the probe capture and state have been saved, then wait for the CDC console and update volume before staging again. Keep the existing `0x15` prohibition and never send reset commands to the OP-Z.
- [ ] Stop capture after a complete decoded leak frame, while retaining the timeout path and raw capture. The current 20-second capture window alone exceeds the 20-second end-to-end target; measure from one volume-ready event to the next.
- [ ] Keep the run resumable and bounded: retain explicit probe/time limits, stop safely on relay errors, unexpected USB identity, missing volume, or an over-budget cycle, and provide a way to continue batches without manual intervention.
- [ ] Add device-free tests for relay command/ack handling, capture-before-power-cycle ordering, saved-state resume, timeout/error stops, and the early-stop-on-complete-frame path.
- [ ] Run one supervised probe cycle, then a short multi-cycle pilot. Verify each cycle logs the probe offset/mask, captured bytes, leak timing, relay action, next-volume detection, and total cycle time; confirm no existing files are overwritten and the decode farm remains disabled.
- [ ] Run the full bounded campaign, preserving raw captures and state outside the device. Resume automatically after a process interruption; stop and retain evidence rather than retrying indefinitely on any unexpected behavior.
- [ ] Validate the completed compressed stream by raw-DEFLATE decompression and the archive entry's expected uncompressed size and CRC. Only then scan the full bootloader plaintext for 32-byte AES-key candidates and verify candidates against known archive data.
- [ ] Document measured cycle time, probe yield, total runtime, and key-search result in `FIRMWARE_ANALYSIS.md` and `HYPOTHESES.csv`.

## Acceptance criteria

- No manual button presses, unplug/replug steps, or volume remounts are needed during the pilot and full run.
- Every probe is saved in resumable state before power is cut; failures stop safely without discarding prior captures.
- The pilot demonstrates the agreed 20-second maximum from volume-ready to next volume-ready; report any exceptions rather than assuming the bound.
- The complete `bootloader.ldr` DEFLATE stream passes size and CRC validation before any key-search conclusion is recorded.

## Boundaries

- Do not issue OP-Z console command `0x15` (NAND format), install or modify engines, alter firmware, or stage a genuine firmware upgrade as a reboot workaround.
- Do not commit firmware binaries, raw device captures, or other large artifacts; retain them in the existing local probe-state directory.
- If the relay fails to produce a verified power cycle, or the 20-second limit cannot be met reliably, stop and report the measured blocker before attempting the long campaign.
