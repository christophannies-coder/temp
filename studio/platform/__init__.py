"""Produktisierungs-Grundlagen für Voiceover Studio.

Die Module in diesem Paket sind absichtlich nebenwirkungsfrei: Sie erkennen
Fähigkeiten und validieren Konfigurationen, ohne beim Import Modelle zu laden
oder externe Programme zu starten.
"""

from .capabilities import CapabilitySnapshot, detect_capabilities, resolve_device
from .config import ApplicationConfig, ConfigurationError
from .ffmpeg import FFmpegManager, FFmpegStatus
from .models import ModelManager, ModelSpec

__all__ = [
    "ApplicationConfig",
    "CapabilitySnapshot",
    "ConfigurationError",
    "FFmpegManager",
    "FFmpegStatus",
    "ModelManager",
    "ModelSpec",
    "detect_capabilities",
    "resolve_device",
]
