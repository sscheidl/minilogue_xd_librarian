"""Native Engine 3 SysEx capture worker."""

from __future__ import annotations

from pathlib import Path
from queue import Queue
import tempfile
import threading
import time

from midi.capture_events import RawCaptureEvent
from midi.engine3_native import (
    CaptureRequest,
    Engine3Native,
    Engine3NativeError,
    capture_finish_reason,
    detect_engine3_native_runtime,
    resolve_input_device,
)


_REALTIME_BYTES = {0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE}


class Engine3SysexCaptureWorker:
    """Capture SysEx through the native TAUREON WinMM helper."""

    def __init__(
        self,
        port_name: str,
        events: Queue[RawCaptureEvent],
        *,
        inactivity_ms: int = 10_000,
        no_data_timeout_s: int = 60,
    ) -> None:
        self.port_name = port_name
        self.events = events
        self.inactivity_ms = max(0, inactivity_ms)
        self.no_data_timeout_s = max(0, no_data_timeout_s)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._engine: Engine3Native | None = None
        self._process = None
        self._capture_file: Path | None = None
        self._diag_file: Path | None = None
        self._stop_file: Path | None = None
        self._capture_pos = 0
        self._open_frame: bytearray | None = None
        self._stderr_lines: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._thread = threading.Thread(target=self._run, name="engine3-native-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._stop_file is not None:
            try:
                self._stop_file.parent.mkdir(parents=True, exist_ok=True)
                self._stop_file.write_text("stop\n", encoding="utf-8")
            except OSError:
                pass

    def wait_stopped(self, timeout: float = 2.0) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=max(0.0, timeout))
        return not thread.is_alive()

    def _run(self) -> None:
        try:
            status = detect_engine3_native_runtime()
            if not status.available or not status.helper_path:
                self.events.put(RawCaptureEvent("error", status.status_text, state="error"))
                return

            self._engine = Engine3Native(status.helper_path)
            device = resolve_input_device(self.port_name, self._engine.list_inputs())

            temp_dir = Path(tempfile.gettempdir())
            capture_stamp = time.time_ns()
            capture_base = temp_dir / f"minilogue_xd_native_capture_{capture_stamp}"
            self._capture_file = capture_base.with_suffix(".syx")
            self._diag_file = capture_base.with_suffix(".diag.log")
            self._stop_file = capture_base.with_suffix(".stop")
            request = CaptureRequest(
                device_index=device.index,
                out_path=self._capture_file,
                timeout_ms=self.no_data_timeout_s * 1000,
                quiet_timeout_ms=self.inactivity_ms,
                diag_log_path=self._diag_file,
                stop_file_path=self._stop_file,
            )
            self._process = self._engine.start_capture_process(request, stderr_pipe=True, stdout_pipe=False)
            self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
            self._stderr_thread.start()

            self.events.put(
                RawCaptureEvent(
                    "state",
                    f"Native capture helper started: {device.index}: {device.name}",
                    state="capturing",
                    port_name=device.name,
                )
            )
            self._poll_capture_file()
        except Engine3NativeError as exc:
            self.events.put(RawCaptureEvent("error", str(exc), state="error"))
        except Exception as exc:  # noqa: BLE001 - helper/process failures vary.
            self.events.put(RawCaptureEvent("error", str(exc), state="error"))
        finally:
            self._cleanup_temp_files()

    def _pump_stderr(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        try:
            for line in self._process.stderr:
                clean = line.strip()
                if clean:
                    self._stderr_lines.append(clean)
        finally:
            try:
                self._process.stderr.close()
            except OSError:
                pass

    def _poll_capture_file(self) -> None:
        if self._process is None:
            raise RuntimeError("_poll_capture_file called before process was started")
        while True:
            for frame in self._read_new_frames():
                self.events.put(RawCaptureEvent("message", raw=frame, state="capturing", port_name=self.port_name))

            returncode = self._process.poll()
            if returncode is not None:
                break
            time.sleep(0.05)

        for frame in self._read_new_frames():
            self.events.put(RawCaptureEvent("message", raw=frame, state="capturing", port_name=self.port_name))
        self._emit_incomplete_frame_warning()

        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=1.0)

        stderr_text = "\n".join(self._stderr_lines)
        if returncode == 0:
            reason = capture_finish_reason(stderr_text) or ("stop-request" if self._stop.is_set() else "completed")
            self.events.put(
                RawCaptureEvent(
                    "finished",
                    f"Native capture finished ({reason}).",
                    state="finished",
                    port_name=self.port_name,
                )
            )
            return

        details = self._stderr_lines[-1] if self._stderr_lines else f"exit={returncode}"
        if self._stop.is_set():
            self.events.put(RawCaptureEvent("cancelled", details, state="cancelled", port_name=self.port_name))
            return
        self.events.put(
            RawCaptureEvent(
                "error",
                f"Native capture helper failed: {details}",
                state="error",
                port_name=self.port_name,
            )
        )

    def _read_new_frames(self) -> list[bytes]:
        capture_path = self._capture_file
        if capture_path is None or not capture_path.exists():
            return []
        try:
            with capture_path.open("rb") as handle:
                handle.seek(self._capture_pos)
                chunk = handle.read()
                self._capture_pos = handle.tell()
        except OSError:
            return []
        if not chunk:
            return []
        return self._extract_frames(chunk)

    def _extract_frames(self, chunk: bytes) -> list[bytes]:
        frames: list[bytes] = []
        for byte in chunk:
            if byte in _REALTIME_BYTES:
                continue
            if byte == 0xF0:
                if self._open_frame is not None:
                    self.events.put(
                        RawCaptureEvent(
                            "warning",
                            f"Incomplete SysEx frame discarded before new F0 ({len(self._open_frame)} bytes buffered).",
                            state="capturing",
                            port_name=self.port_name,
                        )
                    )
                self._open_frame = bytearray([byte])
                continue
            if self._open_frame is None:
                continue
            self._open_frame.append(byte)
            if byte == 0xF7:
                frames.append(bytes(self._open_frame))
                self._open_frame = None
        return frames

    def _emit_incomplete_frame_warning(self) -> None:
        if self._open_frame is None:
            return
        self.events.put(
            RawCaptureEvent(
                "warning",
                f"Capture ended with incomplete SysEx frame ({len(self._open_frame)} bytes buffered).",
                state="capturing",
                port_name=self.port_name,
            )
        )

    def _cleanup_temp_files(self) -> None:
        for path in (self._capture_file, self._diag_file, self._stop_file):
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self._capture_file = None
        self._diag_file = None
        self._stop_file = None
        self._capture_pos = 0
        self._open_frame = None
