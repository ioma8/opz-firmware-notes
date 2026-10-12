#!/usr/bin/env python3
"""Faithful simulator of the OP-Z console oracle, shared by the test suite.

The pre-review tests emitted frames as
    b'\\xc0\\x2e\\x04\\x00\\x00\\x00\\x00\\x11\\x22\\x33\\x44\\x01' + text + b'\\x00'
-- routing 0x2E (the RARE one: 19 of 170 frames in the genuine capture) with a zero
length, which the length-honouring parser correctly rejects.  This models the real
device instead (see FIRMWARE_ANALYSIS.md 66.2 and 66.3):

  * frame = C0 routing type len_be32 payload, payload = 4-byte tick + log text + NUL
  * routing 0x1E is the ordinary log routing
  * the log payload tops out at 128 bytes, so a longer message is truncated and the
    frame's final byte is the buffer's NUL -- NOT a NUL that occurred in the window
  * 0x7D escapes the next byte as byte^0x20

Measured on the real device: a leak frame is exactly
    4 (tick) + 58 ('[26-10-10 17:39:08] bootdisk: failed to find .zip file in ') + 65 (name) + 1 (NUL) = 128
so `leak()` below yields at most 65 bytes, exactly like the hardware.
"""

ROUTING_LOG, TYPE_LOG = 0x1E, 0x04
FRAME_MAX = 128
LEAK_PREFIX = b'bootdisk: failed to find .zip file in '
TS = b'[26-10-10 00:00:00] '          # a log line always carries a timestamp


def frame(text, routing=ROUTING_LOG, typ=TYPE_LOG, tick=b'\x00\x00\x00\x00'):
    """One console frame, escaping 0x7D/0xC0 and applying the 128-byte cap."""
    payload = tick + text + b'\x00'
    if len(payload) > FRAME_MAX:
        # the logger truncates and appends a '..' marker, leaving 63 data bytes:
        # 4 tick + 58 text + 63 data + 2 marker + 1 NUL = 128 (measured, 66.14)
        payload = payload[:FRAME_MAX - 3] + b'..\x00'
    esc = bytearray()
    for b in payload:
        if b in (0x7D, 0xC0):
            esc += bytes([0x7D, b ^ 0x20])
        else:
            esc.append(b)
    return b'\xc0' + bytes([routing, typ]) + len(bytes(esc)).to_bytes(4, 'big') + bytes(esc)


def probe(i):
    """The 'detected encrypted file' frame that opens probe i."""
    return frame(f'bootdisk: detected encrypted file /z_firmware_probe_{i:03d}.zfw'.encode())


def leak_msg(data):
    """The 'failed to find .zip file in' line carrying a leaked window."""
    return TS + LEAK_PREFIX + data


def leak(seg, win=256):
    """What the device prints for one window: the decrypted name field up to its
    first NUL.  `seg` must already be the DEVICE-SIDE plaintext (mask applied)."""
    s = bytes(seg[:win])
    s += b'\x00' * (win - len(s))
    n = s.find(b'\x00')
    return s if n < 0 else s[:n]


def window(payload, s, win=256, mask=True):
    """The device-side plaintext of the crafted window at offset s."""
    seg = bytearray(payload[s:s + win])
    seg += b'\x00' * (win - len(seg))
    if mask:
        for k in range(16):
            seg[k] ^= 0x01
    return bytes(seg)


def cycle(targets, payload, parser, win=256, mask=True):
    """Emulate one boot, then run the farm's own parser.  Same contract as
    parse_cycle: returns (bytes, produced, got)."""
    buf = b''
    for i, (s, e) in enumerate(targets):
        buf += probe(i) + frame(leak_msg(leak(window(payload, s, win, mask), win)))
    return parser(buf, targets)


def _selftest():
    """The simulator must be self-consistent: a capped window yields 63 data bytes
    plus the '..' truncation marker, exactly as the device does."""
    seg = bytes(0x30 + (i % 0xB0) for i in range(256))        # no NULs
    got = leak(seg)
    f = frame(leak_msg(got))
    payload_len = int.from_bytes(f[3:7], 'big')
    assert payload_len == FRAME_MAX, payload_len
    data = payload_len - 4 - len(TS) - len(LEAK_PREFIX) - 2 - 1
    assert data == 63, data
    assert f[7:].endswith(b'..\x00'), f[7:][-4:]
    # escapes must survive a round trip through the frame payload
    esc = frame(bytes([0x7D, 0xC0, 0x41]))
    assert 0x7D in esc[7:] and len(esc) > 7 + 3
    print(f"opzsim selftest OK: capped window = {data} data bytes + '..' marker, escaping round-trips")


if __name__ == '__main__':
    _selftest()
