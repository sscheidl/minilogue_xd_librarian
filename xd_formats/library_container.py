"""Read, write and edit .mnlgxdlib containers."""

from __future__ import annotations

from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

from .constants import DEFAULT_PROG_INFO_XML, PRODUCT_NAME, PROGRAM_COUNT, PROGRAM_SIZE
from .filename_utils import safe_filename, unique_path
from .models import XDLibrary, XDProgram
from .program_container import read_program_name, save_mnlgxdprog, write_program_name
from .validators import validate_product, validate_prog_bin


def load_mnlgxdlib(path: Path | str) -> XDLibrary:
    source_path = Path(path)
    with zipfile.ZipFile(source_path) as archive:
        programs: list[XDProgram] = []
        referenced_files = {"FileInformation.xml"}
        favorite_data = None
        tune_scale_data: dict[str, bytes] = {}
        tune_oct_data: dict[str, bytes] = {}
        try:
            root = ET.fromstring(archive.read("FileInformation.xml"))
            validate_product(root)
            contents = root.find("Contents")
        except (KeyError, ET.ParseError):
            contents = None
        if contents is not None:
            for index, program_data in enumerate(contents.findall("ProgramData")):
                info_name = program_data.findtext("Information", default=f"Prog_{index:03d}.prog_info")
                bin_name = program_data.findtext("ProgramBinary", default=f"Prog_{index:03d}.prog_bin")
                programs.append(_read_program_entry(archive, source_path, index, bin_name, info_name))
                referenced_files.update({info_name, bin_name})

            favorite_file = contents.findtext("./FavoriteData/File")
            if favorite_file:
                favorite_data = archive.read(favorite_file)
                referenced_files.add(favorite_file)

            tune_scale_data = _read_tune_files(archive, contents, "TuneScaleData", "TuneScaleBinary", referenced_files)
            tune_oct_data = _read_tune_files(archive, contents, "TuneOctData", "TuneOctBinary", referenced_files)
        else:
            for index, bin_name in enumerate(_sorted_prog_bin_names(archive.namelist())):
                info_name = bin_name[:-8] + "prog_info" if bin_name.lower().endswith("prog_bin") else f"Prog_{index:03d}.prog_info"
                programs.append(_read_program_entry(archive, source_path, index, bin_name, info_name))
                referenced_files.update({info_name, bin_name})
        if not programs:
            raise ValueError("No *.prog_bin entries found")
        extra_files = {
            name: archive.read(name)
            for name in archive.namelist()
            if name not in referenced_files and not name.endswith("/")
        }

    return XDLibrary(
        programs=programs,
        favorite_data=favorite_data,
        tune_scale_data=tune_scale_data,
        tune_oct_data=tune_oct_data,
        extra_files=extra_files,
        source_path=source_path,
    )


def _read_program_entry(
    archive: zipfile.ZipFile,
    source_path: Path,
    index: int,
    bin_name: str,
    info_name: str,
) -> XDProgram:
    prog_bin = archive.read(bin_name)
    validate_prog_bin(prog_bin)
    try:
        prog_info_xml = archive.read(info_name).decode("utf-8", errors="replace")
    except KeyError:
        prog_info_xml = DEFAULT_PROG_INFO_XML
    return XDProgram(
        slot_index=index,
        name=read_program_name(prog_bin),
        prog_bin=prog_bin,
        prog_info_xml=prog_info_xml,
        source_path=source_path,
        source_type="mnlgxdlib",
    )


def _sorted_prog_bin_names(names: list[str]) -> list[str]:
    return sorted(
        [name for name in names if name.lower().endswith(".prog_bin")],
        key=_prog_bin_sort_key,
    )


def _prog_bin_sort_key(name: str) -> tuple[int, str]:
    match = re.search(r"Prog_(\d+)\.prog_bin$", name, re.IGNORECASE)
    if match:
        return int(match.group(1)), name.casefold()
    return 10_000, name.casefold()


def save_mnlgxdlib(library: XDLibrary, path: Path | str, *, fill_missing: bool = False) -> None:
    target_path = Path(path)
    programs = list(library.programs)
    if fill_missing and len(programs) < PROGRAM_COUNT:
        programs.extend(create_init_program(i) for i in range(len(programs), PROGRAM_COUNT))
    if len(programs) != PROGRAM_COUNT:
        raise ValueError(f"mnlgxdlib export expects {PROGRAM_COUNT} programs, got {len(programs)}")

    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("FileInformation.xml", _library_file_info(library, len(programs)))
        if library.favorite_data is not None:
            archive.writestr("FavoriteData.fav_data", library.favorite_data)
        for index, program in enumerate(programs):
            validate_prog_bin(program.prog_bin)
            archive.writestr(f"Prog_{index:03d}.prog_info", program.prog_info_xml or DEFAULT_PROG_INFO_XML)
            archive.writestr(f"Prog_{index:03d}.prog_bin", program.prog_bin)
        for name, data in library.tune_scale_data.items():
            archive.writestr(name, data)
        for name, data in library.tune_oct_data.items():
            archive.writestr(name, data)
        for name, data in library.extra_files.items():
            if name != "FileInformation.xml":
                archive.writestr(name, data)


