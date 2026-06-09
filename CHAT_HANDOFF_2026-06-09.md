# minilogue xd Librarian - Chat Handoff 2026-06-09

## Goal

This file captures the current project state for a fresh Codex chat continuation.

## Current Product State

- App version is `1.0.0`.
- Core preset librarian workflow is active: edit, transfer, monitor, bank handling.
- MIDI monitor tab exists with local filters, profile-based labeling, exports, and monitoring controls.
- `Play Preset` loads the selected preset into the minilogue xd edit buffer and then plays a short audition pattern.
- User OSC / User FX tabs now support:
  - hardware inventory via official `logue-cli probe`
  - safe slot-based local pending assignment of `.mnlgxdunit` files
  - strict validation before staging any local assignment
  - conservative device write / clear through official `logue-cli load` and `clear`
  - `Send ALL` for pending OSC or FX changes inside the current tab scope

## Confirmed Hardware Result

Hardware inventory read is confirmed working on a real minilogue xd.

Observed positive example:

- Category: `User OSC`
- Slot: `User OSC 13`
- Status: `Installed on XD`
- Display Name: `Bent`
- Unit Name: `Bent`
- Unit Version: `1.00-3`
- API Version: `1.00-0`
- Device: `minilogue xd`
- System Version: `2.10`
- Raw command: `logue-cli probe -m osc -i 1 -o 2`

This confirms:

- `logue-cli.exe` is found and executable
- port resolution works against the selected XD ports
- `probe -m osc` returns real device inventory
- the local parser and details dialog are wired correctly

## User Unit Read Path

Implementation is inventory-focused and intentionally conservative.

- Official transport/parser layer:
  - `devices/korg_minilogue_xd/user_unit_transport.py`
  - `devices/korg_minilogue_xd/user_unit_protocol.py`
  - `devices/korg_minilogue_xd/user_unit_inventory.py`
- GUI integration:
  - `app/main_window.py`

Current behavior:

- `Read from XD` closes open mido ports briefly, runs official `logue-cli probe`, then restores state
- reads User OSC, MOD FX, DELAY FX, REVERB FX inventory
- shows `Installed`, `Empty`, or pending-local states in the trees with `Slot | Name | Version`
- `Details` separates `Hardware inventory` from `Pending Local Assignment`

Not implemented:

- no payload backup from installed user units
- no payload extraction from the XD

## User Unit Write Path

User Unit writes now exist and stay on the official toolchain.

- transport layer:
  - `devices/korg_minilogue_xd/user_unit_transport.py`
- GUI integration:
  - `app/main_window.py`

Current behavior:

- `Send to XD` writes only the selected pending slot
- `Send ALL` writes only slots with pending changes
- pending install uses `logue-cli load`
- pending clear uses `logue-cli clear`
- writes temporarily close open mido ports and restore them afterward
- after success, the GUI automatically runs `Read from XD` once

Current limitations:

- batch send stops on first failure
- no backup/export of the displaced hardware unit
- no bulk diff/preview beyond the confirmation text

## User Unit Slot Assignment

Safe local slot assignment is implemented.

Modules and slot pools:

- `User OSC`: 16
- `MOD FX`: 16
- `DELAY FX`: 8
- `REVERB FX`: 8

Validation covers:

- zip container integrity
- required `manifest.json` and `payload.bin`
- path traversal / encrypted archive rejection
- target platform must be `minilogue-xd`
- manifest module must match payload magic
- destination slot must match module type
- API compatibility rules
- OSC parameter count rules
- FX parameter warnings

Pending states:

- `Pending`
- `Replace pending`
- `Clear pending`

Important:

- hardware inventory and local staged state are intentionally separate
- failed validation never changes assignment state
- inventory refresh reconciles stale pending local state against the latest XD state

## MIDI / Monitoring State

- background port detection and delayed XD warning are implemented
- auto-connect logic was refined so monitor status reflects real port state more honestly
- MIDI monitor is decoupled from the transfer log
- General MIDI controller names were added for the generic monitor profile
- program-change display is bank-aware and Korg-profile aware

## Program Analysis

- captured bank dumps now trigger a Multiengine analysis pass
- the report identifies programs that reference User OSC slots
- report text is written into the dump output location and can use the current User Unit inventory snapshot for labels

