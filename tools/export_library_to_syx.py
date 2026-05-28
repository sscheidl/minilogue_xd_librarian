"""Export a .mnlgxdlib library to clean program-dump SysEx."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xd_formats import load_mnlgxdlib, write_sysex_programs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    library = load_mnlgxdlib(args.library)
    write_sysex_programs(library.programs, args.output)
    print(f"Wrote {len(library.programs)} program dumps to {args.output}")


if __name__ == "__main__":
    main()
