"""Parsing helpers for official logue-cli User Unit inventory output."""

from __future__ import annotations

from dataclasses import dataclass
import re

MODULE_LABELS = {
    "osc": "Oscillator",
    "modfx": "Modulation FX",
    "delfx": "Delay FX",
    "revfx": "Reverb FX",
}

MODULE_TITLES = {
    "osc": "User OSC",
    "modfx": "Mod FX",
    "delfx": "Delay FX",
    "revfx": "Reverb FX",
}


@dataclass(frozen=True)
class LogueCliPort:
    direction: str
    index: int
    name: str


@dataclass(frozen=True)
class LogueCliModuleInfo:
    module: str
    slot_count: int
    max_payload_size: int | None
    max_load_size: int | None


@dataclass(frozen=True)
class LogueCliProbeSummary:
    device_name: str | None
    system_version: str | None
    logue_api_version: str | None
    modules: dict[str, LogueCliModuleInfo]
    raw_output: str


@dataclass(frozen=True)
class ParsedSlotStatus:
    slot_index: int
    occupied: bool | None
    display_name: str | None
    unit_version: str | None
    api_version: str | None
    developer_id: str | None
    unit_id: str | None
    raw_line: str
    warnings: tuple[str, ...] = ()


_PORT_LINE_RE = re.compile(r"^\s*(in|out)\s+(\d+):\s+(.*?)\s*$")
_DEVICE_RE = re.compile(r"^>\s*Device:\s*(.+?)\s*$", re.MULTILINE)
_SYSTEM_VERSION_RE = re.compile(r"^>\s*System version:\s*(.+?)\s*$", re.MULTILINE)
_LOGUE_API_RE = re.compile(r"^>\s*Logue API version:\s*(.+?)\s*$", re.MULTILINE)
_MODULE_INFO_RE = re.compile(
    r"^\s*(Modulation FX|Delay FX|Reverb FX|Oscillator):\s*\[\s*"
    r"slot_count:\s*(\d+),\s*max_payload_size:\s*(\d+),\s*max_load_size:\s*(\d+)\s*"
    r"\]\s*$",
    re.MULTILINE,
)
_STATUS_LINE_RE = re.compile(r"^\[(\d+)\]:\s*(.+?)\s*$")
_INSTALLED_SLOT_RE = re.compile(
    r'^"(?P<name>[^"]+)"\s+v(?P<version>[^\s]+)\s+api:(?P<api>[^\s]+)\s+'
    r"did:(?P<did>[0-9A-Fa-f]+)\s+uid:(?P<uid>[0-9A-Fa-f]+)\s*$"
)


def parse_port_listing(output: str) -> tuple[list[LogueCliPort], list[LogueCliPort]]:
    inputs: list[LogueCliPort] = []
    outputs: list[LogueCliPort] = []
    for line in output.splitlines():
        match = _PORT_LINE_RE.match(line)
        if not match:
            continue
        direction = match.group(1)
        port = LogueCliPort(direction=direction, index=int(match.group(2)), name=match.group(3).strip())
        if direction == "in":
            inputs.append(port)
        else:
            outputs.append(port)
    return inputs, outputs


def parse_probe_summary(output: str) -> LogueCliProbeSummary:
    device_name = _capture_first(_DEVICE_RE, output)
    system_version = _capture_first(_SYSTEM_VERSION_RE, output)
    logue_api_version = _capture_first(_LOGUE_API_RE, output)
    modules: dict[str, LogueCliModuleInfo] = {}
    label_to_module = {label: module for module, label in MODULE_LABELS.items()}
    for match in _MODULE_INFO_RE.finditer(output):
        label = match.group(1)
        module = label_to_module.get(label)
        if module is None:
            continue
        modules[module] = LogueCliModuleInfo(
            module=module,
            slot_count=int(match.group(2)),
            max_payload_size=int(match.group(3)),
            max_load_size=int(match.group(4)),
        )
    return LogueCliProbeSummary(
        device_name=device_name,
        system_version=system_version,
        logue_api_version=logue_api_version,
        modules=modules,
        raw_output=output,
    )


def parse_module_status_output(output: str) -> list[ParsedSlotStatus]:
    parsed: list[ParsedSlotStatus] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("["):
            continue
        status_match = _STATUS_LINE_RE.match(line)
        if not status_match:
            continue
        slot_index = int(status_match.group(1)) + 1
        payload = status_match.group(2).strip()
        if payload.lower() == "free.":
            parsed.append(
                ParsedSlotStatus(
                    slot_index=slot_index,
                    occupied=False,
                    display_name=None,
                    unit_version=None,
                    api_version=None,
                    developer_id=None,
                    unit_id=None,
                    raw_line=line,
                )
            )
            continue
        installed_match = _INSTALLED_SLOT_RE.match(payload)
        if installed_match:
            parsed.append(
                ParsedSlotStatus(
                    slot_index=slot_index,
                    occupied=True,
                    display_name=installed_match.group("name"),
                    unit_version=installed_match.group("version"),
                    api_version=installed_match.group("api"),
                    developer_id=installed_match.group("did").upper(),
                    unit_id=installed_match.group("uid").upper(),
                    raw_line=line,
                )
            )
            continue
        parsed.append(
            ParsedSlotStatus(
                slot_index=slot_index,
                occupied=None,
                display_name=None,
                unit_version=None,
                api_version=None,
                developer_id=None,
                unit_id=None,
                raw_line=line,
                warnings=("Unrecognized slot status format.",),
            )
        )
    return parsed


def _capture_first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return match.group(1).strip()
