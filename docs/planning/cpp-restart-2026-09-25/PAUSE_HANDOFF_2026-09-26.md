# minilogue xd Librarian – Pausen- und Übergabestand

Datum: 2026-09-26

## Entscheidung

Die Planung eines eigenständigen MIDI-Unterbaus für den C++-Neustart ist
gestoppt. TAUREON Synth Tool V4 besitzt bereits den deutlich weiter entwickelten
C++20-Unterbau für MIDI, WinMM, SysEx, Transfer, Routing, Lifetime und Tests.

Der XD-Librarian soll keine zweite, kopierte oder konkurrierende MIDI-Engine
erhalten. Zuerst wird im TAUREON-V4-Projekt geprüft, wie dessen generische
Komponenten zu einer einzigen versionierten, produktunabhängigen Bibliothek
abgegrenzt werden können. Kleinere Synth-Projekte sollen diese Bibliothek später
verwenden; gerätespezifische Protokolle und Formate bleiben in den jeweiligen
Produkten.

## Verifizierter XD-Stand

- Repository: `sscheidl/minilogue_xd_librarian`
- Branch: `main`
- HEAD: `7bd3ce050013a80a679a495a7d23cc75da43bf5c`
- Der produktive Stand ist weiterhin Python/Tkinter.
- SysEx-Senden verwendet Mido/RtMidi; nativer Empfang verwendet einen separaten
  WinMM-Hilfsprozess aus der älteren TAUREON-Linie; User Units verwenden zudem
  `logue-cli`.
- Es wurde noch keine produktive C++-Neufassung implementiert.
- Die Dateien unter `docs/planning/cpp-restart-2026-09-25/` sind ausschließlich
  Bestandsaufnahme, Sicherung und Planung und derzeit unversioniert.

## Wiederverwendungskandidaten aus TAUREON V4

- generische MIDI-Typen, Fehler und Transportzustände;
- `IMidiTransport` und Fake-Transport;
- nativer WinMM-Transport einschließlich `MIDIHDR`-Ownership;
- SysEx-Framing, Capture und Datenverlustmarkierung;
- Transfer-Engine mit Pacing, Abbruch und Fortschritt;
- Route-Persistenz und konservative Auflösung;
- zugehörige Unit- und lokale Integrationstests.

Nicht ungeprüft zu übernehmen sind TAUREON-Anwendungsdienste, GUI, Profile,
Settings und der optionale WMS-Transport. Der gemeinsame CMake-/Paketvertrag ist
noch nicht definiert. TAUREON V4 besitzt außerdem noch keine ausgewählte
Root-Lizenz; dies ist vor projektübergreifender Distribution zu klären.

## Weitere Kandidaten

- Kawai K5000S/R: bereits C++20/Qt, MIDI erst für eine spätere Version geplant;
- Roland D-50: Python, Codec/Bankeditor vorhanden, MIDI noch offen;
- Dreadbox Artemis: Python/Mido/RtMidi mit wenig automatisierter Absicherung;
- Waldorf Protein: frühes Python-/SysEx-Gerüst;
- Typhon: Python/Mido, vor allem CC- und Realtime-Verkehr.

PreenFM+ bleibt wegen JUCE, VST3 und Hostintegration ein Sonderfall und soll
nicht pauschal auf den WinMM-Unterbau umgestellt werden.

## Wiederaufnahmebedingung

Die XD-C++-Arbeit wird erst fortgesetzt, wenn im TAUREON-V4-Kontext folgende
Punkte geklärt sind:

1. tatsächlicher lokaler und Remote-Projektstand einschließlich mobiler/Claude-
   Entwicklung;
2. letzte verbindliche Claude-Anweisung und offener nächster Arbeitsschritt;
3. Umgang mit den bestehenden lokalen TAUREON-Änderungen;
4. reale Windows-, MIDI- und SysEx-Hardwaretests;
5. belastbare Grenze und Versionierung der gemeinsamen MIDI-Bibliothek.

Der bisherige `CLAUDE_REVIEW.md` ist damit vorläufig überholt und darf nicht als
aktueller Prüfauftrag verwendet werden. Ein späterer Review muss die gemeinsame
Bibliotheksstrategie statt eines XD-spezifischen Engine-Ansatzes prüfen.
