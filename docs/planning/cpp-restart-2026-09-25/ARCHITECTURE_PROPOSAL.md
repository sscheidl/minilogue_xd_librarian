# Architekturvorlage XD-CPP-001

Status: Proposed, Claude-Review ausstehend. Datum: 2026-09-25.
Geltung: neuer minilogue-xd-Librarian; kein globaler Ersatz der TAUREON-ADRs.

## Festgelegte Benutzerziele

Durchgängige C++-Anwendung; kein Python und keine Hilfsprozesse zur Laufzeit.
Ein verlässlicher MIDI-/SysEx-Weg ohne Engine-Auswahl für Anwender.
Mindestens Funktionsgleichheit mit dem Korg-Librarian als Produktziel;
nachgewiesene Fähigkeiten und noch ausstehende Funktionen getrennt ausweisen.
Claude unterstützt und prüft unabhängig gegen.

## Vorschlag

C++20, Qt 6 Widgets und CMake. Zusätzlicher XD-Executable-Target in der bestehenden
C++-Codebasis auf einem eigenen Entwicklungsbranch/Worktree. Gemeinsame
Core-/WinMM-Module haben genau eine Quellimplementierung. TAUREONs Standardtarget,
WMS-Implementierung und akzeptierte Identitäts-/Ownership-Verträge bleiben gültig.

Das XD-Produkt verbindet ausschließlich den nativen WinMM-Transport.
TAUREON_ENABLE_WMS_TRANSPORT=OFF wird für seinen isolierten Build fest gepinnt.
Ein zusätzliches Target allein garantiert noch keine SDK-freie Konfiguration;
dies beweist der vorgeschaltete Build-Spike auf einem Buildpfad ohne WMS-Pakete.
Die bestehende Factory kann WinMM erzeugen; Backend-Voreinstellungen in
Settings/MidiTypes und GUI müssen im XD-Composition-Root explizit kontrolliert werden.

Schichten:

1. Qt-Views und Models: Bedienung, Darstellung, Auswahl und Fortschritt.
2. XD-Anwendungsfälle: lokale Bibliothek, Geräte-Abgleich, erlaubte Aktionen.
3. XD-Codec und Protokoll: Container, Programmdaten, Transaktionsautomat.
4. gemeinsamer MIDI-/SysEx-Core und Transfersteuerung.
5. ein WinMM-Transport.

Ein Fake-Transport wird nur für Tests gebaut. Die Testbarkeit rechtfertigt kein
zweites auslieferbares Backend. WMS-/UMP-Typen in gemeinsam genutzten,
versionsgebundenen Datenschemas sind nicht selbst eine zweite MIDI-Engine:
ihre Entfernung erfolgt nicht beiläufig und ist für dieses Ziel nicht erforderlich.
Das Produkt darf WMS-Routen weder akzeptieren noch still in WinMM-Routen umdeuten.

## Warum dieser Zuschnitt

Ein globales Entfernen von WMS würde die breitere TAUREON-Produktdefinition ändern.
Ein vollständiges Kopieren/Forken der Plattform würde eigene Wartung und
Regressionstests für dieselben Fehler erzeugen. Ein zusätzliches Produktziel
begrenzt Änderungen auf XD-Komposition, Build und Gerätemodul.

Diese Wahl ist noch zu bestätigen: Falls das gezielte Review zeigt, dass ein
zusätzliches Target TAUREON zu stark verknüpft, ist eine versionierte gemeinsame
Core-Bibliothek der nächste Kandidat. Kein automatischer Fallback auf einen
kompletten Plattformfork und kein Löschen von WMS als Ausweichmaßnahme.

## Unverändert zu erhaltende Verträge

- Callback -> begrenzte Queue -> Worker; keine GUI-Arbeit in nativen Callbacks.
- MIDIHDR-Besitz, Return/Completion, Unprepare und Close nach ADR-0002.
  Ein zurückgegebener Eingabepuffer wird durch den Worker erneut eingereiht,
  nicht direkt im Callback.
- Datenverlust markiert betroffene SysEx-Captures als unvollständig/tainted.
- Kein Austausch unbekannter Rohbytes; keine stillen Reparaturen.
- Routenauflösung Exact/Missing/Ambiguous/Invalid nach ADR-0001.
- Keine persistierten WinMM-Indizes und keine Zuordnung zum ersten ähnlichen Port.
- Geordneter Abbruch/Shutdown, Generationen gegen verspätete Events, Worker join.
- Keine Hintergrund-Writes und kein stilles Wiederholen fehlgeschlagener Writes.
- Lesewiederholungen sind begrenzt; Schreiben mit unklarem ACK erhält
  Ergebnis-unbekannt statt eines unbelegten Erfolgs oder blinden Retries.
