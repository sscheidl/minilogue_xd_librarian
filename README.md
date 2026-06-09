# minilogue xd Librarian

Windows librarian, transfer, diagnostics, and MIDI monitor tool for the Korg minilogue xd.

Version `1.0.0` is the first consolidated release that brings the librarian workflow, the validated native SysEx receive path, and the new profile-based MIDI Monitor together in one app.

## What `v1.0.0` adds

- native TAUREON WinMM SysEx receive for raw byte-exact capture on Windows
- Korg minilogue xd librarian workflow for programs, banks, imports, exports, and request actions
- profile-based MIDI Monitor with bundled JSON profiles
- bundled `Generic MIDI` profile for universal monitoring
- bundled `Korg Minilogue XD` profile with named controls, bank mapping, and helper CC annotations
- Pocket MIDI text import and analysis helpers for copied monitor dumps
- user unit inspection workflow for `.mnlgxdunit` content
- read-only User OSC / User FX inventory via official `logue-cli probe`
- safe slot-based local User Unit assignment with pending state
- conservative User Unit write support via official `logue-cli load` / `clear`
- per-capture Multiengine analysis report for User OSC usage in decoded program banks

## MIDI Monitor Profiles

The MIDI Monitor is no longer hardcoded to a single synth.

It loads profile definitions from JSON files under `resources/midi_profiles/` and uses them to:

- label MIDI event types
- name CCs and helper controls
- show simple or technical monitor views
- resolve bank select and program numbering
- keep synth-specific knowledge out of the monitor core

Bundled profiles:

- `Generic MIDI`
- `Korg Minilogue XD`

If JSON profiles are unavailable or invalid, the app falls back safely to the built-in `Generic MIDI` profile.

## Current communication model

- SysEx receive uses the native TAUREON WinMM capture helper.
- SysEx send uses the open MIDI OUT port through `mido`/WinMM.
- User Unit inventory read uses the official Korg `logue-cli probe` path when `logue-cli.exe` is available.
- User Unit write uses the official Korg `logue-cli load` / `clear` path and then refreshes inventory from the XD.
- The app does not send MIDI automatically on startup.
- `0x0E` is treated as a global or diagnostic request and is expected to answer with `0x51`.
- Full bank receive is sequential: the app sends `0x1C` slot requests and waits for `0x4C`.
- Current and slot requests use the validated trailing-`00` request variant from the lab tools.

## Main workflows

- `Programs / Banks`: offline library, slot actions, search, sort, rename, export, send, request
- `Transfer / SysEx`: request/send/capture workflow and diagnostics
- `MIDI Monitor`: profile picker, filtered monitor view, copy/export helpers
- `User OSC` / `User FX`: slot-oriented hardware inventory plus safe pending local assignment
- `Options`: MIDI ports, communication controls, transfer settings, paths

## Core files

| File | Purpose |
|---|---|
| `app/main.py` | Entry point and logging bootstrap |
| `app/main_window.py` | Main Tkinter GUI, librarian workflow, MIDI Monitor UI |
| `app/version.py` | Single source of truth for the displayed app version |
| `devices/korg_minilogue_xd/multiengine_analysis.py` | Reports User OSC references found in decoded program banks |
| `devices/korg_minilogue_xd/user_unit_inventory.py` | User Unit inventory model and `logue-cli` reader |
| `devices/korg_minilogue_xd/user_unit_protocol.py` | Parsers for official `logue-cli probe` output |
| `devices/korg_minilogue_xd/user_unit_transport.py` | Safe `logue-cli` subprocess transport, port resolution, and User Unit write helpers |
| `midi/profiles.py` | JSON-backed MIDI profile loading and validation |
| `midi/receiver.py` | MIDI input/output lifecycle and sender factory |
| `midi/sysex_requests.py` | SysEx request builders |
| `resources/midi_profiles/*.json` | Bundled synth monitor profiles |
| `xd_formats/` | Minilogue xd format import/export and Pocket MIDI helpers |

## User Unit Inventory

`Read from XD` in the `User OSC` and `User FX` tabs is intentionally read-only.

What it does:

