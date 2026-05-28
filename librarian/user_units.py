"""User oscillator / user FX file inventory helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


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
    size: int
    sha256: str
    modified: str

    @property
    def short_hash(self) -> str:
        return self.sha256[:12]


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


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_user_unit(path: Path) -> UserUnitFile:
    stat = path.stat()
    return UserUnitFile(
        path=path,
        kind=classify_user_unit(path),
        size=stat.st_size,
        sha256=hash_file(path),
        modified=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
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


def export_manifest(path: Path, units: list[UserUnitFile]) -> None:
    payload = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(units),
        "units": [
            {
                "file": str(unit.path),
                "kind": unit.kind,
                "size": unit.size,
                "sha256": unit.sha256,
                "modified": unit.modified,
            }
            for unit in units
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
