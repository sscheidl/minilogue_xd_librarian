"""Canonical User Unit types, slot limits, and version helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


@dataclass(frozen=True, order=True)
class VersionTriple:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}-{self.patch}"


class UnitModule(str, Enum):
    OSC = "osc"
    MOD_FX = "modfx"
    DELAY_FX = "delfx"
    REVERB_FX = "revfx"

    @property
    def display_name(self) -> str:
        return {
            UnitModule.OSC: "User Oscillator",
            UnitModule.MOD_FX: "Modulation FX",
            UnitModule.DELAY_FX: "Delay FX",
            UnitModule.REVERB_FX: "Reverb FX",
        }[self]

    @property
    def tab_display_name(self) -> str:
        return {
            UnitModule.OSC: "User OSC",
            UnitModule.MOD_FX: "Mod FX",
            UnitModule.DELAY_FX: "Delay FX",
            UnitModule.REVERB_FX: "Reverb FX",
        }[self]

    @property
    def payload_magic(self) -> bytes:
        return {
            UnitModule.OSC: b"UOSC",
            UnitModule.MOD_FX: b"UMOD",
            UnitModule.DELAY_FX: b"UDEL",
            UnitModule.REVERB_FX: b"UREV",
        }[self]

    @property
    def slot_prefix(self) -> str:
        return self.value

    @property
    def slot_range_text(self) -> str:
        limit = UNIT_SLOT_LIMITS[self]
        return f"{self.tab_display_name} slots 01-{limit:02d}"


UNIT_SLOT_LIMITS = {
    UnitModule.OSC: 16,
    UnitModule.MOD_FX: 16,
    UnitModule.DELAY_FX: 8,
    UnitModule.REVERB_FX: 8,
}

SUPPORTED_XD_PLATFORMS = {
    "minilogue-xd",
    "minilogue_xd",
    "minilogue xd",
}

SUPPORTED_API_MAX = VersionTriple(1, 1, 0)
API_1_1_MIN_FIRMWARE = VersionTriple(2, 0, 0)

_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)-(\d+)\s*$")


def parse_version(text: str) -> VersionTriple | None:
    match = _VERSION_RE.match(text or "")
    if match is None:
        return None
    return VersionTriple(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def parse_firmware_version(text: str) -> VersionTriple | None:
    if not text:
        return None
    simple = text.strip().split()[0]
    if "-" in simple:
        return parse_version(simple)
    parts = simple.split(".")
    if len(parts) < 2:
        return None
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    return VersionTriple(major, minor, patch)


def module_from_manifest(value: str) -> UnitModule | None:
    normalized = (value or "").strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "osc": UnitModule.OSC,
        "oscillator": UnitModule.OSC,
        "userosc": UnitModule.OSC,
        "modfx": UnitModule.MOD_FX,
        "modulationfx": UnitModule.MOD_FX,
        "usermodfx": UnitModule.MOD_FX,
        "delfx": UnitModule.DELAY_FX,
        "delayfx": UnitModule.DELAY_FX,
        "userdelayfx": UnitModule.DELAY_FX,
        "revfx": UnitModule.REVERB_FX,
        "reverbfx": UnitModule.REVERB_FX,
        "userreverbfx": UnitModule.REVERB_FX,
    }
    return aliases.get(normalized)


def module_from_payload_magic(value: bytes | str) -> UnitModule | None:
    if isinstance(value, bytes):
        text = value.decode("ascii", errors="ignore")
    else:
        text = value
    normalized = (text or "").strip().upper()
    return {
        "UOSC": UnitModule.OSC,
        "UMOD": UnitModule.MOD_FX,
        "UDEL": UnitModule.DELAY_FX,
        "UREV": UnitModule.REVERB_FX,
    }.get(normalized)


def slot_key_for(module: UnitModule, slot_index: int) -> str:
    return f"{module.slot_prefix}-{slot_index + 1:02d}"


def validate_slot_index(module: UnitModule, slot_index: int) -> bool:
    return 0 <= slot_index < UNIT_SLOT_LIMITS[module]
