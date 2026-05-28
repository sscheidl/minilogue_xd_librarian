# Aktueller Stand - minilogue xd Librarian

Stand: 2026-05-28  
Repository: `sscheidl/minilogue_xd_librarian`  
Branch: `main`  
Zielstand: `v0.4.0-consolidated-workflow`

## Kurzstatus

Der aktuelle Stand ist ein Korg-formatorientierter Librarian fuer den minilogue xd. Programme und Libraries sind der Hauptworkflow; SysEx bleibt Transfer- und Diagnosebereich.

Das Tool ist kein Sound-Editor.

## Start

```powershell
cd "D:\Eigene Dateien\Eigene Dokumente\Playground\minilogue_xd_librarian"
python main.py
```

Gebautes GUI-Programm:

```text
D:\Eigene Dateien\Eigene Dokumente\Playground\minilogue_xd_librarian\dist\minilogue_xd_librarian\minilogue_xd_librarian.exe
```

## GUI

- Tabs: `Programs / Banks`, `Transfer / SysEx`, `User OSC`, `User FX`, `Options`.
- Kein separater Backups-Tab mehr.
- `Programs / Banks` zeigt linear `001..500`.
- Standardspalten: Slot, Program Name, Source, Status, Hash, Notes.
- Live-Suche filtert die Ansicht und zeigt `n / 500 shown`.
- Tabellenkopf-Klick sortiert nur die Ansicht.
- Rechtsklickmenue fuer Cut, Copy, Paste, Move, Rename, Export, Send und Request.
- MIDI Clock wird im normalen Betrieb ausgeblendet und nicht als relevantes MIDI-Event gezaehlt.

## Dateiformate

- Primaer: `.mnlgxdlib`, `.mnlgxdprog`, `.mnlgxdunit`.
- Sekundaer: `.syx` fuer Transfer, Raw Capture und Diagnose.
- `.mnlgxdprog`/`.mnlgxdlib` Import wird validiert.
- CleanDump-`.syx` Programmdumps werden validiert und dekodiert.
- AddInfo/Unknown-SysEx wird nicht als sendbares Programm importiert.

## Request-Workflow

- `Request Current` baut `F0 42 30 00 01 51 10 F7`.
- `Request Slot` baut `F0 42 30 00 01 51 1C lsb msb F7`.
- Slot 001 entspricht intern 0.
- `Request Full Bank` sendet defensiv 500 Einzelrequests und braucht Hardwareverifikation.
- Raw Capture bleibt passives Mitschneiden im Transfer/SysEx-Bereich.

## User Units

- User OSC und User FX bleiben getrennte Tabs.
- Anzeige ist slot-orientiert.
- `.mnlgxdunit` Import zeigt Name, Typ, Kompatibilitaet, Status, Quelle und Hinweise.
- Senden zum XD ist absichtlich deaktiviert, bis Hardwaretransfer sicher geklaert ist.

## Validierung

Zuletzt erfolgreich geprueft:

```powershell
python -m unittest
python -m compileall app devices midi models librarian tests utils xd_formats tools main.py
```

Aktuelle Tests decken u. a. ab:

- Slotmapping
- SysEx-Request-Bytes
- Filename-Sanitizing
- Importvalidierung
- User-Unit-Metadaten
- GUI-Tabs und Bankspalten
- Send-Fehlerpfad und Close-Warnung

## Hardware-Test-Fokus

1. Port 2 waehlen, falls vorhanden.
2. `Request Current` testen.
3. `Request Slot` mit Slot 001 und Slot 150 testen.
4. `Request Full Bank` nur mit Beobachtung von Progress/Timeout testen.
5. `.mnlgxdlib` laden, suchen, sortieren, Rechtsklickmenue testen.
6. Rename exportieren/importieren.
7. MIDI Clock darf Log und Status nicht dominieren.
8. `.mnlgxdunit` Import mit z. B. Reverb/FX-Dateien pruefen.

## Bekannte Grenzen

- Kein Sound-Parameter-Editor.
- `.mnlgxdpreset` ist noch nicht implementiert.
- User-Unit-Transfer ist deaktiviert.
- Microtuning ist nicht implementiert.
- Full-bank Hardware-Receive muss noch am echten XD validiert werden.
