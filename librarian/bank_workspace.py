"""Offline 500-slot bank workspace operations."""

from __future__ import annotations

import hashlib
from collections import Counter

from .models import (
    STATUS_ERROR,
    STATUS_MODIFIED,
    STATUS_SENT,
    STATUS_SYNCED,
    BankSlot,
    BankWorkspace,
    SysexRecord,
)

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
        self.clipboard: list[BankSlot] = []
        self.init_template_prog_bin: bytes | None = None

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
        self.init_template_prog_bin = None

    def load_records(self, records: list[SysexRecord], source: str, status: str = STATUS_SYNCED) -> None:
        self.remember()
        self.workspace = BankWorkspace()
        self.init_template_prog_bin = None
        for index, record in enumerate(records[:500]):
            self.workspace.slots[index] = BankSlot(
                slot=index + 1,
                name=f"Program {index + 1:03d}",
                source=source,
                raw=record.raw,
                prog_bin=b"",
                sha256=record.sha256,
                status=status,
                notes="Loaded from SysEx message; program name not decoded yet.",
            )
        self.mark_duplicates()

    def load_programs(self, programs: list[object], source: str, source_type: str, status: str = STATUS_SYNCED) -> None:
        self.remember()
        self.workspace = BankWorkspace()
        self.init_template_prog_bin = None
        for index, program in enumerate(programs[:500]):
            raw = (
                encode_program_dump(program, index)
                if encode_program_dump is not None and getattr(program, "prog_bin", b"")
                else b""
            )
            prog_bin = getattr(program, "prog_bin", b"")
            name = getattr(program, "name", "") or f"Program {index + 1:03d}"
            self.workspace.slots[index] = BankSlot(
                slot=index + 1,
                name=name,
                source=source,
                raw=raw,
                prog_bin=prog_bin,
                sha256=self.hash_raw(prog_bin or raw),
                status=status,
                notes="Decoded minilogue xd program data.",
            )
            self._remember_init_template(name, prog_bin)
        self.mark_duplicates()

    def load_programs_by_slot(self, programs: list[object], source: str, source_type: str, status: str = STATUS_SYNCED) -> None:
        self.remember()
        self.workspace = BankWorkspace()
        self.init_template_prog_bin = None
        for program in programs:
            slot_index = getattr(program, "slot_index", None)
            if slot_index is None or not self._valid(slot_index):
                continue
            prog_bin = getattr(program, "prog_bin", b"")
            raw = (
                encode_program_dump(program, slot_index)
                if encode_program_dump is not None and prog_bin
                else b""
            )
            name = getattr(program, "name", "") or f"Program {slot_index + 1:03d}"
            self.workspace.slots[slot_index] = BankSlot(
                slot=slot_index + 1,
                name=name,
                source=source,
                raw=raw,
                prog_bin=prog_bin,
                sha256=self.hash_raw(prog_bin or raw),
                status=status,
                notes="Decoded minilogue xd program data from captured bank dump.",
            )
            self._remember_init_template(name, prog_bin)
        self.mark_duplicates()

    def merge_programs(self, programs: list[object], source: str, source_type: str, status: str = STATUS_SYNCED) -> int:
        valid_programs = [
            program
            for program in programs
            if (slot_index := getattr(program, "slot_index", None)) is not None and self._valid(slot_index)
        ]
        if not valid_programs:
            return 0
        self.remember()
        merged = 0
        for program in valid_programs:
            slot_index = getattr(program, "slot_index")
            prog_bin = getattr(program, "prog_bin", b"")
            raw = (
                encode_program_dump(program, slot_index)
                if encode_program_dump is not None and prog_bin
                else b""
            )
            name = getattr(program, "name", "") or f"Program {slot_index + 1:03d}"
            self.workspace.slots[slot_index] = BankSlot(
                slot=slot_index + 1,
                name=name,
                source=source,
                raw=raw,
                prog_bin=prog_bin,
                sha256=self.hash_raw(prog_bin or raw),
                status=status,
                notes="Decoded minilogue xd program data from captured bank dump.",
            )
            self._remember_init_template(name, prog_bin)
            merged += 1
        self.mark_duplicates()
        return merged

    def set_program(
        self,
        slot_index: int,
        program: object,
        source: str,
        source_type: str,
        notes: str = "",
        status: str = STATUS_SYNCED,
    ) -> None:
        if not self._valid(slot_index):
            return
        self.remember()
        raw = (
            encode_program_dump(program, slot_index)
            if encode_program_dump is not None and getattr(program, "prog_bin", b"")
            else b""
        )
        prog_bin = getattr(program, "prog_bin", b"")
        self.workspace.slots[slot_index] = BankSlot(
            slot=slot_index + 1,
            name=getattr(program, "name", "") or "name unknown",
            source=source,
            raw=raw,
            prog_bin=prog_bin,
            sha256=self.hash_raw(prog_bin or raw),
            status=status,
            notes=notes or "Decoded minilogue xd program data.",
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
            slot.status = STATUS_MODIFIED
            slot.notes = "Program name written into bytes 4:16."
        elif slot.raw:
            slot.status = STATUS_MODIFIED
            slot.notes = "Display name override; raw program bytes unchanged."

    def copy(self, slot_index: int) -> None:
        self.copy_indices([slot_index])

    def copy_indices(self, indices: list[int]) -> int:
        self.clipboard = [
            self._clone_slot(self.slots[index])
            for index in sorted(indices)
            if self._valid(index) and (self.slots[index].raw or self.slots[index].prog_bin)
        ]
        return len(self.clipboard)

    def paste(self, slot_index: int) -> None:
        self.paste_many(slot_index)

    def paste_many(self, slot_index: int) -> int:
        if not self.clipboard or not self._valid(slot_index):
            return 0
        if slot_index + len(self.clipboard) > len(self.slots):
            return 0
        self.remember()
        for offset, copied in enumerate(self.clipboard):
            target_index = slot_index + offset
            self.slots[target_index] = BankSlot(
                slot=target_index + 1,
                name=copied.name,
                source=copied.source,
                raw=copied.raw,
                prog_bin=copied.prog_bin,
                sha256=copied.sha256,
                status=STATUS_MODIFIED,
                notes="Pasted offline copy.",
            )
            self._rewrite_slot_payload(target_index)
        self.mark_duplicates()
        return len(self.clipboard)

    def insert_many(self, slot_index: int) -> int:
        if not self.clipboard or not self._valid(slot_index):
            return 0
        count = len(self.clipboard)
        if not self.can_insert(slot_index, count):
            return 0
        self.remember()
        inserted = [self._clone_slot(slot) for slot in self.clipboard]
        self.slots[slot_index:slot_index] = inserted
        self.workspace.slots = self.slots[:500]
        self._renumber(mark_modified=True, start=slot_index)
        self.mark_duplicates()
        return count

    def can_insert(self, slot_index: int, count: int) -> bool:
        if count <= 0 or not self._valid(slot_index):
            return False
        tail = self.slots[-count:]
        return all(not slot.raw and not slot.prog_bin for slot in tail)

    def clear_slot(self, slot_index: int) -> bool:
        return self.clear_slots([slot_index])

    def clear_slots(self, indices: list[int]) -> bool:
        valid = [index for index in sorted(indices) if self._valid(index)]
        if not valid:
            return True
        if self.init_template_prog_bin is None:
            return False
        self.remember()
        for index in valid:
            prog_bin = self.init_template_prog_bin
            self.slots[index] = BankSlot(
                slot=index + 1,
                name="Init",
                source="init template",
                prog_bin=prog_bin,
                sha256=self.hash_raw(prog_bin),
                status=STATUS_MODIFIED,
                notes="Cleared to verified Init template.",
            )
            self._rewrite_slot_payload(index)
        self.mark_duplicates()
        return True

    def swap(self, first: int, second: int) -> None:
        if not self._valid(first) or not self._valid(second):
            return
        self.remember()
        self.slots[first], self.slots[second] = self.slots[second], self.slots[first]
        self._renumber(mark_modified=True)

    def move(self, first: int, second: int) -> None:
        if not self._valid(first) or not self._valid(second):
            return
        self.remember()
        slot = self.slots.pop(first)
        self.slots.insert(second, slot)
        self._renumber(mark_modified=True, start=min(first, second), end=max(first, second))

    def sort_by_name(self, reverse: bool = False) -> None:
        self.remember()
        filled = [slot for slot in self.slots if slot.raw or slot.name]
        empty = [slot for slot in self.slots if not slot.raw and not slot.name]
        filled.sort(key=lambda slot: slot.name.lower(), reverse=reverse)
        self.slots[:] = filled + empty
        self._renumber(mark_modified=True)

    def mark_duplicates(self) -> None:
        counts = Counter(slot.sha256 for slot in self.slots if slot.sha256)
        for slot in self.slots:
            if slot.sha256 and counts[slot.sha256] > 1 and "duplicate" not in slot.notes.lower():
                slot.notes = (slot.notes + " Duplicate program data.").strip()

    def export_selected_bytes(self, indices: list[int]) -> bytes:
        return b"".join(self.raw_for_slot(index) for index in indices if self._valid(index) and self.raw_for_slot(index))

    def raw_for_slot(self, slot_index: int) -> bytes:
        if not self._valid(slot_index):
            return b""
        self._rewrite_slot_payload(slot_index)
        slot = self.slots[slot_index]
        if slot.prog_bin and encode_program_dump is not None:
            return encode_program_dump(_slot_to_program(slot, slot_index), slot_index)
        return slot.raw

    def mark_sent(self, indices: list[int]) -> None:
        for index in indices:
            if self._valid(index) and (self.slots[index].raw or self.slots[index].prog_bin):
                self.slots[index].status = STATUS_SENT

    def mark_error(self, indices: list[int], message: str = "") -> None:
        for index in indices:
            if self._valid(index) and (self.slots[index].raw or self.slots[index].prog_bin):
                self.slots[index].status = STATUS_ERROR
                if message:
                    self.slots[index].notes = message

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

    def _renumber(self, *, mark_modified: bool = False, start: int = 0, end: int | None = None) -> None:
        last = len(self.slots) - 1 if end is None else min(end, len(self.slots) - 1)
        for index, slot in enumerate(self.slots):
            slot.slot = index + 1
            self._rewrite_slot_payload(index)
            if mark_modified and start <= index <= last and (slot.raw or slot.prog_bin):
                slot.status = STATUS_MODIFIED

    def _valid(self, slot_index: int) -> bool:
        return 0 <= slot_index < len(self.slots)

    def _rewrite_slot_payload(self, slot_index: int) -> None:
        if not self._valid(slot_index):
            return
        slot = self.slots[slot_index]
        if slot.prog_bin and encode_program_dump is not None:
            slot.raw = encode_program_dump(_slot_to_program(slot, slot_index), slot_index)
        elif len(slot.raw) > 9 and slot.raw[0] == 0xF0 and slot.raw[6] == 0x4C and slot.raw[-1] == 0xF7:
            raw = bytearray(slot.raw)
            raw[7] = slot_index & 0x7F
            raw[8] = (slot_index >> 7) & 0x7F
            raw[9] = 0x00
            slot.raw = bytes(raw)

    @staticmethod
    def _clone_slot(slot: BankSlot) -> BankSlot:
        return BankSlot(
            slot=slot.slot,
            name=slot.name,
            source=slot.source,
            raw=slot.raw,
            prog_bin=slot.prog_bin,
            sha256=slot.sha256,
            status=slot.status,
            notes=slot.notes,
        )

    def _remember_init_template(self, name: str, prog_bin: bytes) -> None:
        if prog_bin and name.strip().lower().startswith("init"):
            self.init_template_prog_bin = prog_bin


def _slot_to_program(slot: BankSlot, slot_index: int) -> object:
    return XDProgram(
        slot_index=slot_index,
        name=slot.name,
        prog_bin=slot.prog_bin,
        source_type=slot.status,
    )
