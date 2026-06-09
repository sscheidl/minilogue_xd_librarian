"""Strict ZIP container validation for .mnlgxdunit files."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import zipfile
import zlib


@dataclass(frozen=True)
class UnitContainerData:
    source_path: Path
    manifest: dict
    header: dict
    payload_bytes: bytes
    payload_magic: bytes
    payload_size: int
    payload_crc32: int
    manifest_member: str
    payload_member: str
    archive_members: tuple[str, ...]


def load_unit_container(path: Path | str) -> UnitContainerData:
    source_path = Path(path)
    if not source_path.is_file():
        raise ValueError("Selected unit file does not exist.")

    try:
        archive = zipfile.ZipFile(source_path)
    except zipfile.BadZipFile as exc:
        raise ValueError("The selected file is not a valid .mnlgxdunit ZIP container.") from exc

    with archive:
        members = tuple(archive.namelist())
        if not members:
            raise ValueError("The selected unit container is empty.")
        _validate_member_paths(members)
        for info in archive.infolist():
            if info.flag_bits & 0x1:
                raise ValueError("Encrypted unit archives are not supported.")

        manifest_member = _find_required_member(members, "manifest.json")
        payload_member = _find_required_member(members, "payload.bin")

        try:
            manifest = json.loads(archive.read(manifest_member).decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("manifest.json is not valid UTF-8.") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("manifest.json is not valid JSON.") from exc

        if not isinstance(manifest, dict):
            raise ValueError("manifest.json must contain a JSON object.")
        header = manifest.get("header")
        if not isinstance(header, dict):
            raise ValueError("manifest.json must contain a header object.")

        payload_bytes = archive.read(payload_member)
        if not payload_bytes:
            raise ValueError("payload.bin is empty.")

    return UnitContainerData(
        source_path=source_path,
        manifest=manifest,
        header=header,
        payload_bytes=payload_bytes,
        payload_magic=payload_bytes[:4],
        payload_size=len(payload_bytes),
        payload_crc32=zlib.crc32(payload_bytes) & 0xFFFFFFFF,
        manifest_member=manifest_member,
        payload_member=payload_member,
        archive_members=members,
    )


def _validate_member_paths(members: tuple[str, ...]) -> None:
    for member in members:
        pure = PurePosixPath(member)
        if pure.is_absolute():
            raise ValueError("The unit archive contains an absolute path and was rejected.")
        if ".." in pure.parts:
            raise ValueError("The unit archive contains unsafe parent-path entries and was rejected.")
        if ":" in member.split("/", 1)[0]:
            raise ValueError("The unit archive contains an unsafe drive-qualified path and was rejected.")


def _find_required_member(members: tuple[str, ...], suffix: str) -> str:
    matches = [name for name in members if name.lower().endswith(suffix.lower())]
    if not matches:
        raise ValueError(f"The selected unit is missing {suffix}.")
    if len(matches) > 1:
        raise ValueError(f"The selected unit contains multiple {suffix} files.")
    return matches[0]
