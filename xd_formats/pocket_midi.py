"""Offline import helpers for Pocket MIDI text dumps and XD bank SysEx."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from xd_formats.filename_utils import safe_filename
from xd_formats.sysex_codec import (
    decode_current_program_dump,
    decode_program_dump,
    split_sysex_stream_ignoring_realtime,
)


XD_COMMAND_LABELS = {
    0x40: "current-program-dump",
    0x4C: "program-dump-with-slot",
    0x44: "program-bank-index",
    0x45: "sequencer-index",
    0x51: "global-data",
    0x23: "write-ack",
}


@dataclass(frozen=True)
class PocketHexImport:
    raw_bytes: bytes
    token_count: int
    ignored_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class XDSysexDump:
    raw: bytes
    command: int | None
    label: str
    slot_index: int | None = None
    name: str = ""
    status: str = "ok"

    @property
    def display_slot(self) -> str:
        return "Current" if self.slot_index is None else f"{self.slot_index + 1:03d}"


@dataclass(frozen=True)
class BankValidation:
    total_program_dumps: int
    complete: bool
    missing_slots: tuple[int, ...] = ()
    duplicate_slots: tuple[int, ...] = ()
    invalid_lengths: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class XDDumpAnalysis:
    messages: list[XDSysexDump] = field(default_factory=list)

    @property
    def command_counts(self) -> Counter[int | None]:
        return Counter(message.command for message in self.messages)

    @property
    def bank_programs(self) -> list[XDSysexDump]:
        return [message for message in self.messages if message.command == 0x4C]

    @property
    def current_programs(self) -> list[XDSysexDump]:
        return [message for message in self.messages if message.command == 0x40]

    def validate_bank(self) -> BankValidation:
        slots: dict[int, int] = {}
        duplicates: set[int] = set()
        invalid_lengths: list[int] = []
        for message in self.bank_programs:
            if message.slot_index is None:
                continue
            if message.slot_index in slots:
                duplicates.add(message.slot_index)
            slots[message.slot_index] = slots.get(message.slot_index, 0) + 1
            if len(message.raw) != 1181:
                invalid_lengths.append(message.slot_index)
        missing = tuple(index for index in range(500) if index not in slots)
        warnings = []
        if self.current_programs:
            warnings.append(f"{len(self.current_programs)} current program dump(s) present")
        extra = sum(
            count
            for command, count in self.command_counts.items()
            if command not in {0x40, 0x4C}
        )
        if extra:
            warnings.append(f"{extra} non-program SysEx message(s) present")
        return BankValidation(
            total_program_dumps=len(self.bank_programs),
            complete=not missing and not duplicates and not invalid_lengths and len(self.bank_programs) == 500,
            missing_slots=missing,
            duplicate_slots=tuple(sorted(duplicates)),
            invalid_lengths=tuple(invalid_lengths),
            warnings=tuple(warnings),
        )

    def bank_only_bytes(self) -> bytes:
        by_slot = {
            message.slot_index: message.raw
            for message in self.bank_programs
            if message.slot_index is not None
        }
        return b"".join(by_slot[index] for index in sorted(by_slot))

    def all_sysex_bytes(self) -> bytes:
        return b"".join(message.raw for message in self.messages)


def parse_pocket_midi_text(text: str) -> PocketHexImport:
    values = bytearray()
    ignored: list[str] = []
    for token in text.replace("\ufeff", "").split():
        cleaned = token.strip().strip(",;:[](){}")
        if cleaned.lower().startswith("0x"):
            ignored.append(token)
            continue
        if len(cleaned) == 2 and all(char in "0123456789abcdefABCDEF" for char in cleaned):
            values.append(int(cleaned, 16))
        elif cleaned:
            ignored.append(token)
    return PocketHexImport(bytes(values), len(values), tuple(ignored))


def analyze_pocket_midi_text(text: str) -> XDDumpAnalysis:
    parsed = parse_pocket_midi_text(text)
    return analyze_sysex_bytes(parsed.raw_bytes)


def analyze_sysex_file(path: Path | str) -> XDDumpAnalysis:
    source = Path(path)
    if source.suffix.lower() == ".txt":
        return analyze_pocket_midi_text(source.read_text(encoding="utf-8", errors="ignore"))
    return analyze_sysex_bytes(source.read_bytes())


def analyze_sysex_bytes(raw: bytes) -> XDDumpAnalysis:
    return XDDumpAnalysis([classify_dump_message(message) for message in split_sysex_stream_ignoring_realtime(raw)])


def classify_dump_message(raw: bytes) -> XDSysexDump:
    command = raw[6] if _looks_like_xd_sysex(raw) else None
    label = XD_COMMAND_LABELS.get(command, "invalid-or-non-xd" if command is None else "unknown")
    slot_index = raw[7] | (raw[8] << 7) if command == 0x4C and len(raw) > 9 else None
    name = ""
    status = "ok"
    if command == 0x4C:
        try:
            program = decode_program_dump(raw)
            slot_index = program.slot_index
            name = program.name or fallback_program_name(raw)
        except ValueError as exc:
            name = fallback_program_name(raw)
            status = f"decode warning: {exc}"
    elif command == 0x40:
        try:
            program = decode_current_program_dump(raw)
            name = program.name or fallback_program_name(raw)
        except ValueError as exc:
            name = fallback_program_name(raw)
            status = f"decode warning: {exc}"
    return XDSysexDump(raw=raw, command=command, label=label, slot_index=slot_index, name=name, status=status)


def _looks_like_xd_sysex(raw: bytes) -> bool:
    return (
        len(raw) >= 8
        and raw[0] == 0xF0
        and raw[1] == 0x42
        and raw[3:6] == b"\x00\x01\x51"
        and raw[-1] == 0xF7
    )


def fallback_program_name(raw: bytes) -> str:
    marker = raw.find(b"PROG")
    if marker < 0:
        return "name unknown"
    name_bytes = raw[marker + 4 : marker + 16]
    name = "".join(chr(value) for value in name_bytes if 32 <= value <= 126).strip()
    return name or "name unknown"


def write_bank_only_syx(analysis: XDDumpAnalysis, path: Path | str) -> None:
    Path(path).write_bytes(analysis.bank_only_bytes())


def write_all_extracted_syx(analysis: XDDumpAnalysis, path: Path | str) -> None:
    Path(path).write_bytes(analysis.all_sysex_bytes())


def export_individual_programs(analysis: XDDumpAnalysis, folder: Path | str) -> list[Path]:
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for message in analysis.bank_programs:
        if message.slot_index is None:
            continue
        name = safe_filename(message.name or "name_unknown", fallback="name_unknown")
        path = target / f"{message.slot_index + 1:03d}_{name}.syx"
        path.write_bytes(message.raw)
        written.append(path)
    return written
