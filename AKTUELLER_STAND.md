# Aktueller Stand - minilogue xd Librarian

Stand: 2026-05-28  
Repository: `sscheidl/minilogue_xd_librarian`  
Branch: `main`  
Letzter Commit: `0ea8ae7 Harden entry-point logging configuration`

## Kurzstatus

Der aktuelle Stand ist ein Windows/Tkinter-Prototyp fuer Librarian-, Backup-, SysEx- und Diagnose-Workflows rund um den Korg minilogue xd.

Der Fokus liegt auf sicherem lokalen Arbeiten mit Dateien und explizitem MIDI-Transfer. Es ist kein vollstaendiger Sound-Editor fuer Syntheseparameter.

## Start

Aus dem Quellcode:

```powershell
cd "D:\Eigene Dateien\Eigene Dokumente\Playground\minilogue_xd_librarian"
python main.py
```

Gebautes GUI-Programm:

```text
D:\Eigene Dateien\Eigene Dokumente\Playground\minilogue_xd_librarian\dist\minilogue_xd_librarian\minilogue_xd_librarian.exe
```

Debug-Build mit Konsole:

```text
D:\Eigene Dateien\Eigene Dokumente\Playground\minilogue_xd_librarian\dist\minilogue_xd_librarian_debug\minilogue_xd_librarian_debug.exe
```

## Implementierte Bereiche

### GUI

- Starttab ist `Programs / Banks`.
- Weitere Tabs: `Transfer / SysEx`, `Backups`, `User OSC`, `User FX`, `Options`.
- 500 Programmplaetze werden als `001..500` und `A001..E100` angezeigt.
- Doppelklick auf den Programmnamen oeffnet Rename.
- Drag-and-drop innerhalb der Bank-Tabelle verschiebt Programmplaetze.
- Sortieren, Verschieben, Tauschen, Kopieren, Einfuegen, Loeschen und Undo sind vorhanden.
- MIDI Clock wird standardmaessig aus dem Log ausgeblendet, damit der SysEx-Test nicht ueberflutet wird.

### Dateiformate

Neues Package: `xd_formats/`

Unterstuetzt:

- `.mnlgxdprog` Einzelprogramm
- `.mnlgxdlib` Library mit 500 Programmen
- `.syx` CleanDump-Programmdumps
- `.mnlgxdunit` User Units mit `manifest.json` und `payload.bin`

Wichtige Regeln:

- Internes Programmmodell nutzt 1024 Byte `prog_bin`.
- `prog_bin` muss mit `PROG` beginnen.
- Programmname wird aus Bytes `4:16` gelesen.
- Rename schreibt nur diesen Namensbereich.
- AddInfo-`.syx` wird nicht als sendbarer Programmdump importiert.

### SysEx

- CleanDump-Import ist gegen lokale Fixtures verifiziert.
- Export `All Presets.mnlgxdlib` zu `.syx` ist bytegenau identisch zu `All Presets_CleanDump.syx`.
- Programmdumps werden als vollstaendige `F0...F7` SysEx-Nachrichten erzeugt.
- Senden ist nur explizit nach Bestaetigung moeglich.

### MIDI

- Manuelle MIDI-IN- und MIDI-OUT-Auswahl.
- Port-2-Kandidaten fuer minilogue-xd-SysEx werden nur als Hinweis markiert, nicht erzwungen.
- Bekannter funktionierender Port-Hinweis:

```text
MIDI IN:  MIDIIN2 (minilogue xd) 1
MIDI OUT: MIDIOUT2 (minilogue xd) 2
```

### Backups

- Capture kann als `.syx` gespeichert werden.
- Backup erzeugt `.syx`, `.json` und `.zip`.
- Backup-Manifest enthaelt Analyseinformationen.

### User Units

- Lokales Inventar fuer User OSC / User FX.
- Import, Entfernen und Manifest-Export sind vorhanden.
- `.mnlgxdunit` kann gelesen/geschrieben werden.
- Payload-Signaturen werden konservativ bewertet:
  - `UOSC` = User Oscillator
  - `UREV` = User Reverb FX
  - unbekannte Signaturen erzeugen Warnungen statt geratenen Kategorien.

## CLI-Tools

```powershell
python .\tools\inspect_mnlgxd_file.py ".\libraries\All Presets.mnlgxdlib"
python .\tools\inspect_mnlgxd_file.py ".\libraries\All Presets_CleanDump.syx"
python .\tools\export_library_to_syx.py ".\libraries\All Presets.mnlgxdlib" ".\out.syx"
python .\tools\split_library_to_programs.py ".\libraries\All Presets.mnlgxdlib" ".\out_programs"
```

