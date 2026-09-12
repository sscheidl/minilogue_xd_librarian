# Changelog

## 1.0.1-beta.1 – 2026-09-12

- Add conservative User Unit write support through official `logue-cli load` and `clear`.
- Add `Send to XD` and `Send ALL` workflows for pending User OSC / User FX slot changes.
- Refresh User Unit inventory automatically after successful User Unit writes.
- Show User Unit versions in the OSC / FX tree views and keep FX headers compact as `MOD`, `DELAY`, and `REVERB`.
- Reconcile stale pending local User Unit state against refreshed hardware inventory.
- Fix stale User OSC selection leaking into FX details / load actions.
- Add Multiengine analysis reports for captured program banks with User OSC reference summaries.
- Bundle the dedicated PyInstaller one-file spec and `logue-cli` support files needed by the current workflow.
- Remove outdated request-lab helper variants that are no longer part of the maintained path.

## 1.0.0

- Add non-destructive minilogue xd User OSC / User FX inventory reading.
- Add `Read from XD` to the `User OSC` and `User FX` tabs.
- Keep User Unit hardware inventory separate from local `.mnlgxdunit` files and local slot assignments.
- Add safe slot-based local User Unit assignment with strict module, payload, platform, and API validation.
- Add pending states for local User Unit changes without sending anything to the XD.
- Keep User Unit write / install / delete support disabled pending verified transfer protocol work.
