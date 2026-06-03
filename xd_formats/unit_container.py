"""Read and write .mnlgxdunit containers."""

from __future__ import annotations

import json
from pathlib import Path
import zipfile

from .constants import KNOWN_UNIT_SIGNATURES, UNIT_MODULE_LABELS
from .filename_utils import safe_filename
from .models import XDUnit, XDUnitParam


def load_mnlgxdunit(path: Path | str) -> XDUnit:
    source_path = Path(path)
    if source_path.stat().st_size < 4:
        raise ValueError("invalid container/header: file is too short")

    with zipfile.ZipFile(source_path) as archive:
        manifest_name = _find_required_member(archive, "manifest.json")
        payload_name = _find_payload_member(archive)
        manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        payload = archive.read(payload_name) if payload_name else b""

    if not isinstance(manifest, dict):
        raise ValueError("invalid container/header: manifest.json must contain an object")
    header = manifest.get("header", {})
    if not isinstance(header, dict):
        raise ValueError("invalid container/header: manifest header must contain an object")

    params = [_parse_param(param) for param in header.get("params", [])]
    signature = payload[:4].decode("ascii", errors="replace") if payload else ""
    module = _normalize_module(str(header.get("module", header.get("type", ""))))
    warnings: list[str] = []
    expected_module = KNOWN_UNIT_SIGNATURES.get(signature)
    if expected_module is None:
        warnings.append(f"Unknown payload signature: {signature or 'empty'}")
    elif not module:
        module = expected_module
    elif expected_module != module:
        warnings.append(f"Payload signature {signature} does not match module {module}")
    if module and module not in UNIT_MODULE_LABELS:
        warnings.append(f"Unknown module: {module}")
    if not payload_name:
        warnings.append("No payload binary found")

    return XDUnit(
        name=str(header.get("name", source_path.stem)),
        module=module,
        api=str(header.get("api", "")),
        version=str(header.get("version", "")),
        platform=str(header.get("platform", "")),
        dev_id=_parse_int(header.get("dev_id", 0)),
        prg_id=_parse_int(header.get("prg_id", header.get("unit_id", 0))),
        params=params,
        payload=payload,
        payload_signature=signature,
        manifest=manifest,
        source_path=source_path,
        payload_name=payload_name,
        warnings=warnings,
    )


def save_mnlgxdunit(unit: XDUnit, path: Path | str) -> None:
    target_path = Path(path)
    folder = safe_filename(unit.name, fallback=target_path.stem)
    manifest = unit.manifest or _manifest_from_unit(unit)
    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{folder}/manifest.json", json.dumps(manifest, indent=2))
        archive.writestr(f"{folder}/payload.bin", unit.payload)


def _find_required_member(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.lower().endswith(suffix.lower())]
    if len(matches) != 1:
        raise ValueError(f"Expected one {suffix}, found {len(matches)}")
    return matches[0]


def _find_payload_member(archive: zipfile.ZipFile) -> str:
    members = [name for name in archive.namelist() if not name.endswith("/")]
    exact_matches = [name for name in members if name.lower().endswith("payload.bin")]
    if exact_matches:
        return exact_matches[0]

    bin_matches = [name for name in members if name.lower().endswith(".bin")]
    if len(bin_matches) == 1:
        return bin_matches[0]
    if len(bin_matches) > 1:
        prioritized = [
            name for name in bin_matches
            if Path(name).name.lower() in {"unit.bin", "program.bin", "userunit.bin"}
        ]
        if prioritized:
            return prioritized[0]
    return ""


def _parse_param(param: list) -> XDUnitParam:
    name = str(param[0]) if len(param) > 0 else ""
    minimum = param[1] if len(param) > 1 else None
    maximum = param[2] if len(param) > 2 else None
    unit = str(param[3]) if len(param) > 3 else None
    return XDUnitParam(name=name, minimum=minimum, maximum=maximum, unit=unit)


def _parse_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_module(value: str) -> str:
    normalized = value.strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "osc": "osc",
        "oscillator": "osc",
        "userosc": "osc",
        "useroscillator": "osc",
        "modfx": "modfx",
        "modulationfx": "modfx",
        "usermodfx": "modfx",
        "delfx": "delfx",
        "delayfx": "delfx",
        "userdelayfx": "delfx",
        "revfx": "revfx",
        "reverbfx": "revfx",
        "userreverbfx": "revfx",
    }
    return aliases.get(normalized, value.strip().lower())


def _manifest_from_unit(unit: XDUnit) -> dict:
    return {
        "header": {
            "platform": unit.platform,
            "module": unit.module,
            "api": unit.api,
            "dev_id": unit.dev_id,
            "prg_id": unit.prg_id,
            "version": unit.version,
            "name": unit.name,
            "num_param": len(unit.params),
            "params": [
                [param.name, param.minimum, param.maximum, param.unit] for param in unit.params
            ],
        }
    }
