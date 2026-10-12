#!/usr/bin/env python3
"""Build and inspect OP-1/OP-Z sampler AIFF files."""

from __future__ import annotations

import json
import math
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SAMPLE_RATE = 44_100
BYTES_PER_FRAME = 2
DRUM_MAX_FRAMES = SAMPLE_RATE * 12
DRUM_SLICE_MAX_FRAMES = SAMPLE_RATE * 4
SYNTH_MAX_FRAMES = SAMPLE_RATE * 6
SLICE_COUNT = 24
SAMPLE_COORDINATE_SCALE = 4_058
MAX_SAMPLE_COORDINATE = 2_147_483_646
AIFF_44100_EXTENDED = bytes.fromhex("400eac44000000000000")
AUDIO_SUFFIXES = {".aif", ".aiff", ".wav", ".caf", ".m4a", ".mp3", ".flac"}


@dataclass
class ConvertedClip:
    path: Path
    audio: bytes
    original_frames: int
    used_frames: int
    gain_db: float = 0.0


def iter_aiff_chunks(data: bytes) -> Iterable[tuple[bytes, bytes]]:
    if data[:4] != b"FORM" or data[8:12] not in (b"AIFF", b"AIFC"):
        raise ValueError("Not an AIFF/AIFC file")
    cursor = 12
    while cursor + 8 <= len(data):
        chunk_id = data[cursor : cursor + 4]
        size = struct.unpack(">I", data[cursor + 4 : cursor + 8])[0]
        payload_start = cursor + 8
        payload_end = payload_start + size
        if payload_end > len(data):
            raise ValueError(f"Truncated {chunk_id!r} chunk")
        yield chunk_id, data[payload_start:payload_end]
        cursor = payload_end + (size & 1)


def read_aiff_pcm(path: Path) -> tuple[bytes, int]:
    data = path.read_bytes()
    channels = frames = bits = None
    audio = None
    for chunk_id, payload in iter_aiff_chunks(data):
        if chunk_id == b"COMM":
            channels, frames, bits = struct.unpack(">hIh", payload[:8])
        elif chunk_id == b"SSND":
            offset = struct.unpack(">I", payload[:4])[0]
            audio = payload[8 + offset :]
    if (channels, bits) != (1, 16) or frames is None or audio is None:
        raise ValueError("Expected mono 16-bit AIFF PCM")
    expected = frames * BYTES_PER_FRAME
    if len(audio) < expected:
        raise ValueError("AIFF audio is shorter than its COMM frame count")
    return audio[:expected], frames


def read_op1_metadata(path: Path) -> dict[str, Any]:
    for chunk_id, payload in iter_aiff_chunks(path.read_bytes()):
        if chunk_id == b"APPL" and payload.startswith(b"op-1"):
            decoder = json.JSONDecoder()
            text = payload[4:].decode("utf-8", errors="ignore").lstrip()
            metadata, _ = decoder.raw_decode(text)
            return metadata
    raise ValueError("AIFF has no APPL/op-1 metadata")


def _chunk(chunk_id: bytes, payload: bytes) -> bytes:
    padding = b"\0" if len(payload) & 1 else b""
    return chunk_id + struct.pack(">I", len(payload)) + payload + padding


