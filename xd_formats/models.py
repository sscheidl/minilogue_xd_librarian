"""Canonical data models for minilogue xd files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .validators import validate_prog_bin


@dataclass
class XDProgram:
    slot_index: int | None
    name: str
    prog_bin: bytes
    prog_info_xml: str | None = None
    source_path: Path | None = None
    source_type: str | None = None

    def __post_init__(self) -> None:
        validate_prog_bin(self.prog_bin)


@dataclass
class XDLibrary:
    programs: list[XDProgram]
    favorite_data: bytes | None = None
    tune_scale_data: dict[str, bytes] = field(default_factory=dict)
    tune_oct_data: dict[str, bytes] = field(default_factory=dict)
    extra_files: dict[str, bytes] = field(default_factory=dict)
    source_path: Path | None = None

    @property
    def is_complete(self) -> bool:
        return len(self.programs) == 500


@dataclass
class XDUnitParam:
    name: str
    minimum: int | float | None
    maximum: int | float | None
    unit: str | None = None


@dataclass
class XDUnit:
    name: str
    module: str
    api: str
    version: str
    platform: str
    dev_id: int
    prg_id: int
    params: list[XDUnitParam]
    payload: bytes
    payload_signature: str
    manifest: dict
    source_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
