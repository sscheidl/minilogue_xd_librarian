"""Constants for Korg minilogue xd containers."""

PRODUCT_NAME = "minilogue xd"

PROGRAM_COUNT = 500
PROGRAM_SIZE = 1024
PROGRAM_SIGNATURE = b"PROG"
PROGRAM_NAME_OFFSET = 4
PROGRAM_NAME_LENGTH = 12

DEFAULT_PROG_INFO_XML = """<?xml version="1.0" encoding="UTF-8"?>

<xd_ProgramInformation>
  <Programmer></Programmer>
  <Comment></Comment>
</xd_ProgramInformation>
"""

KORG_MANUFACTURER_ID = 0x42
SYSEX_HEADER_PREFIX = bytes([0xF0, KORG_MANUFACTURER_ID, 0x30, 0x00, 0x01, 0x51, 0x4C])
SYSEX_HEADER_LENGTH = 9
SYSEX_PROGRAM_DUMP_LENGTH = 1181
SYSEX_ADDINFO_DUMP_LENGTH = 359

UNIT_MODULE_LABELS = {
    "osc": "User Oscillator",
    "modfx": "User Modulation FX",
    "delfx": "User Delay FX",
    "revfx": "User Reverb FX",
}

KNOWN_UNIT_SIGNATURES = {
    "UOSC": "osc",
    "UMOD": "modfx",
    "UDEL": "delfx",
    "UREV": "revfx",
}
