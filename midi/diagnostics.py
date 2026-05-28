"""MIDI and SysEx diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


KORG_MANUFACTURER_ID = 0x42


@dataclass
class SysexMessage:
    timestamp: float
    raw: bytes
    length: int
    starts_with_f0: bool
    ends_with_f7: bool
    manufacturer_id: Optional[int]
    is_korg: bool


@dataclass
class MidiMessageInfo:
    message_type: str
    length: int
    is_sysex: bool
    starts_with_f0: bool
    ends_with_f7: bool
    manufacturer_id: Optional[int]
    is_korg: bool


def analyze_raw_message(raw: bytes, message_type: str) -> MidiMessageInfo:
    starts_with_f0 = bool(raw) and raw[0] == 0xF0
    ends_with_f7 = bool(raw) and raw[-1] == 0xF7
    is_sysex = message_type == "sysex" or starts_with_f0
    manufacturer_id = raw[1] if len(raw) > 1 and starts_with_f0 else None
    is_korg = starts_with_f0 and ends_with_f7 and manufacturer_id == KORG_MANUFACTURER_ID

    return MidiMessageInfo(
        message_type=message_type,
        length=len(raw),
        is_sysex=is_sysex,
        starts_with_f0=starts_with_f0,
        ends_with_f7=ends_with_f7,
        manufacturer_id=manufacturer_id,
        is_korg=is_korg,
    )


def build_sysex_message(raw: bytes, timestamp: float) -> SysexMessage:
    info = analyze_raw_message(raw, "sysex")
    return SysexMessage(
        timestamp=timestamp,
        raw=raw,
        length=info.length,
        starts_with_f0=info.starts_with_f0,
        ends_with_f7=info.ends_with_f7,
        manufacturer_id=info.manufacturer_id,
        is_korg=info.is_korg,
    )
