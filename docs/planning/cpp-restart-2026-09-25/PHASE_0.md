# XD Librarian: C++-Neustart, Phase 0

Datum: 2026-09-25. Bearbeitung: Codex, auf Wunsch mit Astra.
Status: Pausiert am 2026-09-26; siehe `PAUSE_HANDOFF_2026-09-26.md`.
Die frühere Architekturvorlage und Claude-Gegenprüfung sind bis zur Prüfung der
gemeinsamen TAUREON-V4-MIDI-Bibliotheksstrategie nicht mehr handlungsleitend.
Diese XD-Phase 0 ist keine Wiedereröffnung der abgeschlossenen TAUREON-Stage 0.

## Ergebnis und notwendige Korrektur

Der minilogue-xd-Librarian selbst hat noch keinen C++-Neustart.
TAUREON V4 besitzt eine nutzbare C++20-/Qt-6-Basis, ist aber ein eigenständiges
Produkt mit akzeptierter WMS-plus-WinMM-Architektur. Die Aussage im Gespräch,
diese Doppelarchitektur sei bereits für TAUREON verworfen, war zu weitgehend.
Der Benutzer fordert für den neuen XD Librarian eine durchgängige C++-Anwendung
ohne Python oder externe Hilfsprozesse sowie einen möglichst einfachen MIDI-Unterbau.

Empfehlung zur Gegenprüfung: ein zusätzliches, fokussiertes XD-Produktziel mit
genau einem produktiven WinMM-Transport; vorhandene TAUREON-Module wiederverwenden.
Die TAUREON-Standardausgabe und ihre laufende Stage 5 behalten ihre Verträge.
Die Entscheidung über das konkrete Produktziel ist eine Vorlage, keine bereits
implementierte oder durch Claude bestätigte Architekturänderung.

## Verifizierter Bestand

| Quelle | Stand | Bedeutung |
|---|---|---|
| minilogue_xd_librarian | main, 7bd3ce050013a80a679a495a7d23cc75da43bf5c | Python-Referenz; vor diesem Dokumentpaket sauber |
| TAUREON V4 main, lokal/Remote | d04e99c08d9d7f4134b7040a3e8abba9654045eb | getrennte, gepinnte Vergleichsbasis |
| TAUREON V4 aktueller Branch | codex/stage5-block-b-windows-evidence, 7dc09c9bd241cb773b25b41402d1aea892926d3f | Remote-Branch stimmt mit lokalem HEAD überein |
| TAUREON Arbeitsbaum | 6 geänderte versionierte Dateien; 3514 unversionierte Dateien | letzteres unter .work/stage5-p1-build; nicht als akzeptierter Quellstand übernehmen |

Die sechs Dateihashes, Größen und Remote-Referenzen stehen in BASELINE.json.
TAUREON_LOCAL_CHANGES.patch konserviert den versionierten Diff relativ zum
genannten HEAD. Das ist eine Sicherung der Git-Inhaltsänderungen, keine vollständige
Arbeitsbaum-/Binär-/Index-/Zeilenendensicherung. .work bleibt am Ursprungsort.
Der Patch ist Referenzmaterial und darf nicht ungeprüft angewendet werden.

TAUREONs PROJECT_STATE.md meldet Stage 5 HOLD/ACTIVE:
native 150-/200-Prozent-DPI-Prüfung und physische Hardwarevalidierung sind offen.
Frühere Testberichte bleiben historische Evidenz für ihren jeweiligen Commit.
In dieser Phase wurden weder Builds noch Tests noch MIDI-Verkehr ausgeführt.

## Was aus C++ wiederverwendbar ist

| Bereich in TAUREON | Befund und Grenze |
|---|---|
| src/transports/winmm | eigener nativer Transport, MIDIHDR-Ownership, Callback-/Worker-Grenze und zugehörige Tests |
| src/core/sysex und src/core/transfer | generische Framing-, Integritäts-, Capture- und Transferfunktionen |
| src/app/ConnectionWorker und GUI-Brücke | Anwendungs-/Thread-Grenzen; im neuen Produktziel erneut prüfen |
| src/app/Librarian und src/gui/LibrarianPanel | begrenztes Modell-/View-Gerüst; kein vollständiger Patch-Editor |
| src/profiles | datenbasierte Erkennung und Fähigkeiten; kein minilogue-xd-Protokollmodul |
| src/transports/wms/CMakeLists.txt | TAUREON_ENABLE_WMS_TRANSPORT kann explizit OFF sein |
| src/core/midi/MidiTypes.hpp | WMS-Voreinstellungen in gemeinsamen Typen: XD muss WinMM explizit setzen |
| src/CMakeLists.txt | Fake-Transport liegt aktuell im allgemeinen Core-Target; Test-only-Zuordnung im XD-Build prüfen |

Keine produktive C++-Implementierung der minilogue-xd-Dateiformate oder
Geräte-Transaktionen gefunden. Minilogue-Beispiele im HTML-Mockup sind keine
implementierte Geräteunterstützung.

## Offene lokale TAUREON-Änderungen

Der gespeicherte Diff enthält:

- zusätzlichen Nachweis des MTA-Apartments im WMS-Worker und die ole32-Verknüpfung;
- explizite Prüfung erfolgreicher close-Aufrufe und des Endzustands;
- einen Empfangsprobeverkehr, der tatsächlichen Empfang vor dem Schließen belegt;
- getrennte WMS-/WinMM-Testprozesse;
- Reduktion der Standard-Produkt-Host-Zyklen von 20 auf 5;
- Anwendung des Handle-Wachstumskriteriums erst ab 100 Zyklen;
- geänderte CTest-Timeouts.

