"""Defensive import classification for minilogue xd workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import zipfile

from devices.korg_minilogue_xd.logue_unit_header import (
    COMPATIBILITY_UNKNOWN,
    COMPATIBLE_WITH_XD,
    INCOMPATIBLE_TARGET,
    parse_logue_unit_header,
)
from xd_formats import import_sysex_programs, load_mnlgxdlib, load_mnlgxdprog


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
            header = parse_logue_unit_header(path)
            if header.compatibility == COMPATIBLE_WITH_XD:
                return ImportValidationResult(
                    path,
                    "user-unit",
                    COMPATIBLE,
                    f"{header.unit_type}: {header.unit_name}",
                    False,
                )
            if header.compatibility == INCOMPATIBLE_TARGET:
                return ImportValidationResult(
                    path,
                    "user-unit",
                    INCOMPATIBLE,
                    f"platform={header.platform}",
                    False,
                )
            status = UNKNOWN if header.compatibility == COMPATIBILITY_UNKNOWN else INCOMPATIBLE
            return ImportValidationResult(
                path,
                "user-unit",
                status,
                "; ".join(header.notes) or header.compatibility,
                False,
            )
        return ImportValidationResult(path, "unknown", INCOMPATIBLE, f"Unsupported extension: {suffix or '<none>'}", False)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return ImportValidationResult(path, suffix.lstrip(".") or "unknown", INVALID, str(exc), False)