def move_program(library: XDLibrary, from_index: int, to_index: int) -> None:
    _ensure_index(library, from_index)
    _ensure_index(library, to_index)
    program = library.programs.pop(from_index)
    library.programs.insert(to_index, program)
    _renumber(library)


def swap_programs(library: XDLibrary, first_index: int, second_index: int) -> None:
    _ensure_index(library, first_index)
    _ensure_index(library, second_index)
    library.programs[first_index], library.programs[second_index] = (
        library.programs[second_index],
        library.programs[first_index],
    )
    _renumber(library)


def sort_programs_by_name(library: XDLibrary, *, reverse: bool = False) -> None:
    library.programs.sort(key=lambda program: program.name.casefold(), reverse=reverse)
    _renumber(library)


def rename_program(library: XDLibrary, index: int, new_name: str) -> None:
    _ensure_index(library, index)
    program = library.programs[index]
    renamed_bin = write_program_name(program.prog_bin, new_name)
    program.prog_bin = renamed_bin
    program.name = read_program_name(renamed_bin)


def replace_with_init(library: XDLibrary, index: int, name: str = "Init Program") -> None:
    _ensure_index(library, index)
    library.programs[index] = create_init_program(index, name)


def export_programs_as_mnlgxdprog(
    library: XDLibrary, indices: list[int], directory: Path | str
) -> list[Path]:
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index in indices:
        _ensure_index(library, index)
        program = library.programs[index]
        stem = safe_filename(f"{index + 1:03d} {program.name}", fallback=f"program-{index + 1:03d}")
        path = unique_path(output_dir, stem, ".mnlgxdprog")
        save_mnlgxdprog(program, path)
        written.append(path)
    return written


def create_init_program(slot_index: int | None = None, name: str = "Init Program") -> XDProgram:
    prog_bin = b"PROG" + b" " * (PROGRAM_SIZE - 4)
    prog_bin = write_program_name(prog_bin, name)
    return XDProgram(
        slot_index=slot_index,
        name=read_program_name(prog_bin),
        prog_bin=prog_bin,
        prog_info_xml=DEFAULT_PROG_INFO_XML,
        source_type="generated",
    )


def _read_tune_files(
    archive: zipfile.ZipFile,
    contents: ET.Element,
    parent_tag: str,
    binary_tag: str,
    referenced_files: set[str],
) -> dict[str, bytes]:
    data: dict[str, bytes] = {}
    for entry in contents.findall(parent_tag):
        filename = entry.findtext(binary_tag)
        if filename:
            data[filename] = archive.read(filename)
            referenced_files.add(filename)
    return data


def _library_file_info(library: XDLibrary, program_count: int) -> str:
    num_favorite = 1 if library.favorite_data is not None else 0
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "",
        "<KorgMSLibrarian_Data>",
        f"  <Product>{PRODUCT_NAME}</Product>",
        (
            f'  <Contents NumFavoriteData="{num_favorite}" NumProgramData="{program_count}" '
            f'NumPresetInformation="0" NumTuneScaleData="{len(library.tune_scale_data)}" '
            f'NumTuneOctData="{len(library.tune_oct_data)}">'
        ),
    ]
    if library.favorite_data is not None:
        lines.extend(["    <FavoriteData>", "      <File>FavoriteData.fav_data</File>", "    </FavoriteData>"])
    for index in range(program_count):
        lines.extend(
            [
                "    <ProgramData>",
                f"      <Information>Prog_{index:03d}.prog_info</Information>",
                f"      <ProgramBinary>Prog_{index:03d}.prog_bin</ProgramBinary>",
                "    </ProgramData>",
            ]
        )
    for filename in library.tune_scale_data:
        lines.extend(
            [
                "    <TuneScaleData>",
                f"      <TuneScaleBinary>{filename}</TuneScaleBinary>",
                "    </TuneScaleData>",
            ]
        )
    for filename in library.tune_oct_data:
        lines.extend(
            [
                "    <TuneOctData>",
                f"      <TuneOctBinary>{filename}</TuneOctBinary>",
                "    </TuneOctData>",
            ]
        )
    lines.extend(["  </Contents>", "</KorgMSLibrarian_Data>", ""])
    return "\n".join(lines)


def _ensure_index(library: XDLibrary, index: int) -> None:
    if not 0 <= index < len(library.programs):
        raise IndexError(f"Program index out of range: {index}")


def _renumber(library: XDLibrary) -> None:
    for index, program in enumerate(library.programs):
        program.slot_index = index
