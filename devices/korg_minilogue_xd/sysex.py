"""minilogue xd SysEx helpers reserved for format-specific parsing."""

from __future__ import annotations

from dataclasses import dataclass

from midi.diagnostics import KORG_MANUFACTURER_ID


def is_korg_sysex(raw: bytes) -> bool:
    return len(raw) >= 3 and raw[0] == 0xF0 and raw[1] == KORG_MANUFACTURER_ID and raw[-1] == 0xF7


@dataclass(frozen=True)
class XDSysexClassification:
    command: int | None
    label: str
    sendable_program: bool
    slot_index: int | None = None


def classify_xd_sysex(raw: bytes) -> XDSysexClassification:
    if not is_korg_sysex(raw) or len(raw) < 8:
        return XDSysexClassification(None, "invalid-or-non-korg", False)
    command = raw[6]
    if command == 0x40:
        return XDSysexClassification(command, "current-program-data-dump", True)
    if command == 0x4C:
        slot_index = raw[7] | (raw[8] << 7) if len(raw) > 9 else None
        return XDSysexClassification(command, "program-data-dump-with-slot", True, slot_index)
    if command == 0x44:
        return XDSysexClassification(command, "unknown-index-data", False)
    if command == 0x45:
        return XDSysexClassification(command, "unknown-sequencer-index-data", False)
    if command == 0x51:
        return XDSysexClassification(command, "unknown-global-data", False)
    return XDSysexClassification(command, "unknown", False)
