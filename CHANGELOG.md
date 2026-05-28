# Changelog

## v0.9.0-dev - 2026-05-28

### New Features

- Added tabbed GUI: MIDI/SysEx, Presets, Banks, Backups and Settings.
- Added Port-2 SysEx/Librarian port hinting while preserving manual port choice.
- Added persistent settings for last selected and last successful SysEx port pairs.
- Added separate last MIDI and last SysEx diagnostics so MIDI Clock no longer overwrites SysEx summary.
- Added `.syx` loading, splitting, hashing and heuristic classification.
- Added analyzer report export as text and JSON.
- Added explicit raw SysEx send with confirmation, delay and validation for complete `F0...F7` messages.
- Added preset workspace for loading, filtering, duplicating, deleting, exporting and sending raw messages.
- Added 500-slot offline bank workspace.
- Added bank display rename, copy, paste, move, swap, clear, sort and undo.
- Added hash-based duplicate detection.
- Added backup workflow with `.syx`, JSON manifest and ZIP bundle.
- Added backup loading, sending and basic compare.
- Added User Units tab for local User OSC / User FX file inventory.
- Added bank slot drag reorder inside the bank table.
- Added app log file writing under the user data folder.
- Added entry-point logging, Tkinter startup error handling and explicit close hook wiring.
- Added unit tests for SysEx splitting and offline bank operations.
- Added PyInstaller spec and Windows build scripts.

### Safety / Compatibility Notes

- Unknown raw files can be inspected but are blocked from send unless they contain complete SysEx messages.
- Rename currently stores display names only when raw program-name offsets are not verified.
- User OSC / User FX transfer and microtuning are still out of scope.

### Known Limitations

- `.mnlgxdprog` and `.mnlgxdlib` parsing is still raw/experimental.
- No verified program-name decoding yet.
- Bank drag reorder is table-based only, not OS-level file drag and drop.
- Hardware send path is implemented but not verified on device in this environment.

## v0.1.0 - 2026-05-28

### New Features

- Added first MIDI/SysEx diagnostic Tkinter GUI.
- Added manual MIDI IN and MIDI OUT port selection.
- Added MIDI port refresh.
- Added non-blocking MIDI input through mido callback and GUI Queue processing.
- Added SysEx detection and formatted hex display.
- Added Korg SysEx recognition for manufacturer ID `0x42`.
- Added RX activity indicator.
- Added diagnostic counters for MIDI messages, SysEx messages and SysEx byte totals.
- Added SysEx capture sessions with inactivity and max-timeout finalization.
- Added `.syx` saving for raw captured SysEx data.
- Added GitHub-ready project documentation and basic project structure.