Die zusätzlichen Nachweise und die schwächere Standardabdeckung müssen separat
bewertet werden. Insbesondere kann ein kurzer Lauf ohne aktives Wachstumskriterium
keinen bestandenen Ressourcen-Stresstest ersetzen. Hier wird weder ein Fehler
noch eine Freigabe dieses Diffs behauptet; aktuelle Ausführungsevidenz fehlt.
Die XD-Wiederverwendung beginnt von einem benannten Commit, nicht vom schmutzigen
Arbeitsbaum. Benötigte Änderungen wären einzeln zu prüfen und zu übernehmen.

## Protokoll- und Dateireferenzen

Im Python-Projekt liegen die eigentlichen Formatimplementierungen unter
xd_formats/; devices/korg_minilogue_xd/formats.py enthält nur Erweiterungsnamen.

Bekannte Risiken als Anforderungen übernehmen, nicht mechanisch portieren:

- app/main_window.py, apply_slot_program_receive: expected_slot kann die
  Slotadresse der tatsächlichen Antwort verdrängen. Test: verspätete Antwort
  auf Slot A darf nach Timeout nicht Slot B überschreiben.
- save_bank_to_path erzeugt XDLibrary nur aus programs. C++ muss sämtliche
  unterstützten Zusatzdaten und unbekannten Archivmitglieder erhalten.
- ACK-Verwaltung poppt eine Liste; das ersetzt keinen belegten
  Anfrage-/Antwortautomaten.
- docs/references/logue_sdk_notes.md beschreibt noch deaktivierte Writes,
  während spätere README/Handoff und Code logue-cli load/clear enthalten.
  Dokumente sind hier nicht deckungsgleich.
- Der Marker IMPORTANT_NATIVE_CAPTURE_SUCCESS_2026-06-02.md nennt zwei Dumps
  mit 593228 Bytes und 513 Frames. Die dort genannten Dateien wurden bei der
  heutigen gezielten Suche am angegebenen D:-Wurzelpfad nicht gefunden.
  Historische Angaben sind keine heute geprüften Testfixtures.
- tests/test_xd_formats.py überspringt fixtureabhängige Tests, falls libraries/
  fehlt. Ein grüner Gesamtlauf ersetzt den Fixture-Nachweis nicht.

Bei ZIP-Formaten ist ein unverändertes Programmpayload bytegenau zu erhalten.
Ein neu komprimiertes ZIP muss nicht als komplette Datei denselben Hash besitzen.
Für unveränderte .syx-Dateien wird dagegen bytegleicher Roundtrip erwartet.
Checksummen werden nur für konkret belegte Nachrichten/Container implementiert;
es wird keine universelle Korg-Checksumme angenommen.

## Produkt- und Evidenzgrenzen

- C++-GUI, MIDI, Dateiverarbeitung und Tests ohne Python-Laufzeit oder
  ausgelagerte Capture-/logue-cli-Prozesse.
- CMake, Compiler und C++-/Qt-Bibliotheken sind Build-Werkzeuge bzw. native
  Abhängigkeiten. Eine einzelne EXE ohne DLLs wurde nicht festgelegt.
- Windows 10 22H2 x64 und Windows 11 x64 sind vorgeschlagene Testziele;
  Anwendungskompatibilität ist von Microsofts OS-Supportstatus zu trennen.
- WinMM-only bedeutet unter aktuellem Windows 11 weiterhin Abhängigkeit von
  dessen WinMM-Kompatibilität und funktionierendem MIDI-Dienst.
- Klasse-konformes USB und insbesondere große SysEx-Transfers müssen unter
  älteren Windows-Ständen getrennt geprüft werden. Kein pauschales
  Treiberfreiheits- oder Alle-Windows-Versprechen.
- User-Unit-Dateianalyse ist von Geräteinstallation/-Löschung zu trennen.
  Ein nativer Ersatz für logue-cli ist noch nicht belegt und bleibt ein eigener
  Machbarkeitsblock; die vollständige Funktionsgleichheit ist bis dahin offen.
- TAUREONs Provenance-Tabelle enthält offene Distributions-/Qt-Lizenzentscheidungen.
  Fremdcode und Gerätedumps werden nicht allein wegen lokaler Verfügbarkeit verteilt.

## Nächste konkrete Lieferung

Siehe ARCHITECTURE_PROPOSAL.md und CLAUDE_REVIEW.md.
Zuerst ein unabhängiges Review dieser Vorlage; danach ein isolierter C++-Build-Spike
mit deaktiviertem direkten WMS-Transport, vorhandenen Softwaretests und
Abhängigkeitsprüfung. Erst anschließend das XD-Produktziel und die Geräteportierung.

## Prüfung dieser Lieferung

- Alle sechs gespeicherten SHA-256-Werte stimmen nach Erstellung des Pakets
  weiterhin mit den TAUREON-Quelldateien überein.
- git apply --reverse --check --ignore-space-change für den gesicherten Patch
  gegen den vorhandenen TAUREON-Arbeitsbaum: Exit 0. Es wurde kein Patch angewendet.
- BASELINE.json lässt sich parsen; Markdown-/JSON-Dateien ohne nachlaufende Leerzeichen.
- Im Librarian ist ausschließlich docs/planning/ neu; TAUREONs Status ist unverändert.
- Kein Build, Funktionstest, Commit, Push oder Systemeingriff Bestandteil dieser Lieferung.
- Kein Claude-/Anthropic-Connector in den verfügbaren Werkzeugen gefunden;
  die unabhängige Gegenprüfung ist vorbereitet, aber weiterhin ausstehend.
