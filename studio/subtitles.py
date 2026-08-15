from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .models import Cue


TIME_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Zeichencodierung konnte nicht gelesen werden: {path}")


def parse_timestamp(value: str) -> float:
    match = re.fullmatch(
        r"\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*",
        value,
    )
    if not match:
        raise ValueError(f"Ungültiger SRT-Zeitstempel: {value!r}")
    hours, minutes, seconds, millis = match.groups()
    millis = millis.ljust(3, "0")[:3]
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )


def format_timestamp(value: float) -> str:
    total_ms = max(0, round(value * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    text = text.replace("\ufeff", "")
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"</?(?:i|b|u|font|c)(?:\.[^ >]+)?[^>]*>", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_speaker(text: str) -> tuple[str, str]:
    raw = text.strip()

    voice_tag = re.match(
        r"^<v\s+([^>]+)>\s*(.*?)(?:</v>)?$",
        raw,
        flags=re.I | re.S,
    )
    if voice_tag:
        return voice_tag.group(1).strip(), clean_text(voice_tag.group(2))

    bracket = re.match(r"^\[([^\]]{1,80})\]\s*(.*)$", raw, flags=re.S)
    if bracket:
        candidate = bracket.group(1).strip()
        remainder = clean_text(bracket.group(2))
        if re.match(
            r"^(?:SPEAKER|SPRECHER)[_\- ]?\d+$|^(?:MANN|FRAU|MAN|WOMAN|ERZÄHLER|NARRATOR)$",
            candidate,
            flags=re.I,
        ):
            return candidate.upper().replace(" ", "_").replace("-", "_"), remainder

    named = re.match(
        r"^((?:SPEAKER|SPRECHER)[_\- ]?\d+|MANN|FRAU|MAN|WOMAN|ERZÄHLER|NARRATOR)"
        r"\s*[:\-]\s*(.*)$",
        raw,
        flags=re.I | re.S,
    )
    if named:
        return (
            named.group(1).strip().upper().replace(" ", "_").replace("-", "_"),
            clean_text(named.group(2)),
        )

    return "SPEAKER_00", clean_text(raw)


def parse_srt(path: Path) -> list[Cue]:
    content = read_text_file(path).replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = re.split(r"\n[ \t]*\n+", content)
    cues: list[Cue] = []

    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines()]
        timing_pos = next(
            (index for index, line in enumerate(lines) if TIME_RE.search(line)),
            None,
        )
        if timing_pos is None:
            continue

        timing = TIME_RE.search(lines[timing_pos])
        assert timing is not None
        raw_text = "\n".join(lines[timing_pos + 1:]).strip()
        if not raw_text:
            continue

        start = parse_timestamp(timing.group("start"))
        end = parse_timestamp(timing.group("end"))
        if end <= start:
            end = start + 0.1

        speaker, text = extract_speaker(raw_text)
        if text:
            cues.append(
                Cue(
                    index=len(cues) + 1,
                    start=start,
                    end=end,
                    text=text,
                    speaker=speaker,
                )
            )

    if not cues:
        raise RuntimeError(f"Keine gültigen Untertitel gefunden: {path}")

    cues.sort(key=lambda cue: (cue.start, cue.end, cue.index))
    for index, cue in enumerate(cues, 1):
        cue.index = index
    return cues


def write_srt(
    cues: Iterable[Cue],
    path: Path,
    *,
    include_speakers: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for index, cue in enumerate(cues, 1):
        text = cue.text.strip()
        if include_speakers:
            text = f"[{cue.speaker}] {text}"
        blocks.append(
            f"{index}\n"
            f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}\n"
            f"{text}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8-sig")
    return path


def is_non_speech(text: str) -> bool:
    value = clean_text(text).strip()
    if not value:
        return True
    if any(symbol in value for symbol in ("♪", "♫", "♬")):
        return True

    if (
        (value.startswith("[") and value.endswith("]"))
        or (value.startswith("(") and value.endswith(")"))
        or (value.startswith("{") and value.endswith("}"))
    ):
        inner = value[1:-1].strip().lower()
        markers = (
            "musik", "music", "applaus", "applause", "lacht", "lachen",
            "laughs", "laughing", "seufzt", "sighs", "geräusch", "sound",
            "stöhnen", "moans", "unverständlich", "inaudible",
        )
        return any(marker in inner for marker in markers)
    return False
