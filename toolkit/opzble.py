#!/usr/bin/env python3
"""Pull files off the OP-Z over BLE-MIDI (the transport its own file service answers on).

The device's file service replies never appear on USB MIDI (measured), only over BLE, which is
the same channel the companion app uses. BLE-MIDI = GATT service 03b80e5a-ede8-4b33-a751-6ce34ec4c700,
characteristic 7772e5db-3868-4112-a1a9-f2669d106bf3; notifications start with a timestamp header,
with timestamp tags before MIDI status bytes.

The APK's flow is GATT connect -> discover MIDI service/characteristic -> read characteristic ->
subscribe to notifications. It writes BLE-MIDI packets serially with GATT write responses. File flow:
$51 advertise -> device $34 -> host $52 heartbeat (sync-active 0) -> $35 request -> device $53.

SAFE: sends only $51/$52(sync-active=0)/$35; sync-active 0 does not offer a manifest or file data.
"""
from __future__ import annotations
import asyncio, sys, time, zlib
from pathlib import Path

sys.path.insert(0, str(Path.home() / '.opz-decode/refs/op-z-sysex'))
from opzsysex.sysex import frame, decode_frame          # noqa: E402
from opzsysex.fileprotocol import download_file_id       # noqa: E402

SVC = '03b80e5a-ede8-4b33-a751-6ce34ec4c700'
CHR = '7772e5db-3868-4112-a1a9-f2669d106bf3'
SERVER_ID = 0x4242
OUT = Path.home() / '.opz-decode/pulled'


def server_heartbeat() -> bytes:
    return frame(0x52, SERVER_ID.to_bytes(2, 'little') + b'\x00')


def gatt_write_response(properties) -> bool:
    if 'write' in properties:
        return True
    if 'write-without-response' in properties:
        return False
    raise ValueError('MIDI characteristic does not permit writes')


class BleMidi:
    MAX_PACKET_SIZE = 240

    def __init__(self, client, write_response=True):
        self.client = client
        self.write_response = write_response
        self.sysex = bytearray()
        self.in_sysex = False
        self.frames: list[bytes] = []
        self.write_lock = asyncio.Lock()

    @staticmethod
    def packet(data: bytes, ts: int | None = None) -> bytes:
        packets = BleMidi.packets(data, ts=ts)
        if len(packets) != 1:
            raise ValueError('SysEx frame does not fit in one BLE-MIDI packet')
        return packets[0]

    @staticmethod
    def packets(data: bytes, chunk: int = MAX_PACKET_SIZE, ts: int | None = None) -> list[bytes]:
        """Mirror the APK encoder: timestamp tags precede F0/F7; continuations start with header."""
        if len(data) < 2 or data[0] != 0xF0 or data[-1] != 0xF7:
            raise ValueError('expected a complete SysEx frame')
        if not 5 <= chunk <= BleMidi.MAX_PACKET_SIZE:
            raise ValueError(f'BLE packet size must be 5..{BleMidi.MAX_PACKET_SIZE}')
        if ts is None:
            ts = int(time.monotonic() * 1000) & 0x1FFF
        header = 0x80 | ((ts >> 7) & 0x3F)
        stamp = 0x80 | (ts & 0x7F)
        stream = bytes((stamp,)) + data[:-1]
        capacity = chunk - 1
        end = bytes((stamp, 0xF7))
        if len(stream) + len(end) <= capacity:
            return [bytes((header,)) + stream + end]
        first = stream[:capacity]
        rest = stream[len(first):]
        out = [bytes((header,)) + first]
        while len(rest) + 2 > capacity:
            part = rest[:capacity]
            rest = rest[len(part):]
            out.append(bytes((header,)) + part)
        out.append(bytes((header,)) + rest + end)
        return out

    async def write_to(self, client, data: bytes) -> None:
        async with self.write_lock:
            for pkt in BleMidi.packets(data):
                # The APK waits for onCharacteristicWrite before sending the next packet.
                await client.write_gatt_char(CHR, pkt, response=self.write_response)

    def feed(self, data: bytes) -> None:
        """Reassemble SysEx using the APK's [packet header][timestamp tag][MIDI] framing."""
        if not data or not (data[0] & 0x80):
            return
        after_timestamp = False
        for b in data[1:]:
            if (b & 0x80) and not after_timestamp:
                after_timestamp = True
                continue
            after_timestamp = False
            if b == 0xF0:
                self.sysex = bytearray((b,)); self.in_sysex = True
            elif b == 0xF7:
                if self.in_sysex:
                    self.sysex.append(b)
                    self.frames.append(bytes(self.sysex)); self.in_sysex = False
            elif self.in_sysex and not (b & 0x80):
                self.sysex.append(b)


async def find_device(label='OP-Z'):
    from bleak import BleakScanner
    seen = {}
    def cb(dev, adv):
        svcs = [str(u).lower() for u in (adv.service_uuids or [])]
        seen[dev.address] = (dev, adv.local_name or dev.name or '', any(SVC in s for s in svcs))
    async with BleakScanner(detection_callback=cb):
        await asyncio.sleep(12)
    cands = [(a, v) for a, v in seen.items() if v[2] or label.lower() in (v[1] or '').lower()]
    return cands


