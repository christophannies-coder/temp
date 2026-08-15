from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from .models import Cue, LogCallback, PipelineOptions, ProgressCallback
from .utils import check_cancel


GERMAN_CODES = {"de", "de-de", "german", "deutsch"}


def normalize_language(value: str) -> str:
    return (value or "").strip().lower().replace("_", "-")


def detect_text_language(cues: list[Cue]) -> str:
    sample = " ".join(cue.text for cue in cues[:120])[:12000].strip()
    if not sample:
        return "unknown"
    try:
        from langdetect import detect
        return normalize_language(detect(sample))
    except Exception:
        return "unknown"


def is_german(language: str) -> bool:
    return normalize_language(language) in GERMAN_CODES


def _clean_translation(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:text|markdown)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.I | re.S)
    value = re.sub(
        r"^(?:übersetzung|uebersetzung|translation|deutsch|german)\s*:\s*",
        "",
        value,
        count=1,
        flags=re.I,
    ).strip()
    if not value:
        raise RuntimeError("Die Übersetzung ist leer.")
    return value


class GoogleEngine:
    def __init__(self, source: str):
        try:
            from deep_translator import GoogleTranslator
        except ImportError as exc:
            raise RuntimeError(
                "deep-translator fehlt. Führe INSTALLIEREN.cmd aus."
            ) from exc
        self.translator = GoogleTranslator(
            source="auto" if source in {"", "auto", "unknown"} else source,
            target="de",
        )

    def translate(self, text: str) -> str:
        return _clean_translation(self.translator.translate(text))


class OllamaEngine:
    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/") + "/api/chat"
        self.model = model

    def translate(self, text: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Übersetze den folgenden Untertitel präzise und natürlich "
                        "ins Deutsche. Erhalte Namen, Tonfall und Bedeutung. "
                        "Gib ausschließlich die Übersetzung aus, ohne Erklärung, "
                        "Anführungszeichen oder Markdown. /no_think"
                    ),
                },
                {"role": "user", "content": text},
            ],
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama ist unter {self.url} nicht erreichbar: {exc}"
            ) from exc
        content = result.get("message", {}).get("content", "")
        return _clean_translation(content)


def translate_cues(
    cues: list[Cue],
    source_language: str,
    cache_path: Path,
    options: PipelineOptions,
    *,
    log: LogCallback,
    progress: ProgressCallback,
    cancel_event: Optional[threading.Event] = None,
) -> list[Cue]:
    engine_name = options.translation_engine.lower()
    if engine_name == "none":
        raise RuntimeError(
            "Die Untertitel sind nicht deutsch, aber es ist keine "
            "Übersetzungs-Engine ausgewählt."
        )

    if engine_name == "google":
        engine = GoogleEngine(source_language)
        log("Übersetzung: Google über deep-translator")
    elif engine_name == "ollama":
        engine = OllamaEngine(options.ollama_url, options.ollama_model)
        log(f"Übersetzung: Ollama-Modell {options.ollama_model}")
    else:
        raise RuntimeError(f"Unbekannte Übersetzungs-Engine: {engine_name}")

    cache: dict[str, str] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    translated: list[Cue] = []
    total = len(cues)
    for index, cue in enumerate(cues, 1):
        check_cancel(cancel_event)
        key = f"{engine_name}|{source_language}|de|{cue.text}"
        text = cache.get(key)
        if not text:
            last_error: Exception | None = None
            for attempt in range(1, 4):
                try:
                    text = engine.translate(cue.text)
                    cache[key] = text
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 3:
                        log(
                            f"Übersetzung {index}/{total} fehlgeschlagen "
                            f"({exc}); neuer Versuch …"
                        )
                        time.sleep(attempt * 1.5)
            if not text:
                raise RuntimeError(
                    f"Untertitel {index} konnte nicht übersetzt werden: {last_error}"
                )

        translated.append(
            Cue(
                index=index,
                start=cue.start,
                end=cue.end,
                text=text,
                speaker=cue.speaker,
            )
        )
        progress(
            0.82 + 0.08 * index / max(total, 1),
            f"Übersetze {index}/{total}",
        )

        if index % 20 == 0:
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return translated
