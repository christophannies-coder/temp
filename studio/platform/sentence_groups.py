"""Sentence-aware grouping for subtitle translation and review requests."""

from __future__ import annotations

import re
from collections.abc import Sequence


SENTENCE_END_RE = re.compile(r'[.!?…]["»”’)]?$')


def ends_sentence(text: str) -> bool:
    """Return whether visible source text finishes a sentence."""
    return bool(SENTENCE_END_RE.search((text or "").strip()))


def build_sentence_aware_groups(
    source_texts: Sequence[str],
    translated_texts: Sequence[str],
    gaps_after_ms: Sequence[int],
    non_speech: Sequence[bool],
    *,
    batch_size: int,
    max_chars: int,
    long_pause_ms: int = 4500,
) -> list[tuple[int, int]]:
    """Build request ranges without splitting a source-language sentence.

    Limits are honored between sentence units. A single long sentence is kept
    intact deliberately: preserving its meaning is safer than forcing a split
    at an arbitrary subtitle boundary.
    """
    count = len(source_texts)
    if not (len(translated_texts) == len(gaps_after_ms) == len(non_speech) == count):
        raise ValueError("Gruppierungsdaten besitzen unterschiedliche Längen.")

    sentence_units: list[tuple[int, int, int]] = []
    start = 0
    chars = 0
    for position in range(count):
        chars += len(source_texts[position]) + len(translated_texts[position]) + 80
        boundary = (
            ends_sentence(source_texts[position])
            or non_speech[position]
            or position == count - 1
            or gaps_after_ms[position] >= long_pause_ms
        )
        if boundary:
            sentence_units.append((start, position + 1, chars))
            start = position + 1
            chars = 0

    groups: list[tuple[int, int]] = []
    group_start: int | None = None
    group_end = 0
    group_chars = 0
    group_blocks = 0
    max_blocks = max(1, batch_size)

    for unit_start, unit_end, unit_chars in sentence_units:
        unit_blocks = unit_end - unit_start
        exceeds_limit = (
            group_start is not None
            and (group_blocks + unit_blocks > max_blocks or group_chars + unit_chars > max_chars)
        )
        if exceeds_limit:
            groups.append((group_start, group_end))
            group_start = None
            group_chars = 0
            group_blocks = 0
        if group_start is None:
            group_start = unit_start
        group_end = unit_end
        group_chars += unit_chars
        group_blocks += unit_blocks

    if group_start is not None:
        groups.append((group_start, group_end))
    return groups
