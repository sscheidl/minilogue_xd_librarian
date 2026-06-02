"""Shared event payloads for native SysEx capture."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawCaptureEvent:
    kind: str
    message: str = ""
    raw: bytes = b""
    state: str = ""
    port_name: str = ""
