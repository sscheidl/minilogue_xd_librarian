"""Native WinMM SysEx capture wrapper adapted from the TAUREON helper."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_HARD_TIMEOUT_MS = 60_000
DEFAULT_QUIET_TIMEOUT_MS = 10_000
LIST_INPUTS_TIMEOUT_S = 8
_HELPER_FILENAME = "taureon_midi_capture.exe"
_HELPER_ENV_VARS = ("MINILOGUE_XD_ENGINE3_HELPER", "TAUREON_ENGINE3_HELPER")
_INSTALL_HINT = (
    "Build the TAUREON native helper or set MINILOGUE_XD_ENGINE3_HELPER/"
    "TAUREON_ENGINE3_HELPER to taureon_midi_capture.exe."
)


class Engine3NativeError(RuntimeError):
    """Raised when the native capture helper cannot be used."""


@dataclass(frozen=True)
class Engine3NativeStatus:
    available: bool
    helper_path: str | None
    install_hint: str = _INSTALL_HINT

    @property
    def status_text(self) -> str:
        if self.available and self.helper_path:
            return f"Native Engine 3 capture helper active: {self.helper_path}"
        return f"Native Engine 3 capture helper missing. {self.install_hint}"


@dataclass(frozen=True)
class MidiInputDevice:
    index: int
    name: str
    manufacturer_id: int | None = None
    product_id: int | None = None
    driver_version: int | None = None


@dataclass(frozen=True)
class CaptureRequest:
    device_index: int
    out_path: Path
    timeout_ms: int = DEFAULT_HARD_TIMEOUT_MS
    quiet_timeout_ms: int = DEFAULT_QUIET_TIMEOUT_MS
    diag_log_path: Path | None = None
    stop_file_path: Path | None = None


def _candidate_helper_paths() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    bundle_root = Path(getattr(sys, "_MEIPASS", repo_root))
    candidates = [
        bundle_root / "engine3_native" / "build" / "Release" / _HELPER_FILENAME,
        repo_root / "engine3_native" / "build" / "Release" / _HELPER_FILENAME,
        repo_root.parent / "TAUREON-Synth-Tool" / "engine3_native" / "build" / "Release" / _HELPER_FILENAME,
    ]
    return candidates


def default_helper_path() -> Path:
    for env_var in _HELPER_ENV_VARS:
        env_value = os.environ.get(env_var)
        if env_value:
            return Path(env_value)
    for candidate in _candidate_helper_paths():
        if candidate.exists():
            return candidate
    return _candidate_helper_paths()[0]


def detect_engine3_native_runtime() -> Engine3NativeStatus:
    helper_path = default_helper_path()
    if helper_path.exists():
        return Engine3NativeStatus(True, str(helper_path))
    return Engine3NativeStatus(False, None)


class Engine3Native:
    """Thin process wrapper around the TAUREON native WinMM capture helper."""

    def __init__(self, helper_path: str | os.PathLike[str] | None = None) -> None:
        self.helper_path = Path(helper_path) if helper_path else default_helper_path()

    def _ensure_helper(self) -> None:
        if not self.helper_path.exists():
            raise Engine3NativeError(
                f"Native helper not found: {self.helper_path}\n{_INSTALL_HINT}"
            )

    def list_inputs(self) -> list[MidiInputDevice]:
        self._ensure_helper()
        try:
            proc = subprocess.run(
                [str(self.helper_path), "--list-json"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=LIST_INPUTS_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise Engine3NativeError(
                f"Native device listing timed out after {LIST_INPUTS_TIMEOUT_S}s"
            ) from exc
        except OSError as exc:
            raise Engine3NativeError(f"Native device listing failed: {exc}") from exc
        if proc.returncode != 0:
            raise Engine3NativeError(proc.stderr.strip() or "Native device listing failed")

        try:
            payload: dict[str, Any] = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            snippet = (proc.stdout or "").strip().splitlines()
            preview = snippet[0][:160] if snippet else "<empty output>"
            raise Engine3NativeError(
                f"Native device listing returned invalid JSON: {preview}"
            ) from exc
        devices: list[MidiInputDevice] = []
        for item in payload.get("inputs", []):
            if "error" in item:
                continue
            devices.append(
                MidiInputDevice(
                    index=int(item["index"]),
                    name=str(item["name"]),
                    manufacturer_id=item.get("manufacturer_id"),
                    product_id=item.get("product_id"),
                    driver_version=item.get("driver_version"),
                )
            )
        return devices

    def build_capture_command(self, request: CaptureRequest) -> list[str]:
        self._ensure_helper()
        cmd = [
            str(self.helper_path),
            "--capture",
            "--device-index",
            str(request.device_index),
            "--out",
            str(request.out_path),
            "--timeout-ms",
            str(max(0, request.timeout_ms)),
            "--quiet-timeout-ms",
            str(max(0, request.quiet_timeout_ms)),
        ]
        if request.diag_log_path is not None:
            cmd.extend(["--diag-log", str(request.diag_log_path)])
        if request.stop_file_path is not None:
            cmd.extend(["--stop-file", str(request.stop_file_path)])
        return cmd

    def start_capture_process(
        self,
        request: CaptureRequest,
        *,
        stderr_pipe: bool = True,
        stdout_pipe: bool = False,
    ) -> subprocess.Popen[str]:
        request.out_path.parent.mkdir(parents=True, exist_ok=True)
        if request.diag_log_path is not None:
            request.diag_log_path.parent.mkdir(parents=True, exist_ok=True)
        if request.stop_file_path is not None:
            request.stop_file_path.parent.mkdir(parents=True, exist_ok=True)
            request.stop_file_path.unlink(missing_ok=True)
        return subprocess.Popen(
            self.build_capture_command(request),
            stdout=subprocess.PIPE if stdout_pipe else subprocess.DEVNULL,
            stderr=subprocess.PIPE if stderr_pipe else subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def normalize_port_name(name: str) -> str:
    normalized = name.strip().lower()
    if ":" in normalized:
        normalized = normalized.split(":", 1)[1]
    parts = normalized.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].replace(":", "").isdigit():
        normalized = parts[0]
    return " ".join(normalized.split())


def device_key(name: str) -> str:
    normalized = normalize_port_name(name)
    if "(" in normalized and ")" in normalized:
        normalized = normalized.split("(", 1)[1].split(")", 1)[0]
    for token in ("midiin2", "midiin", "midiout2", "midiout"):
        normalized = normalized.replace(token, " ")
    normalized = normalized.replace("(", " ").replace(")", " ")
    return " ".join(normalized.split())


def resolve_input_device(port_name: str, devices: list[MidiInputDevice]) -> MidiInputDevice:
    wanted = normalize_port_name(port_name)
    wanted_key = device_key(port_name)
    selected: MidiInputDevice | None = None
    sibling_match: MidiInputDevice | None = None
    fuzzy_match: MidiInputDevice | None = None

    for device in devices:
        normalized = normalize_port_name(device.name)
        if normalized == wanted:
            selected = device
            break
        if wanted_key and device_key(device.name) == wanted_key and sibling_match is None:
            sibling_match = device
        if wanted and (wanted in normalized or normalized in wanted) and fuzzy_match is None:
            fuzzy_match = device

    if selected is not None:
        return selected
    if sibling_match is not None:
        return sibling_match
    if fuzzy_match is not None:
        return fuzzy_match

    available = ", ".join(device.name for device in devices[:10])
    raise Engine3NativeError(
        f'MIDI input port "{port_name}" does not match any native WinMM input. '
        f"Available: {available or 'none'}"
    )


def capture_finish_reason(stderr_text: str) -> str:
    match = re.search(r"reason=([^\s]+)", stderr_text or "")
    return match.group(1) if match else ""
