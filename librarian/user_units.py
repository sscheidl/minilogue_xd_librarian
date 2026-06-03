"""User oscillator / user FX file inventory helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from devices.korg_minilogue_xd.logue_unit_header import (
    COMPATIBILITY_UNKNOWN,
    INVALID_HEADER,
    PARSER_ERROR,
    parse_logue_unit_header,
)
from devices.korg_minilogue_xd.user_units import USER_UNIT_SLOTS, matching_slots


USER_UNIT_EXTENSIONS = {
    ".mnlgxdunit",
    ".prlgunit",
    ".logueunit",
    ".zip",
    ".wav",
    ".bin",
}


@dataclass
class UserUnitFile:
    path: Path
    kind: str
    name: str
    module: str
    compatibility: str
    status: str
    size: int
    sha256: str
    modified: str
    notes: str = ""

    @property
    def short_hash(self) -> str:
        return self.sha256[:12]


@dataclass
class UserUnitAssignment:
    filename: str
    display_name: str = ""


def classify_user_unit(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if "fx" in name:
        return "user-fx"
    if "osc" in name or "vpm" in name or "user" in name:
        return "user-osc"
    if suffix in USER_UNIT_EXTENSIONS:
        return "user-unit"
    return "unknown"


def inspect_mnlgxdunit(path: Path) -> tuple[str, str, str, str, str, str]:
    try:
        header = parse_logue_unit_header(path)
    except Exception as exc:
        reason = str(exc) or PARSER_ERROR
        status = INVALID_HEADER if "invalid container/header" in reason else PARSER_ERROR
        return path.stem, "user-unit", "unknown", COMPATIBILITY_UNKNOWN, status, reason

    module = header.unit_type or "unknown"
    kind = "user-osc" if module == "osc" else ("user-fx" if module in {"modfx", "delfx", "revfx"} else "user-unit")
    notes = [
        f"version={header.unit_version or 'unknown'}",
        f"api={header.api_version or 'unknown'}",
        f"dev_id={header.developer_id}",
        f"unit_id={header.unit_id}",
        "hardware status unknown",
        *header.notes,
    ]
    return (
        header.unit_name or path.stem,
        kind,
        module,
        header.compatibility,
        header.status,
        "; ".join(note for note in notes if note),
    )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_user_unit(path: Path) -> UserUnitFile:
    stat = path.stat()
    kind = classify_user_unit(path)
    name = path.stem
    module = kind
    compatibility = "unknown compatibility"
    status = "raw file preserved"
    notes = ""
    if path.suffix.lower() == ".mnlgxdunit":
        name, kind, module, compatibility, status, notes = inspect_mnlgxdunit(path)
    return UserUnitFile(
        path=path,
        kind=kind,
        name=name,
        module=module,
        compatibility=compatibility,
        status=status,
        size=stat.st_size,
        sha256=hash_file(path),
        modified=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        notes=notes,
    )


def import_user_unit(source: Path, library_dir: Path) -> UserUnitFile:
    library_dir.mkdir(parents=True, exist_ok=True)
    target = library_dir / source.name
    if target.exists():
        stem = source.stem
        suffix = source.suffix
        counter = 2
        while target.exists():
            target = library_dir / f"{stem}_{counter}{suffix}"
            counter += 1
    shutil.copy2(source, target)
    return inspect_user_unit(target)


def scan_user_units(library_dir: Path) -> list[UserUnitFile]:
    library_dir.mkdir(parents=True, exist_ok=True)
    return [
        inspect_user_unit(path)
        for path in sorted(library_dir.iterdir())
        if path.is_file()
    ]


def load_user_unit_assignments(path: Path) -> dict[str, UserUnitAssignment]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw_slots = data.get("slots", {}) if isinstance(data, dict) else {}
    assignments: dict[str, UserUnitAssignment] = {}
    valid_keys = {slot.key for slot in USER_UNIT_SLOTS}
    if not isinstance(raw_slots, dict):
        return {}
    for key, raw in raw_slots.items():
        if key not in valid_keys or not isinstance(raw, dict):
            continue
        filename = str(raw.get("filename", "")).strip()
        if not filename:
            continue
        assignments[key] = UserUnitAssignment(
            filename=filename,
            display_name=str(raw.get("display_name", "")),
        )
    return assignments


def save_user_unit_assignments(path: Path, assignments: dict[str, UserUnitAssignment]) -> None:
    slots = {
        key: {"filename": assignment.filename, "display_name": assignment.display_name}
        for key, assignment in sorted(assignments.items())
        if assignment.filename
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "slots": slots}, indent=2), encoding="utf-8")


def first_available_slot_key(
    unit: UserUnitFile,
    assignments: dict[str, UserUnitAssignment],
) -> str:
    for slot in matching_slots(unit.module):
        if slot.key not in assignments:
            return slot.key
    return ""
