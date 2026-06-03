# Minilogue XD Librarian – Fehleranalyse / Neustart-Kontext

Stand: nach Mini-Testtool `minilogue_xd_request_lab_v5_1_probe.py`  
Ziel: In einem neuen Chat die Fehleranalyse sauber fortsetzen, ohne alte Irrwege erneut aufzurollen.

---

## 1. Projektziel

Es geht um ein eigenes Preset-/Bank-Verwaltungstool für den **Korg minilogue xd**.

Nicht Ziel:

- kein Sound-Editor
- kein Parameter-Editor
- kein Sequencer-/Motion-Editor
- User OSC / User FX nur später, getrennt vom Program-Dump-Thema

Aktueller Fokus:

- SysEx-Kommunikation sicher verstehen
- einzelne Presets vom XD empfangen
- später vollständige Bank sichern/laden
- Write Single / Write Bank erst, wenn Receive sicher funktioniert

---

## 2. Hardware-/Systemkontext

System:

- Windows
- Korg minilogue xd per USB
- Windows zeigt zwei logische Portpaare:
  - `minilogue xd 0` / `minilogue xd 1`
  - `MIDIIN2 (minilogue xd) 1` / `MIDIOUT2 (minilogue xd) 2`

Wichtige Beobachtung:

- `MIDIIN2 / MIDIOUT2` funktioniert grundsätzlich.
- Global Diagnostic Request wird dort korrekt gesendet und empfangen.
- Es gab bereits einen Windows-Kernelcrash:
  - `DRIVER_IRQL_NOT_LESS_OR_EQUAL`
  - `USBMidi2.sys`

Konsequenz:

- keine automatische MIDI-Portabfrage beim Start
- keine Auto-Open-Ports
- keine Auto-Requests
- keine aggressiven 500er-Bursts
- keine parallelen MIDI-Tools während Tests, insbesondere kein Studio One
- MIDI-OX ist derzeit keine verlässliche Referenz, da es Ports teils nicht mehr sieht

---

## 3. Aktuelles Mini-Testtool

Aktuelle Testbasis:

```text
minilogue_xd_request_lab_v5_1_probe.py
```

Wichtige Features:

- Safe Startup: keine Port-Enumeration beim Start
- Refresh Ports erst manuell
- Open Ports manuell
- Global Diagnostic Request
- Request Current
- Request Slot
- Full Bank Sequential, aber nur nach erfolgreichem Single-Slot-Test sinnvoll
- Manual Dump Listener
- Probe Current/Slot:
  - Kanäle 0–15
  - Current trailing00 ON/OFF
  - Slot trailing00 ON/OFF
  - stoppt beim ersten `0x40` oder `0x4C`

Wichtig:

- Der Button **Probe Current/Slot** wurde eingebaut.
- In den letzten Logs wurde dieser Probe-Test offenbar **noch nicht ausgeführt**, denn es fehlen Zeilen wie:
  - `PROBE TX ch=...`
  - `FOUND RESPONSE...`
  - `Probe timeout...`

---

## 4. Gesicherte SysEx-Erkenntnisse

### 4.1 Global Diagnostic funktioniert

Gesendeter Request:

```text
F0 42 30 00 01 51 0E F7
```

Antwort:

```text
F0 42 30 00 01 51 51 ...
```

Klassifikation:

```text
cmd=0x51
type=global-data-0x51
```

Bedeutung:

- MIDI OUT vom PC zum XD funktioniert
- MIDI IN vom XD zum PC funktioniert
- der Korg-XD-Header wird akzeptiert
- Portpaar `MIDIIN2 / MIDIOUT2` funktioniert grundsätzlich
- `0x0E` ist **nicht Full Bank**, sondern Global Diagnostic / Global Data

### 4.2 0x0E ist nicht Full Bank

Frühere Annahme war falsch:

```text
F0 42 30 00 01 51 0E F7
```

liefert bei diesem XD:

```text
0x51 Global Data
```

nicht:

```text
500 × 0x4C Program Dumps
```

Konsequenz:

- `0x0E` nie mehr als „Request Full Bank“ bezeichnen
- `0x0E` nur als `Request Global Diagnostic`
- Full Bank kann später nur sequenziell über einzelne Program-Requests laufen, falls diese funktionieren

---

## 5. Bisherige Program-Request-Tests

### 5.1 Current Program Request

Getestet:

```text
F0 42 30 00 01 51 10 00 F7
```

Erwartet:

```text
0x40 Current Program Dump
```

Ergebnis bisher:

```text
keine Antwort
```

Auch Variante ohne trailing `00` wurde zumindest in früherem Test versucht:

