"""SysEx codec for minilogue xd program dumps."""

from __future__ import annotations

from pathlib import Path

from .constants import (
    KORG_MANUFACTURER_ID,
    PROGRAM_SIZE,
    SYSEX_ADDINFO_DUMP_LENGTH,
    SYSEX_HEADER_PREFIX,
    SYSEX_PROGRAM_DUMP_LENGTH,
)
from .models import XDProgram
from .program_container import read_program_name
from .validators import validate_prog_bin


def split_sysex_stream_ignoring_realtime(data: bytes) -> list[bytes]:
    messages: list[bytes] = []
    current: bytearray | None = None
    for byte in data:
        if byte == 0xF0:
            current = bytearray([byte])
        elif current is not None:
            if byte in {0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE}:
                continue
            current.append(byte)
            if byte == 0xF7:
                messages.append(bytes(current))
                current = None
    return messages


def decode_7bit_packed(data: bytes) -> bytes:
    decoded = bytearray()
    index = 0
    while index < len(data):
        msb_flags = data[index]
        if msb_flags & 0x80:
            raise ValueError("Invalid 7-bit packed block header")
        index += 1
        for bit in range(7):
            if index >= len(data):
                break
            value = data[index]
            if value & 0x80:
                raise ValueError("Invalid 7-bit packed data byte")
            decoded.append(value | (((msb_flags >> bit) & 1) << 7))
            index += 1
    return bytes(decoded)


def encode_7bit_packed(data: bytes) -> bytes:
    encoded = bytearray()
    for offset in range(0, len(data), 7):
        group = data[offset : offset + 7]
        flags = 0
        low_bytes = bytearray()
        for bit, value in enumerate(group):
            flags |= ((value >> 7) & 1) << bit
            low_bytes.append(value & 0x7F)
        encoded.append(flags)
        encoded.extend(low_bytes)
    return bytes(encoded)


def decode_program_dump(message: bytes) -> XDProgram:
    if len(message) == SYSEX_ADDINFO_DUMP_LENGTH:
        raise ValueError("AddInfo SysEx dump is not a sendable program dump")
    if len(message) != SYSEX_PROGRAM_DUMP_LENGTH:
        raise ValueError(f"Unexpected SysEx program dump length: {len(message)}")
    if not message.startswith(SYSEX_HEADER_PREFIX) or message[-1] != 0xF7:
        raise ValueError("Unsupported SysEx program dump header")

    slot_index = _slot_from_header(message)
    prog_bin = decode_7bit_packed(message[9:-1])
    if len(prog_bin) != PROGRAM_SIZE:
        raise ValueError(f"Decoded program size mismatch: {len(prog_bin)}")
    validate_prog_bin(prog_bin)
    return XDProgram(
        slot_index=slot_index,
        name=read_program_name(prog_bin),
        prog_bin=prog_bin,
        source_type="syx",
    )


def decode_current_program_dump(message: bytes) -> XDProgram:
    if len(message) < 9:
        raise ValueError(f"Unexpected current program dump length: {len(message)}")
    if (
        message[0] != 0xF0
        or message[1] != KORG_MANUFACTURER_ID
        or message[3:6] != bytes([0x00, 0x01, 0x51])
        or message[6] != 0x40
        or message[-1] != 0xF7
    ):
        raise ValueError("Unsupported current program dump header")
    prog_bin = decode_7bit_packed(message[7:-1])
    if len(prog_bin) != PROGRAM_SIZE:
        raise ValueError(f"Decoded current program size mismatch: {len(prog_bin)}")
    validate_prog_bin(prog_bin)
    return XDProgram(
        slot_index=None,
        name=read_program_name(prog_bin),
        prog_bin=prog_bin,
        source_type="syx-current",
    )


def encode_program_dump(program: XDProgram, slot_index: int | None = None) -> bytes:
    validate_prog_bin(program.prog_bin)
    slot = program.slot_index if slot_index is None else slot_index
    if slot is None:
        slot = 0
    if not 0 <= slot < 16384:
        raise ValueError(f"SysEx slot index out of range: {slot}")
    return bytes(SYSEX_HEADER_PREFIX) + bytes([slot & 0x7F, (slot >> 7) & 0x7F]) + encode_7bit_packed(program.prog_bin) + b"\xF7"


def encode_current_program_dump(program: XDProgram) -> bytes:
    """Encode a program for the minilogue xd current/edit buffer."""
    validate_prog_bin(program.prog_bin)
    header = bytes([0xF0, KORG_MANUFACTURER_ID, 0x30, 0x00, 0x01, 0x51, 0x40])
    return header + encode_7bit_packed(program.prog_bin) + b"\xF7"


def import_sysex_programs(path: Path | str) -> list[XDProgram]:
    source_path = Path(path)
    programs = import_sysex_programs_from_bytes(source_path.read_bytes())
    for program in programs:
        program.source_path = source_path
    return programs


def import_sysex_programs_from_bytes(raw: bytes) -> list[XDProgram]:
    programs: list[XDProgram] = []
    for message in split_sysex_stream_ignoring_realtime(raw):
        if len(message) <= 6 or message[6] != 0x4C:
            continue
        try:
            program = decode_program_dump(message)
        except ValueError:
            continue
        programs.append(program)
    return programs


def import_current_program_from_bytes(raw: bytes) -> XDProgram | None:
    for message in split_sysex_stream_ignoring_realtime(raw):
        if len(message) <= 6 or message[6] != 0x40:
            continue
        try:
            return decode_current_program_dump(message)
        except ValueError:
            continue
    return None


def write_sysex_programs(programs: list[XDProgram], path: Path | str) -> None:
    output = bytearray()
    for index, program in enumerate(programs):
        output.extend(encode_program_dump(program, program.slot_index if program.slot_index is not None else index))
    Path(path).write_bytes(bytes(output))


def _slot_from_header(message: bytes) -> int:
    return message[7] | (message[8] << 7)
