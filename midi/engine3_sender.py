"""SysEx sending via the open mido/WinMM output port."""

from __future__ import annotations

from midi.sender import ProgressCallback, validate_sysex


class Engine3SysexSender:
    """Compatibility wrapper around the app's normal MIDI sender."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True
        cancel = getattr(self._delegate, "cancel", None)
        if callable(cancel):
            cancel()

    def send_messages(
        self,
        messages: list[bytes],
        delay_ms: int,
        progress: ProgressCallback | None = None,
    ) -> int:
        if not messages:
            self._reset_cancel_state()
            return 0
        for raw in messages:
            validate_sysex(raw)
        if self.cancel_requested:
            self._reset_cancel_state()
            return 0
        try:
            self._set_delegate_cancel_state(False)
            return self._delegate.send_messages(messages, delay_ms, progress)
        finally:
            self._reset_cancel_state()

    def _reset_cancel_state(self) -> None:
        self.cancel_requested = False
        self._set_delegate_cancel_state(False)

    def _set_delegate_cancel_state(self, value: bool) -> None:
        if hasattr(self._delegate, "cancel_requested"):
            self._delegate.cancel_requested = value
