"""OP-Z SysEx framing, packed-7 encoding, compression, and stream parsing."""

from __future__ import annotations

from dataclasses import dataclass
import zlib


TE_HEADER = bytes((0xF0, 0x00, 0x20, 0x76, 0x01))
IDENTITY_INQUIRY = bytes((0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7))
PATTERN_QUERY = TE_HEADER + bytes((0x08, 0xF7))
MIDI_CONFIGURATION_QUERY = TE_HEADER + bytes((0x0F, 0xF7))
SAMPLE_VISUALIZATION_QUERY = TE_HEADER + bytes((0x15, 0xF7))
GATE_SEQUENCER_STEP = TE_HEADER + bytes((0x61, 0xF7))


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    message_id: int
    payload: bytes


def pack7(source: bytes) -> bytes:
    """Pack arbitrary 8-bit bytes into the OP-Z/TE 7-bit MIDI representation."""
    out = bytearray()
    for start in range(0, len(source), 7):
        chunk = source[start : start + 7]
        mask = sum(((byte >> 7) & 1) << bit for bit, byte in enumerate(chunk))
        out.append(mask)
        out.extend(byte & 0x7F for byte in chunk)
    return bytes(out)


def unpack7(source: bytes) -> bytes:
    """Decode OP-Z/TE packed-7 bytes."""
    if any(byte > 0x7F for byte in source):
        raise ProtocolError("packed SysEx data contains an 8-bit byte")
    out = bytearray()
    for start in range(0, len(source), 8):
        chunk = source[start : start + 8]
        if not chunk:
            continue
        mask = chunk[0]
        for bit, byte in enumerate(chunk[1:]):
            out.append(byte | (((mask >> bit) & 1) << 7))
    return bytes(out)


def frame(message_id: int, payload: bytes = b"") -> bytes:
    if not 0 <= message_id <= 0x7F:
        raise ProtocolError("message id must be a 7-bit MIDI data byte")
    return TE_HEADER + bytes((message_id,)) + pack7(payload) + b"\xF7"


def decode_frame(data: bytes) -> Frame:
    if len(data) < 7 or not data.startswith(TE_HEADER) or data[-1] != 0xF7:
        raise ProtocolError("invalid OP-Z SysEx frame")
    return Frame(data[5], unpack7(data[6:-1]))


def compress(data: bytes) -> bytes:
    return zlib.compress(data)


def decompress(data: bytes, *, max_size: int | None = None) -> bytes:
    if max_size is None:
        return zlib.decompress(data)
    inflater = zlib.decompressobj()
    result = inflater.decompress(data, max_size + 1)
    if len(result) > max_size or inflater.unconsumed_tail:
        raise ProtocolError(f"inflated payload exceeds {max_size} bytes")
    result += inflater.flush()
    if len(result) > max_size:
        raise ProtocolError(f"inflated payload exceeds {max_size} bytes")
    return result


def heartbeat(token: tuple[int, int]) -> bytes:
    return TE_HEADER + bytes((0x00, 0x01, token[0], token[1], 0x06, 0xF7))


def state_sync_client_hello(client_id: int, protocol_version: int = 6) -> bytes:
    return frame(0x00, client_id.to_bytes(2, "big") + bytes((protocol_version,)))


def state_sync_master_claim(local_session_id: int, remote_session_id: int) -> bytes:
    return frame(0x01, local_session_id.to_bytes(2, "big") + remote_session_id.to_bytes(2, "big"))


def pattern_delta(sequence: int, offset: int, address: int, data: bytes, change_type: int = 0) -> bytes:
    if not 0 < offset <= 0xFFFF or not 0 < len(data) <= 0xFF:
        raise ProtocolError("pattern delta needs a nonzero offset and 1..255 data bytes")
    payload = (
        sequence.to_bytes(2, "little")
        + offset.to_bytes(2, "little")
        + bytes((_byte(address, "address"), len(data), _byte(change_type, "change type")))
        + data
    )
    return frame(0x02, payload)


def active_chain(patterns: list[int], project: int) -> bytes:
    if not 1 <= len(patterns) <= 31 or any(not 0 <= value < 16 for value in patterns):
        raise ProtocolError("active chain needs 1..31 pattern indexes in 0..15")
    if not 0 <= project < 16:
        raise ProtocolError("project must be in 0..15")
    payload = bytearray(20)
    for index, pattern in enumerate(patterns):
        payload[index // 2] |= pattern << (4 if index % 2 else 0)
    payload[16:20] = bytes((len(patterns), patterns[0], 1 if len(patterns) > 1 else 0, project))
    return frame(0x07, bytes(payload))


def pattern_upload_frames(prefix: bytes, address: int, transfer_id: int) -> list[bytes]:
    from .project import PATTERN_BANK_SIZE

    if not 0 < len(prefix) <= PATTERN_BANK_SIZE:
        raise ProtocolError(f"pattern prefix must be 1..{PATTERN_BANK_SIZE} bytes")
    compressed = compress(prefix)
    chunks = [compressed[index : index + 178] for index in range(0, len(compressed), 178)]
    result = []
    for packet_index, chunk in enumerate(chunks):
        payload = (
            bytes((_byte(address, "address"), 0))
            + transfer_id.to_bytes(2, "little")
            + packet_index.to_bytes(2, "little")
            + chunk
        )
        result.append(frame(0x0A if packet_index == len(chunks) - 1 else 0x09, payload))
    return result


def pattern_packet_identity(data: bytes) -> tuple[int, int] | None:
    decoded = decode_frame(data)
    if decoded.message_id not in (0x09, 0x0A) or len(decoded.payload) < 6:
        return None
    return int.from_bytes(decoded.payload[2:4], "little"), int.from_bytes(decoded.payload[4:6], "little")


def global_upload_frame(global_state: bytes) -> bytes:
    if len(global_state) != 568:
        raise ProtocolError("project-global state must be exactly 568 bytes")
    return frame(0x0C, compress(global_state))


class MIDIStreamParser:
    """Incremental parser that tolerates MIDI realtime bytes inside SysEx."""

    def __init__(self) -> None:
        self._sysex: bytearray | None = None

    def feed(self, data: bytes) -> list[tuple[str, bytes | int]]:
        events: list[tuple[str, bytes | int]] = []
        for byte in data:
            if byte >= 0xF8 and byte != 0xF7:
                events.append(("realtime", byte))
                continue
            if self._sysex is None:
                if byte == 0xF0:
                    self._sysex = bytearray((byte,))
                continue
            if byte == 0xF0:
                self._sysex = bytearray((byte,))
            else:
                self._sysex.append(byte)
                if byte == 0xF7:
                    events.append(("sysex", bytes(self._sysex)))
                    self._sysex = None
        return events


def _byte(value: int, label: str) -> int:
    if not 0 <= value <= 0xFF:
        raise ProtocolError(f"{label} must fit in one byte")
    return value
