#!/usr/bin/env python3
"""Stay advertised on USB MIDI forever, and pull the moment the OP-Z connects.

The unit's log shows it receives our $51 advertisement (`server 16962` = 0x4242). A prior no-reply
USB run used the wrong host heartbeat, so transport support remains unproven. Hold the advertisement open and
service a $34 handshake when it appears. Sends $51 / $52(sync-active=0) / $35 only — no manifest or file data.
"""
import sys, time, zlib
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.opz-decode/refs/op-z-sysex'))
import mido
from opzsysex.sysex import frame, decode_frame
from opzsysex.fileprotocol import download_file_id, PART_SIZE

SERVER_ID = 0x4242
OUT = Path.home() / '.opz-decode/pulled'
TARGETS = ["settings/plugs.json", "settings/slotConfiguration.json", "settings/plugPresets.dat",
           "config/general.json", "config/dmx.json", "config/midi.json", "config/userPresets.dat",
           "engines/tapetwo.engine", "engines/analoga.engine", "engines/saw013a.engine",
           "samplepacks/redmountKicks.aif", "samplepacks/1-kick/01/TeKicks.aif",
           "samplepacks/CuckooKicks.aif", "samplepacks/SebaKicks.aif", "samplepacks/AlainKicks.aif",
           "samplepacks/zVinyl.aif", "system/content/samplepacks/sfx.aif"]

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def one_pull(inp, out, path, cid, part_timeout=2.5, cap=12_000_000):
    fid = download_file_id(path)
    got, want = {}, 0
    out.send(mido.Message.from_bytes(list(frame(0x35, SERVER_ID.to_bytes(2,'little') + fid.to_bytes(4,'little') + (0).to_bytes(2,'little')))))
    deadline = time.time() + part_timeout
    last_hb = 0.0
    while time.time() < deadline:
        if time.time() - last_hb > 1.0:
            out.send(mido.Message.from_bytes(list(frame(0x52, SERVER_ID.to_bytes(2,'little') + b'\x00'))))
            last_hb = time.time()
        m = inp.poll()
        if m is None: time.sleep(0.002); continue
        if m.type != 'sysex': continue
        f = decode_frame(bytes([0xF0]) + bytes(m.data) + bytes([0xF7]))
        if f.message_id != 0x53 or len(f.payload) < 9: continue
        if int.from_bytes(f.payload[2:6], 'little') != fid: continue
        part = int.from_bytes(f.payload[6:8], 'little')
        if part < want: continue
        try: got[part] = zlib.decompress(f.payload[9:])
        except Exception: continue
        while want in got: want += 1
        if sum(len(v) for v in got.values()) > cap: return b'', 'cap'
        out.send(mido.Message.from_bytes(list(frame(0x35, SERVER_ID.to_bytes(2,'little') + fid.to_bytes(4,'little') + want.to_bytes(2,'little')))))
        deadline = time.time() + part_timeout
    if not got: return b'', 'not served'
    last = max(got)
    if all(i in got for i in range(last + 1)):
        return b''.join(got[i] for i in range(last + 1)), f'{last+1} parts'
    return b'', f'gap after {last}'

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ins = [n for n in mido.get_input_names() if 'OP-Z' in n.upper()]
    outs = [n for n in mido.get_output_names() if 'OP-Z' in n.upper()]
    if not ins or not outs:
        log('no OP-Z MIDI port'); return 2
    log(f'advertising server {SERVER_ID:#06x} persistently on {ins[0]!r}')
    inp = mido.open_input(ins[0]); out = mido.open_output(outs[0])
    cid = None; last_adv = 0.0; t0 = time.time()
    try:
        while True:
            now = time.time()
            if now - last_adv > 10:
                out.send(mido.Message.from_bytes(list(frame(0x51, SERVER_ID.to_bytes(2,'little'))))); last_adv = now
            m = inp.poll()
            if m is None:
                time.sleep(0.005); continue
            if m.type != 'sysex': continue
            f = decode_frame(bytes([0xF0]) + bytes(m.data) + bytes([0xF7]))
            log(f'<- ${f.message_id:02x} {len(f.payload)}B {f.payload[:16].hex()}')
            if f.message_id == 0x34 and cid is None:
                cid = int.from_bytes(f.payload[:2], 'little')
                log(f'client id {cid} — starting pull')
                out.send(mido.Message.from_bytes(list(frame(0x52, SERVER_ID.to_bytes(2,'little') + b'\x00'))))
                for p in TARGETS:
                    data, note = one_pull(inp, out, p, cid)
                    if data:
                        dest = OUT / p.lstrip('/'); dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
                        log(f'   OK      {p:48s} {len(data):>9,} B ({note})')
                    else:
                        log(f'   MISSING {p:48s} {note}')
                log('pull cycle complete')
                return 0
            # no self-timeout: coverage must not lapse silently while waiting for the unit to answer
    finally:
        inp.close(); out.close()

if __name__ == '__main__':
    raise SystemExit(main())
