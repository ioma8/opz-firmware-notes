#!/usr/bin/env python3
"""Self-check for the two OP-Z pull paths (no device needed).

1. opzpull.pull() against a synthetic $53 sender: sizes, duplicate parts, gaps, foreign file ids.
2. opzble.BleMidi: BLE-MIDI packet framing and sysex reassembly across fragmented notifications.

Run: /tmp/opzuv/bin/python ~/.opz-decode/test_pull_paths.py
"""
import importlib.util, sys, zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'refs/op-z-sysex'))
from opzsysex.sysex import frame, decode_frame
from opzsysex.fileprotocol import PART_SIZE

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

PULL = load('opzpull', str(HERE / 'opzpull.py'))
BLE = load('opzble', str(HERE / 'opzble.py'))
CID = 0x2222
FAILS = []

def check(label, ok, detail=''):
    print(f"  {'PASS' if ok else 'FAIL'}  {label} {detail}")
    if not ok: FAILS.append(label)

class FakeDev:
    def __init__(self, blob, dupe=0, foreign=False):
        self.blob, self.dupe, self.foreign, self.queue, self.asked = blob, dupe, foreign, [], []
        self.heartbeats = 0
        self.hellos = 0
    def send(self, sysex):
        f = decode_frame(sysex)
        if f.message_id == 0x00:
            self.hellos += 1
            if f.payload != b'BB\x06': FAILS.append('bad app-protocol keepalive')
            return
        if f.message_id == 0x52:
            self.heartbeats += 1
            if f.payload != b'BB\x00': FAILS.append('bad $52 server heartbeat')
            return
        if f.message_id != 0x35: FAILS.append('pull sent an unexpected message')
        fid = int.from_bytes(f.payload[2:6], 'little'); part = int.from_bytes(f.payload[6:8], 'little')
        self.asked.append(part)
        if self.foreign and not self.queue:
            self.queue.append(frame(0x53, CID.to_bytes(2,'little') + (999999).to_bytes(4,'little') +
                                    (0).to_bytes(2,'little') + bytes((1,)) + zlib.compress(b'nope')))
        data = self.blob[part*PART_SIZE:(part+1)*PART_SIZE]
        if not data: return
        last = (part+1)*PART_SIZE >= len(self.blob)
        fr = frame(0x53, CID.to_bytes(2,'little') + fid.to_bytes(4,'little') + part.to_bytes(2,'little') +
                   bytes((int(last),)) + zlib.compress(data))
        if self.dupe and part and part % self.dupe == 0: self.queue.append(fr)
        self.queue.append(fr)
    def receive(self, timeout=0.25):
        if self.queue: return self.queue.pop(0)
        raise TimeoutError('no parts')

print("0) USB session startup")
class FakeSession:
    def __init__(self):
        self.sent = []
        self.queue = [frame(0x11, b'identity'), frame(0x34, CID.to_bytes(2, 'little') + b'\x01\x02\x03\x04')]
    def send(self, data): self.sent.append(data)
    def receive(self, timeout=0.25): return self.queue.pop(0)
session = FakeSession()
cid, crc = PULL.open_session(session, timeout=0.5)
from opzsysex.sysex import state_sync_client_hello
check("USB protocol hello precedes file advertisement", session.sent[0] == state_sync_client_hello(PULL.SERVER_ID))
check("USB hello yields file-client identity", cid == CID and crc == 0x04030201)

print("1) opzpull.pull() assembly")
for size, dupe in ((1234, 0), (5000, 7), (200, 0), (1, 0), (401, 3)):
    blob = bytes((i*7+3) & 0xFF for i in range(size))
    dev = FakeDev(blob, dupe)
    out, note = PULL.pull(dev, 'settings/plugs.json', CID, 0, part_timeout=0.4)
    check(f"size={size} dupes={dupe}", out == blob, f"({note}, {len(dev.asked)} requests)")
check("short files refresh both session heartbeats", dev.heartbeats >= 1 and dev.hellos >= 1)
class Deaf:
    def send(self, s): pass
    def receive(self, timeout=0.25): raise TimeoutError
out, note = PULL.pull(Deaf(), 'settings/plugs.json', CID, 0, part_timeout=0.4)
check("unserved file reports cleanly", out == b'' and 'not served' in note, f"({note!r})")
dev = FakeDev(b'x'*450, foreign=True)
out, note = PULL.pull(dev, 'settings/plugs.json', CID, 0, part_timeout=0.5)
check("foreign file id ignored", out == b'x'*450, f"({note})")

class Truncated(FakeDev):
    def send(self, data):
        super().send(data)
        self.queue = [raw for raw in self.queue if int.from_bytes(decode_frame(raw).payload[6:8], 'little') == 0]
out, note = PULL.pull(Truncated(b'x' * 450), 'settings/plugs.json', CID, 0, part_timeout=0.02)
check("missing final flag cannot save a truncated file", out == b'', note)
class WrongSender(FakeDev):
    def receive(self, timeout=0.25):
        raw = super().receive(timeout)
        f = decode_frame(raw)
        return frame(f.message_id, b'\x00\x00' + f.payload[2:])
out, note = PULL.pull(WrongSender(b'x' * 20), 'settings/plugs.json', CID, 0, part_timeout=0.02)
check("foreign sender cannot satisfy a file request", out == b'', note)

print("2) opzble.BleMidi framing")
class FakeClient: pass
bm = BLE.BleMidi(FakeClient())
original = frame(0x53, b'\x01\x02' + (123456).to_bytes(4,'little') + b'\x00\x01' + zlib.compress(b'payload'*30))
pkt = BLE.BleMidi.packet(frame(0x51, b'BB'), ts=0x1234)
check("APK timestamp header/tag precede F0", pkt[0] == 0xA4 and pkt[1] == 0xB4 and pkt[2] == 0xF0)
check("APK timestamp tag precedes F7", pkt[-2] == 0xB4 and pkt[-1] == 0xF7)
parts = BLE.BleMidi.packets(original, chunk=32, ts=0x1234)
check("all BLE packets fit the requested limit", len(parts) > 1 and all(len(p) <= 32 for p in parts))
check("continuation packets start with a BLE header", all(p[0] & 0x80 for p in parts))
for chunk in parts:
    bm.feed(chunk)
check("sysex reassembled across timestamped fragments", len(bm.frames) == 1)
if bm.frames:
    f = decode_frame(bm.frames[0])
    check("reassembled frame decodes identically", f.message_id == 0x53 and f.payload == decode_frame(original).payload)
mid, payload = (lambda f: (f.message_id, f.payload))(decode_frame(BLE.server_heartbeat()))
check("server heartbeat is $52 with active=0", mid == 0x52 and payload == b'BB\x00')
check("GATT uses response writes when advertised", BLE.gatt_write_response(['write', 'notify']))
check("GATT uses no-response when that is the only write mode", not BLE.gatt_write_response(['write-without-response', 'notify']))
# a timestamped non-sysex packet must not create a frame
bm.feed(bytes((0x80, 0x80, 0x90, 0x40, 0x7F)))
check("non-sysex packets ignored", len(bm.frames) == 1)

print(f"\nVERDICT: {'all checks PASS' if not FAILS else str(len(FAILS)) + ' FAILURES: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
