# Changelog

## v0.3.0-format-layer - 2026-05-28

### New Features

- Added `xd_formats` import/export layer for `.mnlgxdprog`, `.mnlgxdlib`, `.syx` program dumps and `.mnlgxdunit`.
- Added verified minilogue xd 7-bit SysEx codec; exporting `All Presets.mnlgxdlib` matches `All Presets_CleanDump.syx` byte-for-byte against local fixtures.
- Added canonical 1024-byte `XDProgram` model with validated `PROG` signature and name handling at bytes `4:16`.
- Added library operations for move, swap, sort, rename, init replacement and program export.
- Added CLI tools for file inspection, library-to-SysEx export and library splitting.
- Bank imports now decode real `.mnlgxdlib`, `.mnlgxdprog` and clean `.syx` program dumps.
- Bank rename writes verified program-name bytes when decoded program data is available.
- Added double-click rename on the program-name column and retained table drag-and-drop slot moving.

### Safety / Compatibility Notes

- AddInfo `.syx` messages are recognized as non-program data and are not imported as sendable program dumps.
- User unit payload signatures are reported conservatively; unknown signatures produce warnings instead of guessed categories.

## v0.2.0-gui-rework - 2026-05-28

### New Features

- Reworked the GUI around a Librarian-first tab layout.
- Made `Programs / Banks` the default first tab.
- Added a 500-slot Programs / Banks table with `001..500` and `A001..E100` slot mapping.
- Added minilogue-xd-specific slot mapping module and tests.
- Added MIDI realtime filter module.
- MIDI Clock is hidden from the log by default and counted separately.
- Added Options tab controls for MIDI ports, communication test, filters, transfer settings and paths.
- Split User OSC and User FX into separate tabs with placeholder management UI.

### Compatibility Notes

- Port-2 SysEx/Librarian candidates are still marked but never forced.
- Clock/realtime messages no longer overwrite the last SysEx summary.
- Hardware behavior must still be verified on the actual minilogue xd after this GUI rework.

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
