"""Typed representation of the 292-byte OP-Z MIDI configuration payload."""

from dataclasses import dataclass

from .sysex import ProtocolError, compress, decompress, frame


BYTE_COUNT = 292


@dataclass
class MIDIConfiguration:
    track_enabled: bytearray
    track_channels: bytearray
    parameter_ccs: bytearray
    settings: int
    padding: bytes

    @classmethod
    def decode(cls, data: bytes) -> "MIDIConfiguration":
        if len(data) != BYTE_COUNT:
            raise ProtocolError(f"MIDI configuration must be {BYTE_COUNT} bytes")
        return cls(bytearray(data[:16]), bytearray(data[16:32]), bytearray(data[32:288]), data[288], data[289:292])

    @classmethod
    def decode_frame(cls, data: bytes) -> "MIDIConfiguration":
        from .sysex import decode_frame

        decoded = decode_frame(data)
        if decoded.message_id != 0x10:
            raise ProtocolError("not a MIDI configuration frame")
        return cls.decode(decompress(decoded.payload))

    def encode(self) -> bytes:
        if not self.valid_for_write():
            raise ProtocolError("invalid MIDI configuration values")
        return bytes(self.track_enabled + self.track_channels + self.parameter_ccs) + bytes((self.settings,)) + self.padding

    def write_frame(self) -> bytes:
        return frame(0x10, compress(self.encode()))

    def valid_for_write(self) -> bool:
        return (
            len(self.track_enabled) == 16
            and all(value <= 1 for value in self.track_enabled)
            and len(self.track_channels) == 16
            and all(value < 16 for value in self.track_channels)
            and len(self.parameter_ccs) == 256
            and all(value < 128 for value in self.parameter_ccs)
            and len(self.padding) == 3
        )

    def set_track_enabled(self, track: int, enabled: bool) -> None:
        _track(track)
        self.track_enabled[track] = int(enabled)

    def set_channel(self, track: int, channel: int) -> None:
        _track(track)
        if not 1 <= channel <= 16:
            raise ProtocolError("MIDI channel must be 1..16")
        self.track_channels[track] = channel - 1

    def set_cc(self, track: int, parameter: int, cc: int) -> None:
        _track(track)
        if not 0 <= parameter < 16 or not 0 <= cc < 128:
            raise ProtocolError("parameter must be 0..15 and CC must be 0..127")
        self.parameter_ccs[track * 16 + parameter] = cc

    def setting(self, bit: int) -> bool:
        if not 0 <= bit < 8:
            raise ProtocolError("setting bit must be 0..7")
        return bool(self.settings & (1 << bit))

    def set_setting(self, bit: int, enabled: bool) -> None:
        if not 0 <= bit < 8:
            raise ProtocolError("setting bit must be 0..7")
        self.settings = self.settings | (1 << bit) if enabled else self.settings & ~(1 << bit)


def _track(track: int) -> None:
    if not 0 <= track < 16:
        raise ProtocolError("track must be 0..15")
