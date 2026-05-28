"""minilogue xd SysEx request builders.

These functions only build request bytes. They do not send anything by
themselves, which keeps hardware-facing actions explicit in the GUI layer.
"""

from __future__ import annotations

KORG_ID = 0x42
XD_FAMILY = [0x00, 0x01, 0x51]
CURRENT_PROGRAM_REQUEST = 0x10
PROGRAM_SLOT_REQUEST = 0x1C
MAX_PROGRAM_SLOT = 499


def korg_xd_header(channel: int = 0) -> list[int]:
    return [0xF0, KORG_ID, 0x30 | (channel & 0x0F), *XD_FAMILY]


def request_current_program(channel: int = 0) -> bytes:
    return bytes([*korg_xd_header(channel), CURRENT_PROGRAM_REQUEST, 0xF7])


def slot_to_lsb_msb(slot_index: int) -> tuple[int, int]:
    if not 0 <= slot_index <= MAX_PROGRAM_SLOT:
        raise ValueError(f"slot_index must be 0..{MAX_PROGRAM_SLOT}")
    return slot_index & 0x7F, (slot_index >> 7) & 0x03


def request_program_slot(slot_index: int, channel: int = 0) -> bytes:
    lsb, msb = slot_to_lsb_msb(slot_index)
    return bytes([*korg_xd_header(channel), PROGRAM_SLOT_REQUEST, lsb, msb, 0xF7])
