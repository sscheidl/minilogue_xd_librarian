"""Defensive import classification for minilogue xd workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import zipfile

from xd_formats import import_sysex_programs, load_mnlgxdlib, load_mnlgxdprog, load_mnlgxdunit


COMPATIBLE = "compatible"
PROBABLY_COMPATIBLE = "probably compatible"
UNKNOWN = "unknown compatibility"
INCOMPATIBLE = "incompatible"
INVALID = "invalid/corrupt"


@dataclass
class ImportValidationResult:
    path: Path
    kind: str
    status: str
    message: str
    sendable: bool = False


def validate_import_path(path: Path) -> ImportValidationResult:
    suffix = path.suffix.lower()
    try:
        if suffix == ".mnlgxdprog":
            program = load_mnlgxdprog(path)
            return ImportValidationResult(path, "program", COMPATIBLE, program.name, True)
        if suffix == ".mnlgxdlib":
            library = load_mnlgxdlib(path)
            status = COMPATIBLE if len(library.programs) == 500 else PROBABLY_COMPATIBLE
            return ImportValidationResult(path, "library", status, f"{len(library.programs)} program(s)", True)
        if suffix == ".syx":
            raw = path.read_bytes()
            if raw and not (raw.startswith(b"\xF0") and raw.endswith(b"\xF7")):
                return ImportValidationResult(path, "sysex", INVALID, "SysEx file does not start with F0 and end with F7", False)
            programs = import_sysex_programs(path)
            if programs:
                return ImportValidationResult(path, "sysex-program-dump", COMPATIBLE, f"{len(programs)} XD program dump(s)", True)
            return ImportValidationResult(path, "sysex", UNKNOWN, "No verified XD program dump found", False)
        if suffix == ".mnlgxdunit":
            unit = load_mnlgxdunit(path)
            if unit.platform and unit.platform not in {"minilogue-xd", "logue-sdk"}:
                return ImportValidationResult(path, "user-unit", INCOMPATIBLE, f"platform={unit.platform}", False)
            if unit.warnings:
                return ImportValidationResult(path, "user-unit", UNKNOWN, "; ".join(unit.warnings), False)
            return ImportValidationResult(path, "user-unit", COMPATIBLE, f"{unit.module}: {unit.name}", False)
        return ImportValidationResult(path, "unknown", INCOMPATIBLE, f"Unsupported extension: {suffix or '<none>'}", False)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return ImportValidationResult(path, suffix.lstrip(".") or "unknown", INVALID, str(exc), False)