## Packaging State

`logue-cli.exe` is now present locally at:

- `tools/logue-cli/logue-cli.exe`

Build support:

- normal PyInstaller folder build bundles `logue-cli.exe`
- dedicated one-file build spec exists:
  - `packaging/pyinstaller/minilogue_xd_librarian_onefile.spec`

Resolver updates:

- `devices/korg_minilogue_xd/user_unit_transport.py` now checks `_MEIPASS` paths
- `main.py` now resolves icon path through `_MEIPASS` too

Important packaging note:

- `assets/icon.ico` is still not present in the repository
- build works without it, but custom executable icon is still pending

## Tests / Verification

Latest known successful checks before this handoff:

- `python -m pytest -q`
  - `176 passed, 21 subtests passed`
- `python -m unittest`
  - `Ran 176 tests ... OK`
- `python -m compileall .`
  - success
- `git diff --check`
  - no diff errors, only CRLF warnings
- `python -m PyInstaller --noconfirm --clean packaging\\pyinstaller\\minilogue_xd_librarian.spec`
  - success
- `python -m PyInstaller --noconfirm --clean packaging\\pyinstaller\\minilogue_xd_librarian_onefile.spec`
  - success

## Key Files Added Recently

- `devices/korg_minilogue_xd/multiengine_analysis.py`
- `devices/korg_minilogue_xd/unit_types.py`
- `devices/korg_minilogue_xd/unit_container.py`
- `devices/korg_minilogue_xd/unit_manifest.py`
- `devices/korg_minilogue_xd/unit_payload.py`
- `devices/korg_minilogue_xd/unit_validator.py`
- `devices/korg_minilogue_xd/unit_workspace.py`
- `devices/korg_minilogue_xd/user_unit_inventory.py`
- `devices/korg_minilogue_xd/user_unit_protocol.py`
- `devices/korg_minilogue_xd/user_unit_transport.py`
- `packaging/pyinstaller/minilogue_xd_librarian_onefile.spec`
- `tests/test_unit_validator.py`
- `tests/test_user_unit_inventory.py`
- `tests/test_multiengine_analysis.py`

## Cleanup Already Done

The following temporary or outdated items were removed during this cleanup pass:

- build artifacts: `build/`, `dist/`
- cache folders: `.pytest_cache/`, all `__pycache__/`
- outdated request-lab helper versions:
  - `tools/minilogue_xd_request_lab_v5.1.py`
  - `tools/minilogue_xd_request_lab_v5.2_multiport.py`
  - `tools/minilogue_xd_request_lab_v5.3_pc_current.py`
  - `tools/minilogue_xd_request_lab_v5.5_port_buttons.py`
  - `tools/minilogue_xd_request_lab_v5.6_split_tx.py`
- outdated transition note:
  - `tools/minilogue_xd_librarian_new_chat_error_analysis.md`

Kept intentionally:

- `tools/minilogue_xd_request_lab_v5.7_raw_port_finder.py`
- `AKTUELLER_STAND.md`
- `IMPORTANT_NATIVE_CAPTURE_SUCCESS_2026-06-02.md`

## Best Next Steps

Most sensible next follow-up items:

1. Decide whether the sequential `Read All from XD` workflow should be hardened into a first-class program-bank feature.
2. UI/details polish for User Unit inventory fields such as `SDK Version`, `Payload Size`, and `CRC` if the official output exposes them reliably.
3. Optional packaging polish:
   - add a real `assets/icon.ico`
   - decide whether the one-file build should become the primary release target
4. If needed later, refine User Unit batch-send ergonomics such as progress, failure summaries, and optional backups.

## Suggested New Chat Prompt

Use this as the starting message for the next Codex chat:

> Continue work on `D:\\Eigene Dateien\\Eigene Dokumente\\Playground\\minilogue_xd_librarian`. Read `CHAT_HANDOFF_2026-06-09.md` first. Current state: User OSC/User FX inventory via official `logue-cli` works on real hardware, conservative User Unit write/clear via official `logue-cli` is implemented, `Send ALL` is available for pending OSC/FX changes, and Multiengine analysis reports are generated after captured bank dumps. Please continue from the handoff and keep hardware-facing changes conservative and explicitly confirmed.
