"""Program slot models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProgramSlot:
    internal_index: int
    display_number: int
    bank_slot: str
    name: str
    source: str
    status: str
    raw_data: bytes | None
    hash_short: str
    notes: str
