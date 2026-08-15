# Produktisierung – Phase 1

## Bestandsaufnahme (15. August 2026)

Die bestehende Anwendung trennt GUI und Pipeline bereits sinnvoll. Die Pipeline
orchestriert Transkription (`faster-whisper`), Übersetzung (Google/Ollama),
KI-Sprachprüfung (Ollama), Voiceover (Edge-TTS) und Muxing (FFmpeg). Die
Komponenten bleiben in dieser Phase unverändert, damit sich das bestehende
Arbeitsverhalten nicht ändert.

## Neu vorbereitete Struktur

`studio/platform/` enthält zentrale, nebenwirkungsfreie Grundlagen:

- `config.py`: Laden, Zusammenführen und Validieren von Konfigurationen.
- `capabilities.py`: sichere CPU/CUDA/FFmpeg-Erkennung mit CPU-Fallback.
- `models.py`: Modellregistrierung und hardwaretaugliche Empfehlungen, ohne
  Gewichte herunterzuladen.
- `ffmpeg.py`: einheitliche FFmpeg-/FFprobe-Prüfung mit konkreter Hilfestellung.
- `errors.py`: strukturierte, UI-taugliche Fehlermeldungen.

`studio/providers/` definiert einen kleinen Provider-Vertrag für künftige
Adapter für Whisper, Übersetzung, Quality und TTS. Er verändert noch keine
Produktionspipeline.

## Validierung

Die Grundlagen werden mit `python -m unittest tests/test_platform.py` geprüft.
Die Tests benötigen weder Modelle, Netzwerk, CUDA noch FFmpeg.

## Nächste Schritte

1. Erledigt: Die GUI lädt und speichert nun über `ApplicationConfig`; unbekannte
   Einstellungen bleiben erhalten und fehlerhaftes JSON wird nicht überschrieben.
2. Erledigt: Whisper läuft hinter `FasterWhisperProvider`; eine angeforderte,
   aber nicht verfügbare CUDA-GPU fällt sicher auf CPU zurück.
3. Danach Edge-TTS sowie die Übersetzungs- und Quality-Backends einzeln
   adaptieren, jeweils mit Rückfall- und Fehlermeldungstests.
4. Vor einem Verkauf Installationspaket, Lizenzprüfung, Datenschutz- und
   Drittanbieter-/Modell-Lizenzprüfung als separate Produktphase planen.
