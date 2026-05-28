"""Program slot numbering for the Korg minilogue xd."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import BANK_LETTERS, BANK_SIZE, PROGRAM_SLOT_COUNT


@dataclass(frozen=True)
class SlotMapping:
    internal_index: int
    display_number: int
    display_number_text: str
    bank_index: int
    bank_slot_number: int
    bank_slot_text: str


def map_slot(internal_index: int) -> SlotMapping:
    if not 0 <= internal_index < PROGRAM_SLOT_COUNT:
        raise ValueError(f"Slot index out of range: {internal_index}")

    display_number = internal_index + 1
    bank_index = internal_index // BANK_SIZE
    bank_slot_number = internal_index % BANK_SIZE + 1
    bank_slot_text = f"{BANK_LETTERS[bank_index]}{bank_slot_number:03d}"
    return SlotMapping(
        internal_index=internal_index,
        display_number=display_number,
        display_number_text=f"{display_number:03d}",
        bank_index=bank_index,
        bank_slot_number=bank_slot_number,
        bank_slot_text=bank_slot_text,
    )