async def pull(path, ble, client_id, client, part_timeout=3.0, cap=12_000_000):
    fid = download_file_id(path)
    got, want = {}, 0
    await ble.write_to(client, frame(0x35, SERVER_ID.to_bytes(2, 'little') + fid.to_bytes(4, 'little') + (0).to_bytes(2, 'little')))
    deadline = time.monotonic() + part_timeout
    while time.monotonic() < deadline:
        while ble.frames:
            raw = ble.frames.pop(0)
            try:
                _f = decode_frame(raw); mid, payload = _f.message_id, _f.payload
            except Exception:
                continue
            if mid != 0x53 or len(payload) < 9 or int.from_bytes(payload[2:6], 'little') != fid:
                continue
            part = int.from_bytes(payload[6:8], 'little')
            if part < want:
                continue
            try:
                got[part] = zlib.decompress(payload[9:])
            except Exception:
                continue
            while want in got:
                want += 1
            if sum(len(v) for v in got.values()) > cap:
                return b'', 'exceeds cap'
            await ble.write_to(client, frame(0x35, SERVER_ID.to_bytes(2, 'little') + fid.to_bytes(4, 'little') + want.to_bytes(2, 'little')))
            deadline = time.monotonic() + part_timeout
        await asyncio.sleep(0.01)
    if not got:
        return b'', 'not served (no part 0)'
    last = max(got)
    if all(i in got for i in range(last + 1)):
        return b''.join(got[i] for i in range(last + 1)), f"{last+1} parts"
    return b'', f'gap after part {last}'


async def main():
    argv = sys.argv[1:]
    forced = None
    if '--address' in argv:
        i = argv.index('--address'); forced = argv[i+1]; del argv[i:i+2]
    paths = argv
    if forced:
        print(f"resolving given address {forced}", flush=True)
        from bleak import BleakScanner
        dev = await BleakScanner.find_device_by_address(forced, timeout=15)
        cands = [(dev.address, (dev, dev.name or 'given', True))] if dev else []
    else:
        print("scanning for the OP-Z BLE-MIDI endpoint…", flush=True)
        cands = []
    for attempt in range(1, 13):
        if forced: break
        try:
            cands = await asyncio.wait_for(find_device(), timeout=45)
        except Exception as e:
            print(f"  scan {attempt}: {type(e).__name__}: {str(e)[:60]}", flush=True)
            cands = []
        if cands:
            break
        await asyncio.sleep(4)
    if not cands:
        print("no OP-Z BLE endpoint found"); return 2
    addr, (dev, name, is_midi) = cands[0]
    from bleak import BleakClient
    target = dev if dev is not None else addr  # keep the BLEDevice discovered by this scan
    print(f"found {addr} name={name!r} ble-midi={is_midi} — connecting…", flush=True)
    def on_disconnect(_client):
        print("GATT disconnected callback", flush=True)
    heartbeat_task = None
    async with BleakClient(target, timeout=45, disconnected_callback=on_disconnect) as client:
        print(f"GATT connected={client.is_connected}", flush=True)
        service = client.services.get_service(SVC)
        characteristic = service.get_characteristic(CHR) if service else None
        properties = characteristic.properties if characteristic else []
        write_response = gatt_write_response(properties)
        print(f"MIDI characteristic properties={properties}; write_response={write_response}", flush=True)
        try:
            print("reading MIDI characteristic…", flush=True)
            await asyncio.wait_for(client.read_gatt_char(CHR), timeout=15)
            print(f"characteristic read complete; connected={client.is_connected}", flush=True)
            ble = BleMidi(client, write_response=write_response)
            rx_count = 0
            def on_midi_data(_characteristic, data):
                nonlocal rx_count
                rx_count += 1
                if rx_count <= 10 or rx_count % 50 == 0:
                    print(f"BLE notify #{rx_count}: {bytes(data[:64]).hex()}", flush=True)
                ble.feed(data)
            print("enabling MIDI notifications…", flush=True)
            await asyncio.wait_for(client.start_notify(CHR, on_midi_data), timeout=15)
            print(f"notifications enabled; connected={client.is_connected}", flush=True)
            advertise = frame(0x51, SERVER_ID.to_bytes(2, 'little'))
            print(f"sending $51: SysEx={advertise.hex()} BLE={BleMidi.packet(advertise).hex()}", flush=True)
            await asyncio.wait_for(ble.write_to(client, advertise), timeout=10)
            print(f"$51 write complete; connected={client.is_connected}", flush=True)

            async def keep_server_alive():
                while True:
                    await asyncio.sleep(1.0)
                    await ble.write_to(client, server_heartbeat())

            t0 = time.monotonic(); client_id = None; last_adv = t0; last_status = 0.0
            while time.monotonic() - t0 < 90:
                while ble.frames:
                    raw = ble.frames.pop(0)
                    try: _f = decode_frame(raw); mid, payload = _f.message_id, _f.payload
                    except Exception: continue
                    print(f"   <- ${mid:02x} {len(payload)}B {payload[:16].hex()}", flush=True)
                    if mid == 0x34:
                        client_id = int.from_bytes(payload[:2], 'little'); break
                if client_id is not None: break
                now = time.monotonic()
                # The device forgets stale server advertisements after ~6 s.
                if now - last_adv > 1.5:
                    await asyncio.wait_for(ble.write_to(client, frame(0x51, SERVER_ID.to_bytes(2, 'little'))), timeout=10)
                    last_adv = now
                if now - last_status > 5.0:
                    print(f"waiting for $34 ({now-t0:.0f}s); connected={client.is_connected}", flush=True)
                    last_status = now
                await asyncio.sleep(0.02)
            print(f"client id = {client_id}", flush=True)
            if client_id is None:
                return 3
            await ble.write_to(client, server_heartbeat())
            heartbeat_task = asyncio.create_task(keep_server_alive())
            OUT.mkdir(parents=True, exist_ok=True)
            for p in paths:
                data, note = await pull(p, ble, client_id, client)
                if data:
                    dest = OUT / p.lstrip('/'); dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
                    print(f"   OK      {p:50s} {len(data):>9,} B  ({note})", flush=True)
                else:
                    print(f"   MISSING {p:50s} {note}", flush=True)
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try: await heartbeat_task
                except asyncio.CancelledError: pass
    return 0

if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
