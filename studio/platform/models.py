"""A small registry for model choices without loading model weights."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .capabilities import CapabilitySnapshot
from .errors import DependencyUnavailableError


@dataclass(frozen=True)
class ModelSpec:
    identifier: str
    task: str
    display_name: str
    requires_cuda: bool = False
    recommended_compute_type: str = "int8"


class ModelManager:
    """Keeps supported model metadata and makes hardware-safe recommendations."""

    def __init__(self, specs: Iterable[ModelSpec] | None = None) -> None:
        self._specs = {spec.identifier: spec for spec in (specs or self.default_specs())}

    @staticmethod
    def default_specs() -> tuple[ModelSpec, ...]:
        return (
            ModelSpec("small", "transcription", "Whisper Small"),
            ModelSpec("medium", "transcription", "Whisper Medium"),
            ModelSpec("large-v3", "transcription", "Whisper Large v3", recommended_compute_type="float16"),
        )

    def get(self, identifier: str) -> ModelSpec:
        try:
            return self._specs[identifier]
        except KeyError as exc:
            raise DependencyUnavailableError(
                "unknown_model",
                f"Das Modell '{identifier}' ist nicht registriert.",
                "Wähle ein unterstütztes Modell oder erweitere die Modellregistrierung.",
            ) from exc

    def recommend_compute_type(self, identifier: str, capabilities: CapabilitySnapshot) -> str:
        spec = self.get(identifier)
        if spec.requires_cuda and not capabilities.cuda_available:
            raise DependencyUnavailableError(
                "cuda_required",
                f"Das Modell '{identifier}' benötigt eine CUDA-GPU.",
                "Wähle ein CPU-taugliches Modell oder verwende einen Rechner mit NVIDIA-GPU.",
            )
        return spec.recommended_compute_type if capabilities.cuda_available else "int8"
