# minilogue xd Librarian

Windows librarian, transfer and diagnostic tool for the Korg minilogue xd.

## Current communication model

- SysEx receive uses the native TAUREON WinMM capture helper.
- SysEx send uses the open MIDI OUT port through mido/WinMM.
- The app does not send MIDI automatically on startup.
- `0x0E` is treated as a global or diagnostic request and is expected to answer with `0x51`.
- Full bank receive is sequential: the app sends `0x1C` slot requests and waits for `0x4C`.
- Current and slot requests use the validated trailing-`00` request variant from the lab tools.

## Core files

| File | Purpose |
|---|---|
| `app/main.py` | Entry point and logging bootstrap |
| `app/main_window.py` | Main Tkinter GUI |
| `app/version.py` | Single source of truth for the displayed app version |
| `midi/engine3_native.py` | Native TAUREON helper wrapper for receive |
| `midi/engine3_capture.py` | Native capture worker |
| `midi/engine3_sender.py` | Send wrapper around the open mido/WinMM output port |
| `midi/receiver.py` | MIDI input/output lifecycle and sender factory |
| `midi/sysex_requests.py` | SysEx request builders |

## Start from source

```bash
cd minilogue_xd_librarian
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

Debug mode:

```bash
DEBUG=1 python -m app.main
```

## Notes

- If the native TAUREON capture helper is missing, send is still available through an opened MIDI OUT port.
- For sending, a MIDI OUT port must be selected and opened first.
- After hardware changes, use `Refresh MIDI Ports` or `Reconnect MIDI`.
