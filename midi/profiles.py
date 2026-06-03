"""JSON-backed MIDI profile loading and lookup helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.app_paths import project_root


@dataclass(frozen=True)
class MidiValueMapEntry:
    label: str
    min_value: int | None = None
    max_value: int | None = None
    exact_value: int | None = None

    def matches(self, value: int) -> bool:
        if self.exact_value is not None:
            return value == self.exact_value
        if self.min_value is None or self.max_value is None:
            return False
        return self.min_value <= value <= self.max_value

    def distance(self, value: int) -> int | None:
        if self.exact_value is None:
            return None
        return abs(self.exact_value - value)


@dataclass(frozen=True)
class MidiControlDefinition:
    number: int
    name: str
    group: str
    kind: str
    min_value: int = 0
    max_value: int = 127
    notes: str = ""
    show_in_simple_view: bool = True
    show_in_technical_view: bool = True
    value_map: tuple[MidiValueMapEntry, ...] = ()

    def label_for_value(self, value: int) -> str:
        for entry in self.value_map:
            if entry.matches(value):
                return entry.label

        exact_entries = [entry for entry in self.value_map if entry.exact_value is not None]
        if exact_entries:
            nearest = min(
                exact_entries,
                key=lambda entry: entry.distance(value) if entry.distance(value) is not None else 9999,
            )
            return nearest.label
        return ""


@dataclass(frozen=True)
class MidiProgramBank:
    name: str
    start_program: int
    end_program: int
    bank_msb: int | None = None
    bank_lsb: int | None = None

    def matches(self, bank_msb: int | None, bank_lsb: int | None) -> bool:
        if self.bank_msb is not None and self.bank_msb != bank_msb:
            return False
        if self.bank_lsb is not None and self.bank_lsb != bank_lsb:
            return False
        return True

    def absolute_program_for_raw(self, raw_program: int, display_base: int) -> int | None:
        span = self.end_program - self.start_program + 1
        display_program = raw_program + display_base
        if display_program < display_base or display_program >= display_base + span:
            return None
        return self.start_program + (display_program - display_base)


@dataclass(frozen=True)
class MidiProgramMapping:
    program_count: int | None
    display_base: int
    uses_bank_select: bool
    bank_select_msb_cc: int
    bank_select_lsb_cc: int
    banks: tuple[MidiProgramBank, ...] = ()

    def display_program_for_raw(self, raw_program: int) -> int:
        return raw_program + self.display_base

    def resolve(
        self,
        raw_program: int,
        bank_msb: int | None,
        bank_lsb: int | None,
    ) -> tuple[MidiProgramBank | None, int | None]:
        for bank in self.banks:
            if not bank.matches(bank_msb, bank_lsb):
                continue
            absolute_program = bank.absolute_program_for_raw(raw_program, self.display_base)
            if absolute_program is not None:
                return bank, absolute_program
        return None, None


@dataclass(frozen=True)
class MidiProfile:
    profile_id: str
    display_name: str
    manufacturer: str
    device: str
    midi_channel_base: int
    notes: str
    event_names: dict[str, str]
    control_changes: dict[int, MidiControlDefinition]
    special_controls: dict[int, MidiControlDefinition]
    program_mapping: MidiProgramMapping | None = None

    def display_name_for_message(self, message_type: str) -> str:
        return self.event_names.get(message_type, message_type.replace("_", " ").title())

    def definition_for_control(self, control_number: int) -> MidiControlDefinition | None:
        if control_number in self.special_controls:
            return self.special_controls[control_number]
        return self.control_changes.get(control_number)


def midi_profiles_dir() -> Path:
    return project_root() / "resources" / "midi_profiles"


def builtin_generic_profile() -> MidiProfile:
    return MidiProfile(
        profile_id="generic_midi",
        display_name="Generic MIDI",
        manufacturer="Generic",
        device="MIDI Device",
        midi_channel_base=1,
        notes="Built-in fallback profile used when JSON profiles are unavailable.",
        event_names={
            "active_sensing": "Active Sensing",
            "aftertouch": "Channel Pressure",
            "clock": "Clock",
            "continue": "Continue",
            "control_change": "Control Change",
            "note_off": "Note Off",
            "note_on": "Note On",
            "pitchwheel": "Pitch Bend",
            "polytouch": "Poly Aftertouch",
            "program_change": "Program Change",
            "reset": "System Reset",
            "start": "Start",
            "stop": "Stop",
            "sysex": "SysEx Summary",
        },
        control_changes={},
        special_controls={},
        program_mapping=MidiProgramMapping(
            program_count=None,
            display_base=1,
            uses_bank_select=True,
            bank_select_msb_cc=0,
            bank_select_lsb_cc=32,
        ),
    )


def load_midi_profiles(directory: Path | None = None) -> tuple[dict[str, MidiProfile], list[str]]:
    base_dir = directory or midi_profiles_dir()
    warnings: list[str] = []
    profiles: dict[str, MidiProfile] = {}

    if not base_dir.exists():
        warnings.append(
            f"Could not load MIDI profiles from '{base_dir}'. Falling back to Generic MIDI."
        )
        generic = builtin_generic_profile()
        return {generic.profile_id: generic}, warnings

    for path in sorted(base_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            warnings.append(
                f"Could not load MIDI profile '{path.name}': {exc}. Falling back to Generic MIDI."
            )
            continue
        except json.JSONDecodeError as exc:
            warnings.append(
                f"Could not load MIDI profile '{path.name}': invalid JSON ({exc.msg}). Falling back to Generic MIDI."
            )
            continue

        profile, profile_warnings = parse_midi_profile(data, path.name)
        warnings.extend(profile_warnings)
        if profile is not None:
            profiles[profile.profile_id] = profile

    if "generic_midi" not in profiles:
        warnings.append("Generic MIDI profile missing. Using built-in Generic MIDI fallback.")
        generic = builtin_generic_profile()
        profiles[generic.profile_id] = generic

    return profiles, warnings


def parse_midi_profile(data: Any, source_name: str) -> tuple[MidiProfile | None, list[str]]:
    warnings: list[str] = []
    if not isinstance(data, dict):
        warnings.append(
            f"Could not load MIDI profile '{source_name}': expected a JSON object. Falling back to Generic MIDI."
        )
        return None, warnings

    profile_id = str(data.get("profile_id") or Path(source_name).stem).strip()
    display_name = str(data.get("display_name") or profile_id).strip() or profile_id
    manufacturer = str(data.get("manufacturer") or "").strip()
    device = str(data.get("device") or "").strip()
    notes = str(data.get("notes") or "").strip()
    midi_channel_base = clamp_int(data.get("midi_channel_base", 1), 1)
    event_names = parse_event_names(data.get("event_names"))
    control_changes = parse_control_map(
        data.get("control_changes"),
        source_name,
        section_name="control_changes",
        warnings=warnings,
    )
    special_controls = parse_control_map(
        data.get("special_controls"),
        source_name,
        section_name="special_controls",
        warnings=warnings,
        default_show_in_simple=False,
    )
    program_mapping = parse_program_mapping(data.get("program_mapping"), source_name, warnings)

    profile = MidiProfile(
        profile_id=profile_id,
        display_name=display_name,
        manufacturer=manufacturer,
        device=device,
        midi_channel_base=midi_channel_base,
        notes=notes,
        event_names=event_names,
        control_changes=control_changes,
        special_controls=special_controls,
        program_mapping=program_mapping,
    )
    return profile, warnings


def parse_event_names(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return builtin_generic_profile().event_names.copy()

    event_names = builtin_generic_profile().event_names.copy()
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, str) and value.strip():
            event_names[key] = value.strip()
    return event_names


def parse_control_map(
    raw: Any,
    source_name: str,
    section_name: str,
    warnings: list[str],
    *,
    default_show_in_simple: bool = True,
) -> dict[int, MidiControlDefinition]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        warnings.append(
            f"Ignored '{section_name}' in MIDI profile '{source_name}': expected an object."
        )
        return {}

    controls: dict[int, MidiControlDefinition] = {}
    for key, value in raw.items():
        try:
            number = int(str(key))
        except ValueError:
            warnings.append(
                f"Ignored control '{key}' in MIDI profile '{source_name}': control number is not numeric."
            )
            continue
        if not isinstance(value, dict):
            warnings.append(
                f"Ignored control '{key}' in MIDI profile '{source_name}': expected an object."
            )
            continue

        name = str(value.get("name") or f"CC {number}").strip() or f"CC {number}"
        group = str(value.get("group") or "General").strip() or "General"
        kind = str(value.get("type") or "continuous").strip() or "continuous"
        min_value = clamp_int(value.get("min", 0), 0)
        max_value = clamp_int(value.get("max", 127), 127)
        notes = str(value.get("notes") or "").strip()
        show_in_simple_view = bool(value.get("show_in_simple_view", default_show_in_simple))
        show_in_technical_view = bool(value.get("show_in_technical_view", True))
        value_map = parse_value_map(value.get("value_map"))

        controls[number] = MidiControlDefinition(
            number=number,
            name=name,
            group=group,
            kind=kind,
            min_value=min_value,
            max_value=max_value,
            notes=notes,
            show_in_simple_view=show_in_simple_view,
            show_in_technical_view=show_in_technical_view,
            value_map=value_map,
        )
    return controls


def parse_value_map(raw: Any) -> tuple[MidiValueMapEntry, ...]:
    if not isinstance(raw, list):
        return ()

    entries: list[MidiValueMapEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue

        if "value" in item:
            entries.append(
                MidiValueMapEntry(
                    label=label,
                    exact_value=clamp_int(item.get("value"), 0),
                )
            )
            continue

        raw_range = item.get("range")
        if isinstance(raw_range, list) and len(raw_range) == 2:
            entries.append(
                MidiValueMapEntry(
                    label=label,
                    min_value=clamp_int(raw_range[0], 0),
                    max_value=clamp_int(raw_range[1], 127),
                )
            )
    return tuple(entries)


def parse_program_mapping(
    raw: Any,
    source_name: str,
    warnings: list[str],
) -> MidiProgramMapping | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        warnings.append(
            f"Ignored 'program_mapping' in MIDI profile '{source_name}': expected an object."
        )
        return None

    bank_select = raw.get("bank_select")
    bank_select_msb_cc = 0
    bank_select_lsb_cc = 32
    if isinstance(bank_select, dict):
        bank_select_msb_cc = clamp_int(bank_select.get("msb_cc", 0), 0)
        bank_select_lsb_cc = clamp_int(bank_select.get("lsb_cc", 32), 32)

    banks_raw = raw.get("banks")
    banks: list[MidiProgramBank] = []
    if isinstance(banks_raw, list):
        for item in banks_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            banks.append(
                MidiProgramBank(
                    name=name,
                    start_program=clamp_int(item.get("start_program", 1), 1),
                    end_program=clamp_int(item.get("end_program", 1), 1),
                    bank_msb=clamp_optional_int(item.get("bank_msb")),
                    bank_lsb=clamp_optional_int(item.get("bank_lsb")),
                )
            )

    return MidiProgramMapping(
        program_count=clamp_optional_int(raw.get("program_count")),
        display_base=clamp_int(raw.get("display_base", 1), 1),
        uses_bank_select=bool(raw.get("uses_bank_select", False)),
        bank_select_msb_cc=bank_select_msb_cc,
        bank_select_lsb_cc=bank_select_lsb_cc,
        banks=tuple(banks),
    )


def clamp_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
