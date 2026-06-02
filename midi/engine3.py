"""Compatibility status for the mido/WinMM send path."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util


ENGINE3_LABEL = "Open MIDI OUT via mido/WinMM"
ENGINE3_INSTALL_HINT = "Install the project MIDI dependencies: mido and python-rtmidi."


@dataclass(frozen=True)
class Engine3Status:
    available: bool
    executable: str | None = None
    label: str = ENGINE3_LABEL
    install_hint: str = ENGINE3_INSTALL_HINT

    @property
    def status_text(self) -> str:
        if self.available:
            return f"Send backend active: {self.label}"
        return f"Send backend unavailable. {self.install_hint}"


def detect_engine3_runtime() -> Engine3Status:
    return Engine3Status(available=importlib.util.find_spec("mido") is not None)
