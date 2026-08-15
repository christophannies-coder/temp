# Integrierte KI-Sprachprüfung

> **Wichtig:** In der kompletten Source-Version ist die KI-Sprachprüfung bereits eingebaut.
> Dort nicht erneut den Patch auf denselben Ordner installieren. Für eine neue
> Installation direkt `INSTALLIEREN.cmd` und anschließend
> `STARTEN_MIT_KONSOLE.cmd` verwenden. Der Installer ab Version 2 erkennt diesen
> Fall automatisch und überspringt Selbstkopien.

Die KI-Sprachprüfung ist fest zwischen Übersetzung und Voiceover eingebaut.

## Ablauf

```text
Transkription
→ Rohübersetzung
→ KI-Prüfung mit Original-Kontext
→ Voiceover
→ Videoausgabe
```

Bei fremdsprachigen Untertiteln erzeugt das Studio:

```text
*_de_roh.srt
*_de.srt
*_de.quality_report.json
translation_quality_cache.json
```

`*_de_roh.srt` ist die unveränderte maschinelle Übersetzung. Das Voiceover
verwendet im normalen Ablauf ausschließlich `*_de.srt`.

## Geprüfte Punkte

- sprachliche Richtigkeit und Grammatik
- Bedeutung gegenüber dem Original
- natürliche deutsche Ausdrucksweise
- Verständlichkeit für gesprochenes Voiceover
- Sätze und Bezüge über mehrere SRT-Blöcke
- Pronomen, Zeitformen, Eigennamen und Fachbegriffe
- Schutz von Zeitstempeln, Sprecherlabels sowie Musik-/Geräuschblöcken

## Einstellungen in der GUI

Im Reiter **Übersetzung** befinden sich die neuen Optionen:

- `Übersetzung vor der Vertonung durch KI sprachlich prüfen`
- separates Ollama-Modell für die Sprachprüfung
- Blöcke und maximale Zeichen pro Prüfpaket
- Kontextblöcke davor und danach
- Verhalten bei einem Prüfungsfehler

Standardmäßig wird bei einem Fehler gestoppt. Dadurch wird nicht unbemerkt eine
ungeprüfte Rohübersetzung vertont. Optional kann bewusst auf die Rohübersetzung
zurückgefallen werden.

## Voraussetzung

Ollama muss laufen und das in der GUI gewählte Modell muss installiert sein,
zum Beispiel:

```powershell
ollama pull qwen3:8b
ollama list
```

Die Übersetzung kann weiterhin über Google erfolgen. Nur die anschließende
Qualitätsprüfung verwendet Ollama.

## Installation des Patchs

1. Patch-ZIP entpacken.
2. `KI_PATCH_INSTALLIEREN.cmd` starten.
3. Den vorhandenen Studio-Ordner auswählen oder als Parameter angeben.
4. Das Installationsprogramm sichert ersetzte Dateien im Unterordner
   `_backup_ki_sprachpruefung_<Datum>`.

Manuell per PowerShell:

```powershell
py .\KI_PATCH_INSTALLIEREN.py "C:\Pfad\zum\Transkript_Voiceover_Studio"
```

## Tests

```powershell
py .\TEST_QUALITAETSKORREKTUR.py
```

Der Test benötigt kein laufendes Ollama und kontrolliert SRT-Struktur,
blockübergreifende Korrektur und den Schutz von Musikblöcken.
