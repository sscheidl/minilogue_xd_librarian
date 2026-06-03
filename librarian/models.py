"""Data models for offline librarian workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


STATUS_EMPTY = "empty"
STATUS_SYNCED = "Synced"
STATUS_IMPORTED = "Imported"
STATUS_MODIFIED = "Modified in editor"
STATUS_SENT = "Sent to XD"
STATUS_ERROR = "Error"


@dataclass
class SysexRecord:
    index: int
    raw: bytes
    length: int
    manufacturer_id: Optional[int]
    is_korg: bool
    dump_type: str
    sha256: str
    notes: str = ""

    @property
    def short_hash(self) -> str:
        return self.sha256[:12]


@dataclass
class PresetItem:
    name: str
    source_path: str
    record: SysexRecord
    display_name_override: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.display_name_override or self.name


@dataclass
class BankSlot:
    slot: int
    name: str = ""
    source: str = ""
    raw: bytes = b""
    prog_bin: bytes = b""
    sha256: str = ""
    status: str = STATUS_EMPTY
    notes: str = ""

    @property
    def short_hash(self) -> str:
        return self.sha256[:12] if self.sha256 else ""


@dataclass
class BankWorkspace:
    slots: list[BankSlot] = field(
        default_factory=lambda: [BankSlot(slot=i + 1) for i in range(500)]
    )

    def snapshot(self) -> list[BankSlot]:
        return [
            BankSlot(
                slot=slot.slot,
                name=slot.name,
                source=slot.source,
                raw=slot.raw,
                prog_bin=slot.prog_bin,
                sha256=slot.sha256,
                status=slot.status,
                notes=slot.notes,
            )
            for slot in self.slots
        ]

    def restore(self, snapshot: list[BankSlot]) -> None:
        self.slots = [
            BankSlot(
                slot=i + 1,
                name=slot.name,
                source=slot.source,
                raw=slot.raw,
                prog_bin=slot.prog_bin,
                sha256=slot.sha256,
                status=slot.status,
                notes=slot.notes,
            )
            for i, slot in enumerate(snapshot[:500])
        ]
        while len(self.slots) < 500:
            self.slots.append(BankSlot(slot=len(self.slots) + 1))
