"""Read-only minilogue xd User Unit inventory model and reader."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from devices.korg_minilogue_xd.user_unit_protocol import (
    MODULE_TITLES,
    LogueCliModuleInfo,
    LogueCliProbeSummary,
    ParsedSlotStatus,
    parse_module_status_output,
    parse_probe_summary,
)
from devices.korg_minilogue_xd.user_unit_transport import LogueCliTransport
from devices.korg_minilogue_xd.user_units import USER_FX_SLOTS, USER_OSC_SLOTS

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class UserUnitSlotInfo:
    module: str
    category: str
    slot_key: str
    slot_index: int
    occupied: bool | None
    status: str
    display_name: str | None
    unit_name: str | None
    unit_version: str | None
    api_version: str | None
    sdk_version: str | None
    developer_id: str | None
    unit_id: str | None
    target_platform: str | None
    compatibility: str | None
    payload_size: int | None
    checksum: str | None
    source: str
    raw_metadata: bytes | None
    raw_protocol_command: str | None
    raw_metadata_length: int | None
    read_timestamp: str | None
    device_name: str | None
    system_version: str | None
    logue_api_version: str | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class UserUnitInventorySnapshot:
    input_port_name: str
    output_port_name: str
    device_name: str
    system_version: str | None
    logue_api_version: str | None
    read_timestamp: str
    module_info: dict[str, LogueCliModuleInfo]
    slots: dict[str, UserUnitSlotInfo]
    warnings: tuple[str, ...] = ()


class UserUnitInventoryReader:
    """Read User OSC / User FX inventory via the official logue-cli probe path."""

    def __init__(
        self,
        input_port_name: str,
        output_port_name: str,
        *,
        transport: LogueCliTransport | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.input_port_name = input_port_name
        self.output_port_name = output_port_name
        self.transport = transport or LogueCliTransport()
        self.progress_callback = progress_callback
        self._input_index: int | None = None
        self._output_index: int | None = None
        self._summary: LogueCliProbeSummary | None = None
        self._timestamp: str | None = None

    def cancel(self) -> None:
        self.transport.cancel()

    def detect_device(self) -> bool:
        self._report("Connecting to minilogue xd...")
        summary = self._ensure_summary()
        return "minilogue xd" in summary.device_name.casefold()

    def read_oscillator_slots(self) -> list[UserUnitSlotInfo]:
        return self._read_module_slots("osc", "Reading User OSC inventory...")

    def read_mod_fx_slots(self) -> list[UserUnitSlotInfo]:
        return self._read_module_slots("modfx", "Reading Mod FX inventory...")

    def read_delay_fx_slots(self) -> list[UserUnitSlotInfo]:
        return self._read_module_slots("delfx", "Reading Delay FX inventory...")

    def read_reverb_fx_slots(self) -> list[UserUnitSlotInfo]:
        return self._read_module_slots("revfx", "Reading Reverb FX inventory...")

    def read_inventory(self) -> UserUnitInventorySnapshot:
        summary = self._ensure_summary()
        if "minilogue xd" not in summary.device_name.casefold():
            raise RuntimeError("No compatible minilogue xd detected.")

        all_slots: dict[str, UserUnitSlotInfo] = {}
        warnings: list[str] = []
        for info in self.read_oscillator_slots():
            all_slots[info.slot_key] = info
            warnings.extend(info.warnings)
        for info in self.read_mod_fx_slots():
            all_slots[info.slot_key] = info
            warnings.extend(info.warnings)
        for info in self.read_delay_fx_slots():
            all_slots[info.slot_key] = info
            warnings.extend(info.warnings)
        for info in self.read_reverb_fx_slots():
            all_slots[info.slot_key] = info
            warnings.extend(info.warnings)
        timestamp = self._timestamp or _timestamp_now()
        return UserUnitInventorySnapshot(
            input_port_name=self.input_port_name,
            output_port_name=self.output_port_name,
            device_name=summary.device_name,
            system_version=summary.system_version,
            logue_api_version=summary.logue_api_version,
            read_timestamp=timestamp,
            module_info=dict(summary.modules),
            slots=all_slots,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _ensure_summary(self) -> LogueCliProbeSummary:
        if self._summary is not None:
            return self._summary
        input_index, output_index = self.transport.resolve_port_indices(
            self.input_port_name,
            self.output_port_name,
        )
        summary_output = self.transport.probe_summary(input_index, output_index)
        summary = parse_probe_summary(summary_output)
        if not summary.device_name:
            raise RuntimeError("The minilogue xd was detected, but the inventory response could not be parsed safely.")
        self._input_index = input_index
        self._output_index = output_index
        self._summary = summary
        self._timestamp = _timestamp_now()
        return summary

    def _read_module_slots(self, module: str, progress_message: str) -> list[UserUnitSlotInfo]:
        summary = self._ensure_summary()
        self._report(progress_message)
        if self._input_index is None or self._output_index is None:
            raise RuntimeError("User Unit inventory transport was not initialized.")
        output = self.transport.probe_module(module, self._input_index, self._output_index)
        parsed = parse_module_status_output(output)
        module_info = summary.modules.get(module)
        slot_count = _slot_count_for_module(module_info, module)
        return _normalize_module_slots(
            module=module,
            parsed=parsed,
            slot_count=slot_count,
            summary=summary,
            timestamp=self._timestamp or _timestamp_now(),
            raw_command=f"logue-cli probe -m {module} -i {self._input_index} -o {self._output_index}",
        )

    def _report(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)


def _normalize_module_slots(
    *,
    module: str,
    parsed: list[ParsedSlotStatus],
    slot_count: int,
    summary: LogueCliProbeSummary,
    timestamp: str,
    raw_command: str,
) -> list[UserUnitSlotInfo]:
    parsed_by_slot = {item.slot_index: item for item in parsed}
    slots: list[UserUnitSlotInfo] = []
    for slot_number in range(1, slot_count + 1):
        parsed_slot = parsed_by_slot.get(slot_number)
        if parsed_slot is None:
            slots.append(
                UserUnitSlotInfo(
                    module=module,
                    category=MODULE_TITLES[module],
                    slot_key=_slot_key(module, slot_number),
                    slot_index=slot_number,
                    occupied=None,
                    status="Unknown",
                    display_name=None,
                    unit_name=None,
                    unit_version=None,
                    api_version=None,
                    sdk_version=None,
                    developer_id=None,
                    unit_id=None,
                    target_platform="minilogue xd",
                    compatibility="Unknown",
                    payload_size=None,
                    checksum=None,
                    source="hardware_inventory",
                    raw_metadata=None,
                    raw_protocol_command=raw_command,
                    raw_metadata_length=None,
                    read_timestamp=timestamp,
                    device_name=summary.device_name,
                    system_version=summary.system_version,
                    logue_api_version=summary.logue_api_version,
                    warnings=("Slot was not present in the probe response.",),
                )
            )
            continue

        status = "Installed" if parsed_slot.occupied else "Empty"
        if parsed_slot.occupied is None:
            status = "Unknown"
        raw_metadata = parsed_slot.raw_line.encode("utf-8", errors="replace")
        slots.append(
            UserUnitSlotInfo(
                module=module,
                category=MODULE_TITLES[module],
                slot_key=_slot_key(module, slot_number),
                slot_index=slot_number,
                occupied=parsed_slot.occupied,
                status=status,
                display_name=parsed_slot.display_name,
                unit_name=parsed_slot.display_name,
                unit_version=parsed_slot.unit_version,
                api_version=parsed_slot.api_version,
                sdk_version=None,
                developer_id=parsed_slot.developer_id,
                unit_id=parsed_slot.unit_id,
                target_platform="minilogue xd",
                compatibility="Unknown" if parsed_slot.occupied else None,
                payload_size=None,
                checksum=None,
                source="hardware_inventory",
                raw_metadata=raw_metadata,
                raw_protocol_command=raw_command,
                raw_metadata_length=len(raw_metadata),
                read_timestamp=timestamp,
                device_name=summary.device_name,
                system_version=summary.system_version,
                logue_api_version=summary.logue_api_version,
                warnings=parsed_slot.warnings,
            )
        )
    return slots


def _slot_count_for_module(module_info: LogueCliModuleInfo | None, module: str) -> int:
    if module_info is not None and module_info.slot_count > 0:
        return module_info.slot_count
    if module == "osc":
        return len(USER_OSC_SLOTS)
    return sum(1 for slot in USER_FX_SLOTS if slot.key.startswith(f"{module}-"))


def _slot_key(module: str, slot_index: int) -> str:
    return f"{module}-{slot_index:02d}"


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
