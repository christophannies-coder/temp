from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Optional

from .models import LogCallback, PipelineOptions, ProgressCallback
from .translation_quality import CorrectionError, CorrectionResult, correct_translation_srt
from .utils import check_cancel


def review_translation(
    source_srt: Path,
    raw_translation_srt: Path,
    final_srt: Path,
    options: PipelineOptions,
    *,
    log: LogCallback,
    progress: ProgressCallback,
    cancel_event: Optional[threading.Event] = None,
) -> CorrectionResult | None:
    """Prüft eine deutsche Rohübersetzung mit Kontext vor dem Voiceover.

    Bei ``quality_fail_mode == 'use_raw'`` wird nach einem Fehler die
    Rohübersetzung bewusst als finale Datei übernommen. Standardmäßig wird der
    Ablauf gestoppt, damit niemals unbemerkt ungeprüfter Text vertont wird.
    """
    check_cancel(cancel_event)
    source_srt = Path(source_srt).resolve()
    raw_translation_srt = Path(raw_translation_srt).resolve()
    final_srt = Path(final_srt).resolve()

    if not source_srt.exists():
        raise FileNotFoundError(source_srt)
    if not raw_translation_srt.exists():
        raise FileNotFoundError(raw_translation_srt)

    log(
        "KI-Sprachprüfung: prüfe Bedeutung, Grammatik, Ausdruck, "
        "Verständlichkeit und Satzbezüge über mehrere Untertitelblöcke."
    )

    def quality_progress(message: str) -> None:
        check_cancel(cancel_event)
        log(message)
        progress(0.91, message)

    try:
        result = correct_translation_srt(
            source_srt,
            raw_translation_srt,
            final_srt,
            model=options.quality_model.strip() or options.ollama_model.strip(),
            ollama_url=options.ollama_url.strip(),
            batch_size=max(1, int(options.quality_batch_size)),
            max_chars=max(1000, int(options.quality_max_chars)),
            context_before=max(0, int(options.quality_context_before)),
            context_after=max(0, int(options.quality_context_after)),
            cache_path=final_srt.parent / "translation_quality_cache.json",
            report_path=final_srt.with_suffix(".quality_report.json"),
            progress=quality_progress,
        )
    except Exception as exc:
        final_srt.unlink(missing_ok=True)
        if options.quality_fail_mode == "use_raw":
            shutil.copy2(raw_translation_srt, final_srt)
            log(
                "WARNUNG: KI-Sprachprüfung fehlgeschlagen. Gemäß Einstellung "
                "wird die Rohübersetzung verwendet. Fehler: " + str(exc)
            )
            return None
        raise CorrectionError(
            "Die KI-Sprachprüfung ist fehlgeschlagen. Das Voiceover wurde "
            "nicht mit einer ungeprüften Übersetzung gestartet. "
            f"Rohübersetzung: {raw_translation_srt}. Fehler: {exc}"
        ) from exc

    check_cancel(cancel_event)
    log(
        f"KI-Sprachprüfung abgeschlossen: "
        f"{result.changed_blocks}/{result.blocks} Blöcke überarbeitet."
    )
    log(f"Prüfbericht: {result.report}")
    return result
