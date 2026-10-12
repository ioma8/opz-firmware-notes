"""OP-Z project-global and 16-pattern bank decoders/editors."""

from __future__ import annotations

from dataclasses import dataclass
import struct

from .sysex import ProtocolError


PATTERN_SIZE = 21_392
PATTERN_COUNT = 16
PATTERN_BANK_SIZE = PATTERN_SIZE * PATTERN_COUNT
GLOBAL_SIZE = 568
TRACK_NAMES = ("kick", "snare", "percussion", "sample", "bass", "lead", "arp", "chord", "fx1", "fx2", "tape", "master", "perform", "module", "lights", "motion")
NOTES_PER_STEP = (2, 2, 2, 2, 4, 4, 8, 4, 1, 1, 1, 4, 6, 6, 4, 4)
NOTE_OFFSETS = (0, 2, 4, 6, 8, 12, 16, 24, 28, 29, 30, 31, 35, 41, 47, 51)


@dataclass(frozen=True)
class Note:
    note: int
    velocity: int = 100
    duration: int = 6200
    microtiming_ticks: int = 0
    age: int = 0


@dataclass(frozen=True)
class GlobalSummary:
    drum_level: int
    synth_level: int
    punch_level: int
    master_level: int
    tempo: int
    swing: int
    metronome_level: int
    metronome_sound: int
    chains: tuple[tuple[int, ...], ...]
    active_chain: tuple[int, ...]
    selected_chain_raw: int


def decode_global(data: bytes) -> GlobalSummary:
    if len(data) != GLOBAL_SIZE:
        raise ProtocolError(f"project-global block must be {GLOBAL_SIZE} bytes")
    chains = []
    for index in range(16):
        record = data[index * 32 : index * 32 + 32]
        chains.append(tuple(record[: record.find(b"\xFF") if b"\xFF" in record else len(record)]))
    return GlobalSummary(data[512], data[513], data[514], data[515], int.from_bytes(data[516:518], "little"), data[561], data[562], data[563], tuple(chains[:15]), chains[15], data[564])


class GlobalEditor:
    def __init__(self, data: bytes):
        if len(data) != GLOBAL_SIZE:
            raise ProtocolError(f"project-global block must be {GLOBAL_SIZE} bytes")
        self.data = bytearray(data)

    def set_tempo(self, tempo: int) -> None:
        if not 40 <= tempo <= 200:
            raise ProtocolError("tempo must be 40..200 BPM")
        self.data[516:518] = tempo.to_bytes(2, "little")

    def set_level(self, group: str, value: int) -> None:
        offsets = {"drum": 512, "synth": 513, "punch": 514, "master": 515}
        if group not in offsets or not 0 <= value <= 255:
            raise ProtocolError("level group must be drum/synth/punch/master and value 0..255")
        self.data[offsets[group]] = value

    def set_chain(self, slot: int, patterns: list[int]) -> None:
        if not 0 <= slot < 15 or len(patterns) > 31 or any(not 0 <= value < 16 for value in patterns):
            raise ProtocolError("saved chain needs slot 0..14 and up to 31 patterns in 0..15")
        offset = slot * 32
        self.data[offset : offset + 32] = bytes(patterns) + b"\xFF" * (32 - len(patterns))

    def bytes(self) -> bytes:
        return bytes(self.data)


