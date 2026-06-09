"""Manifest parsing for minilogue xd User Units."""

from __future__ import annotations

from dataclasses import dataclass

from devices.korg_minilogue_xd.unit_types import UnitModule, VersionTriple, module_from_manifest, parse_version


@dataclass(frozen=True)
class ManifestInfo:
    display_name: str
    platform: str
    module: UnitModule | None
    api_version: VersionTriple | None
    unit_version: VersionTriple | None
    developer_id: int | None
    program_id: int | None
    num_param: int
    params: tuple[object, ...]


def parse_manifest_info(header: dict, fallback_name: str) -> ManifestInfo:
    return ManifestInfo(
        display_name=str(header.get("name") or fallback_name).strip() or fallback_name,
        platform=str(header.get("platform", "")).strip(),
        module=module_from_manifest(str(header.get("module", header.get("type", "")))),
        api_version=parse_version(str(header.get("api", "")).strip()),
        unit_version=parse_version(str(header.get("version", "")).strip()),
        developer_id=_parse_int_or_none(header.get("dev_id")),
        program_id=_parse_int_or_none(header.get("prg_id", header.get("unit_id"))),
        num_param=_parse_int_or_default(header.get("num_param"), default=len(header.get("params", []) or [])),
        params=tuple(header.get("params", []) or []),
    )


def _parse_int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_int_or_default(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
