"""Conservative logue SDK user-unit metadata parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from xd_formats.constants import KNOWN_UNIT_SIGNATURES, PRODUCT_NAME, UNIT_MODULE_LABELS
from xd_formats.unit_container import load_mnlgxdunit


COMPATIBLE_WITH_XD = "compatible with minilogue xd"
COMPATIBILITY_UNKNOWN = "compatibility unknown - not sendable to XD"
INCOMPATIBLE_TARGET = "incompatible / wrong target"
INVALID_HEADER = "invalid container/header"
UNSUPPORTED_UNIT_TYPE = "unsupported unit type"
PARSER_ERROR = "parser error"

_XD_PLATFORMS = {"minilogue-xd", "minilogue_xd", "minilogue xd", PRODUCT_NAME}
_GENERIC_LOGUE_PLATFORMS = {"logue-sdk", "logue sdk", "logue"}


@dataclass
class LogueUnitHeader:
    source_path: Path
    file_size: int
    magic: str
    unit_type: str
    api_version: str
    unit_name: str
    unit_version: str
    developer_id: int
    unit_id: int
    platform: str
    compatibility: str
    status: str
    notes: list[str] = field(default_factory=list)

    @property
    def is_supported_type(self) -> bool:
        return self.unit_type in UNIT_MODULE_LABELS

    @property
    def is_xd_compatible(self) -> bool:
        return self.compatibility == COMPATIBLE_WITH_XD

    @property
    def hardware_sendable(self) -> bool:
        return False


def parse_logue_unit_header(path: Path | str) -> LogueUnitHeader:
    source_path = Path(path)
    if source_path.stat().st_size < 4:
        raise ValueError(f"{INVALID_HEADER}: file is too short")

    unit = load_mnlgxdunit(source_path)
    notes = list(unit.warnings)
    if unit.payload_name:
        notes.append(f"payload={unit.payload_name}")
    if unit.payload_signature:
        notes.append(f"magic={unit.payload_signature}")

    status = "local file"
    if unit.module and unit.module not in UNIT_MODULE_LABELS:
        status = UNSUPPORTED_UNIT_TYPE

    compatibility = classify_compatibility(unit.platform, unit.module, unit.warnings)
    return LogueUnitHeader(
        source_path=source_path,
        file_size=source_path.stat().st_size,
        magic=unit.payload_signature,
        unit_type=unit.module or KNOWN_UNIT_SIGNATURES.get(unit.payload_signature, ""),
        api_version=unit.api,
        unit_name=unit.name,
        unit_version=unit.version,
        developer_id=unit.dev_id,
        unit_id=unit.prg_id,
        platform=unit.platform,
        compatibility=compatibility,
        status=status,
        notes=notes,
    )


def classify_compatibility(platform: str, module: str, warnings: list[str]) -> str:
    normalized_platform = platform.strip().lower()
    if module not in UNIT_MODULE_LABELS:
        return COMPATIBILITY_UNKNOWN
    if warnings:
        return COMPATIBILITY_UNKNOWN
    if normalized_platform in _XD_PLATFORMS:
        return COMPATIBLE_WITH_XD
    if normalized_platform in _GENERIC_LOGUE_PLATFORMS:
        return COMPATIBILITY_UNKNOWN
    if not normalized_platform:
        return COMPATIBILITY_UNKNOWN
    return INCOMPATIBLE_TARGET
