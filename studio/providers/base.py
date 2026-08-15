"""Common provider contracts for transcription, translation, quality and TTS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    available: bool
    detail: str = ""


class Provider(Protocol):
    """Minimal contract implemented by future engine adapters."""

    name: str

    def health_check(self) -> ProviderHealth:
        """Check availability without performing paid or long-running work."""
