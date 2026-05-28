"""MIDI message filtering helpers."""

from __future__ import annotations

from dataclasses import dataclass


REALTIME_MESSAGE_TYPES = {
    "clock",
    "start",
    "stop",
    "continue",
    "active_sensing",
    "reset",
}

NOTE_CONTROLLER_TYPES = {
    "note_on",
    "note_off",
    "control_change",
    "polytouch",
    "aftertouch",
    "pitchwheel",
    "program_change",
}


@dataclass(frozen=True)
class MidiFilterSettings:
    show_sysex_only: bool = True
    hide_midi_clock: bool = True
    show_realtime: bool = False
    show_note_controller: bool = False


def is_realtime_message(message_type: str) -> bool:
    return message_type in REALTIME_MESSAGE_TYPES


def is_note_controller_message(message_type: str) -> bool:
    return message_type in NOTE_CONTROLLER_TYPES


def should_log_message(message_type: str, is_sysex: bool, settings: MidiFilterSettings) -> bool:
    if is_sysex:
        return True
    if message_type == "clock" and settings.hide_midi_clock:
        return False
    if is_realtime_message(message_type):
        return settings.show_realtime
    if settings.show_sysex_only:
        return False
    if is_note_controller_message(message_type):
        return settings.show_note_controller
    return True
