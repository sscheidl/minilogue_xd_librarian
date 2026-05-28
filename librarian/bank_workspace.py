"""Offline 500-slot bank workspace operations."""

from __future__ import annotations

import hashlib
from collections import Counter

from .models import BankSlot, BankWorkspace, SysexRecord

try:
    from xd_formats import XDLibrary, XDProgram, encode_program_dump, read_program_name, write_program_name
except ImportError:  # pragma: no cover - keeps the legacy SysEx-only path importable.
    XDLibrary = None
    XDProgram = None
    encode_program_dump = None
    read_program_name = None
    write_program_name = None


class OfflineBank:
    def __init__(self) -> None:
        self.workspace = BankWorkspace()
        self._undo: list[list[BankSlot]] = []
        self.clipboard: BankSlot | None = None

    @property
    def slots(self) -> list[BankSlot]:
        return self.workspace.slots

    def remember(self) -> None:
        self._undo.append(self.workspace.snapshot())
        self._undo = self._undo[-20:]

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.workspace.restore(self._undo.pop())
        return True

    def clear(self) -> None:
        self.remember()
        self.workspace = BankWorkspace()

    def load_records(self, records: list[SysexRecord], source: str) -> None:
        self.remember()
        self.workspace = BankWorkspace()
        for index, record in enumerate(records[:500]):
            self.workspace.slots[index] = BankSlot(
                slot=index + 1,
                name=f"Program {index + 1:03d}",
                source=source,
                raw=record.raw,
                prog_bin=b"",
                sha256=record.sha256,
                status=record.dump_type,
                notes="Loaded from SysEx message; program name not decoded yet.",
            )
        self.mark_duplicates()

    def load_programs(self, programs: list[object], source: str, source_type: str) -> None:
        self.remember()
        self.workspace = BankWorkspace()
        for index, program in enumerate(programs[:500]):
            raw = (
                encode_program_dump(program, index)
                if encode_program_dump is not None and getattr(program, "prog_bin", b"")
                else b""
            )
            prog_bin = getattr(program, "prog_bin", b"")
            self.workspace.slots[index] = BankSlot(
                slot=index + 1,
                name=getattr(program, "name", "") or f"Program {index + 1:03d}",
                source=source,
                raw=raw,
                prog_bin=prog_bin,
                sha256=self.hash_raw(prog_bin or raw),
                status=source_type,
                notes="Decoded minilogue xd program data.",
            )
        self.mark_duplicates()

    def rename(self, slot_index: int, name: str) -> None:
        if not self._valid(slot_index):
            return
        self.remember()
        slot = self.slots[slot_index]
        new_name = name.strip()
        slot.name = new_name
        if slot.prog_bin and write_program_name is not None and read_program_name is not None:
            slot.prog_bin = write_program_name(slot.prog_bin, new_name)
            slot.name = read_program_name(slot.prog_bin)
            slot.sha256 = self.hash_raw(slot.prog_bin)
            if encode_program_dump is not None:
                slot.raw = encode_program_dump(_slot_to_program(slot, slot_index), slot_index)
            slot.notes = "Program name written into bytes 4:16."
        elif slot.raw:
            slot.notes = "Display name override; raw program bytes unchanged."

    def copy(self, slot_index: int) -> None:
        if self._valid(slot_index):
            slot = self.slots[slot_index]
            self.clipboard = BankSlot(
                slot=slot.slot,
                name=slot.name,
                source=slot.source,
                raw=slot.raw,
                prog_bin=slot.prog_bin,
                sha256=slot.sha256,
                status=slot.status,
                notes=slot.notes,
            )

    def paste(self, slot_index: int) -> None:
        if self.clipboard is None or not self._valid(slot_index):
            return
        self.remember()
        self.slots[slot_index] = BankSlot(
            slot=slot_index + 1,
            name=self.clipboard.name,
            source=self.clipboard.source,
            raw=self.clipboard.raw,
            prog_bin=self.clipboard.prog_bin,
            sha256=self.clipboard.sha256,
            status=self.clipboard.status,
            notes="Pasted offline copy.",
        )
        self.mark_duplicates()

    def swap(self, first: int, second: int) -> None:
        if not self._valid(first) or not self._valid(second):
            return
        self.remember()
        self.slots[first], self.slots[second] = self.slots[second], self.slots[first]
        self._renumber()

    def move(self, first: int, second: int) -> None:
        if not self._valid(first) or not self._valid(second):
            return
        self.remember()
        slot = self.slots.pop(first)
        self.slots.insert(second, slot)
        self._renumber()

    def clear_slot(self, slot_index: int) -> None:
        if not self._valid(slot_index):
            return
        self.remember()
        self.slots[slot_index] = BankSlot(slot=slot_index + 1, status="empty")
        self.mark_duplicates()

    def sort_by_name(self, reverse: bool = False) -> None:
        self.remember()
        filled = [slot for slot in self.slots if slot.raw or slot.name]
        empty = [slot for slot in self.slots if not slot.raw and not slot.name]
        filled.sort(key=lambda slot: slot.name.lower(), reverse=reverse)
        self.slots[:] = filled + empty
        self._renumber()

    def mark_duplicates(self) -> None:
        counts = Counter(slot.sha256 for slot in self.slots if slot.sha256)
        for slot in self.slots:
            if slot.sha256 and counts[slot.sha256] > 1:
                slot.status = f"{slot.status}; duplicate"

    def export_selected_bytes(self, indices: list[int]) -> bytes:
        return b"".join(self.slots[index].raw for index in indices if self._valid(index))

    def export_programs(self, indices: list[int] | None = None) -> list[object]:
        if XDProgram is None:
            return []
        selected = indices if indices is not None else list(range(len(self.slots)))
        programs = []
        for index in selected:
            if not self._valid(index):
                continue
            slot = self.slots[index]
            if slot.prog_bin:
                programs.append(_slot_to_program(slot, index))
        return programs

    @staticmethod
    def hash_raw(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest() if raw else ""

    def _renumber(self) -> None:
        for index, slot in enumerate(self.slots):
            slot.slot = index + 1

    def _valid(self, slot_index: int) -> bool:
        return 0 <= slot_index < len(self.slots)


def _slot_to_program(slot: BankSlot, slot_index: int) -> object:
    return XDProgram(
        slot_index=slot_index,
        name=slot.name,
        prog_bin=slot.prog_bin,
        source_type=slot.status,
    )
