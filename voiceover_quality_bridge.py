"""Kompatibilität für ältere Einbauvarianten des Qualitätspatches."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from studio.models import PipelineOptions
from studio.quality import review_translation
from studio.subtitles import parse_srt
from studio.translation_quality import CorrectionError, CorrectionResult


def raw_translation_path(translated_srt: str | Path) -> Path:
    path = Path(translated_srt)
    stem = path.stem
    if stem.casefold().endswith("_de"):
        return path.with_name(stem[:-3] + "_de_roh" + path.suffix)
    return path.with_name(stem + "_roh" + path.suffix)


def finalize_translation_before_voiceover(
    *,
    source_srt: str | Path,
    translated_srt: str | Path,
    model: str = "qwen3:8b",
    ollama_url: str = "http://127.0.0.1:11434",
    log: Callable[[str], None] | None = None,
    overwrite_raw: bool = False,
) -> Path:
    """Ältere Aufrufe auf die integrierte Prüfung weiterleiten."""
    final = Path(translated_srt).expanduser().resolve()
    raw = raw_translation_path(final)
    if not final.exists():
        raise FileNotFoundError(final)
    if overwrite_raw or not raw.exists():
        shutil.copy2(final, raw)
    options = PipelineOptions(
        quality_check=True,
        quality_model=model,
        ollama_url=ollama_url,
        quality_fail_mode="stop",
    )
    review_translation(
        Path(source_srt),
        raw,
        final,
        options,
        log=log or (lambda _message: None),
        progress=lambda _value, _message: None,
    )
    # Sicherstellen, dass die Ausgabe auch vom Studio-Parser gelesen werden kann.
    parse_srt(final)
    return final


__all__ = [
    "review_translation",
    "finalize_translation_before_voiceover",
    "raw_translation_path",
    "CorrectionError",
    "CorrectionResult",
]
