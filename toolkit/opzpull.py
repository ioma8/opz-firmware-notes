#!/usr/bin/env python3
"""Pull files off a running (normal-mode) OP-Z over its SysEx file service.

Protocol: $00 protocol-version-6 client hello -> $51 advertise -> device $34 -> host $52 (sync-active=0) ->
$35 request (requester id, file id, part) -> $53 part (sender id, file id, part, last, zlib).
File id = crc32(lowercase(path)); reserved 0/1/2 = settings/slotConfiguration.json, settings/plugs.json, syncjob.json.
"""
import sys, time, zlib, argparse, hashlib
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.opz-decode/refs/op-z-sysex'))
from opzsysex.device import Device                       # noqa: E402
from opzsysex.sysex import frame, decode_frame, state_sync_client_hello, ProtocolError  # noqa: E402
from opzsysex.fileprotocol import download_file_id       # noqa: E402

SERVER_ID = 0x4242
OUT = Path.home() / '.opz-decode/pulled'


def open_session(dev, timeout=240.0):
    # The device ignores file-sync traffic until the app-protocol hello.
    dev.send(state_sync_client_hello(SERVER_ID))
    dev.send(frame(0x51, SERVER_ID.to_bytes(2, 'little')))
    t0 = time.monotonic(); last_adv = t0
    while time.monotonic() - t0 < timeout:
        if time.monotonic() - last_adv > 1.5:             # keep ahead of the device's ~6 s expiry
            print(f"   ... re-advertising $51 (t={time.monotonic()-t0:.0f}s)", flush=True)
            dev.send(frame(0x51, SERVER_ID.to_bytes(2, 'little')))
            last_adv = time.monotonic()
        try:
            rx = dev.receive(0.4)
        except Exception:
            continue
        try:
            _f = decode_frame(rx); mid, payload = _f.message_id, _f.payload
        except ProtocolError:
            continue
        print(f"   <- ${mid:02x} {len(payload)} B {payload[:16].hex()}", flush=True)
        if mid == 0x34 and len(payload) >= 6:
            return int.from_bytes(payload[:2], 'little'), int.from_bytes(payload[2:6], 'little')
    return None, None


def keep_session_alive(dev):
    # The app-protocol and file-server sessions have independent timeouts.
    dev.send(state_sync_client_hello(SERVER_ID))
    dev.send(frame(0x52, SERVER_ID.to_bytes(2, 'little') + b'\x00'))


def pull(dev, path, client_id, state_crc, part_timeout=2.5, cap=12_000_000):
    fid = download_file_id(path)
    got = {}
    want = 0
    last_part = None
    retries = 0
    # Also refresh between short/unserved files, which may finish before the timer fires.
    keep_session_alive(dev)
    t0 = time.time(); last_hb = time.time()
    while True:
        dev.send(frame(0x35, SERVER_ID.to_bytes(2, 'little') + fid.to_bytes(4, 'little') + want.to_bytes(2, 'little')))
        deadline = time.time() + part_timeout
        while time.time() < deadline:
            if time.time() - last_hb > 1.0:
                keep_session_alive(dev)
                last_hb = time.time()
            try:
                rx = dev.receive(0.25)
            except Exception:
                continue
            try:
                _f = decode_frame(rx); mid, payload = _f.message_id, _f.payload
            except ProtocolError:
                continue
            if mid != 0x53 or len(payload) < 9:
                continue
            if int.from_bytes(payload[:2], 'little') != client_id:
                continue
            if int.from_bytes(payload[2:6], 'little') != fid:
                continue
            part = int.from_bytes(payload[6:8], 'little')
            if part < want:
                continue                                   # duplicate / earlier part
            try:
                got[part] = zlib.decompress(payload[9:])
            except Exception:
                continue
            if payload[8] == 1:
                last_part = part
            if part == want:
                retries = 0
                want += 1
                while want in got:
                    want += 1
                if sum(len(v) for v in got.values()) > cap:
                    return b'', 'exceeds cap'
            if last_part is not None and want > last_part:
                data = b''.join(got[i] for i in range(last_part + 1))
                return data, f"{last_part+1} parts in {time.time()-t0:.1f}s (final flag verified)"
            break
        else:                                              # retry the missing cursor, never save partial data
            if not got:
                return b'', 'not served (no part 0)'
            retries += 1
            if retries >= 2:
                return b'', f'incomplete: missing part {want} or final flag'
        # continue: either the sender auto-advanced or we just requested the next part


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--match', default='OP-Z')
    ap.add_argument('--probe', action='store_true', help='print availability only, do not save')
    ap.add_argument('--timeout', type=float, default=2.5)
    ap.add_argument('--wait', type=float, default=240.0)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with Device(a.match) as dev:
        cid, crc = open_session(dev, timeout=a.wait)
        print(f"session: client id={cid} state crc={crc:#010x}" if cid is not None else "session: NO $34 answer")
        if cid is None:
            return 1
        dev.send(frame(0x52, SERVER_ID.to_bytes(2, 'little') + b'\x00'))
        missing = False
        for p in a.paths:
            data, note = pull(dev, p, cid, crc or 0, part_timeout=a.timeout)
            if data:
                print(f"   OK      {p:52s} {len(data):>9,} B   ({note}); sha256={hashlib.sha256(data).hexdigest()}", flush=True)
                if not a.probe:
                    dest = OUT / p.lstrip('/'); dest.parent.mkdir(parents=True, exist_ok=True)
                    temporary = dest.with_name(dest.name + '.partial')
                    temporary.write_bytes(data)
                    temporary.replace(dest)
            else:
                missing = True
                print(f"   MISSING {p:52s} {'':>9s}   ({note})", flush=True)
    return 3 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
