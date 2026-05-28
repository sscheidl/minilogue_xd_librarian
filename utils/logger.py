"""Small text-formatting helpers for GUI log messages."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log_line(message: str) -> str:
    return f"[{timestamp()}] {message}"


def append_to_file(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")
