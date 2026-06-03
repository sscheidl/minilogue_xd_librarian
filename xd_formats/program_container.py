"""Read and write single-program .mnlgxdprog containers."""

from __future__ import annotations

from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from .constants import (
    DEFAULT_PROG_INFO_XML,
    PRODUCT_NAME,
    PROGRAM_NAME_LENGTH,
    PROGRAM_NAME_OFFSET,
)
from .models import XDProgram
from .validators import validate_product, validate_prog_bin


def read_program_name(prog_bin: bytes) -> str:
    validate_prog_bin(prog_bin)
    raw = prog_bin[PROGRAM_NAME_OFFSET : PROGRAM_NAME_OFFSET + PROGRAM_NAME_LENGTH]
    return "".join(chr(value) for value in raw if 32 <= value <= 126).strip()


def write_program_name(prog_bin: bytes, new_name: str) -> bytes:
    validate_prog_bin(prog_bin)
    encoded = new_name.encode("latin-1", errors="replace")[:PROGRAM_NAME_LENGTH]
    padded = encoded.ljust(PROGRAM_NAME_LENGTH, b" ")
    data = bytearray(prog_bin)
    data[PROGRAM_NAME_OFFSET : PROGRAM_NAME_OFFSET + PROGRAM_NAME_LENGTH] = padded
    return bytes(data)


def load_mnlgxdprog(path: Path | str) -> XDProgram:
    source_path = Path(path)
    with zipfile.ZipFile(source_path) as archive:
        try:
            root = ET.fromstring(archive.read("FileInformation.xml"))
            validate_product(root)
            program_data = root.find("./Contents/ProgramData")
        except (KeyError, ET.ParseError):
            program_data = None
        if program_data is not None:
            info_name = program_data.findtext("Information", default="Prog_000.prog_info")
            bin_name = program_data.findtext("ProgramBinary", default="Prog_000.prog_bin")
        else:
            prog_bins = sorted(name for name in archive.namelist() if name.lower().endswith(".prog_bin"))
            if not prog_bins:
                raise ValueError("No *.prog_bin entry found")
            bin_name = prog_bins[0]
            info_name = bin_name[:-8] + "prog_info" if bin_name.lower().endswith("prog_bin") else "Prog_000.prog_info"
        prog_bin = archive.read(bin_name)
        validate_prog_bin(prog_bin)
        try:
            prog_info_xml = archive.read(info_name).decode("utf-8", errors="replace")
        except KeyError:
            prog_info_xml = DEFAULT_PROG_INFO_XML

    return XDProgram(
        slot_index=0,
        name=read_program_name(prog_bin),
        prog_bin=prog_bin,
        prog_info_xml=prog_info_xml,
        source_path=source_path,
        source_type="mnlgxdprog",
    )


def save_mnlgxdprog(program: XDProgram, path: Path | str) -> None:
    target_path = Path(path)
    prog_info_xml = program.prog_info_xml or DEFAULT_PROG_INFO_XML
    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("FileInformation.xml", _single_program_file_info())
        archive.writestr("Prog_000.prog_info", prog_info_xml)
        archive.writestr("Prog_000.prog_bin", program.prog_bin)


def _single_program_file_info() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>

<KorgMSLibrarian_Data>
  <Product>{PRODUCT_NAME}</Product>
  <Contents NumFavoriteData="0" NumProgramData="1" NumPresetInformation="0"
            NumTuneScaleData="0" NumTuneOctData="0">
    <ProgramData>
      <Information>Prog_000.prog_info</Information>
      <ProgramBinary>Prog_000.prog_bin</ProgramBinary>
    </ProgramData>
  </Contents>
</KorgMSLibrarian_Data>
"""