class PatternBankEditor:
    def __init__(self, data: bytes):
        if len(data) != PATTERN_BANK_SIZE:
            raise ProtocolError(f"pattern bank must be {PATTERN_BANK_SIZE} bytes")
        self.data = bytearray(data)

    def set_notes(self, pattern: int, track: int, step: int, notes: list[Note]) -> None:
        self._validate(pattern, track, step)
        if len(notes) > NOTES_PER_STEP[track]:
            raise ProtocolError(f"{TRACK_NAMES[track]} stores at most {NOTES_PER_STEP[track]} notes per step")
        for note in notes:
            if not 0 <= note.note <= 127 or not 1 <= note.velocity <= 127 or note.duration <= 0:
                raise ProtocolError("note, velocity, or duration is outside the writable range")
            raw_timing = note.microtiming_ticks * 8
            if not -96 <= raw_timing <= 88:
                raise ProtocolError("microtiming ticks must encode to raw -96..88")
            if not 0 <= note.age <= 255:
                raise ProtocolError("note age must be 0..255")
        for slot in range(NOTES_PER_STEP[track]):
            offset = self._note_offset(pattern, track, step, slot)
            if slot < len(notes):
                note = notes[slot]
                self.data[offset : offset + 8] = struct.pack("<iBBB", note.duration, note.note, note.velocity, note.microtiming_ticks * 8 & 0xFF) + bytes((note.age,))
            else:
                self.data[offset + 4] = 0xFF

    def set_parameter_lock(self, pattern: int, track: int, step: int, parameter: int, value: int | None) -> None:
        self._validate(pattern, track, step)
        if not 0 <= parameter < 18:
            raise ProtocolError("parameter must be 0..17")
        offset = self._step_offset(pattern, track, step)
        if value is None:
            self.data[offset + 36 + parameter] = 0
        elif 0 <= value <= 255:
            self.data[offset + 18 + parameter] = value
            self.data[offset + 36 + parameter] = 0xFF
        else:
            raise ProtocolError("parameter-lock value must be 0..255")

    def set_component(self, pattern: int, track: int, step: int, component: int, value: int | None) -> None:
        self._validate(pattern, track, step)
        if not 0 <= component < 16:
            raise ProtocolError("component must be 0..15")
        offset = self._step_offset(pattern, track, step)
        mask = int.from_bytes(self.data[offset : offset + 2], "little")
        if value is None:
            mask &= ~(1 << component)
        elif 0 <= value <= 255:
            mask |= 1 << component
            self.data[offset + 2 + component] = value
        else:
            raise ProtocolError("component value must be 0..255")
        self.data[offset : offset + 2] = mask.to_bytes(2, "little")

    def set_sound_parameter(self, pattern: int, track: int, parameter: int, value: int) -> None:
        self._validate(pattern, track)
        if not 0 <= parameter < 18 or not 0 <= value <= 255:
            raise ProtocolError("sound parameter must be 0..17 and value 0..255")
        self.data[pattern * PATTERN_SIZE + 21_056 + track * 18 + parameter] = value

    def set_active_plug(self, pattern: int, track: int, plug_id: int) -> None:
        self._validate(pattern, track)
        if not 0 < plug_id <= 0xFFFFFFFF:
            raise ProtocolError("plug id must be a nonzero UInt32")
        offset = pattern * PATTERN_SIZE + track * 12
        self.data[offset : offset + 4] = plug_id.to_bytes(4, "little")

    def set_step_count(self, pattern: int, track: int, count: int) -> None:
        self._validate(pattern, track)
        if not 1 <= count <= 16:
            raise ProtocolError("step count must be 1..16")
        self.data[pattern * PATTERN_SIZE + track * 12 + 4] = count

    def set_muted(self, pattern: int, track: int, muted: bool) -> None:
        self._validate(pattern, track)
        base = pattern * PATTERN_SIZE
        group = min(self.data[base + 21_388], 9)
        offset = base + 21_344 + group * 4 + track // 4
        mask = 1 << ((track % 4) * 2 + 1)
        self.data[offset] = self.data[offset] | mask if muted else self.data[offset] & ~mask

    def set_routing(self, pattern: int, *, tape: int | None = None, master: int | None = None) -> None:
        self._validate(pattern, 0)
        base = pattern * PATTERN_SIZE
        for value, offset in ((tape, 21_384), (master, 21_386)):
            if value is not None:
                if not 0 <= value <= 0xFFFF:
                    raise ProtocolError("routing mask must fit UInt16")
                self.data[base + offset : base + offset + 2] = value.to_bytes(2, "little")

    def bytes(self) -> bytes:
        return bytes(self.data)

    @staticmethod
    def _validate(pattern: int, track: int, step: int | None = None) -> None:
        if not 0 <= pattern < 16 or not 0 <= track < 16 or (step is not None and not 0 <= step < 16):
            raise ProtocolError("pattern, track, or step is outside 0..15")

    @staticmethod
    def _note_offset(pattern: int, track: int, step: int, slot: int) -> int:
        return pattern * PATTERN_SIZE + 192 + (step * 55 + NOTE_OFFSETS[track] + slot) * 8

    @staticmethod
    def _step_offset(pattern: int, track: int, step: int) -> int:
        return pattern * PATTERN_SIZE + 7_232 + (track * 16 + step) * 54
