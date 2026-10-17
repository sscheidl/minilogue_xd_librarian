# Prüfauftrag für Claude Sonnet 5

> **PAUSIERT / VORLÄUFIG ÜBERHOLT (2026-09-26):** Nicht ausführen, bevor die
> gemeinsame TAUREON-V4-MIDI-Bibliotheksstrategie geprüft und dieser Auftrag
> entsprechend neu formuliert wurde. Siehe `PAUSE_HANDOFF_2026-09-26.md`.

Empfohlene Einstellung: Sonnet 5, high/adaptives Denken.
Status: Auftrag vorbereitet; Claude wurde noch nicht ausgeführt.
Die Claude-CLI war in dieser Shell nicht auf PATH. Ein anderer installierter
Zugangsweg oder eine Claude-Sitzung wird damit nicht ausgeschlossen.

## Direkt verwendbarer Auftrag

Prüfe die Architekturvorlage für einen vollständigen C++-Neustart des
minilogue-xd-Librarian. Arbeite unabhängig und zunächst ausschließlich lesend.
Bewerte Quellcode und Belege; die Aussagen von Codex sind zu prüfende Hypothesen.
Keine Dateien ändern, keine Branches umschalten, keine Installation und kein
MIDI-Verkehr. Nutze aktuelle Primärquellen für zeitabhängige Aussagen und gib
Abrufdatum sowie direkte URLs an. Liefere einen Reviewbericht in deiner Antwort.

Benutzerziele: C++20/Qt, keine Python-Laufzeit, keine externen MIDI-Hilfsprozesse,
ein produktiver WinMM-Transport im XD-Produkt. TAUREON V4 ist eine eigenständige,
weiter bestehende C++-Basis mit WMS und WinMM. Der Vorschlag lautet zusätzliches
XD-Produktziel mit gemeinsamem Core, ohne globalen Rückbau des TAUREON-Produkts.

Lies zuerst dieses Paket:

1. PHASE_0.md
2. BASELINE.json
3. ARCHITECTURE_PROPOSAL.md
4. TAUREON_LOCAL_CHANGES.patch nur für die Bewertung des vorhandenen lokalen Diffs

Projektquellen:

- sscheidl/minilogue_xd_librarian, 7bd3ce050013a80a679a495a7d23cc75da43bf5c
- sscheidl/TAUREON-Synth-Tool-V4, 7dc09c9bd241cb773b25b41402d1aea892926d3f
- TAUREON main-Vergleich: d04e99c08d9d7f4134b7040a3e8abba9654045eb

Lokale Pfade befinden sich jeweils unter
D:/Eigene Dateien/Eigene Dokumente/Playground/.
Diese Pfade sind Komfortangaben; für ein Cloud-Review genügen die benannten
Repositories, Commits und dieses Paket. Fehlenden Zugriff explizit nennen,
kein PASS aus einer bloßen Zusammenfassung ableiten.

Lies im TAUREON-Repository AGENTS.md und die dort geforderten aktuellen
Projekt-/Prozessdokumente. Relevante Quellen sind:

- docs/status/PROJECT_STATE.md, docs/stages/STAGE_5_BRIEF.md
- docs/process/AI_COLLABORATION.md und QUALITY_POLICY.md
- docs/architecture/adr/ADR-0001-backend-specific-route-identity.md
- docs/architecture/adr/ADR-0002-winmm-callback-and-header-ownership.md
- src/CMakeLists.txt, src/transports/wms/CMakeLists.txt
- src/transports/winmm und zugehörige Tests
- src/app/NativeTransportFactory.cpp, Settings, ConnectionWorker
- src/core/midi/MidiTypes.hpp und RoutePersistence/RouteResolver
- src/app/Librarian.hpp und docs/reference/PROVENANCE.md

Prüffragen:

1. Kann ein zusätzlicher XD-Target den gemeinsamen C++-Core nutzen und genau
   einen WinMM-Transport ausliefern, ohne TAUREONs Produktvertrag zu ändern?
   Welche minimalen CMake-/Factory-/Settings-Trennungen sind notwendig?
