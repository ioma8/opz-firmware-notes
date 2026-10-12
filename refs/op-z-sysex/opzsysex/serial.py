"""Reverse-engineered OP-Z serial tunnel carried by SysEx message $66."""

from dataclasses import dataclass

from .sysex import ProtocolError, decode_frame, frame


START = 0xC0
ESCAPE = 0x7D
ESCAPE_XOR = 0x20


@dataclass(frozen=True)
class SerialMessage:
    routing: int
    message_type: int
    payload: bytes


def serial_frame(
    message_type: int,
    payload: bytes = b"",
    routing: int = 5,
    *,
    allow_unsafe: bool = False,
) -> bytes:
    if message_type not in (0, 1) and not allow_unsafe:
        raise ProtocolError("only proven ping/pong types 0 and 1 are enabled by default")
    if len(payload) > 256:
        raise ProtocolError("serial-tunnel payload exceeds guarded 256-byte limit")
    raw = bytes((START, routing, message_type)) + len(payload).to_bytes(4, "big") + payload
    escaped = bytes((raw[0],)) + _escape(raw[1:])
    return frame(0x66, escaped)


def decode_serial_frame(data: bytes) -> SerialMessage:
    decoded = decode_frame(data)
    if decoded.message_id != 0x66:
        raise ProtocolError("not an OP-Z serial-tunnel frame")
    raw = _unescape(decoded.payload)
    if len(raw) < 7 or raw[0] != START:
        raise ProtocolError("malformed serial-tunnel payload")
    size = int.from_bytes(raw[3:7], "big")
    if size > 256 or len(raw) != size + 7:
        raise ProtocolError("invalid serial-tunnel length")
    return SerialMessage(raw[1], raw[2], raw[7:])


def _escape(data: bytes) -> bytes:
    out = bytearray()
    for byte in data:
        if byte in (START, ESCAPE):
            out.extend((ESCAPE, byte ^ ESCAPE_XOR))
        else:
            out.append(byte)
    return bytes(out)


def _unescape(data: bytes) -> bytes:
    out = bytearray()
    escaped = False
    for byte in data:
        if escaped:
            out.append(byte ^ ESCAPE_XOR)
            escaped = False
        elif byte == ESCAPE:
            escaped = True
        else:
            out.append(byte)
    if escaped:
        raise ProtocolError("dangling serial-tunnel escape")
    return bytes(out)
