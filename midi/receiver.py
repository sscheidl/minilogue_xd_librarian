"""Background-safe MIDI receiver wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from typing import Any, Optional

import mido

from midi.sender import MidiSender


@dataclass
class QueuedMidiMessage:
    """A MIDI message transferred from the mido callback to the GUI thread."""

    message: Any
    raw: bytes
    message_type: str


@dataclass
class QueuedMidiError:
    """An error transferred from MIDI setup code to the GUI thread."""

    message: str


class MidiReceiver:
    """Open MIDI ports and queue incoming input messages.

    mido invokes input callbacks outside the Tkinter event loop. The callback
    must therefore avoid all GUI operations and only place data into a Queue.
    """

    def __init__(self, message_queue: Queue[QueuedMidiMessage | QueuedMidiError]):
        self._queue = message_queue
        self._input_port: Optional[mido.ports.BaseInput] = None
        self._output_port: Optional[mido.ports.BaseOutput] = None
        self.input_name: Optional[str] = None
        self.output_name: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self._input_port is not None or self._output_port is not None

    def open_ports(self, input_name: str | None, output_name: str | None) -> None:
        self.close_ports()

        try:
            if input_name:
                self._input_port = mido.open_input(input_name, callback=self._on_message)
                self.input_name = input_name

            if output_name:
                # Step 1 only verifies the port can be opened. Nothing is sent.
                self._output_port = mido.open_output(output_name)
                self.output_name = output_name
        except Exception as exc:  # noqa: BLE001 - backend exceptions vary by system
            self.close_ports()
            self._queue.put(QueuedMidiError(f"Could not open MIDI ports: {exc}"))

    def close_ports(self) -> None:
        for port in (self._input_port, self._output_port):
            if port is not None:
                try:
                    port.close()
                except Exception:  # noqa: BLE001 - closing should be best-effort
                    pass

        self._input_port = None
        self._output_port = None
        self.input_name = None
        self.output_name = None

    def make_sender(self) -> MidiSender:
        return MidiSender(self._output_port)

    def _on_message(self, message: Any) -> None:
        try:
            raw = bytes(message.bytes())
        except Exception:
            raw = bytes()

        self._queue.put(
            QueuedMidiMessage(
                message=message,
                raw=raw,
                message_type=getattr(message, "type", "unknown"),
            )
        )
