# minilogue xd Librarian

Current milestone: v0.3.0-format-layer  
Target platform: Windows 11  
Runtime: Python 3.10+  
License: TBD

This is a librarian, backup, transfer and diagnostic tool for the Korg minilogue xd.

It is not a sound editor. It does not edit oscillator, filter, envelope, LFO, sequencer, modulation or effect parameters.

## Current Scope

The app now provides a broad prototype workbench:

- MIDI/SysEx receive diagnostics.
- Manual MIDI IN and MIDI OUT selection.
- Port-2 SysEx/Librarian port hints without forcing a choice.
- Programs / Banks is the default workspace and shows all 500 slots.
- Slot mapping follows `001..500` and `A001..E100`.
- MIDI Clock and realtime messages are hidden by default to avoid log flooding.
- Persistent settings for the last successful SysEx port pair.
- Separate last MIDI and last SysEx summaries, so MIDI Clock does not overwrite SysEx diagnostics.
- SysEx capture, inactivity finalization and `.syx` saving.
- Verified `.mnlgxdprog`, `.mnlgxdlib` and clean `.syx` program-dump import.
- `.mnlgxdlib` and `.syx` export from decoded bank data.
- `.mnlgxdunit` manifest and payload import/export helpers.
- Canonical 1024-byte program model with validated `PROG` signature.
- Program-name decoding and writing at bytes `4:16`.
- SysEx splitting, hashing and heuristic dump classification.
- Analyzer report export as `.txt` and `.json`.
- Explicit raw SysEx send for complete `F0...F7` messages only, with confirmation and delay.
- Preset workspace for loading, filtering, duplicating, deleting, exporting and sending raw messages.
- 500-slot offline bank workspace.
- Offline bank operations: rename program, copy, paste, move, swap, clear, sort and undo.
- Double-click rename in the program-name column.
- Bank slot reordering by drag inside the table.
- Duplicate detection by hash.
- Backup creation with `.syx`, JSON manifest and ZIP bundle.
- Backup loading, sending and basic comparison.
- User OSC / User FX local file inventory with import, remove and manifest export.
- CLI helpers under `tools/` for inspection, SysEx export and library splitting.
- App log file under the user data folder.
- Entry-point startup logging and Tkinter initialization error reporting.
- Windows onedir PyInstaller build scripts.

## Main Tabs

- Programs / Banks
- Transfer / SysEx
- Backups
- User OSC
- User FX
- Options

## Safety

No automatic writes are performed. Sending is available only as an explicit action after user confirmation. Unknown raw files that are not complete SysEx messages are loadable for inspection but are blocked from sending.

## Install From Source

```powershell
cd "D:\Eigene Dateien\Eigene Dokumente\Playground\minilogue_xd_librarian"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run From Source

```powershell
python main.py
```

## Build Windows EXE

Debug build with console:

```powershell
.\build_windows_debug.bat
```

GUI build without console:

```powershell
.\build_windows.bat
```

Expected output folders:

```text
dist/
  minilogue_xd_librarian/
  minilogue_xd_librarian_debug/
```

The onedir build is preferred while MIDI backend behavior is still being tested.

## Hardware Port Note

On the first Windows hardware test, SysEx worked through the second minilogue xd endpoint pair:

```text
MIDI IN:  MIDIIN2 (minilogue xd) 1
MIDI OUT: MIDIOUT2 (minilogue xd) 2
```

The app marks likely Port-2 candidates as possible SysEx/Librarian ports, but all ports remain selectable.

## Manual Test Checklist

1. Start the app.
2. Confirm that `Programs / Banks` opens first and shows 500 slots.
3. Check slot mapping: `001 / A001`, `100 / A100`, `101 / B001`, `500 / E100`.
4. Open `Options`.
5. Select `MIDIIN2 (minilogue xd)` and `MIDIOUT2 (minilogue xd)` if present.
6. Click `Open Ports`.
7. Click `Test selected ports` or `Listen for SysEx`.
8. Trigger a Program Dump or All Dump on the minilogue xd.
9. Open `All Presets.mnlgxdlib` or a clean program-dump `.syx` and confirm decoded program names appear.
10. Double-click a program name, rename it and confirm the new name remains after export/import.
11. Drag a bank row onto another row and confirm the program moves to the target slot.
12. Confirm that MIDI Clock does not flood the Transfer / SysEx log.
13. Confirm that last SysEx still shows `F0`, `F7` and Korg `0x42` even if MIDI Clock arrives afterward.
14. Save the capture as `.syx`.
15. Load the saved `.syx`, export an analyzer report and verify message count/bytes.
16. Create a backup and verify that `.syx`, `.json` and `.zip` are created under the app data backup folder.

## Known Limitations

- Bank import from unknown files is raw/experimental and preserves bytes.
- AddInfo `.syx` files are diagnostic/metadata dumps and are not imported as sendable programs.
- User OSC and User FX transfer is not implemented yet; local file inventory only.
- Microtuning management is not implemented yet.
- Hardware send workflows need careful real-device testing before daily use.

## Tests

```powershell
python -m unittest
python -m compileall app devices midi models librarian tests utils xd_formats tools main.py
```

## Suggested Commit Message

```text
v0.3.0: Add verified minilogue xd format layer
```
