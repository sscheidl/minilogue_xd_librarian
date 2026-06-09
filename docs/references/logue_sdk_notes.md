# logue SDK / User Unit Notes

These notes document the current minilogue xd librarian boundary for User OSC and User FX handling.

## Programs vs User Units

Programs and banks are handled through the normal minilogue xd MIDI/SysEx program dump workflow:

- current program request
- individual program slot requests
- decoded program dumps in `.mnlgxdprog`, `.mnlgxdlib`, and clean `.syx`

User OSC and User FX are different. They are logue SDK User Units distributed as `.mnlgxdunit` files, with compiled unit payload plus manifest/header metadata. They must not be treated as normal program dumps.

## Current Implementation

The app currently supports:

- import `.mnlgxdunit` files into the local user-unit library folder
- parse ZIP-based manifests and binary payload signatures conservatively
- show metadata such as name, type, API, version, developer ID, unit ID, payload magic, and file size
- classify supported unit types as `osc`, `modfx`, `delfx`, or `revfx`
- maintain local slot assignments for:
  - User OSC 1-16
  - Mod FX 1-16
  - Delay FX 1-8
  - Reverb FX 1-8
- read-only hardware inventory for:
  - User OSC 1-16
  - Mod FX 1-16
  - Delay FX 1-8
  - Reverb FX 1-8
- local slot-based pending assignment for:
  - User OSC 1-16
  - Mod FX 1-16
  - Delay FX 1-8
  - Reverb FX 1-8

Local assignments are not hardware inventory. They mean "this is what the user has locally assigned in the librarian", not "this is known to be installed on the connected minilogue xd".

Pending assignment is also not a hardware write. It means "this validated file is staged locally for that slot", not "this was uploaded to the synth".

## Compatibility Policy

Compatibility is intentionally conservative:

- `compatible with minilogue xd`: header and payload are plausible for minilogue xd
- `compatibility unknown - not sendable to XD`: generic logue SDK target, missing target, unknown signature, warning, or incomplete metadata
- `incompatible / wrong target`: explicit non-xd target

Even when a unit is classified as compatible, hardware transfer remains disabled until the User Unit transfer protocol is verified.

## Hardware Read / Write Boundary

`Read from XD` for User OSC/User FX is inventory-only. `Send to XD` remains intentionally disabled.

Verified read-only path:

- `logue-cli probe -l`
- `logue-cli probe`
- `logue-cli probe -m osc`
- `logue-cli probe -m modfx`
- `logue-cli probe -m delfx`
- `logue-cli probe -m revfx`

The app uses these official Korg `logue-cli` probe commands through a small local transport/parser layer. It does not reimplement unknown User Unit SysEx transfer commands in the GUI.

Write/install/delete remains disabled because minilogue xd User Unit slots are not exposed through the normal Program Dump workflow. Enabling writes still requires verified transfer behavior including chunking, target slot addressing, acknowledgements, timeouts, and Windows MIDI buffer behavior.

## What The Reader Returns

The current read-only inventory can safely surface:

- slot occupancy
- display name
- unit version
- unit API version
- developer ID
- unit ID
- device name
- system version
- logue API version
- raw status line length and raw command string

The current reader does not yet provide:

- executable payload backup
- per-slot payload size from the hardware
- per-slot checksum / CRC from the hardware
- install / clear / overwrite support

## Local Assignment Safety Rules

The slot-based local assignment workflow enforces:

- four separate unit classes: `osc`, `modfx`, `delfx`, `revfx`
- fixed slot counts: `16 / 16 / 8 / 8`
- ZIP container validation for `manifest.json` and `payload.bin`
- blocked encrypted archives and unsafe archive paths
- strict platform match to `minilogue-xd`
- strict manifest-module / payload-magic / destination-slot agreement
- API checks for `1.0-x` and `1.1-x`
- pending local state only, with no device write

The GUI therefore distinguishes three different concepts:

- `installed_on_xd`
- `pending_assignment`
- `pending_clear`

## Future SDK Use

If deeper transfer support is needed, add the official Korg logue SDK as an external reference instead of vendoring it directly into GUI code. Preferred options:

```text
third_party/logue-sdk/
```

or:

```powershell
git submodule add https://github.com/korginc/logue-sdk third_party/logue-sdk
```

The GUI should still talk to a small local parser/transfer abstraction, not directly to SDK build-system code.
