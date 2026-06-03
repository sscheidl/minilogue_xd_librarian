"""minilogue xd SysEx helpers reserved for format-specific parsing."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter

from midi.diagnostics import KORG_MANUFACTURER_ID
from xd_formats.sysex_codec import split_sysex_stream_ignoring_realtime

XD_FAMILY_ID = bytes([0x00, 0x01, 0x51])


def is_korg_sysex(raw: bytes) -> bool:
    return len(raw) >= 3 and raw[0] == 0xF0 and raw[1] == KORG_MANUFACTURER_ID and raw[-1] == 0xF7


def is_minilogue_xd_sysex(raw: bytes) -> bool:
    return is_korg_sysex(raw) and len(raw) >= 7 and raw[3:6] == XD_FAMILY_ID


@dataclass(frozen=True)
class XDSysexClassification:
    command: int | None
    label: str
    sendable_program: bool
    slot_index: int | None = None


def classify_xd_sysex(raw: bytes) -> XDSysexClassification:
    if not is_korg_sysex(raw) or len(raw) < 8:
        return XDSysexClassification(None, "invalid-or-non-korg", False)
    if not is_minilogue_xd_sysex(raw):
        return XDSysexClassification(raw[6], "unsupported-korg-family", False)
    command = raw[6]
    if command == 0x40:
        return XDSysexClassification(command, "current-program-data-dump", True)
    if command == 0x4C:
        slot_index = raw[7] | (raw[8] << 7) if len(raw) > 9 else None
        return XDSysexClassification(command, "program-data-dump-with-slot", True, slot_index)
    if command == 0x23:
        return XDSysexClassification(command, "write-ack", False)
    if command == 0x44:
        return XDSysexClassification(command, "program-index-data-dump", False)
    if command == 0x45:
        return XDSysexClassification(command, "sequencer-index-data-dump", False)
    if command == 0x51:
        return XDSysexClassification(command, "global-data-dump", False)
    return XDSysexClassification(command, "unknown", False)


def summarize_xd_sysex_stream(raw: bytes) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for message in split_sysex_stream_ignoring_realtime(raw):
        info = classify_xd_sysex(message)
        if info.label == "unsupported-korg-family":
            counts["unknown"] += 1
        elif info.command == 0x40:
            counts["0x40 current program"] += 1
        elif info.command == 0x4C:
            counts["0x4C program dumps"] += 1
        elif info.command == 0x44:
            counts["0x44 bank index"] += 1
        elif info.command == 0x45:
            counts["0x45 sequencer index"] += 1
        elif info.command == 0x51:
            counts["0x51 global data"] += 1
        elif info.command == 0x23:
            counts["0x23 write ack"] += 1
        else:
            counts["unknown"] += 1
    return {
        "0x40 current program": counts["0x40 current program"],
        "0x4C program dumps": counts["0x4C program dumps"],
        "0x44 bank index": counts["0x44 bank index"],
        "0x45 sequencer index": counts["0x45 sequencer index"],
        "0x51 global data": counts["0x51 global data"],
        "0x23 write ack": counts["0x23 write ack"],
        "unknown": counts["unknown"],
    }
