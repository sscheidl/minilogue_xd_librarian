"""Hex formatting helpers."""

from __future__ import annotations


def format_hex(data: bytes, bytes_per_line: int = 16) -> str:
    if not data:
        return ""

    lines = []
    for offset in range(0, len(data), bytes_per_line):
        chunk = data[offset : offset + bytes_per_line]
        hex_bytes = " ".join(f"{byte:02X}" for byte in chunk)
        lines.append(f"{offset:04X}: {hex_bytes}")
    return "\n".join(lines)
