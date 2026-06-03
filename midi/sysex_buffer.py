"""Capture buffer for incoming SysEx dumps.

A ``SysexCapture`` accumulates ``SysexMessage`` objects until finalized
either by inactivity, a hard timeout, or an explicit ``finalize()`` call.
``SysexBuffer`` manages the active capture and exposes timeout checking
so the GUI timer can trigger finalization in the main thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from midi.diagnostics import SysexMessage, build_sysex_message

_log = logging.getLogger(__name__)

__all__ = ["SysexCapture", "SysexBuffer"]


@dataclass
class SysexCapture:
    """A single contiguous SysEx capture session.

    Attributes:
        started_at:   Monotonic timestamp (``time.time()``) when the first
                      message arrived.
        finished_at:  Set when finalized; ``None`` while active.
        messages:     Ordered list of received SysEx messages.
        total_bytes:  Running sum of all message lengths.
        finalized_by: Human-readable reason string (``"inactivity"``,
                      ``"timeout"``, ``"manual"``).  ``None`` = still active.
    """

    started_at: float
    finished_at: Optional[float] = None
    messages: list[SysexMessage] = field(default_factory=list)
    total_bytes: int = 0
    finalized_by: Optional[str] = None

    @property
    def is_active(self) -> bool:
        """True while the capture has not been finalized."""
        return self.finalized_by is None


class SysexBuffer:
    """Collects related SysEx messages into a single capture session.

    Thread safety
    -------------
    All public methods are intended to be called from the **GUI thread only**.
    The underlying ``SysexCapture`` is not protected by a lock; the mido
    callback in ``MidiReceiver`` puts raw bytes into a ``Queue``, and
    ``MainWindow.process_queue`` calls ``add_message`` in the GUI thread.
    """

    def __init__(self) -> None:
        self.capture: Optional[SysexCapture] = None
        self.last_sysex_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Discard any active or finalized capture and reset timestamps."""
        self.capture = None
        self.last_sysex_at = None
        _log.debug("SysexBuffer cleared.")

    def add_message(self, raw: bytes, timestamp: float) -> SysexMessage:
        """Append a SysEx message to the current (or a new) capture session.

        A new ``SysexCapture`` is started automatically whenever the buffer
        has no active capture.

        Args:
            raw:       Raw SysEx bytes (should start with 0xF0 and end with
                       0xF7, but no validation is performed here).
            timestamp: ``time.time()`` value for when the message arrived.

        Returns:
            The ``SysexMessage`` that was appended.
        """
        if self.capture is None or not self.capture.is_active:
            self.capture = SysexCapture(started_at=timestamp)
            _log.debug("New SysexCapture started at %.3f", timestamp)

        message = build_sysex_message(raw, timestamp)
        self.capture.messages.append(message)
        self.capture.total_bytes += message.length
        self.last_sysex_at = timestamp
        return message

    def finalize(self, finalized_by: str, timestamp: float) -> bool:
        """Mark the active capture as finished.

        Args:
            finalized_by: Reason string stored on the capture object.
            timestamp:    ``time.time()`` value for the finalization time.

        Returns:
            ``True`` if a capture was active and has now been finalized;
            ``False`` if there was no active capture.
        """
        if self.capture is None or not self.capture.is_active:
            return False

        self.capture.finished_at = timestamp
        self.capture.finalized_by = finalized_by
        _log.debug(
            "SysexCapture finalized by %r: %d messages, %d bytes",
            finalized_by,
            len(self.capture.messages),
            self.capture.total_bytes,
        )
        return True

    # ------------------------------------------------------------------
    # Timeout polling (called from GUI timer)
    # ------------------------------------------------------------------

    def check_timeouts(
        self,
        now: float,
        inactivity_ms: int,
        max_timeout_s: int,
    ) -> Optional[str]:
        """Finalize the active capture if a timeout condition is met.

        Should be called periodically from the GUI event loop.

        Args:
            now:            Current ``time.time()`` value.
            inactivity_ms:  Finalize if no new message has arrived for this
                            many milliseconds.  0 disables inactivity timeout.
            max_timeout_s:  Finalize if the capture has been active for this
                            many seconds.  0 disables hard timeout.

        Returns:
            The reason string (``"timeout"`` or ``"inactivity"``) if the
            capture was just finalized; ``None`` otherwise.
        """
        if self.capture is None or not self.capture.is_active:
            return None

        if max_timeout_s > 0 and now - self.capture.started_at >= max_timeout_s:
            self.finalize("timeout", now)
            return "timeout"

        if (
            self.last_sysex_at is not None
            and inactivity_ms > 0
            and (now - self.last_sysex_at) * 1000 >= inactivity_ms
        ):
            self.finalize("inactivity", now)
            return "inactivity"

        return None

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Return the concatenated raw bytes of all captured messages.

        Returns:
            Empty bytes if no capture exists; otherwise all raw SysEx bytes
            in receive order.
        """
        if self.capture is None:
            return b""
        return b"".join(message.raw for message in self.capture.messages)
