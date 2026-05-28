"""Capture buffer for incoming SysEx dumps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from midi.diagnostics import SysexMessage, build_sysex_message


@dataclass
class SysexCapture:
    started_at: float
    finished_at: Optional[float] = None
    messages: list[SysexMessage] = field(default_factory=list)
    total_bytes: int = 0
    finalized_by: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.finalized_by is None


class SysexBuffer:
    """Collects related SysEx messages into a single capture session."""

    def __init__(self) -> None:
        self.capture: Optional[SysexCapture] = None
        self.last_sysex_at: Optional[float] = None

    def clear(self) -> None:
        self.capture = None
        self.last_sysex_at = None

    def add_message(self, raw: bytes, timestamp: float) -> SysexMessage:
        if self.capture is None or not self.capture.is_active:
            self.capture = SysexCapture(started_at=timestamp)

        message = build_sysex_message(raw, timestamp)
        self.capture.messages.append(message)
        self.capture.total_bytes += message.length
        self.last_sysex_at = timestamp
        return message

    def finalize(self, finalized_by: str, timestamp: float) -> bool:
        if self.capture is None or not self.capture.is_active:
            return False

        self.capture.finished_at = timestamp
        self.capture.finalized_by = finalized_by
        return True

    def check_timeouts(
        self,
        now: float,
        inactivity_ms: int,
        max_timeout_s: int,
    ) -> Optional[str]:
        if self.capture is None or not self.capture.is_active:
            return None

        if max_timeout_s > 0 and now - self.capture.started_at >= max_timeout_s:
            self.finalize("timeout", now)
            return "timeout"

        if self.last_sysex_at is not None and inactivity_ms > 0:
            if (now - self.last_sysex_at) * 1000 >= inactivity_ms:
                self.finalize("inactivity", now)
                return "inactivity"

        return None

    def to_bytes(self) -> bytes:
        if self.capture is None:
            return b""

        return b"".join(message.raw for message in self.capture.messages)
