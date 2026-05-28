"""User oscillator / user FX file inventory helpers."""

from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from xd_formats import load_mnlgxdunit


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
        unit = load_mnlgxdunit(path)
    except Exception as exc:
        return path.stem, "unknown", "unknown", "invalid/corrupt", "parser error", str(exc)
    compatibility = "compatible"
    notes = ""
    if unit.platform and unit.platform not in {"minilogue-xd", "logue-sdk"}:
        compatibility = "incompatible"
        notes = f"platform={unit.platform}"
    elif unit.warnings:
        compatibility = "unknown compatibility"
        notes = "; ".join(unit.warnings)
    module = unit.module or "unknown"
    kind = "user-osc" if module == "osc" else ("user-fx" if module in {"modfx", "delfx", "revfx"} else "user-unit")
    return unit.name or path.stem, kind, module, compatibility, "imported successfully", notes


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