```text
F0 42 30 00 01 51 10 F7
```

ebenfalls ohne Erfolg.

### 5.2 Slot / Program Dump Request

Getestet:

```text
F0 42 30 00 01 51 1C 00 00 00 F7
```

für Slot 001.

Erwartet:

```text
0x4C Program Dump
```

Ergebnis bisher:

```text
keine Antwort
```

Auch Variante ohne trailing `00` wurde versucht:

```text
F0 42 30 00 01 51 1C 00 00 F7
```

ebenfalls ohne Erfolg.

### 5.3 Full Bank Sequential

Full Bank wurde testweise sequenziell gestartet:

```text
Slot 001 -> timeout
Slot 002 -> timeout
Slot 003 -> timeout
...
```

Da Einzel-Slot-Request noch nicht funktioniert, ist Full Bank derzeit sinnlos.

Regel:

```text
Full Bank erst testen, wenn Request Slot 001 ein 0x4C liefert.
```

---

## 6. Manual Dump Beobachtungen

### 6.1 Manual Dump über Port 2 liefert Daten, aber keine Programmdaten

Beim manuellen Dump kamen wiederholt:

```text
6 × 0x44 Program Bank Index, je 393 Bytes
6 × 0x45 Sequencer Index, je 45 Bytes
1 × 0x51 Global Data, 100 Bytes
```

Nicht enthalten:

```text
0 × 0x40
0 × 0x4C
```

Bedeutung:

- Tool empfängt SysEx korrekt
- XD sendet über USB/Port 2
- aber der ausgelöste Dump enthält keine Sound-/Programmdaten
- das ist kein Parserproblem

### 6.2 Mögliche Erklärung

Sehr wahrscheinlich wurde bisher **GLOBAL EDIT → ALL DUMP** oder ein verwandter Index-/Global-Dump ausgelöst.

Das ist nicht identisch mit:

```text
PROGRAM EDIT → DUMP → Program Dump
```

Der Program-Dump-Weg muss gezielt getestet werden.

---

## 7. Handbuchrelevante Bedienung am XD

Nach Handbuch gibt es zwei getrennte Bereiche:

### 7.1 Einzelnes Program Dump

Pfad am XD:

```text
EDIT MODE
→ PROGRAM EDIT
→ Button 14 (DUMP)
→ Program Dump
→ PROGRAM/VALUE drehen bis "Press WRITE"
→ WRITE drücken
```

Erwartung im Tool:

```text
RX cmd=0x40
```

oder:

```text
RX cmd=0x4C
```

Das ist der wichtigste nächste manuelle Test.

### 7.2 All Dump

Pfad am XD:

```text
GLOBAL EDIT
→ Button 15 (ALL DUMP)
→ All Dump (USB) oder All Dump (MIDI)
→ Press WRITE
```

Laut Handbuch soll All Dump über USB bzw. MIDI laufen. In den bisherigen Logs kamen dabei aber offenbar nur Index-/Globaldaten:

```text
0x44 / 0x45 / 0x51
```

Noch offen:

- ob All Dump tatsächlich später noch Programmdaten schicken sollte
- ob ein Treiber-/Port-/Bufferproblem größere Programmdaten verschluckt
- ob ein falscher Menüpunkt gewählt wurde
- ob Firmware/Settings das Verhalten beeinflussen

---

## 8. Wichtige XD-Global-Settings prüfen

Am Gerät prüfen:

```text
GLOBAL EDIT → GLOBAL 4
```

Parameter:

```text
MIDI Route = USB oder USB+MIDI
MIDI Ch = 1
```

Weitere relevante Punkte, falls vorhanden:

```text
SysEx = Enable
MIDI Filter / Dump Filter = nicht blockieren
MIDI OUT = USB oder USB+MIDI
```

Wichtig:

- Korg kodiert den MIDI-Kanal im SysEx-Header als `0x30 + channel`.
- MIDI Ch 1 entspricht Header `0x30`.
- Wenn XD auf MIDI Ch 2–16 steht, könnten Current/Slot Requests mit `0x30` ignoriert werden.
- Deshalb ist der Probe-Button wichtig.

---

## 9. Nächste Tests nach Neustart

Vorbereitung:

```text
1. PC neu starten
2. XD ausschalten
3. USB kurz abziehen
4. XD wieder einschalten
5. USB wieder verbinden
6. Studio One, MIDI-OX und andere MIDI-Tools geschlossen lassen
```

Dann:

```text
1. Mini-Tool v5.1 starten
2. Refresh Ports
3. MIDIIN2 / MIDIOUT2 auswählen
4. Open Ports
5. Global Diagnostic testen
   Erwartung: 0x51
```

