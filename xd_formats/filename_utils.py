"""Filename helpers for exported minilogue xd files."""

from __future__ import annotations

import re
from pathlib import Path

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def safe_filename(name: str, fallback: str = "program") -> str:
    cleaned = _UNSAFE_CHARS.sub("_", name.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or fallback


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    path = directory / f"{stem}{suffix}"
    counter = 2
    while path.exists():
        path = directory / f"{stem} ({counter}){suffix}"
        counter += 1
    return path
