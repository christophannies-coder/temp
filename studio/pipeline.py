from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Optional

from .models import (
    PipelineOptions,
    PipelineResult,
    LogCallback,
    ProgressCallback,
)
from .mux import MEDIA_EXTENSIONS, find_matching_media, mux_voiceover
from .quality import review_translation
from .subtitles import parse_srt, write_srt
from .providers import EdgeTTSProvider, FasterWhisperProvider
from .translation import (
    detect_text_language,
    is_german,
    normalize_language,
    translate_cues,
)
from .utils import check_cancel


AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
}
SUPPORTED_INPUTS = MEDIA_EXTENSIONS | AUDIO_EXTENSIONS | {".srt"}


def classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".srt":
        return "SRT"
    if suffix in MEDIA_EXTENSIONS:
        return "Video"
    if suffix in AUDIO_EXTENSIONS:
        return "Audio"
    return "Unbekannt"


def _output_dir(source: Path, options: PipelineOptions) -> Path:
    if options.output_root.strip():
        return Path(options.output_root).expanduser().resolve() / source.stem
    return source.parent / f"{source.stem}_studio"


def process(
    source: Path,
    companion_media: Optional[Path],
    options: PipelineOptions,
    *,
    mode: str,
    log: LogCallback,
    progress: ProgressCallback,
    cancel_event: Optional[threading.Event] = None,
) -> PipelineResult:
    source = source.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.suffix.lower() not in SUPPORTED_INPUTS:
        raise RuntimeError(f"Nicht unterstützte Eingabe: {source.suffix}")

    output_dir = _output_dir(source, options)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "_arbeit"
    work_dir.mkdir(exist_ok=True)
    result = PipelineResult(source=source, output_dir=output_dir)

    is_srt_input = source.suffix.lower() == ".srt"
    is_media_input = source.suffix.lower() in (MEDIA_EXTENSIONS | AUDIO_EXTENSIONS)
    current_srt: Optional[Path] = None
    current_cues = None
    detected_language = ""

    do_transcribe = mode in {"full", "transcribe"} and options.do_transcribe
    do_translate = mode in {"full", "translate"} and options.do_translate
    do_voiceover = mode in {"full", "voiceover"} and options.do_voiceover
    do_mux = mode in {"full", "mux"} and options.do_mux

    # Direkter Einstieg mit einer SRT
    if is_srt_input:
        current_srt = source
        current_cues = parse_srt(source)
        forced = normalize_language(options.srt_language)
        detected_language = (
            detect_text_language(current_cues)
            if forced in {"", "auto"}
            else forced
        )
        result.detected_language = detected_language
        log(f"SRT-Einstieg | Sprache: {detected_language}")

    # Einstieg mit Video/Audio
    elif is_media_input:
        if not do_transcribe:
            raise RuntimeError(
                "Bei einer Video-/Audiodatei muss zuerst transkribiert werden. "
                "Aktiviere 'Transkription' oder füge stattdessen eine SRT hinzu."
            )
        log("Stufe 1/5: Transkription")
        current_cues, detected_language, audio_path = FasterWhisperProvider().transcribe(
            source,
            work_dir,
            options,
            log=log,
            progress=progress,
            cancel_event=cancel_event,
        )
        result.detected_language = detected_language
        current_srt = output_dir / f"{source.stem}_transcript.srt"
        write_srt(current_cues, current_srt, include_speakers=True)
        result.transcript_srt = current_srt
        log(f"Transkript gespeichert: {current_srt}")

        if mode == "transcribe":
            if not options.keep_temp:
                audio_path.unlink(missing_ok=True)
            progress(1.0, "Transkription fertig")
            return result

    check_cancel(cancel_event)
    assert current_srt is not None
    assert current_cues is not None

    # Direkter Einstieg auf Übersetzungsebene
    if mode == "translate" and not is_srt_input:
        raise RuntimeError("'Nur Übersetzung' erwartet eine SRT-Datei als Eingabe.")

    if do_translate and not is_german(detected_language):
        # Für den KI-Abgleich wird das Original normalisiert geschrieben. Dadurch
        # stimmen Reihenfolge, Nummerierung und Zeitstempel garantiert mit der
        # späteren Rohübersetzung überein, auch wenn die Eingabe-SRT ungewöhnlich
        # formatiert oder nicht fortlaufend nummeriert war.
        source_srt_for_quality = work_dir / "quality_source_normalized.srt"
        write_srt(current_cues, source_srt_for_quality, include_speakers=True)

        log("Stufe 2/5: Übersetzung nach Deutsch")
        current_cues = translate_cues(
            current_cues,
            detected_language,
            output_dir / "translation_cache.json",
            options,
            log=log,
            progress=progress,
            cancel_event=cancel_event,
        )

        final_srt = output_dir / f"{source.stem}_de.srt"
        if options.quality_check:
            raw_srt = output_dir / f"{source.stem}_de_roh.srt"
            write_srt(current_cues, raw_srt, include_speakers=True)
            result.raw_german_srt = raw_srt
            log(f"Deutsche Rohübersetzung gespeichert: {raw_srt}")

            check_cancel(cancel_event)
            log("Stufe 3/5: KI-Sprachprüfung")
            try:
                quality_result = review_translation(
                    source_srt_for_quality,
                    raw_srt,
                    final_srt,
                    options,
                    log=log,
                    progress=progress,
                    cancel_event=cancel_event,
                )
            finally:
                if not options.keep_temp:
                    source_srt_for_quality.unlink(missing_ok=True)
            if quality_result is not None:
                result.quality_report = Path(quality_result.report)
                result.extra["quality_changed_blocks"] = quality_result.changed_blocks
                result.extra["quality_blocks"] = quality_result.blocks
            current_cues = parse_srt(final_srt)
            current_srt = final_srt
            log(f"KI-geprüfte deutsche SRT gespeichert: {final_srt}")
        else:
            write_srt(current_cues, final_srt, include_speakers=True)
            current_srt = final_srt
            if not options.keep_temp:
                source_srt_for_quality.unlink(missing_ok=True)
            log(f"Deutsche SRT gespeichert: {final_srt}")

        result.german_srt = current_srt
        detected_language = "de"
    elif is_german(detected_language):
        log("Übersetzung übersprungen: Untertitel sind bereits deutsch.")
        result.german_srt = current_srt
    elif do_voiceover:
        raise RuntimeError(
            f"Die Untertitel sind offenbar '{detected_language}', aber die "
            "Übersetzung ist deaktiviert. Aktiviere die Übersetzung oder setze "
            "die SRT-Sprache ausdrücklich auf Deutsch."
        )

    if mode == "translate":
        progress(1.0, "Übersetzung und Sprachprüfung fertig")
        return result

    check_cancel(cancel_event)

    # Direkter Einstieg auf Voiceover-Ebene
    if do_voiceover:
        if not is_german(detected_language):
            raise RuntimeError("Voiceover benötigt eine deutsche SRT.")
        log("Stufe 4/5: Voiceover")
        voiceover = output_dir / f"{source.stem}_voiceover.mp3"
        voiceover, voices = EdgeTTSProvider().build_voiceover(
            current_cues,
            voiceover,
            work_dir,
            options,
            log=log,
            progress=progress,
            cancel_event=cancel_event,
        )
        result.voiceover_mp3 = voiceover
        result.extra["voices"] = voices
        log(f"Voiceover gespeichert: {voiceover}")

    if mode == "voiceover":
        progress(1.0, "Voiceover fertig")
        return result

    check_cancel(cancel_event)

    if do_mux:
        if result.voiceover_mp3 is None:
            existing = output_dir / f"{source.stem}_voiceover.mp3"
            if existing.exists():
                result.voiceover_mp3 = existing
            else:
                raise RuntimeError(
                    "Für die Videoausgabe wurde kein Voiceover erzeugt oder gefunden."
                )

        media = companion_media
        if is_media_input and source.suffix.lower() in MEDIA_EXTENSIONS:
            media = source
        elif media is None and is_srt_input:
            media = find_matching_media(source)

        if media is None or not Path(media).exists():
            raise RuntimeError(
                "Für die Videoausgabe fehlt ein MP4/MKV. Ordne der SRT über "
                "'Begleitvideo zuordnen' ein Video zu."
            )

        log("Stufe 5/5: Voiceover mit Video verbinden")
        muxed = output_dir / f"{Path(media).stem}_de_voiceover.mkv"
        result.muxed_media = mux_voiceover(
            Path(media),
            result.voiceover_mp3,
            muxed,
            options,
            log=log,
            cancel_event=cancel_event,
        )
        log(f"Video gespeichert: {muxed}")

    if not options.keep_temp:
        audio = work_dir / "audio_16khz_mono.wav"
        audio.unlink(missing_ok=True)
        try:
            if not any(work_dir.iterdir()):
                work_dir.rmdir()
        except OSError:
            pass

    progress(1.0, "Fertig")
    return result