2. Reicht WMS_TRANSPORT=OFF für SDK-/Runtime-Unabhängigkeit vom direkten
   WMS-Backend? Wo verbleiben Defaults, Tests oder Links auf WMS?
3. Welche WinMM-/SysEx-/Lifetime-Tests müssen erhalten bleiben?
   Gibt es Gründe gegen die Wiederverwendung des bestehenden WinMM-Moduls?
4. Ist die Portidentität hinreichend konservativ? Keine erfundene dauerhafte
   USB-Identität, keine unsichere Portauswahl bei gleichen Namen.
5. Sind die Windows-Kompatibilitätsgrenzen korrekt formuliert, insbesondere
   Legacy-USB, große SysEx-Nachrichten, Full WMS und Hybrid?
6. Reichen die vorgeschlagenen Offline-Tests für verspätete/falsche Antworten,
   unkorrelierte ACKs, Abbruch und eine nachfolgende Sitzung?
7. Werden unbekannte Containerdaten, Favorites/Tuning, Programmpayload und
   ZIP-vs.-SysEx-Roundtrip korrekt getrennt?
8. Welche Funktionslücken verhindern noch die behauptete Korg-Parität?
   Welche User-Unit-Fakten fehlen für den Ersatz von logue-cli?
9. Bewerte den lokalen TAUREON-Diff separat: Empfangsnachweis,
   MTA-/Close-Prüfungen, 20 -> 5 Zyklen und Wachstumsgate erst ab 100.
   Keine Übernahmeempfehlung ohne passende Ausführungsevidenz.
10. Fehlen Herkunfts-/Distributionsnachweise für Code, Qt oder Fixtures?
11. Prüfe anhand aktueller offizieller Korg-Quellen, ob Korg für Windows 11
    tatsächlich die Deinstallation des bisherigen Korg-USB-MIDI-Treibers
    empfiehlt, für welche Geräte/Versionen dies gilt und welche Konsequenzen
    daraus für den XD-Librarian folgen. Marketing-, Support- und
    Treiber-Downloadseiten nicht miteinander vermischen.
12. Prüfe anhand aktueller Microsoft-Primärquellen den Produktions-, Preview-
    oder Beta-Status der neuen Windows-MIDI-Services. Trenne Betriebssystem-
    Bestandteil, separat installierbare Komponenten, SDK und Runtime. Leite
    daraus keine pauschale Verfügbarkeit für alle Windows-11-Systeme ab.
13. Führe eine Kreuzprüfung mit aktiv gepflegten Open-Source-Projekten für den
    minilogue xd beziehungsweise dessen SysEx-/Program-Dump-Format durch.
    Dokumentiere Repository, Commit/Release und konkret wiederverwendbare
    Erkenntnisse zu Portauswahl, Treiberannahmen, SysEx-Framing, Timing,
    Request/Response-Korrelation und Fehlerbehandlung. Fremdcode nur als
    Evidenz behandeln; Lizenz und Herkunft vor jeder Übernahme prüfen.

Liefere:

- tatsächlich gelesene Quellen und exakte Commits; Einschränkungen getrennt;
- Befunde als P0/P1/P2/P3 mit Datei/Zeile, Fehlerszenario, Evidenz,
  minimaler Korrektur und Sicherheit der Einschätzung;
- klare Empfehlung zur Produktgrenze und zum minimalen XD-1a-Build-Spike;
- eine getrennte Tabelle "bestätigte Fakten / plausible Annahmen / ungeklärte
  Hardwarefragen" für Korg, Windows MIDI und SysEx;
- ein Urteil PASS / PASS mit Follow-ups / HOLD für die Architekturvorlage,
  ausdrücklich keine Hardware- oder Releasefreigabe.

Bei Streitfragen alternative Hypothesen nennen. Nicht einfach einen zweiten
Backend als pauschale Lösung hinzufügen. Auch eine Ein-Backend-Anforderung
rechtfertigt kein unhaltbares Alle-Windows-Kompatibilitätsversprechen.
