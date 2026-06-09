"""Analyze minilogue xd User OSC references inside decoded program banks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devices.korg_minilogue_xd.user_unit_inventory import UserUnitInventorySnapshot


# Offsets from the official KORG minilogue xd MIDI Implementation Rev. 1.01,
# TABLE 2 "PROGRAM PARAMETER".
_MULTI_TYPE_OFFSET = 38
_SELECT_USER_OFFSET = 41
_MULTI_TYPE_USER = 2
_USER_OSC_SLOT_COUNT = 16


@dataclass
class MultiengineRef:
    slot_index: int
    slot_display: str
    program_name: str
    user_osc_index: int
    user_osc_display: str


@dataclass
class MultiengineReport:
    total_programs: int
    multiengine_count: int
    builtin_osc_count: int
    refs_by_user_osc: dict[int, list[MultiengineRef]] = field(default_factory=dict)
    unresolved: list[MultiengineRef] = field(default_factory=list)


def analyze_multiengine_refs(programs: list[object]) -> MultiengineReport:
    """Return a grouped report of programs that reference User OSC slots."""

    report = MultiengineReport(
        total_programs=len(programs),
        multiengine_count=0,
        builtin_osc_count=0,
    )
    required_size = max(_MULTI_TYPE_OFFSET, _SELECT_USER_OFFSET) + 1

    for fallback_slot_index, program in enumerate(programs):
        prog_bin = getattr(program, "prog_bin", b"") or b""
        if len(prog_bin) < required_size:
            report.builtin_osc_count += 1
            continue

        multi_type = prog_bin[_MULTI_TYPE_OFFSET]
        if multi_type != _MULTI_TYPE_USER:
            report.builtin_osc_count += 1
            continue

        slot_index = _normalize_slot_index(getattr(program, "slot_index", None), fallback_slot_index)
        user_osc_index = int(prog_bin[_SELECT_USER_OFFSET])
        reference = MultiengineRef(
            slot_index=slot_index,
            slot_display=f"{slot_index + 1:03d}",
            program_name=_program_name(program),
            user_osc_index=user_osc_index,
            user_osc_display=_user_osc_display(user_osc_index),
        )
        report.multiengine_count += 1

        if 0 <= user_osc_index < _USER_OSC_SLOT_COUNT:
            report.refs_by_user_osc.setdefault(user_osc_index, []).append(reference)
        else:
            report.unresolved.append(reference)

    for refs in report.refs_by_user_osc.values():
        refs.sort(key=lambda item: item.slot_index)
    report.unresolved.sort(key=lambda item: item.slot_index)
    return report


def report_text(
    report: MultiengineReport,
    inventory_snapshot: UserUnitInventorySnapshot | None = None,
    source_label: str = "",
) -> str:
    """Render a readable multiengine analysis report."""

    lines = [
        "minilogue xd Multiengine Analysis",
        f"Source: {source_label or '(unknown)'}",
        f"Total programs: {report.total_programs}",
        f"Programs using User OSC: {report.multiengine_count}",
        f"Programs using built-in Multi Engine: {report.builtin_osc_count}",
        f"Referenced User OSC slots: {len(report.refs_by_user_osc)}",
        f"Unresolved references: {len(report.unresolved)}",
    ]

    if inventory_snapshot is not None:
        lines.append(
            "Inventory snapshot: "
            f"{inventory_snapshot.device_name} @ {inventory_snapshot.read_timestamp}"
        )

    lines.append("")
    lines.append("User OSC References")

    if not report.refs_by_user_osc:
        lines.append("None.")
    else:
        for user_osc_index in sorted(report.refs_by_user_osc):
            refs = report.refs_by_user_osc[user_osc_index]
            lines.append(
                f"{_user_osc_display(user_osc_index)} | "
                f"{_inventory_label(inventory_snapshot, user_osc_index)} | "
                f"{len(refs)} program(s)"
            )
            for ref in refs:
                lines.append(f"  {ref.slot_display} | {ref.program_name}")

    lines.append("")
    lines.append("Unresolved")
    if not report.unresolved:
        lines.append("None.")
    else:
        for ref in report.unresolved:
            lines.append(
                f"{ref.slot_display} | {ref.program_name} | "
                f"invalid User OSC index {ref.user_osc_index}"
            )

    lines.append("")
    lines.append("CSV")
    lines.append("slot_index,program_name,user_osc_index")
    for user_osc_index in sorted(report.refs_by_user_osc):
        for ref in report.refs_by_user_osc[user_osc_index]:
            lines.append(f"{ref.slot_display},{_csv_escape(ref.program_name)},{ref.user_osc_index}")
    for ref in report.unresolved:
        lines.append(f"{ref.slot_display},{_csv_escape(ref.program_name)},{ref.user_osc_index}")
    return "\n".join(lines)


def _normalize_slot_index(slot_index: object, fallback_slot_index: int) -> int:
    if isinstance(slot_index, int) and 0 <= slot_index <= 499:
        return slot_index
    return fallback_slot_index


def _program_name(program: object) -> str:
    name = str(getattr(program, "name", "") or "").strip()
    return name or "name unknown"


def _user_osc_display(user_osc_index: int) -> str:
    if 0 <= user_osc_index < _USER_OSC_SLOT_COUNT:
        return f"User OSC {user_osc_index + 1:02d}"
    return f"User OSC ? ({user_osc_index})"


def _inventory_label(
    inventory_snapshot: UserUnitInventorySnapshot | None,
    user_osc_index: int,
) -> str:
    if inventory_snapshot is None:
        return "inventory unavailable"

    slot_info = inventory_snapshot.slots.get(f"osc-{user_osc_index + 1:02d}")
    if slot_info is None:
        return "slot missing in inventory"

    unit_name = (slot_info.display_name or slot_info.unit_name or "").strip()
    if unit_name:
        return unit_name
    if slot_info.status:
        return slot_info.status
    return "unnamed"


def _csv_escape(value: str) -> str:
    if "," not in value and '"' not in value:
        return value
    return '"' + value.replace('"', '""') + '"'
