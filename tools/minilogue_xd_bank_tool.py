#!/usr/bin/env python3
"""Offline minilogue xd Pocket MIDI / SysEx bank dump tool."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from xd_formats.pocket_midi import (
    analyze_sysex_file,
    export_individual_programs,
    write_all_extracted_syx,
    write_bank_only_syx,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze/export offline minilogue xd SysEx bank dumps.")
    parser.add_argument("input", type=Path, help="Pocket MIDI .txt or extracted .syx file")
    parser.add_argument("--save-all", type=Path, help="Write all extracted SysEx messages")
    parser.add_argument("--save-bank", type=Path, help="Write 0x4C bank messages sorted by slot")
    parser.add_argument("--export-singles", type=Path, help="Export individual 0x4C programs to folder")
    args = parser.parse_args()

    analysis = analyze_sysex_file(args.input)
    validation = analysis.validate_bank()
    counts = analysis.command_counts

    print(f"SysEx messages total: {len(analysis.messages)}")
    for command in (0x40, 0x4C, 0x44, 0x45, 0x51):
        print(f"0x{command:02X}: {counts[command]}")
    print(f"unknown: {counts[None]}")
    print(f"Bank completeness: {len(set(m.slot_index for m in analysis.bank_programs if m.slot_index is not None))}/500")
    print(f"Bank complete: {'yes' if validation.complete else 'no'}")
    if validation.missing_slots:
        print("Missing slots:", ", ".join(f"{slot + 1:03d}" for slot in validation.missing_slots[:20]))
    if validation.duplicate_slots:
        print("Duplicate slots:", ", ".join(f"{slot + 1:03d}" for slot in validation.duplicate_slots[:20]))
    if validation.invalid_lengths:
        print("Invalid lengths:", ", ".join(f"{slot + 1:03d}" for slot in validation.invalid_lengths[:20]))
    for message in analysis.bank_programs[:10]:
        print(f"{message.slot_index + 1:03d} {message.name} len={len(message.raw)}")

    if args.save_all:
        write_all_extracted_syx(analysis, args.save_all)
        print(f"Wrote all SysEx: {args.save_all}")
    if args.save_bank:
        write_bank_only_syx(analysis, args.save_bank)
        print(f"Wrote bank-only SysEx: {args.save_bank}")
    if args.export_singles:
        written = export_individual_programs(analysis, args.export_singles)
        print(f"Exported singles: {len(written)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
