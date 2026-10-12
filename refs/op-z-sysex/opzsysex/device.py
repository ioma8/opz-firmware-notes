"""Small cross-platform mido transport; imported only for live device I/O."""

from __future__ import annotations

import time
from typing import Iterable


class DeviceError(RuntimeError):
    pass


def list_ports() -> tuple[list[str], list[str]]:
    mido = _mido()
    return list(mido.get_input_names()), list(mido.get_output_names())


def find_port(names: Iterable[str], match: str = "OP-Z") -> str:
    matches = [name for name in names if match.lower() in name.lower()]
    if len(matches) != 1:
        raise DeviceError(f"expected one MIDI port matching {match!r}, found {matches}")
    return matches[0]


class Device:
    def __init__(self, match: str = "OP-Z"):
        mido = _mido()
        self._mido = mido
        self.input_name = find_port(mido.get_input_names(), match)
        self.output_name = find_port(mido.get_output_names(), match)
        self.input = None
        self.output = None

    def __enter__(self) -> "Device":
        self.input = self._mido.open_input(self.input_name)
        self.output = self._mido.open_output(self.output_name)
        return self

    def __exit__(self, *_args) -> None:
        if self.input is not None:
            self.input.close()
        if self.output is not None:
            self.output.close()

    def send(self, sysex: bytes) -> None:
        if self.output is None or sysex[:1] != b"\xF0" or sysex[-1:] != b"\xF7":
            raise DeviceError("device is closed or frame is not complete SysEx")
        self.output.send(self._mido.Message("sysex", data=sysex[1:-1]))

    def receive(self, timeout: float = 2.0) -> bytes:
        if self.input is None:
            raise DeviceError("device is closed")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.input.poll()
            if message is not None and message.type == "sysex":
                return bytes((0xF0, *message.data, 0xF7))
            time.sleep(0.002)
        raise DeviceError(f"timed out after {timeout:.3f}s")

    def request(self, sysex: bytes, timeout: float = 2.0) -> bytes:
        self.send(sysex)
        return self.receive(timeout)


def _mido():
    try:
        import mido
    except ImportError as error:
        raise DeviceError('device I/O requires: pip install -e ".[device]"') from error
    return mido
