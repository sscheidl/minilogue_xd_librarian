"""Safe transport wrapper around the official logue-cli command surface."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from devices.korg_minilogue_xd.user_unit_protocol import (
    LogueCliPort,
    parse_port_listing,
)

_DEFAULT_TIMEOUT_S = 12.0


class LogueCliError(RuntimeError):
    """Base class for logue-cli transport failures."""


class LogueCliNotFoundError(LogueCliError):
    """The official logue-cli executable could not be located."""


class LogueCliCommandError(LogueCliError):
    """A logue-cli command failed or returned an error."""


class InventoryTimeoutError(LogueCliError):
    """A logue-cli command timed out."""


class InventoryCancelledError(LogueCliError):
    """A running inventory command was cancelled."""


class PortResolutionError(LogueCliError):
    """The selected MIDI port name could not be resolved for logue-cli."""


class LogueCliTransport:
    """Subprocess transport for the official logue-cli utility."""

    def __init__(self, executable_path: str | Path | None = None) -> None:
        self.executable_path = self._resolve_executable_path(executable_path)
        self._active_process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        with self._process_lock:
            if self._active_process is not None and self._active_process.poll() is None:
                try:
                    self._active_process.terminate()
                except OSError:
                    pass

    def list_ports(self) -> tuple[list[LogueCliPort], list[LogueCliPort]]:
        output = self.run_command(["probe", "-l"], timeout_s=8.0)
        return parse_port_listing(output)

    def resolve_port_indices(
        self,
        input_name: str | None,
        output_name: str | None,
    ) -> tuple[int, int]:
        if not input_name or not output_name:
            raise PortResolutionError("Select MIDI IN and MIDI OUT ports first.")
        inputs, outputs = self.list_ports()
        input_port = self._resolve_named_port(input_name, inputs)
        output_port = self._resolve_named_port(output_name, outputs)
        return input_port.index, output_port.index

    def probe_summary(self, input_index: int, output_index: int) -> str:
        return self.run_command(
            ["probe", "-i", str(input_index), "-o", str(output_index)],
            timeout_s=_DEFAULT_TIMEOUT_S,
        )

    def probe_module(self, module: str, input_index: int, output_index: int) -> str:
        return self.run_command(
            ["probe", "-m", module, "-i", str(input_index), "-o", str(output_index)],
            timeout_s=_DEFAULT_TIMEOUT_S,
        )

    def load_unit_archive(
        self,
        unit_path: Path | str,
        *,
        slot_index: int,
        input_index: int,
        output_index: int,
    ) -> str:
        return self.run_command(
            [
                "load",
                "-u",
                str(Path(unit_path)),
                "-s",
                str(slot_index),
                "-i",
                str(input_index),
                "-o",
                str(output_index),
            ],
            timeout_s=45.0,
        )

    def clear_slot(
        self,
        module: str,
        *,
        slot_index: int,
        input_index: int,
        output_index: int,
    ) -> str:
        return self.run_command(
            [
                "clear",
                "-m",
                module,
                "-s",
                str(slot_index),
                "-i",
                str(input_index),
                "-o",
                str(output_index),
            ],
            timeout_s=20.0,
        )

    def run_command(self, args: list[str], *, timeout_s: float) -> str:
        if not self.executable_path:
            raise LogueCliNotFoundError(self.not_found_message())
        if self._cancel_requested:
            raise InventoryCancelledError("Inventory read cancelled.")

        command = [str(self.executable_path), *args]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        with self._process_lock:
            self._active_process = process
        try:
            stdout, stderr = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            stdout, stderr = process.communicate()
            output = self._combine_output(stdout, stderr)
            raise InventoryTimeoutError(
                f"Timed out while running {' '.join(args)}.\n{output.strip()}".strip()
            ) from exc
        finally:
            with self._process_lock:
                self._active_process = None

        if self._cancel_requested:
            raise InventoryCancelledError("Inventory read cancelled.")

        output = self._combine_output(stdout, stderr)
        if process.returncode != 0 or "Error:" in output:
            raise LogueCliCommandError(output.strip() or f"Failed to run {' '.join(args)}.")
        return output

    @staticmethod
    def not_found_message() -> str:
        return (
            "The official Korg logue-cli executable was not found. "
            "Install logue-cli or place logue-cli.exe on PATH, in tools/logue-cli/, "
            "or set the MINILOGUE_XD_LOGUE_CLI environment variable."
        )

    @staticmethod
    def _resolve_named_port(name: str, ports: list[LogueCliPort]) -> LogueCliPort:
        for port in ports:
            if port.name == name:
                return port
        normalized_name = _normalize_port_name(name)
        for port in ports:
            if _normalize_port_name(port.name) == normalized_name:
                return port
        raise PortResolutionError(
            f"The selected MIDI port '{name}' is not visible to logue-cli. "
            "Use the SOUND ports shown by the Korg driver."
        )

    @classmethod
    def _resolve_executable_path(cls, executable_path: str | Path | None) -> Path | None:
        if executable_path:
            candidate = Path(executable_path)
            return candidate if candidate.is_file() else None

        env_path = os.environ.get("MINILOGUE_XD_LOGUE_CLI")
        if env_path:
            candidate = Path(env_path)
            if candidate.is_file():
                return candidate

        direct = shutil.which("logue-cli") or shutil.which("logue-cli.exe")
        if direct:
            return Path(direct)

        project_root = Path(__file__).resolve().parents[2]
        bundle_root = Path(getattr(sys, "_MEIPASS", project_root))
        candidates = (
            bundle_root / "tools" / "logue-cli" / "logue-cli.exe",
            bundle_root / "logue-cli.exe",
            project_root / "tools" / "logue-cli" / "logue-cli.exe",
            project_root / "third_party" / "logue-cli" / "logue-cli.exe",
            Path(sys.executable).resolve().parent / "logue-cli.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _combine_output(stdout: str | None, stderr: str | None) -> str:
        left = (stdout or "").strip()
        right = (stderr or "").strip()
        if left and right:
            return left + "\n" + right
        return left or right


def _normalize_port_name(name: str) -> str:
    return " ".join(name.casefold().split())
