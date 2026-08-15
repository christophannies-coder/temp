#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kontextübergreifende Qualitätskorrektur für SRT-Übersetzungen.

Die Rohübersetzung wird NICHT blockweise isoliert geprüft. Stattdessen bekommt
das lokale Ollama-Modell zusammenhängende Gruppen mit Originaltext,
Rohübersetzung sowie Nachbarblöcken. Zeitstempel, Reihenfolge und Sprecherlabels
bleiben erhalten.

Nur Python-Standardbibliothek; keine zusätzlichen Pakete erforderlich.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .platform.sentence_groups import build_sentence_aware_groups


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_BATCH_SIZE = 10
DEFAULT_MAX_CHARS = 5200
DEFAULT_CONTEXT_BEFORE = 2
DEFAULT_CONTEXT_AFTER = 2

TIME_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
    r"\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
    r"(.*)$"
)

LEADING_ASS_RE = re.compile(r"^(?:\s*\{\\[^}]+\}\s*)+")
LEADING_HTML_RE = re.compile(
    r"^(?:\s*<(?:i|b|u|font|c(?:\.[^ >]+)?)(?:\s+[^>]*)?>\s*)+",
    flags=re.IGNORECASE,
)
VOICE_TAG_RE = re.compile(r"^\s*<v\s+([^>]+)>\s*(.*?)(?:</v>)?\s*$", re.I | re.S)
BRACKET_SPEAKER_RE = re.compile(
    r"^\s*\[((?:SPEAKER|SPRECHER)[_\- ]?\d+|MANN|FRAU|MAN|WOMAN|"
    r"ERZÄHLER|NARRATOR|DIANE|JORDAN|JENNIFER|JAMES|JULISSA|JOLINDA)"
    r"\]\s*(.*)$",
    re.I | re.S,
)
NAMED_SPEAKER_RE = re.compile(
    r"^\s*((?:SPEAKER|SPRECHER)[_\- ]?\d+|MANN|FRAU|MAN|WOMAN|"
    r"ERZÄHLER|NARRATOR|[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’\-]{1,35})"
    r"\s*:\s*(.*)$",
    re.S,
)

NON_SPEECH_WORDS = (
    "musik", "music", "applaus", "applause", "lacht", "lachen", "laugh",
    "seufzt", "sigh", "schreit", "scream", "telefon klingelt", "phone rings",
    "tür", "door", "klopfen", "knocking", "unverständlich", "inaudible",
    "spannungsmusik", "dramatische musik", "traurige musik",
)


class CorrectionError(RuntimeError):
    """Die Qualitätskorrektur konnte nicht sicher abgeschlossen werden."""


@dataclass
class Cue:
    index: int
    start_ms: int
    end_ms: int
    timing_suffix: str
    text: str

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


@dataclass
class CorrectionChange:
    index: int
    source: str
    raw_translation: str
    corrected_translation: str
    changed: bool


@dataclass
class CorrectionResult:
    output: str
    report: str
    cache: str
    blocks: int
    changed_blocks: int
    model: str
    started_at: str
    finished_at: str


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise CorrectionError(f"Zeichencodierung konnte nicht gelesen werden: {path}")


def timestamp_to_ms(parts: Sequence[str]) -> int:
    hours, minutes, seconds, millis = parts
    millis = millis.ljust(3, "0")[:3]
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(millis)
    )


