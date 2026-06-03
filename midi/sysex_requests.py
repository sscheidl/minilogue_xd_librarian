"""minilogue xd SysEx request builders.

These functions only build request bytes. They do not send anything by
themselves, which keeps hardware-facing actions explicit in the GUI layer.

Korg minilogue xd SysEx structure (MIDI System Exclusive):
    F0  42  3n  00 01 51  <cmd>  [lsb msb]  F7
    n = MIDI channel (0-based, default 0)

Command bytes (request direction, host -> device):
    0x0E  Global Diagnostic Request  -> device sends one 0x51 response
    0x10  Current Program Dump Req.  -> device sends one 0x40 response
    0x1C  Program Parameter Dump Req -> device sends 0x4C for the given slot
"""

from __future__ import annotations

__all__ = [
    "KORG_ID",
    "XD_FAMILY",
    "CURRENT_PROGRAM_REQUEST",
    "PROGRAM_SLOT_REQUEST",
    "GLOBAL_DATA_REQUEST",
    "ALL_PROGRAMS_REQUEST",
    "MAX_PROGRAM_SLOT",
    "korg_xd_header",
    "request_current_program",
    "request_global_data",
    "build_all_programs_request",
    "slot_to_lsb_msb",
    "request_program_slot",
]

KORG_ID: int = 0x42
XD_FAMILY: list[int] = [0x00, 0x01, 0x51]

# Request command bytes (host -> device)
CURRENT_PROGRAM_REQUEST: int = 0x10
PROGRAM_SLOT_REQUEST: int = 0x1C
GLOBAL_DATA_REQUEST: int = 0x0E
ALL_PROGRAMS_REQUEST: int = GLOBAL_DATA_REQUEST

MAX_PROGRAM_SLOT: int = 499  # 0-based; slots 0-499 = display numbers 1-500


def korg_xd_header(channel: int = 0) -> list[int]:
    """Return the 5-byte Korg XD SysEx header for the given MIDI channel.

    Args:
        channel: MIDI channel, 0-based (0..15).

    Returns:
        List of ints: [F0, 42, 3n, 00, 01, 51]

    Raises:
        ValueError: if channel is outside 0..15.
    """
    if not 0 <= channel <= 15:
        raise ValueError(f"channel must be 0..15, got {channel!r}")
    return [0xF0, KORG_ID, 0x30 | (channel & 0x0F), *XD_FAMILY]


def request_current_program(channel: int = 0, trailing_zero: bool = True) -> bytes:
    """Build a Current Program Dump Request (cmd 0x10).

    The device responds with a Current Program Dump (cmd 0x40).
    """
    body = [CURRENT_PROGRAM_REQUEST]
    if trailing_zero:
        body.append(0x00)
    return bytes([*korg_xd_header(channel), *body, 0xF7])


def request_global_data(channel: int = 0) -> bytes:
    """Build a Global Diagnostic/Data Request (cmd 0x0E).

    Hardware tests showed this command returns 0x51 data, not program dumps.
    """
    return bytes([*korg_xd_header(channel), GLOBAL_DATA_REQUEST, 0xF7])


def slot_to_lsb_msb(slot_index: int) -> tuple[int, int]:
    """Split a 0-based slot index into (LSB, MSB) for SysEx encoding.

    The minilogue xd encodes slot numbers as two 7-bit values:
        LSB = slot_index & 0x7F
        MSB = (slot_index >> 7) & 0x03  (max 499 fits in 9 bits)

    Args:
        slot_index: 0-based slot (0..MAX_PROGRAM_SLOT).

    Returns:
        Tuple (lsb, msb).

    Raises:
        ValueError: if slot_index is outside 0..MAX_PROGRAM_SLOT.
    """
    if not 0 <= slot_index <= MAX_PROGRAM_SLOT:
        raise ValueError(
            f"slot_index must be 0..{MAX_PROGRAM_SLOT}, got {slot_index!r}"
        )
    return slot_index & 0x7F, (slot_index >> 7) & 0x03


def request_program_slot(slot_index: int, channel: int = 0, trailing_zero: bool = True) -> bytes:
    """Build a Program Parameter Dump Request (cmd 0x1C) for one slot.

    The device responds with a Program Parameter Dump (cmd 0x4C).

    Args:
        slot_index: 0-based slot index (0..MAX_PROGRAM_SLOT).
        channel:    MIDI channel, 0-based (0..15).

    Returns:
        SysEx bytes ready to send via MIDI OUT.
    """
    lsb, msb = slot_to_lsb_msb(slot_index)
    body = [PROGRAM_SLOT_REQUEST, lsb, msb]
    if trailing_zero:
        body.append(0x00)
    return bytes([*korg_xd_header(channel), *body, 0xF7])


# Backward-compatible alias for older tests/docs. 0x0E is not used for full-bank
# receive in the GUI anymore because hardware returned 0x51 global data.
build_all_programs_request = request_global_data
