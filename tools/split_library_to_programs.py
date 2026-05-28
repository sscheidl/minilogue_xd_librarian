"""Split a .mnlgxdlib library into .mnlgxdprog files."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xd_formats import export_programs_as_mnlgxdprog, load_mnlgxdlib


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    library = load_mnlgxdlib(args.library)
    paths = export_programs_as_mnlgxdprog(library, list(range(len(library.programs))), args.output_dir)
    print(f"Wrote {len(paths)} program files to {args.output_dir}")


if __name__ == "__main__":
    main()