Danach zwei getrennte Wege testen.

---

## 10. Test A: echter manueller Program Dump

Im Mini-Tool:

```text
Listen Manual Dump
```

Am XD:

```text
EDIT MODE
→ PROGRAM EDIT
→ Button 14 DUMP
→ Program Dump
→ Press WRITE
→ WRITE
```

Gesucht:

```text
RX cmd=0x40
```

oder:

```text
RX cmd=0x4C
```

Wenn wieder nur kommt:

```text
0x44 / 0x45 / 0x51
```

dann war es vermutlich wieder All Dump / Index Dump / Global Dump, nicht Program Dump.

Wenn gar nichts kommt:

- falscher Port
- falsche XD-Global-Settings
- Treiber hängt
- Dump wurde nicht wirklich ausgeführt

---

## 11. Test B: Probe Current/Slot

Nur wenn Global Diagnostic funktioniert.

Button:

```text
Probe Current/Slot
```

Erwartete Logzeilen:

```text
PROBE TX ch=0 header=0x30 Current trailing00=ON: ...
Probe timeout: channel=0, Current trailing00=ON
PROBE TX ch=0 header=0x30 Current trailing00=OFF: ...
...
PROBE TX ch=1 header=0x31 ...
...
```

Der Probe-Test prüft:

```text
Channel 0–15
Current trailing00=ON
Current trailing00=OFF
Slot trailing00=ON
Slot trailing00=OFF
```

Wenn Treffer:

```text
FOUND RESPONSE: channel=X, header=0x3X, request=..., response=0x40/0x4C
```

Dann:

- gefundene Kanal-/Trailing-Einstellung merken
- manuell genau diese Einstellung nochmal testen
- erst danach Full Bank Sequential

---

## 12. Was aktuell NICHT tun

Nicht tun:

```text
Full Bank testen, solange Slot 001 kein 0x4C liefert
Write Single to XD
Write Bank to XD
User OSC / FX
große Bank-Bursts
MIDI-OX parallel laufen lassen
Studio One parallel laufen lassen
```

Write-Funktionen bleiben gefährlich, bis Receive zuverlässig funktioniert.

---

## 13. Interpretation des aktuellen Stands

Aktueller Arbeitsstand:

```text
Kein Parserproblem.
Kein grundsätzliches Portproblem.
Kein grundsätzliches SysEx-Problem.
```

Stattdessen:

```text
Der XD liefert bisher nur Index-/Globaldaten, aber keine Programmdumps.
```

Offene Hauptfragen:

```text
1. Wurde am XD der richtige Program-Dump-Menüpunkt verwendet?
2. Sind MIDI Route / MIDI Ch / SysEx-Filter korrekt?
3. Kommt Program Dump eventuell auf anderem Kanal/Header?
4. Verhindert der aktuelle Windows/Korg-MIDI-Treiberzustand Program Dumps?
5. Gibt es beim XD/Firmware-Verhalten eine Besonderheit, dass Programmdaten nur einzeln per Program Edit Dump kommen?
```

---

## 14. Ziel für den nächsten Chat

Der nächste Chat soll nicht wieder neue Features bauen, sondern gezielt klären:

```text
Wie erzeugen wir zuverlässig genau ein 0x40 oder 0x4C Paket?
```

Erst danach:

```text
Full Bank Sequential
Write Single
Write Bank
Integration in großes Librarian Tool
```

---

## 15. Relevante Dateien

Aktuelle Mini-Testbasis:

```text
minilogue_xd_request_lab_v5_1_probe.py
```

Nützliches gespeichertes Capture:

```text
test.syx / test(1).syx
```

Inhalt der bisherigen Captures:

```text
6 × 0x44
6 × 0x45
1 × 0x51
keine Programmdumps
```

---

## 16. Kurzfassung für neuen Chat

```text
Wir bauen einen minilogue xd Librarian. 
Das Mini-Testtool empfängt SysEx korrekt. Global Diagnostic 0x0E liefert zuverlässig 0x51.
Manual All Dump liefert bisher nur 6×0x44, 6×0x45, 1×0x51, aber kein 0x40/0x4C.
Current Request 0x10 und Slot Request 0x1C liefern bisher keine Antwort.
Port MIDIIN2/MIDIOUT2 funktioniert grundsätzlich.
Nach USBMidi2.sys-BSOD ist Safe Startup Pflicht.
Nächster Schritt: Nach PC/XD-Neustart echten PROGRAM EDIT → DUMP → Program Dump testen und den Probe Current/Slot Button ausführen.
Ziel ist genau ein 0x40 oder 0x4C zu erzeugen.
```