- resolves the selected MIDI IN / OUT names against `logue-cli probe -l`
- detects the connected device via `logue-cli probe`
- reads slot status via `logue-cli probe -m osc`, `modfx`, `delfx`, and `revfx`
- updates the GUI with `Slot | Name | Version`
- keeps hardware inventory separate from local `.mnlgxdunit` files and local slot assignments

What it does not do:

- no User Unit payload backup yet
- no payload extraction from already-installed units
- no undocumented transfer commands
- no direct low-level destructive MIDI write path outside the official toolchain

Notes:

- Source/dev runs still look for `logue-cli.exe` on `PATH`, in `tools/logue-cli/`, or via `MINILOGUE_XD_LOGUE_CLI`.
- Packaged PyInstaller builds can bundle `logue-cli.exe` directly. The project now includes a dedicated one-file spec at `packaging/pyinstaller/minilogue_xd_librarian_onefile.spec`.
- If `logue-cli` is unavailable or the XD cannot be verified safely, the read stops with a warning and no device data is modified.

## User Unit Write

The `User OSC` and `User FX` tabs now support conservative hardware writes through the official `logue-cli` workflow.

What it does:

- `Send to XD` writes only the selected pending slot
- `Send ALL` writes only pending changes inside the current tab scope
- pending installs use `logue-cli load`
- pending clear actions use `logue-cli clear`
- after a successful write, the app automatically runs `Read from XD` once to refresh the visible hardware state

Current safety model:

- only slots with pending local changes are sent
- one write operation at a time
- User Unit writes temporarily close open `mido` ports and restore them afterward
- FX and OSC writes use the same guarded confirmation / worker flow

Current limitations:

- batch send stops on the first write failure
- no backup/export of the displaced hardware unit before overwrite
- no install-diff preview beyond the confirmation text

## User Unit Slot Assignment

The local User Unit workflow now follows the Korg-style slot-first pattern:

- select a target slot
- double-click the slot, press `Enter`, or use the context menu
- choose a `.mnlgxdunit` file
- run strict container / platform / module / payload / API validation
- store the result as a local `Pending` assignment only

Supported slot groups stay strictly separated:

- `User OSC`: 16 slots
- `MOD FX`: 16 slots
- `DELAY FX`: 8 slots
- `REVERB FX`: 8 slots

Strict validation includes:

- ZIP container checks for `manifest.json` and `payload.bin`
- blocked encrypted or unsafe archive paths
- target platform must be `minilogue-xd`
- manifest module, payload magic, and destination slot type must match
- API compatibility checks for `1.0-x` and `1.1-x`
- basic parameter sanity checks

Important:

- `Pending` is not an upload
- `Replace pending` becomes a real overwrite only when you confirm `Send to XD` or `Send ALL`
- `Clear pending` becomes a real device clear only when you confirm a send
- local pending state is reconciled against hardware inventory after refresh

## Program Bank Analysis

After captured program dumps are decoded into the bank workspace, the app also writes a Multiengine report that summarizes User OSC references found in the loaded programs.

Current behavior:

- decoded program banks are scanned for User OSC references
- a text report is saved into the dump/report location
- the report can include resolved names from the current User Unit inventory snapshot
- this is analysis only and does not modify the XD

## Start from source

```powershell
cd "D:\Eigene Dateien\Eigene Dokumente\Playground\minilogue_xd_librarian"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

Debug mode:

```powershell
$env:DEBUG = "1"
python -m app.main
```

## Validation

Current test baseline:

```powershell
python -m pytest -q
```

Latest verified result for the current freeze state:

- `176 passed, 21 subtests passed`

## Notes

- If the native TAUREON capture helper is missing, send remains available through an opened MIDI OUT port.
- For sending, a MIDI OUT port must be selected and opened first.
- After hardware changes, use `Refresh MIDI Ports` or `Reconnect MIDI`.
- User Unit hardware inventory depends on the official `logue-cli` probe backend.
- User Unit writes depend on the official `logue-cli` load/clear backend.
- The sequential `0x1C` full-bank request path exists, but it should still be treated as a conservative explicit workflow rather than an automatic startup sync.

## Release summary

The consolidated release note is tracked in:

- `AKTUELLER_STAND.md`
