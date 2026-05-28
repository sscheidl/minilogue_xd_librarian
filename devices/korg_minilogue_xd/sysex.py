"""minilogue xd SysEx helpers reserved for format-specific parsing."""

from __future__ import annotations

from midi.diagnostics import KORG_MANUFACTURER_ID


def is_korg_sysex(raw: bytes) -> bool:
    return len(raw) >= 3 and raw[0] == 0xF0 and raw[1] == KORG_MANUFACTURER_ID and raw[-1] == 0xF7
