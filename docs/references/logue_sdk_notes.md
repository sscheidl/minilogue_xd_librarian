# logue SDK / User Unit Notes

These notes document the current minilogue xd librarian boundary for User OSC and User FX handling.

## Programs vs User Units

Programs and banks are handled through the normal minilogue xd MIDI/SysEx program dump workflow:

- current program request
- individual program slot requests
- decoded program dumps in `.mnlgxdprog`, `.mnlgxdlib`, and clean `.syx`

User OSC and User FX are different. They are logue SDK User Units distributed as `.mnlgxdunit` files, with compiled unit payload plus manifest/header metadata. They must not be treated as normal program dumps.

## Current Implementation

The app currently supports local User Unit handling only:

- import `.mnlgxdunit` files into the local user-unit library folder
- parse ZIP-based manifests and binary payload signatures conservatively
- show metadata such as name, type, API, version, developer ID, unit ID, payload magic, and file size
- classify supported unit types as `osc`, `modfx`, `delfx`, or `revfx`
- maintain local slot assignments for:
  - User OSC 1-16
  - Mod FX 1-16
  - Delay FX 1-8
  - Reverb FX 1-8

Local assignments are not hardware inventory. They mean "this is what the user has locally assigned in the librarian", not "this is known to be installed on the connected minilogue xd".

## Compatibility Policy

Compatibility is intentionally conservative:

- `compatible with minilogue xd`: header and payload are plausible for minilogue xd
- `compatibility unknown - not sendable to XD`: generic logue SDK target, missing target, unknown signature, warning, or incomplete metadata
- `incompatible / wrong target`: explicit non-xd target

Even when a unit is classified as compatible, hardware transfer remains disabled until the User Unit transfer protocol is verified.

## Hardware Read / Write Boundary

`Read from XD` and `Send to XD` for User OSC/User FX are intentionally disabled.

Reason: minilogue xd User Unit slots are not exposed through the normal Program Dump workflow. Implementing this requires verification against the logue SDK, logue-cli behavior, or Korg Librarian transfer behavior, including chunking, target slot addressing, device acknowledgements, timeouts, and Windows MIDI buffer behavior.

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