- SysEx ohne Transaktions-ID braucht Serialisierung und eine dokumentierte
  Behandlung später Antworten. Hostseitige Sequenznummern machen eine alte,
  auf dem Draht nicht unterscheidbare Geräteantwort nicht identifizierbar.

## Etappen mit Abnahmekriterien

| Etappe | Ergebnis | Abnahme |
|---|---|---|
| XD-0, diese Lieferung | Audit, Diff-Sicherung, Architektur- und Reviewvorlage | Claude hat Befunde/Empfehlung geliefert; Disposition dokumentiert |
| XD-1a | isolierter WinMM-only-Build-Spike | gepinnter Ausgangscommit; configure/build ohne direkten WMS-SDK-Input; relevante CTest-Softwaretests bestehen |
| XD-1b | eigenständiger XD-Composition-Root und Qt-Shell | kein Python/Sidecar/zweiter Transport; TAUREON-Standardbuild unverändert testbar; XD-Settings getrennt |
| XD-2 | C++-Formatkern | .syx/.mnlgxdprog/.mnlgxdlib; 7-Bit-Grenzfälle; 500 Slots; Metadaten/opaque members erhalten; fehlerhafte Archive begrenzt behandelt |
| XD-3 | C++-Gerätesimulator und Read-Transaktionen | Delay, Fragmentierung, Echtzeitbytes, falscher Slot/Device, Duplikat, Timeout, Disconnect/Cancel; nachvollziehbare Vollständigkeit |
| XD-4 | lokale Bibliothek und Qt-Workflow | Import, Auswahl, Rename, Copy/Move/Undo und Save As; GUI verwendet denselben Formatkern |
| XD-5 | Gerätevalidierung und Program-Writes | zunächst Read-only; danach explizit bestimmter Testslot, ACK und unabhängiges Readback; Bank-Writes erst danach |
| XD-6 | native User-Unit-Funktionen | dokumentierter Transfer/Adressierung/Chunking/ACK; keine logue-cli-Abhängigkeit; sichere Belege vor Geräte-Writes |
| XD-7 | Distribution | Windows-Matrix, Abhängigkeits-/Lizenznachweise, DPI, Release-Review und dokumentierte Restgrenzen |

XD-2 bis XD-4 können weitgehend ohne Gerät entwickelt werden. XD-6 beginnt mit
Dokumentations-/Machbarkeitsprüfung und darf die übrige Offline-Entwicklung nicht
von einem ungeklärten Transferprotokoll abhängig machen. Endgültige Feature-Parität
bleibt offen, bis alle tatsächlich benötigten Korg-Funktionen inventarisiert und belegt sind.

Windows-Matrix für spätere Tests: Windows 10 x64 Legacy, Windows 11 x64 Legacy,
Windows 11 mit Full WMS, sowie gesondert der verfügbare Preview-/RC-Zustand.
Verfügbarkeit eines Ports ist kein Beweis für vollständigen SysEx-Roundtrip.
Keine globale Windows-API-Modusänderung zur Herstellung eines Test-PASS.
Loopbacks sind getrennte lokale Evidenz; sie ersetzen keinen USB-/DIN-Gerätetest.

## Minimaler Auftrag XD-1a nach Review

In einem isolierten Checkout eines gemeinsam festgelegten Commits:
CMake mit WMS-Transport, Stage-1-Spikes und lokalen MIDI-Integrationstests
ausgeschaltet konfigurieren. Vorhandene reguläre Softwaretests bauen/ausführen.
Dabei sichtbar machen, welche Targets Qt, Fake, WMS oder WinMM benötigen.
Keine fremden Pakete automatisch installieren. Buildlogs, Commit,
Abhängigkeitsliste und Testnamen/-ergebnisse protokollieren.
Fehlende WMS-/Physiktests gelten in diesem Build als außerhalb des Scopes,
nicht als ausgeführt oder bestanden.

Danach höchstens notwendige additive Target-Trennungen vorschlagen.
Keine pauschale Entfernung von Backend-Enums, UMP-Parsern oder TAUREON-Tests.

## Modell-/Reviewvertrag

Astra high für Architektur und begrenzte Umsetzung; xhigh gezielt für
Ownership-, Integritäts- oder P0/P1-Fragen. Sonnet 5 high als unabhängiger Reviewer
der Architekturvorlage. Für Routinearbeiten medium/high nach Umfang.
Dies sind Arbeitszuordnungen, keine Behauptung über eine technisch umgestellte
Session-Einstellung.

Die aktuelle Benutzerentscheidung, Sonnet einzusetzen, gilt für diese
Gegenprüfung. TAUREONs bestehende Opus-Empfehlung für kritische
Lifetime-/P0/P1-Reviews wird dadurch nicht als bereits erfüllt dargestellt.
Bei solchen Befunden einen gezielten stärkeren Review erwägen; keine pauschale
Modellaufrüstung statt reproduzierbarer Tests.
