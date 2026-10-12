#!/usr/bin/env python3
"""Read-only file fetch from the OP-Z over USB-MIDI (clean-room $35/$53 transport).

SAFE BY CONSTRUCTION: this tool only ever sends an *advertise* ($51) and *file
requests* ($35). It never sends an upload manifest ($52) or file parts ($53) to the
device, so it cannot write anything. It exists to answer one question the console
oracle cannot: can the OS-level file service serve paths outside the user tree
(for example the components the updater extracted), which would be a host-side read
path to the OS image?

Protocol: F0 00 20 76 01 <id> <7-bit payload> F7 ; $51 advertises a server, the OP-Z
answers $34 with its client id, $35 requests a file by id at a part index, $53 carries
<=200 uncompressed bytes per part as an individual zlib stream. fileId =
crc32(utf8(lowercase(relativePath))) with the three reserved ids in the reference.

Reference implementation: ~/.opz-decode/refs/op-z-sysex (device-proven 2026-07-26).

usage: opzfetch.py [--ports] PATH [PATH ...]
"""
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path.home() / '.opz-decode' / 'refs' / 'op-z-sysex'))
from opzsysex.sysex import frame, decode_frame          # noqa: E402
from opzsysex.fileprotocol import DownloadState, download_file_id  # noqa: E402

SERVER_ID = 0x4242
OUT = Path.home() / '.opz-decode' / 'fetched'


def ports():
    import mido
    ins = mido.get_input_names()
    outs = mido.get_output_names()
    print('MIDI inputs :', ins)
    print('MIDI outputs:', outs)
    hit = [n for n in ins if 'OP-Z' in n.upper()] and [n for n in outs if 'OP-Z' in n.upper()]
    print('OP-Z MIDI present:', bool(hit))
    return hit


def main():
    args = [a for a in sys.argv[1:]]
    wait = 300
    if '--wait' in args:
        i = args.index('--wait'); wait = int(args[i + 1]); del args[i:i + 2]
    if not args or '--ports' in args:
        ports()
        if not args:
            return 0
        args.remove('--ports')
    import mido
    ins = [n for n in mido.get_input_names() if 'OP-Z' in n.upper()]
    outs = [n for n in mido.get_output_names() if 'OP-Z' in n.upper()]
    if not ins or not outs:
        print('no OP-Z MIDI port: the unit must be in a mode where the OS runs')
        print('(update mode has no MIDI; try content mode = power on holding TRACK)')
        return 2
    OUT.mkdir(exist_ok=True)
    targets = [(download_file_id(p), p) for p in args]
    for fid, p in targets:
        print(f'  {p}  -> fileId {fid}')
    state = DownloadState(targets)
    got = {}

    with mido.open_input(ins[0]) as inp, mido.open_output(outs[0]) as out:
        print(f'advertising server {SERVER_ID:#06x} on {ins[0]!r}; waiting up to {wait}s')
        out.send(mido.Message.from_bytes(list(frame(0x51, SERVER_ID.to_bytes(2, 'little')))))
        client_id = None
        requested = False
        deadline = time.time() + wait
        req = None
        next_advert = time.time() + 15
        seen_ids = {}
        while time.time() < deadline:
            if time.time() >= next_advert and client_id is None:
                out.send(mido.Message.from_bytes(list(frame(0x51, SERVER_ID.to_bytes(2, 'little')))))
                next_advert = time.time() + 15
            msg = inp.poll()
            if msg is None:
                time.sleep(0.01)
                continue
            if msg.type != 'sysex':
                print(f'  (non-sysex from device: {msg})')
                continue
            raw = bytes([0xF0]) + bytes(msg.data) + bytes([0xF7])
            try:
                dec = decode_frame(raw)
            except Exception:
                print(f'  (undecodable {len(raw)} B: {raw[:24].hex()})')
                continue
            seen_ids[dec.message_id] = seen_ids.get(dec.message_id, 0) + 1
            print(f'  <- ${dec.message_id:02x} len={len(dec.payload)} payload={dec.payload[:24].hex()}'
                  + (f' ascii={dec.payload[:24]!r}' if all(32 <= c < 127 for c in dec.payload[:24]) else ''))
            if dec.message_id == 0x34 and client_id is None:
                client_id = int.from_bytes(dec.payload[:2], 'little')
                print(f'client id {client_id}  state CRC {dec.payload[2:6].hex()}')
            if client_id is None:
                continue
            if not requested:
                req = state.begin(SERVER_ID)
                requested = True
            if req:
                out.send(mido.Message.from_bytes(list(req)))
                req = None
            if dec.message_id == 0x53:
                done, nxt = state.accept_part(dec.payload, client_id, SERVER_ID)
                if done:
                    path, blob = done
                    got[path] = blob
                    print(f'  RECEIVED {path}: {len(blob)} bytes')
                    (OUT / path.replace('/', '_')).write_bytes(blob)
                req = nxt
            if state.complete:
                break
        if not requested:
            print(f'the device never answered $34 in {wait}s; message ids seen: '
                  f'{{{", ".join(f"${k:02x} x{v}" for k, v in sorted(seen_ids.items()))}}}' if seen_ids else
                  f'the device sent nothing in {wait}s (message ids seen: none)')
    print()
    for p in args:
        b = got.get(p)
        if b is None:
            print(f'  {p}: NOT SERVED')
            continue
        head = b[:64]
        print(f'  {p}: {len(b)} bytes  head={head[:32].hex()}')
        if p.endswith('.json') or b[:1] in (b'{', b'['):
            try:
                print('     json:', b[:200].decode('utf-8', 'replace'))
            except Exception:
                pass
    print(f'\nsaved under {OUT}')
    return 0 if got else 3


if __name__ == '__main__':
    sys.exit(main())
