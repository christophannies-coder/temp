"""Adapter that exposes the existing faster-whisper engine as a provider."""

from __future__ import annotations

import importlib.util
from typing import Any

from .base import ProviderHealth


class FasterWhisperProvider:
    """Thin, lazy adapter that preserves the established transcription engine."""

    name = "faster-whisper"

    def health_check(self) -> ProviderHealth:
        available = importlib.util.find_spec("faster_whisper") is not None
        detail = "Bereit" if available else "Das Paket faster-whisper ist nicht installiert."
        return ProviderHealth(self.name, available, detail)

    def transcribe(self, *args: Any, **kwargs: Any) -> Any:
        # Import lazily so a missing optional provider does not break the UI.
        from ..transcription import transcribe_media

        return transcribe_media(*args, **kwargs)