## Logging

- Logdatei liegt unter dem App-Datenpfad aus `app.app_paths`.
- Standard-Level ist `INFO`.
- Debug-Logging:

```powershell
$env:DEBUG = "1"
python main.py
```

Alternativ:

```powershell
$env:MINILOGUE_XD_LOG_LEVEL = "DEBUG"
python main.py
```

Falls die Logdatei nicht angelegt werden kann, faellt die App auf Konsolen-Logging zurueck.

## Validierter Stand

Zuletzt erfolgreich geprueft:

```powershell
python -m unittest
python -m compileall app devices midi models librarian tests utils xd_formats tools main.py
.\build_windows_debug.bat
.\build_windows.bat
```

Ergebnisse:

- 16 Unit-Tests erfolgreich.
- Compileall erfolgreich.
- Debug- und GUI-Windows-Build erfolgreich.
- Beide EXEs starten.
- GitHub-Push auf `origin/main` funktioniert.

## Test-Checkliste am Geraet

### 1. App-Start

- EXE oder `python main.py` starten.
- Pruefen, ob `Programs / Banks` als erster Tab erscheint.
- Pruefen, ob Slot 1 als `001 / A001` und Slot 500 als `500 / E100` angezeigt wird.

### 2. MIDI-Port-Test

- In `Options` oder `Transfer / SysEx` MIDI-IN und MIDI-OUT waehlen.
- Wenn vorhanden, Port 2 waehlen:

```text
MIDIIN2 (minilogue xd)
MIDIOUT2 (minilogue xd)
```

- `Open Ports` klicken.
- `Listen for SysEx` klicken.
- Am minilogue xd einen Program Dump oder All Dump ausloesen.
- Erwartung:
  - MIDI Clock flutet das Log nicht.
  - SysEx wird erkannt.
  - Korg Manufacturer `0x42` wird angezeigt.

### 3. Library laden

- `Programs / Banks` oeffnen.
- `Open Bank` klicken.
- `.mnlgxdlib` oder CleanDump-`.syx` laden.
- Erwartung:
  - Programmnamen erscheinen lesbar.
  - 500 Slots werden befuellt.

### 4. Rename testen

- In der Bank-Tabelle einen Programmnamen doppelklicken.
- Namen aendern.
- Als `.syx` exportieren oder Bank speichern.
- Datei erneut laden.
- Erwartung:
  - Der neue Name bleibt erhalten.
  - Bei dekodierten Programmen wird der Name in Bytes `4:16` geschrieben.

### 5. Drag-and-drop testen

- Einen Bankeintrag mit gedrueckter Maustaste auf einen anderen Slot ziehen.
- Erwartung:
  - Programmplatz wird verschoben.
  - Slotnummern werden neu sortiert angezeigt.

### 6. Export testen

- Eine `.mnlgxdlib` laden.
- `Save Bank` / Export als `.syx` testen.
- Optional mit CLI inspizieren:

```powershell
python .\tools\inspect_mnlgxd_file.py ".\export.syx"
```

### 7. Senden testen

- Nur mit bewusst gewaehltem MIDI-OUT.
- Einzelne Slots auswaehlen.
- `Send Selected` klicken.
- Sicherheitsdialog bestaetigen.
- Erwartung:
  - Es werden nur vollstaendige `F0...F7` Nachrichten gesendet.
  - Keine automatische Sendung ohne Bestaetigung.

### 8. Backup testen

- SysEx empfangen oder laden.
- Backup erzeugen.
- Erwartung:
  - `.syx`, `.json` und `.zip` werden im App-Daten-Backupordner angelegt.

## Bekannte Grenzen

- Kein Sound-Parameter-Editor.
- User OSC / User FX Transfer zum Geraet ist noch nicht implementiert.
- Microtuning-Management ist noch nicht implementiert.
- Hardware-Senden muss am echten minilogue xd vorsichtig verifiziert werden.
- Unknown/raw-Dateien werden erhalten, aber nicht blind als sendbare Programme behandelt.

## Naechste sinnvolle Schritte

- Hardware-Test mit Port 2 fuer Receive und Send.
- Rename-Export-Import am echten Geraet pruefen.
- Vollstaendige Bank vom Geraet empfangen und mit `.mnlgxdlib`/CleanDump vergleichen.
- Bedienung fuer User Units ausbauen.
- Optional: App-Icon unter `assets/icon.ico` ergaenzen.
