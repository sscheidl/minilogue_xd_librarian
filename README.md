# minilogue xd Librarian

Current milestone: v0.4.0-consolidated-workflow
Target platform: Windows 11
Runtime: Python 3.10+
License: TBD

This is a librarian, backup, transfer and diagnostic tool for the Korg minilogue xd.

It is not a sound editor. It does not edit oscillator, filter, envelope, LFO, sequencer, modulation or effect parameters.

## Current Scope

- Korg-native formats are the normal workflow: `.mnlgxdlib`, `.mnlgxdprog`, `.mnlgxdunit`.
- Raw `.syx` is secondary and lives in `Transfer / SysEx` for diagnostics, capture and special transfer workflows.
- `Programs / Banks` is the default workspace and shows all 500 linear slots as `001..500`.
- Bank-label mapping `A001..E100` is still available internally and in tests, but is not a default table column.
- `.mnlgxdprog`, `.mnlgxdlib` and clean `.syx` program-dump import are validated before active import.
- `.mnlgxdlib` and `.syx` export from decoded bank data are available.
- Single program export prefers `.mnlgxdprog` and uses a sanitized patch name.
- MIDI Clock and realtime messages are hidden by default and do not count as relevant MIDI events.
- Request builders exist for current program and individual slots; full-bank receive currently sends iterative slot requests and needs hardware verification.
- User OSC and User FX tabs use slot-oriented local inventory tables; transfer to the device is intentionally disabled until verified.
- Backups are workflow actions, not a separate tab.

## Main Tabs

- Programs / Banks
- Transfer / SysEx
- User OSC
- User FX
- Options

## Safety

No automatic writes are performed. Sending is available only as an explicit action after user confirmation. Unknown or incompatible imports are blocked from the active workspace, while raw SysEx diagnostics remain available in the transfer tab.

Before writing a whole bank to the device, the app recommends creating a backup first. Hardware write workflows still need careful real-device testing.

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

```powershell
.\build_windows_debug.bat
.\build_windows.bat
```

Expected output folders:

```text
dist/
  minilogue_xd_librarian/
  minilogue_xd_librarian_debug/
```

## Hardware Port Note

On the first Windows hardware test, SysEx worked through the second minilogue xd endpoint pair:

```text
MIDI IN:  MIDIIN2 (minilogue xd) 1
MIDI OUT: MIDIOUT2 (minilogue xd) 2
```

The app marks likely Port-2 candidates as possible SysEx/Librarian ports, but all ports remain selectable. The true port is the one that answers requests.

## Manual Test Checklist

1. Start the app without the XD connected and confirm it does not crash.
2. Confirm tabs are `Programs / Banks`, `Transfer / SysEx`, `User OSC`, `User FX`, `Options`.
3. Open a `.mnlgxdlib` and confirm 500 slots and decoded names.
4. Type into Search and confirm live filtering plus `n / 500 shown`.
5. Click table headers and confirm view-only sorting.
6. Right-click a bank row and confirm context menu entries are enabled/disabled sensibly.
7. Rename a decoded program and round-trip export/import.
8. Use `Transfer / SysEx` for Raw Capture and `.syx` analysis.
9. Confirm MIDI Clock does not flood the log and does not dominate the main status.
10. With Port 2 selected, test `Request Current` and `Request Slot`.
11. Treat `Request Full Bank` as hardware-verification workflow.
12. Import a `.mnlgxdunit` and confirm type, compatibility and status are visible.

## Known Limitations

- No sound-parameter editor.
- `.mnlgxdpreset` preset-pack import is not implemented yet.
- Full-bank request/receive needs real minilogue xd verification.
- User OSC / User FX sending to the device is intentionally disabled.
- Microtuning management is not implemented yet.
- Unknown raw data is preserved only for diagnostics, not active sending.

## Tests

```powershell
python -m unittest
python -m compileall app devices midi models librarian tests utils xd_formats tools main.py
```

## Suggested Commit Message

```text
v0.4.0: Consolidate librarian workflow, GUI cleanup and format validation
```
