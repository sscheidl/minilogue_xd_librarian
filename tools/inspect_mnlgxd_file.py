"""Inspect minilogue xd program, library, unit and SysEx files."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xd_formats import import_sysex_programs, load_mnlgxdlib, load_mnlgxdprog, load_mnlgxdunit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    path = args.path

    if path.suffix == ".mnlgxdlib":
        library = load_mnlgxdlib(path)
        print(f"Library: {path}")
        print(f"Programs: {len(library.programs)}")
        for program in library.programs[:10]:
            print(f"{program.slot_index + 1:03d}: {program.name}")
    elif path.suffix == ".mnlgxdprog":
        program = load_mnlgxdprog(path)
        print(f"Program: {program.name}")
        print(f"Size: {len(program.prog_bin)} bytes")
    elif path.suffix == ".mnlgxdunit":
        unit = load_mnlgxdunit(path)
        print(f"Unit: {unit.name}")
        print(f"Module: {unit.module}")
        print(f"Payload signature: {unit.payload_signature}")
        for warning in unit.warnings:
            print(f"Warning: {warning}")
    elif path.suffix == ".syx":
        programs = import_sysex_programs(path)
        print(f"SysEx program dumps: {len(programs)}")
        for program in programs[:10]:
            print(f"{program.slot_index + 1:03d}: {program.name}")
    else:
        raise SystemExit(f"Unsupported suffix: {path.suffix}")


if __name__ == "__main__":
    main()