def write_sampler_aiff(path: Path, audio: bytes, metadata: dict[str, Any]) -> None:
    if len(audio) % BYTES_PER_FRAME:
        raise ValueError("16-bit mono PCM must contain complete frames")
    frame_count = len(audio) // BYTES_PER_FRAME
    comm = struct.pack(">hIh", 1, frame_count, 16) + AIFF_44100_EXTENDED
    appl = b"op-1" + json.dumps(
        metadata, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    ssnd = struct.pack(">II", 0, 0) + audio
    body = b"AIFF" + _chunk(b"COMM", comm) + _chunk(b"APPL", appl) + _chunk(b"SSND", ssnd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"FORM" + struct.pack(">I", len(body)) + body)


def convert_clip(path: Path, frame_limit: int | None = None) -> ConvertedClip:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as source:
            if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != SAMPLE_RATE:
                raise ValueError("WAV input must be mono 16-bit PCM at 44.1 kHz")
            frames = source.getnframes()
            little_endian = source.readframes(frames)
        audio = b"".join(little_endian[index : index + 2][::-1] for index in range(0, len(little_endian), 2))
    elif path.suffix.lower() in {".aif", ".aiff"}:
        audio, frames = read_aiff_pcm(path)
    else:
        try:
            process = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16be", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as error:
            raise RuntimeError("non-WAV/AIFF conversion requires the cross-platform ffmpeg executable") from error
        audio = process.stdout
        frames = len(audio) // BYTES_PER_FRAME
    used_frames = min(frames, frame_limit) if frame_limit else frames
    return ConvertedClip(
        path=path,
        audio=audio[: used_frames * BYTES_PER_FRAME],
        original_frames=frames,
        used_frames=used_frames,
    )


def synth_metadata(name: str, base_frequency: float) -> dict[str, Any]:
    return {
        "adsr": [512, 10746, 32767, 10000, 4000, 64, 4000, 4000],
        "base_freq": base_frequency,
        "fx_active": False,
        "fx_params": [4480, 15544, 10788, 12104, 0, 0, 0, 0],
        "fx_type": "delay",
        "knobs": [0, 0, 32767, 32767, 12000, 0, 0, 8304],
        "lfo_active": False,
        "lfo_params": [11840, 18431, 1024, 15144, 0, 0, 0, 0],
        "lfo_type": "random",
        "name": name,
        "octave": 0,
        "synth_version": 1,
        "type": "sampler",
    }


def create_synth_sample(
    source: Path, output: Path, name: str, base_frequency: float = 440.0
) -> dict[str, Any]:
    clip = convert_clip(source, SYNTH_MAX_FRAMES)
    write_sampler_aiff(output, clip.audio, synth_metadata(name, base_frequency))
    return {
        "kind": "synth",
        "name": name,
        "source": str(source),
        "output": str(output),
        "original_frames": clip.original_frames,
        "used_frames": clip.used_frames,
        "duration_seconds": clip.used_frames / SAMPLE_RATE,
        "trimmed": clip.used_frames != clip.original_frames,
    }


def _coordinate(frame: int) -> int:
    return min(frame * SAMPLE_COORDINATE_SCALE, MAX_SAMPLE_COORDINATE)


def _gain_value(gain_db: float) -> int:
    return max(0, min(32767, round(8192 * math.pow(10, gain_db / 20))))


def drum_metadata(name: str, clips: list[ConvertedClip]) -> dict[str, Any]:
    starts: list[int] = []
    ends: list[int] = []
    volumes: list[int] = []
    cursor = 0
    for clip in clips:
        starts.append(_coordinate(cursor))
        cursor += clip.used_frames
        ends.append(_coordinate(cursor))
        volumes.append(_gain_value(clip.gain_db))
    final = _coordinate(cursor)
    starts.extend([final] * (SLICE_COUNT - len(starts)))
    ends.extend([final] * (SLICE_COUNT - len(ends)))
    volumes.extend([8192] * (SLICE_COUNT - len(volumes)))
    return {
        "drum_version": 2,
        "dyna_env": [0, 8192, 0, 8192, 0, 0, 0, 0],
        "end": ends,
        "fx_active": False,
        "fx_params": [8000] * 8,
        "fx_type": "delay",
        "lfo_active": False,
        "lfo_params": [16000, 16000, 16000, 16000, 0, 0, 0, 0],
        "lfo_type": "tremolo",
        "name": name,
        "octave": 0,
        "pitch": [0] * SLICE_COUNT,
        "playmode": [8192] * SLICE_COUNT,
        "reverse": [8192] * SLICE_COUNT,
        "start": starts,
        "type": "drum",
        "volume": volumes,
    }


def sources_from_directory(directory: Path) -> list[tuple[Path, int | None, float]]:
    patch = directory / "patch.json"
    if patch.is_file():
        document = json.loads(patch.read_text())
        regions = document.get("regions")
        if isinstance(regions, list):
            sources = []
            for region in regions:
                path = directory / region["sample"]
                frame_limit = region.get("sample.end") or region.get("framecount") or None
                if frame_limit == 0:
                    frame_limit = None
                sources.append((path, frame_limit, float(region.get("gain", 0))))
            return sources
    paths = sorted(
        path for path in directory.iterdir() if path.suffix.lower() in AUDIO_SUFFIXES
    )
    return [(path, None, 0.0) for path in paths]


def _fit_drum_budget(clips: list[ConvertedClip], maximum_frames: int) -> None:
    excess = sum(clip.used_frames for clip in clips) - maximum_frames
    while excess > 0:
        longest_length = max(clip.used_frames for clip in clips)
        longest = [clip for clip in clips if clip.used_frames == longest_length]
        shorter = [
            clip.used_frames for clip in clips if clip.used_frames < longest_length
        ]
        next_length = max(shorter, default=1)
        removable = (longest_length - next_length) * len(longest)
        if removable == 0:
            raise ValueError("Cannot fit drum slices into the requested duration")
        removed = min(excess, removable)
        per_clip, remainder = divmod(removed, len(longest))
        for index, clip in enumerate(longest):
            clip.used_frames -= per_clip + (1 if index < remainder else 0)
            clip.audio = clip.audio[: clip.used_frames * BYTES_PER_FRAME]
        excess -= removed


def create_drum_sample(
    sources: list[tuple[Path, int | None, float]],
    output: Path,
    name: str,
    maximum_frames: int = DRUM_MAX_FRAMES,
) -> dict[str, Any]:
    if not sources:
        raise ValueError("A drum kit needs at least one source")
    if len(sources) > SLICE_COUNT:
        raise ValueError(f"A drum kit supports at most {SLICE_COUNT} slices")
    clips = []
    for path, requested_limit, gain_db in sources:
        limit = min(requested_limit or DRUM_SLICE_MAX_FRAMES, DRUM_SLICE_MAX_FRAMES)
        clip = convert_clip(path, limit)
        clip.gain_db = gain_db
        clips.append(clip)
    _fit_drum_budget(clips, min(maximum_frames, DRUM_MAX_FRAMES))
    write_sampler_aiff(output, b"".join(clip.audio for clip in clips), drum_metadata(name, clips))

    cursor = 0
    slices = []
    for index, clip in enumerate(clips, start=1):
        start = cursor
        cursor += clip.used_frames
        slices.append(
            {
                "slice": index,
                "source": str(clip.path),
                "original_frames": clip.original_frames,
                "used_frames": clip.used_frames,
                "start_frame": start,
                "end_frame": cursor,
                "duration_seconds": clip.used_frames / SAMPLE_RATE,
                "gain_db": clip.gain_db,
                "trimmed": clip.used_frames != clip.original_frames,
            }
        )
    return {
        "kind": "drum",
        "name": name,
        "output": str(output),
        "slice_count": len(clips),
        "total_frames": cursor,
        "duration_seconds": cursor / SAMPLE_RATE,
        "slices": slices,
    }
