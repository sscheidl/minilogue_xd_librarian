"""Background-safe MIDI receiver wrapper.

Design contract
---------------
- The ``MidiReceiver`` opens mido ports and routes incoming messages into
  a thread-safe ``Queue``.  The callback runs in a mido background thread and
  must NEVER touch Tkinter widgets directly.
- Errors during port setup are also routed through the queue as
  ``QueuedMidiError`` objects so the GUI can display them without
  cross-thread Tk calls.
- ``make_sender()`` returns a ``MidiSender`` bound to the current output
  port.  Callers must check ``is_open`` before calling this.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from queue import Queue
from typing import Any, Optional

import mido

from midi.sender import MidiSender

_log = logging.getLogger(__name__)

__all__ = [
    "QueuedMidiMessage",
    "QueuedMidiError",
    "MidiReceiver",
]


@dataclass(frozen=True)
class QueuedMidiMessage:
    """A MIDI message transferred from the mido callback to the GUI thread."""

    message: Any
    raw: bytes
    message_type: str


@dataclass(frozen=True)
class QueuedMidiError:
    """An error transferred from MIDI setup code to the GUI thread."""

    message: str


class MidiReceiver:
    """Open MIDI ports and queue incoming input messages.

    mido invokes input callbacks outside the Tkinter event loop. The callback
    must therefore avoid all GUI operations and only place data into a Queue.

    Usage::

        receiver = MidiReceiver(queue)
        receiver.open_ports("minilogue xd MIDI 2", "minilogue xd MIDI 2")
        # ... mainloop ...
        receiver.close_ports()
    """

    def __init__(
        self, message_queue: Queue[QueuedMidiMessage | QueuedMidiError]
    ) -> None:
        self._queue = message_queue
        self._input_port: Optional[mido.ports.BaseInput] = None
        self._output_port: Optional[mido.ports.BaseOutput] = None
        self.input_name: Optional[str] = None
        self.output_name: Optional[str] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """True if at least one port (IN or OUT) is currently open."""
        return self._input_port is not None or self._output_port is not None

    @property
    def output_port(self) -> Optional[mido.ports.BaseOutput]:
        """Return the currently open MIDI OUT port, if any."""
        return self._output_port

    # ------------------------------------------------------------------
    # Port lifecycle
    # ------------------------------------------------------------------

    def open_ports(
        self, input_name: str | None, output_name: str | None
    ) -> None:
        """Close any existing ports, then open the named ports.

        Errors are posted to the message queue as ``QueuedMidiError`` so
        the GUI can display them without a direct cross-thread call.

        Args:
            input_name:  MIDI IN port name, or ``None`` to skip.
            output_name: MIDI OUT port name, or ``None`` to skip.
        """
        self.close_ports()
        try:
            if input_name:
                self._input_port = mido.open_input(
                    input_name, callback=self._on_message
                )
                self.input_name = input_name
                _log.debug("MIDI IN opened: %s", input_name)

            if output_name:
                self._output_port = mido.open_output(output_name)
                self.output_name = output_name
                _log.debug("MIDI OUT opened: %s", output_name)

        except Exception as exc:  # noqa: BLE001 – backend exceptions vary
            _log.error("Could not open MIDI ports: %s", exc)
            self.close_ports()
            self._queue.put(QueuedMidiError(f"Could not open MIDI ports: {exc}"))

    def close_ports(self) -> None:
        """Close all open ports; silently ignore errors (best-effort)."""
        for port in (self._input_port, self._output_port):
            if port is not None:
                try:
                    port.close()
                except Exception:  # noqa: BLE001
                    pass

        self._input_port = None
        self._output_port = None
        self.input_name = None
        self.output_name = None
        _log.debug("MIDI ports closed.")

    # ------------------------------------------------------------------
    # Sender factory
    # ------------------------------------------------------------------

    def make_sender(self) -> MidiSender:
        """Return a ``MidiSender`` bound to the current output port.

        The output port may be ``None`` if no OUT port is open; ``MidiSender``
        will raise in that case.  Callers should guard with ``is_open``.
        """
        return MidiSender(self._output_port)

    # ------------------------------------------------------------------
    # Internal mido callback (background thread)
    # ------------------------------------------------------------------

    def _on_message(self, message: Any) -> None:
        """mido callback – runs in a background thread; no GUI calls allowed."""
        try:
            raw = bytes(message.bytes())
        except Exception:  # noqa: BLE001
            raw = bytes()

        self._queue.put(
            QueuedMidiMessage(
                message=message,
                raw=raw,
                message_type=getattr(message, "type", "unknown"),
            )
        )
