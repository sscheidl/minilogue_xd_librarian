"""Payload helpers for minilogue xd User Units."""

from __future__ import annotations

from devices.korg_minilogue_xd.unit_types import UnitModule, module_from_payload_magic


def detect_payload_module(payload_magic: bytes) -> UnitModule | None:
    return module_from_payload_magic(payload_magic)
