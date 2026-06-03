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
- The app does not send MIDI automatically on startup.
- `0x0E` is treated as a global or diagnostic request and is expected to answer with `0x51`.
- Full bank receive is sequential: the app sends `0x1C` slot requests and waits for `0x4C`.
- Current and slot requests use the validated trailing-`00` request variant from the lab tools.

## Main workflows

- `Programs / Banks`: offline library, slot actions, search, sort, rename, export, send, request
- `Transfer / SysEx`: request/send/capture workflow and diagnostics
- `MIDI Monitor`: profile picker, filtered monitor view, copy/export helpers
- `User OSC` / `User FX`: slot-oriented user unit inspection
- `Options`: MIDI ports, communication controls, transfer settings, paths

## Core files

| File | Purpose |
|---|---|
| `app/main.py` | Entry point and logging bootstrap |
| `app/main_window.py` | Main Tkinter GUI, librarian workflow, MIDI Monitor UI |
| `app/version.py` | Single source of truth for the displayed app version |
| `midi/profiles.py` | JSON-backed MIDI profile loading and validation |
| `midi/receiver.py` | MIDI input/output lifecycle and sender factory |
| `midi/sysex_requests.py` | SysEx request builders |
| `resources/midi_profiles/*.json` | Bundled synth monitor profiles |
| `xd_formats/` | Minilogue xd format import/export and Pocket MIDI helpers |

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

Latest verified result for this release:

- `130 passed, 21 subtests passed`

## Notes

- If the native TAUREON capture helper is missing, send remains available through an opened MIDI OUT port.
- For sending, a MIDI OUT port must be selected and opened first.
- After hardware changes, use `Refresh MIDI Ports` or `Reconnect MIDI`.
- User-unit send remains intentionally conservative until the hardware transfer path is fully verified.

## Release summary

The consolidated release note is tracked in:

- `AKTUELLER_STAND.md`
