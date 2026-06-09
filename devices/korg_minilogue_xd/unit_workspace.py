"""Persistent local workspace for User Unit pending assignments."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil

from devices.korg_minilogue_xd.unit_types import UnitModule, slot_key_for, validate_slot_index
from devices.korg_minilogue_xd.unit_validator import UserUnitValidator, ValidatedUserUnit
from devices.korg_minilogue_xd.user_unit_inventory import UserUnitSlotInfo


@dataclass
class UserUnitSlotState:
    module: UnitModule
    slot_index: int
    installed_on_xd: UserUnitSlotInfo | None
    pending_assignment: ValidatedUserUnit | None
    pending_clear: bool = False


class UserUnitWorkspace:
    """Track installed hardware state separately from local pending changes."""

    def __init__(
        self,
        *,
        library_dir: Path,
        state_path: Path,
        validator: UserUnitValidator,
    ) -> None:
        self.library_dir = library_dir
        self.state_path = state_path
        self.validator = validator
        self.slot_states: dict[str, UserUnitSlotState] = {}
        for module, limit in (
            (UnitModule.OSC, 16),
            (UnitModule.MOD_FX, 16),
            (UnitModule.DELAY_FX, 8),
            (UnitModule.REVERB_FX, 8),
        ):
            for slot_index in range(limit):
                key = slot_key_for(module, slot_index)
                self.slot_states[key] = UserUnitSlotState(
                    module=module,
                    slot_index=slot_index,
                    installed_on_xd=None,
                    pending_assignment=None,
                )
        self.load()

    def slot_state(self, slot_key: str) -> UserUnitSlotState:
        return self.slot_states[slot_key]

    def set_hardware_inventory(self, inventory: dict[str, UserUnitSlotInfo]) -> None:
        for key, state in self.slot_states.items():
            state.installed_on_xd = inventory.get(key)

    def reconcile_pending_with_hardware(self) -> bool:
        changed = False
        for state in self.slot_states.values():
            hardware = state.installed_on_xd
            if hardware is None:
                continue
            if state.pending_clear and hardware.occupied is False:
                state.pending_clear = False
                changed = True
            pending = state.pending_assignment
            if pending is not None and _hardware_matches_pending(hardware, pending):
                state.pending_assignment = None
                state.pending_clear = False
                changed = True
        if changed:
            self.save()
        return changed

    def assign_pending(
        self,
        *,
        module: UnitModule,
        slot_index: int,
        unit: ValidatedUserUnit | None,
    ) -> ValidatedUserUnit:
        if not validate_slot_index(module, slot_index):
            raise ValueError("Invalid destination slot.")
        if unit is None:
            raise ValueError("Validated user unit is required for pending assignment.")
        self.library_dir.mkdir(parents=True, exist_ok=True)
        target = self._unique_library_path(unit.source_path)
        shutil.copy2(unit.source_path, target)
        staged_unit = self.validator.restage_unit(unit, new_source_path=target)
        state = self.slot_states[slot_key_for(module, slot_index)]
        state.pending_assignment = staged_unit
        state.pending_clear = False
        self.save()
        return staged_unit

    def clear_pending_assignment(self, *, module: UnitModule, slot_index: int) -> None:
        state = self.slot_states[slot_key_for(module, slot_index)]
        state.pending_assignment = None
        state.pending_clear = False
        self.save()

    def mark_slot_for_clear(self, *, module: UnitModule, slot_index: int) -> None:
        state = self.slot_states[slot_key_for(module, slot_index)]
        state.pending_assignment = None
        state.pending_clear = True
        self.save()

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        slots = {}
        for key, state in sorted(self.slot_states.items()):
            if state.pending_assignment is None and not state.pending_clear:
                continue
            entry: dict[str, object] = {"pending_clear": state.pending_clear}
            if state.pending_assignment is not None:
                entry["filename"] = state.pending_assignment.source_path.name
            slots[key] = entry
        self.state_path.write_text(
            json.dumps({"version": 2, "slots": slots}, indent=2),
            encoding="utf-8",
        )

    def load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        raw_slots = data.get("slots", {}) if isinstance(data, dict) else {}
        if not isinstance(raw_slots, dict):
            return
        for key, raw in raw_slots.items():
            state = self.slot_states.get(key)
            if state is None or not isinstance(raw, dict):
                continue
            state.pending_clear = bool(raw.get("pending_clear", False))
            filename = str(raw.get("filename", "")).strip()
            if not filename:
                continue
            candidate = self.library_dir / filename
            if not candidate.is_file():
                continue
            result = self.validator.validate_for_destination(
                path=candidate,
                destination_module=state.module,
                destination_slot=state.slot_index,
            )
            if result.ok and result.unit is not None:
                state.pending_assignment = result.unit

    def _unique_library_path(self, source_path: Path) -> Path:
        target = self.library_dir / source_path.name
        if not target.exists():
            return target
        stem = source_path.stem
        suffix = source_path.suffix
        counter = 2
        while target.exists():
            target = self.library_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        return target


def _hardware_matches_pending(
    hardware: UserUnitSlotInfo,
    pending: ValidatedUserUnit,
) -> bool:
    if not hardware.occupied:
        return False
    hardware_name = (hardware.display_name or hardware.unit_name or "").strip().casefold()
    pending_name = (pending.display_name or "").strip().casefold()
    if not hardware_name or hardware_name != pending_name:
        return False
    hardware_version = (hardware.unit_version or "").strip()
    pending_version = str(pending.unit_version).strip()
    if hardware_version and pending_version:
        return hardware_version == pending_version
    return True
