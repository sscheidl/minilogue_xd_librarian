"""SysEx file parsing, classification and report helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from midi.diagnostics import KORG_MANUFACTURER_ID

from .models import SysexRecord


def split_sysex_stream(data: bytes) -> list[bytes]:
    messages: list[bytes] = []
    start: int | None = None

    for index, byte in enumerate(data):
        if byte == 0xF0:
            start = index
        elif byte == 0xF7 and start is not None:
            messages.append(data[start : index + 1])
            start = None

    return messages


def classify_sysex(raw: bytes) -> str:
    if not raw.startswith(b"\xF0") or not raw.endswith(b"\xF7"):
        return "invalid"
    if len(raw) < 3:
        return "short-sysex"
    if raw[1] != KORG_MANUFACTURER_ID:
        return "non-korg-sysex"

    length = len(raw)
    if length < 256:
        return "korg-short-message"
    if length < 2048:
        return "possible-program-dump"
    if length < 20000:
        return "possible-bank-or-partial-dump"
    return "possible-all-dump"


def build_records(data: bytes) -> list[SysexRecord]:
    records = []
    messages = split_sysex_stream(data)
    if not messages and data:
        messages = [data]

    for index, raw in enumerate(messages, start=1):
        manufacturer_id = raw[1] if len(raw) > 1 else None
        is_complete_sysex = raw.startswith(b"\xF0") and raw.endswith(b"\xF7")
        records.append(
            SysexRecord(
                index=index,
                raw=raw,
                length=len(raw),
                manufacturer_id=manufacturer_id,
                is_korg=is_complete_sysex and manufacturer_id == KORG_MANUFACTURER_ID,
                dump_type=classify_sysex(raw) if is_complete_sysex else "raw-unknown-file",
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return records


def read_sysex_file(path: Path) -> list[SysexRecord]:
    return build_records(path.read_bytes())


def records_to_bytes(records: list[SysexRecord]) -> bytes:
    return b"".join(record.raw for record in records)


def report_dict(path: str, records: list[SysexRecord]) -> dict[str, Any]:
    return {
        "source": path,
        "message_count": len(records),
        "total_bytes": sum(record.length for record in records),
        "messages": [
            {
                "index": record.index,
                "length": record.length,
                "manufacturer_id": (
                    f"0x{record.manufacturer_id:02X}"
                    if record.manufacturer_id is not None
                    else None
                ),
                "is_korg": record.is_korg,
                "dump_type": record.dump_type,
                "sha256": record.sha256,
            }
            for record in records
        ],
    }


def report_text(path: str, records: list[SysexRecord]) -> str:
    lines = [
        f"Source: {path}",
        f"Messages: {len(records)}",
        f"Total bytes: {sum(record.length for record in records)}",
        "",
    ]
    for record in records:
        manufacturer = (
            f"0x{record.manufacturer_id:02X}" if record.manufacturer_id is not None else "none"
        )
        lines.append(
            f"{record.index:03d}: len={record.length} manufacturer={manufacturer} "
            f"korg={record.is_korg} type={record.dump_type} sha256={record.sha256}"
        )
    return "\n".join(lines)


def write_report_files(base_path: Path, source_path: str, records: list[SysexRecord]) -> None:
    base_path.with_suffix(".txt").write_text(
        report_text(source_path, records),
        encoding="utf-8",
    )
    base_path.with_suffix(".json").write_text(
        json.dumps(report_dict(source_path, records), indent=2),
        encoding="utf-8",
    )