def ms_to_timestamp(value: int) -> str:
    value = max(0, int(value))
    hours, rest = divmod(value, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def parse_srt(path: Path) -> list[Cue]:
    text = read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n{2,}", text.strip())
    cues: list[Cue] = []

    for position, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if not lines:
            continue

        timing_pos = None
        match = None
        for i, line in enumerate(lines[:3]):
            current = TIME_RE.match(line)
            if current:
                timing_pos = i
                match = current
                break

        if timing_pos is None or match is None:
            continue

        index = position
        if timing_pos > 0:
            try:
                index = int(lines[timing_pos - 1].strip())
            except ValueError:
                index = position

        start_ms = timestamp_to_ms(match.groups()[0:4])
        end_ms = timestamp_to_ms(match.groups()[4:8])
        suffix = match.group(9) or ""
        body = "\n".join(lines[timing_pos + 1:]).strip()

        cues.append(
            Cue(
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                timing_suffix=suffix,
                text=body,
            )
        )

    if not cues:
        raise CorrectionError(f"Keine gültigen SRT-Blöcke gefunden: {path}")
    return cues


def write_srt(path: Path, cues: Sequence[Cue]) -> None:
    parts: list[str] = []
    for cue in cues:
        parts.append(
            f"{cue.index}\n"
            f"{ms_to_timestamp(cue.start_ms)} --> "
            f"{ms_to_timestamp(cue.end_ms)}{cue.timing_suffix}\n"
            f"{cue.text.strip()}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8-sig")


def normalize_visible_text(text: str) -> str:
    value = text.replace("\u00a0", " ").replace("\ufeff", "")
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"</?(?:i|b|u|font|c)(?:\.[^ >]+)?[^>]*>", "", value, flags=re.I)
    value = re.sub(r"\{\\[^}]+\}", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def is_non_speech(text: str) -> bool:
    value = normalize_visible_text(text).strip()
    lower = value.casefold()

    if not value:
        return True
    if value.startswith("♪") and value.endswith("♪"):
        return True
    if (
        (value.startswith("[") and value.endswith("]"))
        or (value.startswith("(") and value.endswith(")"))
    ):
        return any(word in lower for word in NON_SPEECH_WORDS)
    return False


@dataclass
class TextEnvelope:
    prefix: str
    suffix: str
    content: str


def split_envelope(text: str) -> TextEnvelope:
    """
    Entfernt nur strukturelle Präfixe/Suffixe für die Modellbearbeitung und
    setzt sie anschließend unverändert wieder ein.
    """
    original = text.strip()
    prefix = ""
    suffix = ""
    work = original

    ass = LEADING_ASS_RE.match(work)
    if ass:
        prefix += ass.group(0)
        work = work[ass.end():]

    voice = VOICE_TAG_RE.match(work)
    if voice:
        prefix += f"<v {voice.group(1).strip()}>"
        suffix = "</v>"
        work = voice.group(2)
    else:
        html_prefix = LEADING_HTML_RE.match(work)
        if html_prefix:
            tags = html_prefix.group(0)
            prefix += tags
            work = work[html_prefix.end():]
            opening_tags = re.findall(
                r"<(i|b|u)>", tags, flags=re.I
            )
            if opening_tags:
                suffix = "".join(f"</{tag.lower()}>" for tag in reversed(opening_tags))

        bracket = BRACKET_SPEAKER_RE.match(work)
        if bracket:
            prefix += f"[{bracket.group(1).strip()}] "
            work = bracket.group(2)
        else:
            named = NAMED_SPEAKER_RE.match(work)
            if named:
                prefix += f"{named.group(1).strip()}: "
                work = named.group(2)

    return TextEnvelope(prefix=prefix, suffix=suffix, content=normalize_visible_text(work))


def reapply_envelope(envelope: TextEnvelope, corrected: str) -> str:
    value = normalize_model_text(corrected)
    return f"{envelope.prefix}{value}{envelope.suffix}".strip()


def normalize_model_text(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json|text|markdown)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.I | re.S)
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def validate_parallel(source: Sequence[Cue], translated: Sequence[Cue]) -> None:
    if len(source) != len(translated):
        raise CorrectionError(
            "Original und Rohübersetzung besitzen unterschiedlich viele SRT-Blöcke: "
            f"{len(source)} gegenüber {len(translated)}."
        )

    mismatched = []
    for pos, (src, dst) in enumerate(zip(source, translated), 1):
        if src.index != dst.index:
            mismatched.append((pos, src.index, dst.index))
        if abs(src.start_ms - dst.start_ms) > 5 or abs(src.end_ms - dst.end_ms) > 5:
            raise CorrectionError(
                f"Zeitstempel von Block {src.index} stimmen zwischen Original "
                "und Rohübersetzung nicht überein."
            )

    if mismatched:
        preview = ", ".join(
            f"Position {p}: {a}/{b}" for p, a, b in mismatched[:5]
        )
        raise CorrectionError(
            "Blocknummern stimmen zwischen Original und Rohübersetzung nicht überein: "
            + preview
        )


