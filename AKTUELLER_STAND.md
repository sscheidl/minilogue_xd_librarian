# Aktueller Stand - minilogue xd Librarian `v1.0.0`

Stand: 2026-06-03  
Repository: `sscheidl/minilogue_xd_librarian`  
Branch: `main`  
Release: `v1.0.0`

## Kurzfassung

`v1.0.0` ist die erste zusammengezogene Release-Version des Projekts.

Der aktuelle Stand kombiniert:

- den Korg-minilogue-xd-Librarian-Workflow
- die validierte native SysEx-Capture-Richtung fuer Windows
- einen universellen MIDI-Monitor mit JSON-basierten Synth-Profilen
- Import- und Analysewerkzeuge fuer Pocket-MIDI-Text und xd-Dateiformate

Das Tool ist weiterhin kein Echtzeit-Soundeditor. Der Schwerpunkt liegt auf Librarian, Transfer, Diagnose, Analyse und sicheren Import-/Export-Workflows.

## Wichtigste Ergebnisse

### 1. Librarian-Workflow konsolidiert

- `Programs / Banks` ist der Hauptarbeitsbereich.
- 500 Programme werden konsistent als `001..500` und intern bankbezogen behandelt.
- Suchen, Sortieren, Rename, Export, Send und Request sind als Arbeitsablaeufe zusammengefuehrt.
- Importvalidierung blockiert unpassende oder unklare Inhalte defensiv statt sie still zu akzeptieren.

### 2. Native SysEx-Capture erfolgreich integriert

- SysEx-Empfang nutzt den nativen TAUREON-WinMM-Helper.
- Capture bleibt roh und byte-exakt.
- Die erfolgreiche Richtung und die Hardware-Notizen sind separat dokumentiert in:
  - `IMPORTANT_NATIVE_CAPTURE_SUCCESS_2026-06-02.md`

### 3. Universeller MIDI Monitor auf JSON-Basis

- Der MIDI-Monitor ist nicht mehr an nur ein Geraet fest verdrahtet.
- Synth-spezifisches Wissen wird aus JSON-Profilen geladen.
- Das Profilsystem steuert:
  - Anzeigenamen fuer MIDI-Ereignisse
  - CC-Namen und Hilfs-Controller
  - einfache vs. technische Ansicht
  - Bank- und Programmlogik

Gebuendelte Profile:

- `Generic MIDI`
- `Korg Minilogue XD`

Pfad:

- `resources/midi_profiles/`

Sicherheitsverhalten:

- Falls JSON-Profile fehlen oder ungueltig sind, faellt das Tool sicher auf ein eingebautes `Generic MIDI`-Profil zurueck.

### 4. Pocket-MIDI-Import und Analyse

- Hex-Text aus Zwischenablage oder Monitor-Exports kann analysiert werden.
- Realtime-Muell und irrelevante Textfragmente werden beim Parsen ignoriert.
- Programmdumps lassen sich aus analysiertem Material einzeln exportieren.
- Clean-Dump-Bankmaterial kann auf Vollstaendigkeit und Slot-Abdeckung geprueft werden.

### 5. User-Unit- und xd-Format-Schicht erweitert

- `.mnlgxdprog`, `.mnlgxdlib`, `.mnlgxdunit` und CleanDump-SysEx bleiben Teil des validierten Format-Layers.
- User-Units werden konservativ inspiziert und angezeigt.
- Transfer fuer User-Units bleibt absichtlich vorsichtig, bis das Verhalten am Geraet voll abgesichert ist.

## MIDI-Monitor-Architektur

Die universelle MIDI-Monitor-Variante basiert auf JSON-Dateien pro Synthesizer.

Erwartete Top-Level-Felder:

- `profile_id`
- `display_name`
- `manufacturer`
- `device`
- `midi_channel_base`
- `notes`
- `event_names`
- `control_changes`
- `special_controls`
- optional `program_mapping`

Damit bleibt der Monitor selbst generisch, waehrend Synth-spezifische Details austauschbar in Daten gepflegt werden koennen.

## Kommunikationsmodell

- SysEx receive: nativer TAUREON-WinMM-Capture-Helper
- SysEx send: geoeffneter MIDI-OUT-Port ueber `mido`/WinMM
- kein automatisches MIDI-Senden beim Start
- `0x0E` wird als globaler/diagnostischer Request behandelt und erwartet `0x51`
- Full-bank receive bleibt sequentiell ueber `0x1C`-Slot-Requests mit `0x4C`-Antworten
- Current- und Slot-Requests nutzen die validierte Trailing-`00`-Variante

## GUI-Stand

Aktive Arbeitsbereiche:

- `Programs / Banks`
- `Transfer / SysEx`
- `MIDI Monitor`
- `User OSC`
- `User FX`
- `Options`

Der MIDI-Monitor bietet jetzt:

- Profil-Auswahl
- Start/Stop Monitoring
- Filter fuer Event-Typen
- einfache und technische Sicht
- Copy/Export nach Text und CSV

## Validierung

Fuer diesen Release-Stand erfolgreich gelaufen:

```powershell
python -m pytest -q
```

Ergebnis:

- `130 passed, 21 subtests passed`

Abgedeckte Bereiche umfassen unter anderem:

- MIDI-Profile und JSON-Fallback
- SysEx-Requests
- Bank-Workspace-Operationen
- GUI-Monitor-Workflow
- Pocket-MIDI-Import
- User-Units
- xd-Format-Import/Export

## Bekannte Grenzen

- Das Tool ist kein vollstaendiger Parameter-Editor.
- User-Unit-Senden bleibt konservativ bzw. eingeschraenkt.
- Der generische MIDI-Monitor ist datengetrieben, aber die Qualitaet einzelner Profile haengt von den gepflegten JSON-Definitionen ab.
- Weitere Synth-Profile muessen noch als eigene JSON-Dateien ergaenzt werden, wenn der universelle Monitor breiter genutzt werden soll.

## Empfohlene naechste Schritte

1. Weitere Synth-Profile in `resources/midi_profiles/` aufnehmen.
2. Profile gegen echte Hardware-Mitschnitte pruefen.
3. User-Unit-Transferpfad nur nach verifizierter Hardware-Rueckmeldung erweitern.
4. Falls gewuenscht, spaeter einen echten generischen Multi-Synth-Monitor als eigenes Produkt aus dem Profilsystem herausziehen.
