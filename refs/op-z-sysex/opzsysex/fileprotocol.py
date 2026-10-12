"""Clean-room OP-Z filesystem-over-SysEx protocol state machines."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import time
import zlib

from .sysex import ProtocolError, compress, decode_frame, decompress, frame


PART_SIZE = 200
SLOT_CONFIGURATION_ID = 0
PLUGS_ID = 1
SYNC_JOB_ID = 2


@dataclass(frozen=True)
class FileDescriptor:
    file_id: int
    path: str
    crc: int
    size: int


def file_id(path: str) -> int:
    return zlib.crc32(path.lower().encode("utf-8")) & 0xFFFFFFFF


def download_file_id(path: str) -> int:
    reserved = {
        "settings/slotconfiguration.json": SLOT_CONFIGURATION_ID,
        "settings/plugs.json": PLUGS_ID,
        "syncjob.json": SYNC_JOB_ID,
    }
    return reserved.get(path.lower(), file_id(path))


def decode_file_frame(data: bytes) -> tuple[int, bytes]:
    decoded = decode_frame(data)
    return decoded.message_id, decoded.payload


class UploadState:
    maximum_in_flight_parts = 64

    def __init__(self, files: list[tuple[str, bytes]], remove_plug_ids: list[int] | None = None):
        self._files: dict[int, bytes] = {}
        self.descriptors: list[FileDescriptor] = []
        for path, data in files:
            if not data:
                raise ProtocolError(f"empty hosted files are not supported: {path}")
            identifier = file_id(path)
            if identifier in self._files:
                raise ProtocolError(f"file-id collision for {path}: {identifier}")
            if len(data) > PART_SIZE * 0xFFFF:
                raise ProtocolError(f"file exceeds UInt16 part limit: {path}")
            self._files[identifier] = data
            self.descriptors.append(FileDescriptor(identifier, path, zlib.crc32(data) & 0xFFFFFFFF, len(data)))
        manifest_files: list[dict[str, int | str]] = [
            {"fileId": item.file_id, "path": item.path, "crc": item.crc, "size": item.size}
            for item in self.descriptors
        ]
        manifest_files.extend({"operation": "remove", "plugId": value} for value in (remove_plug_ids or []))
        self.sync_job = json.dumps({"files": manifest_files}, sort_keys=True, separators=(",", ":")).encode()
        self.active_file_id: int | None = None
        self.next_part = 0
        self.last_part_sent_at = -math.inf
        self.sent_last_file_ids: set[int] = set()
        self.sent_part_count = 0
        self.client_completed_part_count: int | None = None

    def accept_request(self, payload: bytes, client_id: int) -> None:
        if len(payload) != 8:
            raise ProtocolError(f"$35 request payload must be 8 bytes, got {len(payload)}")
        requester = int.from_bytes(payload[:2], "little")
        if requester != client_id:
            raise ProtocolError(f"unexpected file client {requester}; expected {client_id}")
        self.active_file_id = int.from_bytes(payload[2:6], "little")
        self.next_part = int.from_bytes(payload[6:8], "little")
        self.last_part_sent_at = -math.inf

    def observe_completed_parts(self, count: int) -> None:
        self.client_completed_part_count = max(self.client_completed_part_count or 0, count)

    @property
    def in_flight_parts(self) -> int:
        completed = self.client_completed_part_count or 0
        return max(0, self.sent_part_count - completed)

    @property
    def sent_all_files(self) -> bool:
        return all(item.file_id in self.sent_last_file_ids for item in self.descriptors)

    def next_frame(self, server_id: int, *, now: float | None = None, minimum_interval: float = 0.010) -> bytes | None:
        if self.active_file_id is None or self.in_flight_parts >= self.maximum_in_flight_parts:
            return None
        now = time.monotonic() if now is None else now
        interval = max(minimum_interval, 0.050 if self.in_flight_parts >= 33 else 0.020 if self.in_flight_parts >= 17 else minimum_interval)
        if now - self.last_part_sent_at < interval:
            return None
        data = self.sync_job if self.active_file_id == SYNC_JOB_ID else self._files.get(self.active_file_id)
        if data is None:
            raise ProtocolError(f"unknown hosted file id {self.active_file_id}")
        start = self.next_part * PART_SIZE
        if start >= len(data):
            raise ProtocolError(f"part {self.next_part} is beyond file {self.active_file_id}")
        end = min(start + PART_SIZE, len(data))
        last = end == len(data)
        payload = server_id.to_bytes(2, "little") + self.active_file_id.to_bytes(4, "little") + self.next_part.to_bytes(2, "little") + bytes((int(last),)) + compress(data[start:end])
        result = frame(0x53, payload)
        self.last_part_sent_at = now
        self.sent_part_count += 1
        if last:
            if self.active_file_id != SYNC_JOB_ID:
                self.sent_last_file_ids.add(self.active_file_id)
            self.active_file_id = None
        else:
            self.next_part += 1
        return result


class DownloadState:
    def __init__(self, files: list[tuple[int, str]]):
        self.queued = list(files)
        self.current: tuple[int, str, int, bytearray] | None = None

    @property
    def complete(self) -> bool:
        return self.current is None and not self.queued

    def begin(self, server_id: int) -> bytes | None:
        if self.current is not None or not self.queued:
            return None
        identifier, path = self.queued.pop(0)
        self.current = (identifier, path, 0, bytearray())
        return self._request(server_id)

    def accept_part(self, payload: bytes, client_id: int, server_id: int) -> tuple[tuple[str, bytes] | None, bytes | None]:
        if len(payload) < 9 or self.current is None:
            raise ProtocolError("invalid or unexpected $53 file part")
        sender = int.from_bytes(payload[:2], "little")
        identifier = int.from_bytes(payload[2:6], "little")
        part = int.from_bytes(payload[6:8], "little")
        expected_id, path, expected_part, content = self.current
        if sender != client_id or identifier != expected_id or part != expected_part:
            raise ProtocolError("out-of-order file part or unexpected client")
        content.extend(decompress(payload[9:], max_size=PART_SIZE))
        if payload[8]:
            completed = (path, bytes(content))
            self.current = None
            return completed, self.begin(server_id)
        self.current = (expected_id, path, expected_part + 1, content)
        return None, self._request(server_id)

    def _request(self, server_id: int) -> bytes:
        assert self.current is not None
        identifier, _path, part, _content = self.current
        return frame(0x35, server_id.to_bytes(2, "little") + identifier.to_bytes(4, "little") + part.to_bytes(2, "little"))
