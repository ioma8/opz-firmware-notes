#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyserial"]
# ///
"""Collect a bounded byte range from the OP-Z update-mode filename oracle.

Example: uv run --script toolkit/opzbootprobe.py --start 467296 --length 64 --max-probes 4
Each probe is one boot cycle. After capture, the script automatically polls for
the update volume before staging the next probe. It never cleans the disk or
sends console commands.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from opzframe import FRAME_MAX, frames

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "z_firmware_1_2_45.zfw"
VOLUME = Path("/Volumes/OP-Z")
PROBE_NAME = "z_firmware_probe_000.zfw"
LEAK_PREFIX = b"failed to find .zip file in "


def align16(n):
    return n - n % 16


def make_probe(source, offset, delta=1):
    payload_len = int.from_bytes(source[0x80:0x84], "little")
    offset = align16(offset)
    if offset < 0 or offset >= payload_len or 0x400 + offset + 16 > len(source):
        raise ValueError(f"payload offset out of range: {offset}")
    start = 0x400 + offset
    window = source[start:start + 256].ljust(256, b"\0")
    probe = bytearray(source[:0x400])
    probe[0x70:0x80] = bytes(b ^ delta for b in source[start - 16:start])
    probe[0x300:0x400] = window
    return bytes(probe + source[0x400:0x420]), offset


def decode_leaks(capture, offset, delta=1):
    out = []
    for _, _, _, payload in frames(capture):
        at = payload.find(LEAK_PREFIX)
        if at < 0:
            continue
        tail = payload[at + len(LEAK_PREFIX):]
        capped = len(payload) >= FRAME_MAX
        nul = tail.find(b"\0")
        terminated = nul >= 0
        data = tail if nul < 0 else tail[:nul]
        marker = capped and data.endswith(b"..")
        if marker:
            data = data[:-2]
        decoded = bytearray(data)
        for i in range(min(16, len(decoded))):
            decoded[i] ^= delta
        out.append({
            "offset": offset,
            "frame_payload_length": len(payload),
            "capped": capped,
            "truncation_marker_removed": marker,
            "terminated_by_nul": terminated,
            "terminator_value": (delta if len(data) < 16 else 0) if terminated and not capped else None,
            "hex": bytes(decoded).hex(),
            "bytes": bytes(decoded),
        })
    return out


def check_no_farm():
    processes = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    if "opzfarm.py" in processes or "opzautocycle.py" in processes:
        raise RuntimeError("an OP-Z decode farm is still running; stop it before probing")
    jobs = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    if "com.opz.decode" in jobs:
        raise RuntimeError("launchd job com.opz.decode is loaded; unload it before probing")


def wait_for_volume(timeout):
    deadline = time.monotonic() + timeout
    if not (VOLUME / "systeminfo").is_dir():
        print(f"Waiting up to {timeout}s for {VOLUME} ...", flush=True)
    while time.monotonic() < deadline:
        if (VOLUME / "systeminfo").is_dir():
            detected_at = time.monotonic()
            print("Update volume ready.", flush=True)
            return detected_at
        time.sleep(1)
    raise TimeoutError(f"{VOLUME} did not mount within {timeout}s")


def console_port():
    ports = sorted(Path("/dev").glob("cu.usbmodem*"))
    if len(ports) != 1:
        raise RuntimeError(f"expected one OP-Z CDC port, found: {ports}")
    return str(ports[0])


def next_missing(state, start, end):
    known = state["bytes"]
    for offset in range(start, end):
        if str(offset) not in known:
            return align16(offset)
    return None


def choose_delta(state, offset):
    used = {r.get("mask_delta", 1) for r in state["reads"] if r["window_offset"] == offset}
    known = {state["bytes"][str(offset + i)] for i in range(16)
             if str(offset + i) in state["bytes"]}
    return next((d for d in range(1, 256) if d not in used and d not in known), None)


def apply_leak(state, leak):
    offset, data = leak["offset"], leak["bytes"]
    for i, byte in enumerate(data):
        state["bytes"][str(offset + i)] = byte
    if leak["terminator_value"] is not None:
        state["bytes"][str(offset + len(data))] = leak["terminator_value"]


def repair_state(state):
    """Rebuild the byte map so legacy masked-block NULs are not recorded as zero."""
    rebuilt = {}
    for read in state["reads"]:
        delta = read.get("mask_delta", 1)
        for leak in read["leaks"]:
            data = bytes.fromhex(leak["hex"])
            offset = leak["offset"]
            for i, byte in enumerate(data):
                rebuilt[str(offset + i)] = byte
            if leak["terminated_by_nul"] and not leak["capped"]:
                rebuilt[str(offset + len(data))] = delta if len(data) < 16 else 0
    for offset, byte in state["bytes"].items():
        rebuilt.setdefault(offset, byte)
    state["bytes"] = rebuilt


def save_state(path, state):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, path)


def one_cycle(source, output, state_path, state, offset, delta, cycle, wait_seconds, capture_seconds):
    volume_detected_at = wait_for_volume(wait_seconds)
    check_no_farm()
    names = []
    with os.scandir(VOLUME) as entries:
        names = [entry.name for entry in entries]
    zfws = [name for name in names if name.lower().endswith(".zfw")]
    if zfws:
        raise RuntimeError(f"refusing to compete with existing firmware files: {zfws}")

    probe, offset = make_probe(source, offset, delta)
    target = VOLUME / PROBE_NAME
    if target.exists():
        raise RuntimeError(f"refusing to overwrite {target}")
    old_sidecar = VOLUME / ("._" + PROBE_NAME)
    if old_sidecar.exists():
        raise RuntimeError(f"refusing to overwrite {old_sidecar}")

    import serial
    port = serial.Serial(console_port(), 115200, timeout=0.25)
    try:
        port.reset_input_buffer()
        os.environ["COPYFILE_DISABLE"] = "1"
        with target.open("xb") as stream:
            stream.write(probe)
            stream.flush()
            os.fsync(stream.fileno())
        if old_sidecar.exists():
            old_sidecar.unlink()  # only this probe's own macOS sidecar
        with os.scandir(VOLUME) as entries:
            staged = [entry.name for entry in entries if entry.name.lower().endswith(".zfw")]
        if staged != [PROBE_NAME]:
            raise RuntimeError(f"expected only our probe on the disk, found: {staged}")

        eject = subprocess.run(["diskutil", "eject", str(VOLUME)], capture_output=True, text=True)
        if eject.returncode:
            raise RuntimeError("safe eject failed; probe remains staged:\n" + eject.stdout + eject.stderr)

        capture = bytearray()
        leak_received_at = None
        deadline = time.monotonic() + capture_seconds
        while time.monotonic() < deadline:
            try:
                if not port.is_open:
                    raise serial.SerialException("console port closed")
                chunk = port.read(4096)
                if chunk:
                    capture.extend(chunk)
                    if leak_received_at is None and decode_leaks(bytes(capture), offset, delta):
                        leak_received_at = time.monotonic()
            except serial.SerialException as error:
                print(f"Console disconnected ({error}); reopening.", flush=True)
                port.close()
                port = None
                while time.monotonic() < deadline:
                    try:
                        port = serial.Serial(console_port(), 115200, timeout=0.25)
                        break
                    except (serial.SerialException, RuntimeError):
                        time.sleep(0.5)
                if port is None:
                    break
    finally:
        if port is not None:
            port.close()

    capture_finished_at = time.monotonic()
    raw_path = output / f"cycle-{len(state['reads']) + 1:03d}-offset-{offset}.bin"
    raw_path.write_bytes(capture)
    leaks = decode_leaks(bytes(capture), offset, delta)
    record = {
        "cycle": cycle,
        "requested_offset": offset,
        "window_offset": offset,
        "mask_delta": delta,
        "probe_sha256": hashlib.sha256(probe).hexdigest(),
        "capture": str(raw_path),
        "capture_bytes": len(capture),
        "seconds_from_volume_to_leak": (round(leak_received_at - volume_detected_at, 3)
                                         if leak_received_at is not None else None),
        "capture_duration_seconds": round(capture_finished_at - volume_detected_at, 3),
        "leaks": [],
    }
    for leak in leaks:
        record["leaks"].append({k: v for k, v in leak.items() if k != "bytes"})
        apply_leak(state, leak)
    state["reads"].append(record)
    save_state(state_path, state)
    return record


def encode_frame(payload):
    escaped = payload.replace(b"\x7d", b"\x7d\x5d").replace(b"\xc0", b"\x7d\xe0")
    return b"\xc0\x1e\x04" + len(payload).to_bytes(4, "big") + escaped


def self_test(source):
    probe, offset = make_probe(source, 467296)
    assert offset == 467296 and len(probe) == 0x420
    start = 0x400 + offset
    assert probe[0x300:0x400] == source[start:start + 256]
    assert probe[0x70:0x80] == bytes(b ^ 1 for b in source[start - 16:start])
    # Check CBC first-block unmasking with a synthetic, escaped console frame.
    plain = bytes(range(2, 18)) + b"header-tail"
    encoded = bytes(b ^ 1 for b in plain[:16]) + plain[16:]
    payload = b"\0\0\0\0" + LEAK_PREFIX + encoded + b"\0"
    capture = encode_frame(payload)
    leaks = decode_leaks(capture, 467296)
    assert leaks and leaks[0]["hex"] == plain.hex()
    assert all(not decode_leaks(capture[:end], 467296) for end in range(len(capture)))

    # A mask can itself create the string terminator: plaintext 1 XOR delta 1 is NUL.
    blocked = bytes([0x20, 0x22, 0x30, 0x40, 0x50, 0x60])
    payload = b"\0\0\0\0" + LEAK_PREFIX + bytes(b ^ 1 for b in blocked) + b"\0"
    leak = decode_leaks(encode_frame(payload), 467808)[0]
    assert leak["hex"] == blocked.hex() and leak["terminator_value"] == 1
    state = {"bytes": {}, "reads": []}
    apply_leak(state, leak)
    assert state["bytes"]["467814"] == 1
    legacy = {"bytes": {"467814": 0}, "reads": [{"window_offset": 467808, "leaks": [
        {"offset": 467808, "hex": blocked.hex(), "terminated_by_nul": True, "capped": False}
    ]}]}
    repair_state(legacy)
    assert legacy["bytes"]["467814"] == 1
    state["reads"].append({"window_offset": 467808, "mask_delta": 1})
    delta = choose_delta(state, 467808)
    assert delta not in (1, *blocked)
    print("self-test passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--start", type=int, default=467296, help="archive payload offset")
    parser.add_argument("--length", type=int, default=64, help="bytes to collect")
    parser.add_argument("--max-probes", type=int, default=1, help="hard per-run cycle limit (1..64)")
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--capture-seconds", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path.home() / ".opz-decode/bootloader-probes")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    source = args.source.read_bytes()
    if args.self_test:
        self_test(source)
        return 0
    payload_len = int.from_bytes(source[0x80:0x84], "little")
    if not (0 <= args.start < payload_len and 0 < args.length <= payload_len - args.start
            and 1 <= args.max_probes <= 64):
        parser.error("requested range must fit the firmware payload; max-probes must be 1..64")

    source_hash = hashlib.sha256(source).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    state_path = args.output / f"state-{args.start}-{args.length}.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if (state["source_sha256"], state["start"], state["length"]) != (source_hash, args.start, args.length):
            parser.error(f"{state_path} belongs to a different source/range; choose another --output")
    else:
        state = {"source_sha256": source_hash, "start": args.start, "length": args.length,
                 "bytes": {}, "reads": []}
        save_state(state_path, state)

    end = args.start + args.length
    repair_state(state)
    save_state(state_path, state)
    for cycle in range(1, args.max_probes + 1):
        offset = next_missing(state, args.start, end)
        if offset is None:
            break
        delta = choose_delta(state, offset)
        if delta is None:
            raise RuntimeError(f"all useful first-block masks exhausted at payload offset {offset}")
        check_no_farm()
        before = sum(1 for n in state["bytes"] if args.start <= int(n) < end)
        record = one_cycle(source, args.output, state_path, state, offset, delta,
                           len(state["reads"]) + 1, args.wait_seconds, args.capture_seconds)
        got = sum(1 for n in state["bytes"] if args.start <= int(n) < end)
        leak_time = record["seconds_from_volume_to_leak"]
        timing = (f"decrypted after {leak_time:.3f}s from volume detection" if leak_time is not None
                  else f"no decrypted bytes in {record['capture_duration_seconds']:.3f}s")
        print(f"cycle {cycle}/{args.max_probes}: offset={offset}, mask={delta:#04x}, "
              f"capture={record['capture_bytes']} B, {timing}, new={got - before}, "
              f"leak={[(len(x['hex']) // 2, x['capped']) for x in record['leaks']]}, "
              f"range={got}/{args.length} bytes")
        if got < args.length:
            print("Waiting automatically for the update volume before the next probe.")
    covered = [str(i) in state["bytes"] for i in range(args.start, end)]
    print(f"saved {sum(covered)}/{args.length} bytes in {state_path}")
    if args.length <= 128:
        final = bytes(state["bytes"].get(str(i), 0) for i in range(args.start, end))
        print("range hex:", " ".join(f"{b:02x}" if ok else "??" for b, ok in zip(final, covered)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
