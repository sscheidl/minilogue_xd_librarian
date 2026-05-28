"""MIDI port discovery helpers."""

from __future__ import annotations

from typing import List

import mido


def get_input_ports() -> List[str]:
    """Return all visible MIDI input ports without device-name filtering."""
    return list(mido.get_input_names())


def get_output_ports() -> List[str]:
    """Return all visible MIDI output ports without device-name filtering."""
    return list(mido.get_output_names())