def batch_positions(
    source: Sequence[Cue],
    translated: Sequence[Cue],
    batch_size: int,
    max_chars: int,
) -> list[tuple[int, int]]:
    """Create correction groups from source-language sentence boundaries.

    The raw German translation may already contain false sentence boundaries.
    It must therefore never decide where a correction request is split.
    """
    source_texts = [split_envelope(cue.text).content for cue in source]
    translated_texts = [split_envelope(cue.text).content for cue in translated]
    gaps_after_ms = [
        max(0, source[position + 1].start_ms - cue.end_ms)
        if position + 1 < len(source)
        else 0
        for position, cue in enumerate(source)
    ]
    non_speech = [is_non_speech(cue.text) for cue in source]
    return build_sentence_aware_groups(
        source_texts,
        translated_texts,
        gaps_after_ms,
        non_speech,
        batch_size=batch_size,
        max_chars=max_chars,
    )

class JsonCache:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict[str, str]] = {}
        if path.exists():
            try:
                loaded = json.loads(read_text(path))
                if isinstance(loaded, dict):
                    self.data = {
                        str(key): value
                        for key, value in loaded.items()
                        if isinstance(value, dict)
                    }
            except Exception:
                self.data = {}

    def get(self, key: str) -> dict[int, str] | None:
        value = self.data.get(key)
        if not value:
            return None
        try:
            return {int(k): str(v) for k, v in value.items()}
        except Exception:
            return None

    def put(self, key: str, value: dict[int, str]) -> None:
        self.data[key] = {str(k): v for k, v in value.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def make_batch_key(model: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {"version": 1, "model": model, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def response_schema(expected_ids: Sequence[int]) -> dict[str, Any]:
    ids = [int(x) for x in expected_ids]
    return {
        "type": "object",
        "properties": {
            "corrections": {
                "type": "array",
                "minItems": len(ids),
                "maxItems": len(ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "enum": ids},
                        "text": {"type": "string", "minLength": 1},
                    },
                    "required": ["id", "text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["corrections"],
        "additionalProperties": False,
    }


def system_prompt() -> str:
    return (
        "Du bist ein professioneller deutscher Dialog-, Untertitel- und "
        "Synchronredakteur. Prüfe eine bereits maschinell erzeugte deutsche "
        "Übersetzung anhand des fremdsprachigen Originals und des Zusammenhangs "
        "über mehrere Untertitelblöcke hinweg. "
        "Korrigiere Bedeutungsfehler, falsche Bezüge, Pronomen, Zeitformen, "
        "Eigennamen, idiomatische Wendungen, juristische und technische Begriffe, "
        "unnatürliche Wortstellung und blockübergreifend zerbrochene Sätze. "
        "Die deutsche Fassung soll natürlich gesprochen klingen und sich für ein "
        "Voiceover eignen. Kürze nur Füllwörter, wenn dadurch keine Information "
        "verloren geht. Erfinde nichts, zensiere nichts und füge keine Erklärungen "
        "hinzu. Jeder Zielblock muss genau einmal zurückgegeben werden. "
        "Achte darauf, dass aufeinanderfolgende Fragmente gemeinsam einen "
        "grammatisch und inhaltlich korrekten Satz bilden. "
        "Gib ausschließlich das verlangte JSON zurück."
    )


def ollama_request(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    timeout: int,
) -> str:
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {
            "temperature": 0,
            "num_ctx": 8192,
        },
        "keep_alive": "10m",
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise CorrectionError(f"Ollama HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise CorrectionError(
            "Ollama ist nicht erreichbar. Starte Ollama und prüfe "
            f"{base_url.rstrip('/')}. Technischer Fehler: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise CorrectionError("Zeitüberschreitung bei der Ollama-Korrektur.") from exc

    message = result.get("message") if isinstance(result, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise CorrectionError("Ollama lieferte keine verwertbare Antwort.")
    return content


def parse_corrections(raw: str, expected_ids: set[int]) -> dict[int, str]:
    value = normalize_model_text(raw)
    try:
        obj = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CorrectionError(f"Ungültiges JSON vom Korrekturmodell: {exc}") from exc

    items = obj.get("corrections") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        raise CorrectionError("Modellantwort enthält kein Array 'corrections'.")

    result: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        text = normalize_model_text(str(item.get("text", "")))
        if idx in expected_ids and text and idx not in result:
            result[idx] = text

    missing = expected_ids.difference(result)
    extra = set(result).difference(expected_ids)
    if missing or extra or len(result) != len(expected_ids):
        raise CorrectionError(
            f"Unvollständige Modellantwort. Fehlend: {sorted(missing)}, "
            f"unerwartet: {sorted(extra)}"
        )
    return result


def make_payload(
    source: Sequence[Cue],
    translated: Sequence[Cue],
    target_start: int,
    target_end: int,
    context_before: int,
    context_after: int,
) -> tuple[dict[str, Any], list[int], dict[int, TextEnvelope]]:
    left = max(0, target_start - context_before)
    right = min(len(source), target_end + context_after)
    target_ids = [source[pos].index for pos in range(target_start, target_end)]
    envelopes: dict[int, TextEnvelope] = {}

    items: list[dict[str, Any]] = []
    for pos in range(left, right):
        src_env = split_envelope(source[pos].text)
        dst_env = split_envelope(translated[pos].text)
        envelopes[source[pos].index] = dst_env

        items.append(
            {
                "id": source[pos].index,
                "target": target_start <= pos < target_end,
                "source": src_env.content,
                "raw_german": dst_env.content,
                "previous_gap_ms": (
                    None if pos == 0
                    else max(0, source[pos].start_ms - source[pos - 1].end_ms)
                ),
            }
        )

    payload = {
        "instruction": (
            "Bearbeite nur Einträge mit target=true. Die anderen Einträge sind "
            "Kontext und dürfen nicht ausgegeben werden. Gib für jeden Ziel-ID "
            "eine natürliche, inhaltlich genaue deutsche Voiceover-Fassung zurück. "
            "Behalte die Verteilung auf dieselben IDs bei, aber formuliere "
            "Satzfragmente so, dass sie über die Blockgrenzen hinweg korrekt "
            "zusammenpassen."
        ),
        "target_ids": target_ids,
        "items": items,
    }
    return payload, target_ids, envelopes


def request_batch(
    *,
    payload: dict[str, Any],
    target_ids: Sequence[int],
    model: str,
    base_url: str,
    retries: int,
    timeout: int,
    request_fn: Callable[..., str] = ollama_request,
) -> dict[int, str]:
    schema = response_schema(target_ids)
    messages = [
        {"role": "system", "content": system_prompt()},
        {
            "role": "user",
            "content": (
                "JSON-Schema der Antwort:\n"
                + json.dumps(schema, ensure_ascii=False)
                + "\n\nZu prüfende Untertitel:\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
        },
    ]

    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            raw = request_fn(
                base_url=base_url,
                model=model,
                messages=messages,
                schema=schema,
                timeout=timeout,
            )
            return parse_corrections(raw, set(target_ids))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2.0 * attempt, 5.0))

    raise CorrectionError(
        f"Korrekturpaket mit IDs {list(target_ids)} ist nach "
        f"{retries} Versuch(en) fehlgeschlagen: {last_error}"
    )


def correct_range_resilient(
    *,
    source: Sequence[Cue],
    translated: Sequence[Cue],
    start: int,
    end: int,
    context_before: int,
    context_after: int,
    model: str,
    base_url: str,
    retries: int,
    timeout: int,
    cache: JsonCache,
    request_fn: Callable[..., str],
) -> dict[int, str]:
    payload, target_ids, _envelopes = make_payload(
        source,
        translated,
        start,
        end,
        context_before,
        context_after,
    )
    cache_key = make_batch_key(model, payload)
    cached = cache.get(cache_key)
    if cached is not None and set(cached) == set(target_ids):
        return cached

    try:
        result = request_batch(
            payload=payload,
            target_ids=target_ids,
            model=model,
            base_url=base_url,
            retries=retries,
            timeout=timeout,
            request_fn=request_fn,
        )
        cache.put(cache_key, result)
        return result
    except CorrectionError:
        if end - start <= 1:
            raise
        middle = start + (end - start) // 2
        left = correct_range_resilient(
            source=source,
            translated=translated,
            start=start,
            end=middle,
            context_before=context_before,
            context_after=context_after,
            model=model,
            base_url=base_url,
            retries=retries,
            timeout=timeout,
            cache=cache,
            request_fn=request_fn,
        )
        right = correct_range_resilient(
            source=source,
            translated=translated,
            start=middle,
            end=end,
            context_before=context_before,
            context_after=context_after,
            model=model,
            base_url=base_url,
            retries=retries,
            timeout=timeout,
            cache=cache,
            request_fn=request_fn,
        )
        left.update(right)
        return left


def correct_translation_srt(
    source_srt: str | Path,
    raw_translation_srt: str | Path,
    output_srt: str | Path,
    *,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_chars: int = DEFAULT_MAX_CHARS,
    context_before: int = DEFAULT_CONTEXT_BEFORE,
    context_after: int = DEFAULT_CONTEXT_AFTER,
    retries: int = 3,
    timeout: int = 600,
    cache_path: str | Path | None = None,
    report_path: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
    request_fn: Callable[..., str] = ollama_request,
) -> CorrectionResult:
    source_path = Path(source_srt).expanduser().resolve()
    raw_path = Path(raw_translation_srt).expanduser().resolve()
    output_path = Path(output_srt).expanduser().resolve()

    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if not raw_path.exists():
        raise FileNotFoundError(raw_path)

    started = dt.datetime.now().astimezone()
    source = parse_srt(source_path)
    raw = parse_srt(raw_path)
    validate_parallel(source, raw)

    if cache_path is None:
        cache_file = output_path.parent / "translation_quality_cache.json"
    else:
        cache_file = Path(cache_path).expanduser().resolve()

    if report_path is None:
        report_file = output_path.with_suffix(".quality_report.json")
    else:
        report_file = Path(report_path).expanduser().resolve()

    cache = JsonCache(cache_file)
    groups = batch_positions(source, raw, batch_size, max_chars)
    corrections: dict[int, str] = {}

    for group_number, (start, end) in enumerate(groups, 1):
        if progress:
            progress(
                f"Qualitätskorrektur {group_number}/{len(groups)} "
                f"(Blöcke {source[start].index}–{source[end - 1].index})"
            )

        # Musik/Geräuschblöcke bleiben exakt unverändert.
        speech_positions = [
            pos for pos in range(start, end)
            if not is_non_speech(source[pos].text)
            and split_envelope(raw[pos].text).content
        ]
        if not speech_positions:
            continue

        # Zusammenhängende Teilbereiche innerhalb der Gruppe bilden.
        run_start = speech_positions[0]
        previous = speech_positions[0]
        runs: list[tuple[int, int]] = []
        for pos in speech_positions[1:]:
            if pos != previous + 1:
                runs.append((run_start, previous + 1))
                run_start = pos
            previous = pos
        runs.append((run_start, previous + 1))

        for sub_start, sub_end in runs:
            result = correct_range_resilient(
                source=source,
                translated=raw,
                start=sub_start,
                end=sub_end,
                context_before=context_before,
                context_after=context_after,
                model=model,
                base_url=ollama_url,
                retries=retries,
                timeout=timeout,
                cache=cache,
                request_fn=request_fn,
            )
            corrections.update(result)

    corrected_cues: list[Cue] = []
    changes: list[CorrectionChange] = []

    for src, raw_cue in zip(source, raw):
        envelope = split_envelope(raw_cue.text)
        if is_non_speech(src.text) or src.index not in corrections:
            corrected_text = raw_cue.text
        else:
            corrected_text = reapply_envelope(envelope, corrections[src.index])

        if not normalize_visible_text(corrected_text):
            raise CorrectionError(
                f"Die Korrektur von Block {src.index} wäre leer. "
                "Aus Sicherheitsgründen wird kein Voiceover gestartet."
            )

        corrected_cues.append(
            Cue(
                index=raw_cue.index,
                start_ms=raw_cue.start_ms,
                end_ms=raw_cue.end_ms,
                timing_suffix=raw_cue.timing_suffix,
                text=corrected_text,
            )
        )
        changes.append(
            CorrectionChange(
                index=src.index,
                source=src.text,
                raw_translation=raw_cue.text,
                corrected_translation=corrected_text,
                changed=normalize_visible_text(raw_cue.text)
                != normalize_visible_text(corrected_text),
            )
        )

    write_srt(output_path, corrected_cues)

    finished = dt.datetime.now().astimezone()
    report = {
        "version": 1,
        "source_srt": str(source_path),
        "raw_translation_srt": str(raw_path),
        "corrected_srt": str(output_path),
        "model": model,
        "ollama_url": ollama_url,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "blocks": len(changes),
        "changed_blocks": sum(change.changed for change in changes),
        "settings": {
            "batch_size": batch_size,
            "max_chars": max_chars,
            "context_before": context_before,
            "context_after": context_after,
            "retries": retries,
        },
        "changes": [asdict(change) for change in changes if change.changed],
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return CorrectionResult(
        output=str(output_path),
        report=str(report_file),
        cache=str(cache_file),
        blocks=len(changes),
        changed_blocks=report["changed_blocks"],
        model=model,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prüft eine deutsche SRT-Rohübersetzung mit Satzkontext über mehrere "
            "Blöcke und erzeugt die korrigierte Voiceover-Fassung."
        )
    )
    parser.add_argument("source_srt", help="Originalsprachige SRT")
    parser.add_argument("raw_translation_srt", help="Deutsche Rohübersetzung")
    parser.add_argument("output_srt", help="Korrigierte deutsche SRT")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--context-before", type=int, default=DEFAULT_CONTEXT_BEFORE)
    parser.add_argument("--context-after", type=int, default=DEFAULT_CONTEXT_AFTER)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--cache")
    parser.add_argument("--report")
    args = parser.parse_args(argv)

    try:
        result = correct_translation_srt(
            args.source_srt,
            args.raw_translation_srt,
            args.output_srt,
            model=args.model,
            ollama_url=args.ollama_url,
            batch_size=args.batch_size,
            max_chars=args.max_chars,
            context_before=args.context_before,
            context_after=args.context_after,
            retries=args.retries,
            timeout=args.timeout,
            cache_path=args.cache,
            report_path=args.report,
            progress=lambda message: print(message, flush=True),
        )
    except KeyboardInterrupt:
        print("\nAbgebrochen. Bereits geprüfte Pakete bleiben im Cache.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"Korrigierte SRT: {result.output}")
    print(f"Änderungen: {result.changed_blocks}/{result.blocks}")
    print(f"Bericht: {result.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
