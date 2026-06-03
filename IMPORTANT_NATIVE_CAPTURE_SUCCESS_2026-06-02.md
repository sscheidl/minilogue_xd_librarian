# IMPORTANT: NATIVE CAPTURE SUCCESS 2026-06-02

This is a local project marker for the current minilogue xd capture status.

## Key Result

The native WinMM / `engine3_native` raw-byte capture path has now produced
reproducibly clean full minilogue xd dumps under Windows 11.

## Confirmed Runs

Artifacts outside the repo:

- `D:\native_capture_20260602_153949.syx`
- `D:\native_capture_20260602_153949.diag.log`
- `D:\native_capture_20260602_153949.summary.json`
- `D:\native_capture_20260602_154540.syx`
- `D:\native_capture_20260602_154540.diag.log`
- `D:\native_capture_20260602_154540.summary.json`

Observed facts:

- Two successful full dumps on `MIDIIN2 (minilogue xd)`.
- Run 1 ended by manual stop.
- Run 2 ended automatically by `quiet-timeout` after 10 seconds.
- Both runs produced `593228` bytes.
- Both runs produced `513` complete frames.
- `0` incomplete frames.
- `0` outside bytes.
- `0` fragment events.
- `0` suspicious events.

Semantic validation of the dumps:

- `500 x 0x4C` program dumps
- `6 x 0x44` bank index blocks
- `6 x 0x45` sequencer index blocks
- `1 x 0x51` global block
- slots `0..499` present and unique

## Development Consequence

Do **not** continue patching the older text-based MIDI capture path as the main
solution direction.

Preferred direction:

- native raw-byte capture first
- diagnosis and stability before UI complexity
- no automatic dump repair

## Next Recommended Step

Use the same native capture approach for Waldorf Protein testing and compare
whether the previous Protein issues were caused by the old capture path, or by
device/driver behavior beyond the transport layer.
