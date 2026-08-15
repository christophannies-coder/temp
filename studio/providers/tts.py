"""Adapter that exposes the established Edge-TTS voiceover engine."""

from __future__ import annotations

import importlib.util
from typing import Any

from .base import ProviderHealth


class EdgeTTSProvider:
    """Thin, lazy adapter that leaves all timing and mix logic unchanged."""

    name = "edge-tts"

    def health_check(self) -> ProviderHealth:
        available = importlib.util.find_spec("edge_tts") is not None
        detail = "Bereit" if available else "Das Paket edge-tts ist nicht installiert."
        return ProviderHealth(self.name, available, detail)

    def build_voiceover(self, *args: Any, **kwargs: Any) -> Any:
        # Import lazily so the optional TTS dependency does not break startup.
        from ..voiceover import build_voiceover

        return build_voiceover(*args, **kwargs)
