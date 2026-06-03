"""Safe raw SysEx sending helpers."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import mido


ProgressCallback = Callable[[int, int, int], None]


def validate_sysex(raw: bytes) -> None:
    if len(raw) < 2 or raw[0] != 0xF0 or raw[-1] != 0xF7:
        raise ValueError("Only complete SysEx messages starting with F0 and ending with F7 can be sent.")


def make_mido_sysex(raw: bytes) -> mido.Message:
    validate_sysex(raw)
    return mido.Message("sysex", data=list(raw[1:-1]))


class MidiSender:
    """Send explicit raw SysEx messages through an already-open MIDI OUT port."""

    def __init__(self, output_port: Any):
        self.output_port = output_port
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True

    def send_messages(
        self,
        messages: list[bytes],
        delay_ms: int,
        progress: ProgressCallback | None = None,
    ) -> int:
        if self.output_port is None:
            raise RuntimeError(
                "No MIDI OUT port is open. Open a MIDI OUT port in the Transfer tab before sending data to the Minilogue XD."
            )

        sent = 0
        total = len(messages)
        for index, raw in enumerate(messages, start=1):
            if self.cancel_requested:
                break
            self.output_port.send(make_mido_sysex(raw))
            sent += 1
            if progress is not None:
                progress(index, total, len(raw))
            if delay_ms > 0 and index < total:
                time.sleep(delay_ms / 1000)
        return sent
