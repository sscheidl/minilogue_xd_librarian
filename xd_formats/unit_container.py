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
    with zipfile.ZipFile(source_path) as archive:
        manifest_name = _find_member(archive, "manifest.json")
        payload_name = _find_member(archive, "payload.bin")
        manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        payload = archive.read(payload_name)

    header = manifest.get("header", {})
    params = [_parse_param(param) for param in header.get("params", [])]
    signature = payload[:4].decode("ascii", errors="replace") if payload else ""
    module = str(header.get("module", ""))
    warnings: list[str] = []
    expected_module = KNOWN_UNIT_SIGNATURES.get(signature)
    if expected_module is None:
        warnings.append(f"Unknown payload signature: {signature or 'empty'}")
    elif expected_module != module:
        warnings.append(f"Payload signature {signature} does not match module {module}")
    if module and module not in UNIT_MODULE_LABELS:
        warnings.append(f"Unknown module: {module}")

    return XDUnit(
        name=str(header.get("name", source_path.stem)),
        module=module,
        api=str(header.get("api", "")),
        version=str(header.get("version", "")),
        platform=str(header.get("platform", "")),
        dev_id=int(header.get("dev_id", 0)),
        prg_id=int(header.get("prg_id", 0)),
        params=params,
        payload=payload,
        payload_signature=signature,
        manifest=manifest,
        source_path=source_path,
        warnings=warnings,
    )


def save_mnlgxdunit(unit: XDUnit, path: Path | str) -> None:
    target_path = Path(path)
    folder = safe_filename(unit.name, fallback=target_path.stem)
    manifest = unit.manifest or _manifest_from_unit(unit)
    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{folder}/manifest.json", json.dumps(manifest, indent=2))
        archive.writestr(f"{folder}/payload.bin", unit.payload)


def _find_member(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"Expected one {suffix}, found {len(matches)}")
    return matches[0]


def _parse_param(param: list) -> XDUnitParam:
    name = str(param[0]) if len(param) > 0 else ""
    minimum = param[1] if len(param) > 1 else None
    maximum = param[2] if len(param) > 2 else None
    unit = str(param[3]) if len(param) > 3 else None
    return XDUnitParam(name=name, minimum=minimum, maximum=maximum, unit=unit)


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
