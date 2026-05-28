# minilogue xd Librarian

Current milestone: v0.2.0-gui-rework  
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
- `.syx`, `.mnlgxdprog` and `.mnlgxdlib` raw file loading.
- SysEx splitting, hashing and heuristic dump classification.
- Analyzer report export as `.txt` and `.json`.
- Explicit raw SysEx send for complete `F0...F7` messages only, with confirmation and delay.
- Preset workspace for loading, filtering, duplicating, deleting, exporting and sending raw messages.
- 500-slot offline bank workspace.
- Offline bank operations: rename display name, copy, paste, move, swap, clear, sort and undo.
- Duplicate detection by hash.
- Backup creation with `.syx`, JSON manifest and ZIP bundle.
- Backup loading, sending and basic comparison.
- User OSC / User FX local file inventory with import, remove and manifest export.
- Bank slot reordering by drag inside the table.
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
9. Confirm that MIDI Clock does not flood the Transfer / SysEx log.
10. Confirm that last SysEx still shows `F0`, `F7` and Korg `0x42` even if MIDI Clock arrives afterward.
11. Save the capture as `.syx`.
12. Load the saved `.syx`, export an analyzer report and verify message count/bytes.
13. Create a backup and verify that `.syx`, `.json` and `.zip` are created under the app data backup folder.

## Known Limitations

- `.mnlgxdprog` and `.mnlgxdlib` structures are not fully decoded yet.
- Program names are not safely decoded from raw data yet.
- Bank import from unknown files is raw/experimental and preserves bytes.
- Rename is a display override in the workspace, not a verified write into program data.
- Drag and drop inside the bank grid is not implemented yet.
- User OSC and User FX transfer is not implemented yet; local file inventory only.
- Microtuning management is not implemented yet.
- Hardware send workflows need careful real-device testing before daily use.

## Tests

```powershell
python -m unittest
python -m compileall .
```

## Suggested Commit Message

```text
v0.2.0: Rework GUI and filter MIDI clock
```
