from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from .models import Cue, LogCallback, PipelineOptions, ProgressCallback
from .platform.capabilities import resolve_device
from .utils import check_cancel, extract_audio, probe_duration


def _resolve_device(requested: str) -> str:
    return resolve_device(requested)


def _resolve_compute_type(requested: str, device: str) -> str:
    if requested != "auto":
        return requested
    return "float16" if device == "cuda" else "int8"


def _diarize(
    audio_path: Path,
    options: PipelineOptions,
    *,
    log: LogCallback,
    cancel_event: Optional[threading.Event],
) -> list[tuple[float, float, str]]:
    check_cancel(cancel_event)
    if not options.hf_token.strip():
        raise RuntimeError(
            "Für die Sprechererkennung fehlt der Hugging-Face-Token. "
            "Akzeptiere außerdem die Bedingungen des pyannote-Modells."
        )
    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise RuntimeError(
            "pyannote.audio fehlt. Führe INSTALLIEREN.cmd erneut aus."
        ) from exc

    model_id = "pyannote/speaker-diarization-community-1"
    log(f"Lade Sprechererkennung: {model_id}")
    try:
        pipeline = Pipeline.from_pretrained(model_id, token=options.hf_token.strip())
    except TypeError:
        pipeline = Pipeline.from_pretrained(
            model_id,
            use_auth_token=options.hf_token.strip(),
        )

    device = _resolve_device(options.device)
    if device == "cuda":
        try:
            import torch
            pipeline.to(torch.device("cuda"))
        except Exception as exc:
            log(f"CUDA für pyannote nicht nutzbar, verwende Standardgerät: {exc}")

    check_cancel(cancel_event)
    log("Ermittle Sprecherwechsel …")
    output = pipeline(str(audio_path))
    annotation = getattr(output, "speaker_diarization", output)

    turns: list[tuple[float, float, str]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        turns.append((float(turn.start), float(turn.end), str(speaker)))
    if not turns:
        log("Keine Sprechersegmente erkannt; verwende SPEAKER_00.")
    else:
        log(f"{len(turns)} Sprechersegmente erkannt.")
    return turns


def _assign_speaker(
    start: float,
    end: float,
    turns: list[tuple[float, float, str]],
) -> str:
    if not turns:
        return "SPEAKER_00"

    best_speaker = "SPEAKER_00"
    best_overlap = 0.0
    for turn_start, turn_end, speaker in turns:
        overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker

    if best_overlap > 0:
        return best_speaker

    midpoint = (start + end) / 2.0
    nearest = min(
        turns,
        key=lambda item: abs(((item[0] + item[1]) / 2.0) - midpoint),
    )
    return nearest[2]


def transcribe_media(
    source: Path,
    work_dir: Path,
    options: PipelineOptions,
    *,
    log: LogCallback,
    progress: ProgressCallback,
    cancel_event: Optional[threading.Event] = None,
) -> tuple[list[Cue], str, Path]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper fehlt. Führe INSTALLIEREN.cmd aus."
        ) from exc

    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / "audio_16khz_mono.wav"
    progress(0.02, "Extrahiere Tonspur")
    extract_audio(source, audio_path, log=log, cancel_event=cancel_event)
    duration = max(probe_duration(audio_path, cancel_event=cancel_event), 0.1)

    device = _resolve_device(options.device)
    if options.device.lower() == "cuda" and device != "cuda":
        log("CUDA wurde angefordert, ist aber nicht verfügbar; verwende CPU.")
    compute_type = _resolve_compute_type(options.compute_type, device)
    log(
        f"Lade Whisper-Modell '{options.whisper_model}' "
        f"auf {device} ({compute_type}) …"
    )
    model = WhisperModel(
        options.whisper_model,
        device=device,
        compute_type=compute_type,
    )

    language = (
        None
        if options.whisper_language.lower() == "auto"
        else options.whisper_language.lower()
    )
    progress(0.08, "Transkribiere")
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=max(1, options.beam_size),
        vad_filter=options.vad_filter,
        condition_on_previous_text=True,
    )

    raw_segments: list[tuple[float, float, str]] = []
    for segment in segments:
        check_cancel(cancel_event)
        text = str(segment.text or "").strip()
        if not text:
            continue
        start = max(float(segment.start), 0.0)
        end = max(float(segment.end), start + 0.1)
        raw_segments.append((start, end, text))
        progress(
            min(0.72, 0.08 + 0.64 * min(end / duration, 1.0)),
            f"Transkribiere bei {end / 60:.1f} min",
        )

    detected_language = str(getattr(info, "language", "") or language or "unknown")
    probability = getattr(info, "language_probability", None)
    if probability is not None:
        log(
            f"Erkannte Sprache: {detected_language} "
            f"({float(probability) * 100:.1f} %)"
        )
    else:
        log(f"Erkannte Sprache: {detected_language}")

    turns: list[tuple[float, float, str]] = []
    if options.diarization:
        progress(0.74, "Ermittle Sprecher")
        turns = _diarize(
            audio_path,
            options,
            log=log,
            cancel_event=cancel_event,
        )

    cues = [
        Cue(
            index=index,
            start=start,
            end=end,
            text=text,
            speaker=_assign_speaker(start, end, turns),
        )
        for index, (start, end, text) in enumerate(raw_segments, 1)
    ]
    if not cues:
        raise RuntimeError("Whisper hat keine gesprochenen Inhalte erkannt.")

    progress(0.82, f"{len(cues)} Untertitelblöcke erzeugt")
    return cues, detected_language, audio_path
