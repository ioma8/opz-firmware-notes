#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pyserial", "pycryptodome"]
# ///
"""Collect a bounded byte range from the OP-Z update-mode filename oracle.

Example: uv run --script toolkit/opzbootprobe.py --start 467296 --length 64 --max-probes 4
Each probe is one boot cycle, but the tool never power-cycles: it stages a probe,
ejects the volume and captures the console, then waits for you (or the relay plan)
to bring the unit back up. It never cleans the disk or sends console commands.

After every probe it re-inflates the recovered bootloader.ldr prefix and tests
each new 32-byte window as an AES key, halting the run on a match. Use
--key-scan-only to run that scan alone over already-saved probe state, which
works even if the original .zfw is gone.

Exit status: 0 = the AES key was found (written to KEY-FOUND.txt), 3 = a collection
run whose requested range finished and holds no key, 2 = the range is incomplete or
the probe budget was spent, 1 = error. A driver can re-invoke on 2 and stop on 0 or
3. An offline scan reports only 0 or 2.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import zlib
from pathlib import Path

from opzframe import FRAME_MAX, frames

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "z_firmware_1_2_45.zfw"
VOLUME = Path("/Volumes/OP-Z")
PROBE_NAME = "z_firmware_probe_000.zfw"
LEAK_PREFIX = b"failed to find .zip file in "
sys.path.append(str(ROOT))       # reuses opzkeymine.check(), the verified AES oracle
DEFLATE_START = 467573           # firmware/blackfin/bin/bootloader.ldr deflate stream
KEY_PATH = "KEY-FOUND.txt"
EXIT_KEY_FOUND, EXIT_ERROR, EXIT_INCOMPLETE, EXIT_COMPLETE_NO_KEY = 0, 1, 2, 3
PREFIX_PATH = "plaintext-prefix.json"


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
            "terminator_inferred": bool(terminated and not capped and len(data) < 16),
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


def atomic_write(path, data):
    """Write bytes atomically, so a crash cannot leave a half-written artifact."""
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(bytes(data))
    os.replace(tmp, path)


def save_state(path, state):
    atomic_write(path, (json.dumps(state, indent=2) + "\n").encode())


def load_bytes(directory, source_sha256):
    """Union the byte maps of the saved probe states that belong to this source firmware.

    State files are keyed only by range, so a run against a different --source in the same
    --output directory would otherwise be merged at the same payload offsets.
    """
    merged = {}
    for path in sorted(directory.glob("state-*.json")):
        state = json.loads(path.read_text())
        if state.get("source_sha256") != source_sha256:
            continue
        repair_state(state)   # the live run repairs before probing; the offline scan must too
        merged.update(state["bytes"])
    return merged


def scan_source_hash(args):
    """The source hash for an offline scan.

    Falls back to the single source recorded in the state files, so a scan still runs after the
    original .zfw has been deleted.
    """
    if args.source.exists():
        return hashlib.sha256(args.source.read_bytes()).hexdigest()
    found = {json.loads(p.read_text()).get("source_sha256") for p in args.output.glob("state-*.json")}
    found.discard(None)
    if len(found) != 1:
        raise SystemExit(f"--source {args.source} not found and {args.output} holds {len(found)} "
                         f"distinct source firmwares; pass --source explicitly")
    return found.pop()


def contiguous(bytes_map, start):
    out = bytearray()
    while str(start + len(out)) in bytes_map:
        out.append(bytes_map[str(start + len(out))])
    return bytes(out)


_LAST_INFLATE_ERROR = None


def inflate(raw):
    """Inflate as much of a truncated raw-DEFLATE stream as possible.

    A corrupt byte anywhere in the recovered stream would otherwise throw and zero the whole
    prefix, silently disabling the key scan for the rest of the campaign.
    """
    global _LAST_INFLATE_ERROR
    try:
        return zlib.decompressobj(-15).decompress(raw)
    except zlib.error as error:
        if str(error) != _LAST_INFLATE_ERROR:   # do not repeat one warning on every probe
            _LAST_INFLATE_ERROR = str(error)
            print(f"inflate error ({error}); salvaging the prefix before the bad byte", flush=True)
    obj, out = zlib.decompressobj(-15), bytearray()
    for i in range(0, len(raw), 64):
        try:
            out += obj.decompress(raw[i:i + 64])
        except zlib.error:
            break
    return bytes(out)


TESTED_UPTO = -1
_LAST_PLAINTEXT = None
_WARNED_DIVERGENCE = None


def check_prefix_stable(plaintext):
    """DEFLATE output is prefix-stable, so a later probe may only ever append.

    Any change to the already-recovered prefix proves an earlier byte was mis-decoded. Nothing
    else in this tool can detect that, and the failure mode is not a crash: the campaign would
    scan garbage for hours and then report "no key in the bootloader", which would be false.
    This is the check that would have caught the masked-NUL bug immediately instead of by
    accident (a stalled probe).
    """
    global _LAST_PLAINTEXT
    previous, _LAST_PLAINTEXT = _LAST_PLAINTEXT, plaintext
    if previous is None:
        return True
    at = first_divergence(previous, plaintext)
    if at is not None:
        print(f"*** INTEGRITY: recovered plaintext changed at inflated offset {at}: "
              f"was {previous[at]:02x}, now {plaintext[at]:02x}. An earlier probe was "
              f"mis-decoded, so 'no key' is NOT trustworthy -- re-verify the run ***",
              flush=True)
        return False
    return True


def first_divergence(previous, current):
    """Inflated offset of the first byte that disagrees, or None if one is a prefix of the other."""
    for i in range(min(len(previous), len(current))):
        if previous[i] != current[i]:
            return i
    return None


def check_prefix_persisted(plaintext, path, source_sha256):
    """Re-verify the recovered prefix against the digest left by an earlier process.

    check_prefix_stable only covers one process and the --max-probes cap forces the campaign
    through many restarts, so without this the first probe of every run would be unguarded.
    When the digest matches, the tested-window counter is restored too: windows depend only on
    the plaintext, so a verified prefix makes the old counter valid again and a rescan is wasted.
    """
    global TESTED_UPTO, _WARNED_DIVERGENCE
    saved = json.loads(path.read_text()) if path.exists() else None
    if saved and saved.get("source_sha256") != source_sha256:
        saved = None
    if saved and len(plaintext) >= saved["length"]:
        if hashlib.sha256(plaintext[:saved["length"]]).hexdigest() != saved["sha256"]:
            if saved["sha256"] != _WARNED_DIVERGENCE:    # warn once per bad digest, not per probe
                _WARNED_DIVERGENCE = saved["sha256"]
                print(f"*** INTEGRITY: the recovered prefix disagrees with the {saved['length']}-byte "
                      f"digest saved by an earlier run, so a probe was mis-decoded across a restart. "
                      f"'No key' is NOT trustworthy -- re-verify the run ***", flush=True)
            return False
        TESTED_UPTO = max(TESTED_UPTO, saved.get("tested_upto", -1))
    return True


def save_prefix_digest(path, plaintext, source_sha256):
    """Record the verified prefix so a later process can re-check it and skip the rescan."""
    atomic_write(path, json.dumps({"source_sha256": source_sha256, "length": len(plaintext),
                                   "tested_upto": TESTED_UPTO,
                                   "sha256": hashlib.sha256(plaintext).hexdigest()}).encode())


def exit_status(found_key, complete):
    """0 = the key was found, 3 = the range finished without one, 2 = still incomplete."""
    if found_key:
        return EXIT_KEY_FOUND
    return EXIT_COMPLETE_NO_KEY if complete else EXIT_INCOMPLETE


def scan_for_key(plaintext, key_path):
    """Test every not-yet-tested 32-byte window of the inflated bootloader."""
    global TESTED_UPTO
    from opzkeymine import check
    last = len(plaintext) - 32
    if last < 0:
        return None, 0
    if last < TESTED_UPTO:   # the plaintext shrank (a state file went away); rescan from the start
        TESTED_UPTO = -1
    if last == TESTED_UPTO:
        return None, 0
    tested = 0
    for i in range(TESTED_UPTO + 1, last + 1):
        tested += 1
        window = plaintext[i:i + 32]
        result = check(window)
        if result and not result.startswith("HEURISTIC:"):
            # the real key always satisfies the hardware-verified ZIP-header test, so a
            # heuristic-only hit is a coincidence in the filename branch, not the key
            atomic_write(key_path, f"inflated_offset={i}\nkey={window.hex()}\nresult={result}\n".encode())
            return window.hex(), tested
    TESTED_UPTO = last
    return None, tested


def scan_saved(directory, member_start, source_sha256):
    """Re-inflate the recovered prefix and test new key windows. Returns key hex or None."""
    raw = contiguous(load_bytes(directory, source_sha256), member_start)
    if not raw:
        print(f"key scan: no recovered bytes at or after payload offset {member_start}", flush=True)
        return None
    plaintext = inflate(raw)
    stable = check_prefix_stable(plaintext)
    persisted = check_prefix_persisted(plaintext, directory / PREFIX_PATH, source_sha256)
    found, tested = scan_for_key(plaintext, directory / KEY_PATH)
    if stable and persisted:      # never overwrite a good digest with a divergent prefix
        save_prefix_digest(directory / PREFIX_PATH, plaintext, source_sha256)
    print(f"key scan: {len(raw)} deflate bytes -> {len(plaintext)} inflated, "
          f"{tested} new windows tested", flush=True)
    if found:
        print(f"*** AES KEY FOUND: {found} ***", flush=True)
    return found


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
    atomic_write(raw_path, capture)
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


def self_test_keys():
    """The key scan must find a planted key at its exact offset and resume incrementally."""
    global TESTED_UPTO, _LAST_PLAINTEXT
    import contextlib
    import io
    import opzkeymine
    from Crypto.Cipher import AES
    key = hashlib.sha256(b"opz-selftest").digest()
    saved = (opzkeymine.IV, opzkeymine.C0, opzkeymine.IV2, opzkeymine.C2)
    saved_check = opzkeymine.check
    opzkeymine.IV2 = bytes(16)                                     # synthetic oracle that
    opzkeymine.C2 = AES.new(key, AES.MODE_ECB).encrypt(opzkeymine.WANT2)   # accepts only `key`
    path = Path("/tmp/opz-key-selftest.txt")
    try:
        plaintext = bytes(range(256)) * 3 + key + b"\xff" * 40
        TESTED_UPTO = -1
        assert scan_for_key(plaintext, path) == (key.hex(), 769), "planted key not found at 768"
        assert path.read_text().startswith("inflated_offset=768\n")
        TESTED_UPTO = -1
        assert scan_for_key(plaintext[:768], path) == (None, 737), "matched a key that is not there"
        assert scan_for_key(plaintext, path) == (key.hex(), 32), "resume did not test only new windows"
        assert scan_for_key(plaintext[:100], path) == (None, 69), "shrunk plaintext did not rescan"
        opzkeymine.check = lambda window: "HEURISTIC:nope"     # must not stop the campaign
        TESTED_UPTO = -1
        assert scan_for_key(plaintext, path) == (None, 809), "a heuristic hit halted the run"
        assert contiguous({"5": 0xAA, "6": 0xBB, "8": 0xCC}, 5) == b"\xaa\xbb"
        assert contiguous({}, 5) == b""
        data = b"".join(hashlib.sha256(str(i).encode()).digest() for i in range(32))
        comp = zlib.compressobj(9, zlib.DEFLATED, -15)
        stream = comp.compress(data) + comp.flush()
        assert inflate(stream) == data, "a complete stream must round-trip"
        half = inflate(stream[:len(stream) // 2])
        assert half and data.startswith(half), "a truncated stream must still yield a prefix"
        assert inflate(b"\xff\xff\xff\xff") == b"", "garbage must not raise"
        _LAST_PLAINTEXT = None
        assert check_prefix_stable(b"abcdef") is True, "first sighting must pass"
        assert check_prefix_stable(b"abcdefgh") is True, "growth must pass"
        assert first_divergence(b"abcdefgh", b"abXdefgh") == 2, "divergence offset must be exact"
        assert first_divergence(b"abc", b"abc") is None, "an identical prefix must not diverge"
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            assert check_prefix_stable(b"abXdefgh") is False, "a changed prefix byte must be caught"
        assert "INTEGRITY" in captured.getvalue(), "the integrity warning must be emitted"
        pref = Path("/tmp/opz-prefix-selftest.json")
        pref.unlink(missing_ok=True)
        assert check_prefix_persisted(b"abcdef", pref, "s") is True, "no digest yet must pass"
        save_prefix_digest(pref, b"abcdef", "s")
        assert check_prefix_persisted(b"abcdefgh", pref, "s") is True, "growth must still match"
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            assert check_prefix_persisted(b"abXdefgh", pref, "s") is False, "cross-run divergence missed"
        assert "INTEGRITY" in captured.getvalue()
        assert check_prefix_persisted(b"abcdefgh", pref, "other") is True, "another source must not compare"
        TESTED_UPTO = 500
        save_prefix_digest(pref, b"abcdefgh", "s")
        TESTED_UPTO = -1
        assert check_prefix_persisted(b"abcdefgh", pref, "s") is True
        assert TESTED_UPTO == 500, "the tested-window counter must be restored on a matching digest"
        TESTED_UPTO = -1
        pref.unlink(missing_ok=True)
        replays = replay_real_captures()
        assert replays > 0, "no real capture was replayed"
    finally:
        opzkeymine.IV, opzkeymine.C0, opzkeymine.IV2, opzkeymine.C2 = saved
        opzkeymine.check = saved_check
        TESTED_UPTO = -1
        path.unlink(missing_ok=True)
    print("key-scan self-test passed")


def replay_real_captures():
    """Re-decode every real device capture and require the saved state to match exactly.

    This is the closest thing to a hardware test that runs without the device: it replays genuine
    console bytes through the decoder and compares against what the run recorded at the time.
    """
    directory = Path.home() / ".opz-decode/bootloader-probes"
    replayed = 0
    for state_path in sorted(directory.glob("state-*.json")):
        for read in json.loads(state_path.read_text())["reads"]:
            capture = Path(read.get("capture", ""))
            if not capture.exists():
                continue
            got = [x["hex"] for x in decode_leaks(capture.read_bytes(), read["window_offset"],
                                                  read.get("mask_delta", 1))]
            want = [x["hex"] for x in read["leaks"]]
            assert got == want, (f"{state_path.name} cycle {read['cycle']} at {read['window_offset']}: "
                                 f"replay {got} != recorded {want}")
            replayed += 1
    print(f"real-capture replay: {replayed} cycles decoded identically")
    return replayed


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
    assert leaks[0]["terminator_inferred"] is False, "a NUL past byte 16 is observed, not inferred"
    assert (exit_status(True, False), exit_status(False, True), exit_status(False, False)) == (0, 3, 2)
    assert all(not decode_leaks(capture[:end], 467296) for end in range(len(capture)))

    # A mask can itself create the string terminator: plaintext 1 XOR delta 1 is NUL.
    blocked = bytes([0x20, 0x22, 0x30, 0x40, 0x50, 0x60])
    payload = b"\0\0\0\0" + LEAK_PREFIX + bytes(b ^ 1 for b in blocked) + b"\0"
    leak = decode_leaks(encode_frame(payload), 467808)[0]
    assert leak["hex"] == blocked.hex() and leak["terminator_value"] == 1
    assert leak["terminator_inferred"] is True, "a masked-NUL terminator is inferred from delta"
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
    self_test_keys()
    print("self-test passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     epilog="exit status: 0 key found, 3 range complete without one, "
                                            "2 incomplete, 1 error")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--start", type=int, default=467296, help="archive payload offset")
    parser.add_argument("--length", type=int, default=64, help="bytes to collect")
    parser.add_argument("--max-probes", type=int, default=1, help="hard per-run cycle limit (1..64)")
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--capture-seconds", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path.home() / ".opz-decode/bootloader-probes")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--key-member-start", type=int, default=DEFLATE_START,
                        help="payload offset of the bootloader.ldr deflate stream")
    parser.add_argument("--key-scan-only", action="store_true",
                        help="scan saved probe state for the AES key and exit")
    args = parser.parse_args()
    if args.self_test:
        self_test(args.source.read_bytes())
        return EXIT_KEY_FOUND                 # 0 = success
    if args.key_scan_only:
        args.output.mkdir(parents=True, exist_ok=True)
        source_hash = scan_source_hash(args)
        return (EXIT_KEY_FOUND if scan_saved(args.output, args.key_member_start, source_hash)
                else EXIT_INCOMPLETE)
    source = args.source.read_bytes()
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
    found_key = False
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
        if scan_saved(args.output, args.key_member_start, source_hash):
            print("Halting: the AES key is in the recovered prefix.", flush=True)
            found_key = True
            break
        if got < args.length:
            print("Waiting automatically for the update volume before the next probe.")
    covered = [str(i) in state["bytes"] for i in range(args.start, end)]
    complete = sum(covered) == args.length
    print(f"saved {sum(covered)}/{args.length} bytes in {state_path}"
          f"{' (range complete)' if complete else ' (range INCOMPLETE - re-invoke to continue)'}")
    if args.length <= 128:
        final = bytes(state["bytes"].get(str(i), 0) for i in range(args.start, end))
        print("range hex:", " ".join(f"{b:02x}" if ok else "??" for b, ok in zip(final, covered)))
    return exit_status(found_key, complete)


if __name__ == "__main__":
    raise SystemExit(main())
