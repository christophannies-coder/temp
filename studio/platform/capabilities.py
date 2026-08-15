"""Safe runtime capability detection; no optional dependency is required."""

from __future__ import annotations

import importlib.util
import platform
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilitySnapshot:
    operating_system: str
    python_version: str
    ffmpeg_available: bool
    ffprobe_available: bool
    cuda_available: bool
    cuda_device_name: str = ""
    torch_available: bool = False

    @property
    def recommended_device(self) -> str:
        return "cuda" if self.cuda_available else "cpu"


def resolve_device(requested: str, capabilities: CapabilitySnapshot | None = None) -> str:
    """Resolve a requested device without allowing an unavailable CUDA target."""
    requested = requested.strip().lower()
    snapshot = capabilities or detect_capabilities()
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        return "cuda" if snapshot.cuda_available else "cpu"
    return snapshot.recommended_device


def detect_capabilities() -> CapabilitySnapshot:
    """Return best-effort system information without raising on optional tools."""
    torch_available = importlib.util.find_spec("torch") is not None
    cuda_available = False
    device_name = ""
    if torch_available:
        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                device_name = str(torch.cuda.get_device_name(0))
        except Exception:
            # A broken Torch/CUDA install must not prevent a CPU fallback.
            cuda_available = False
            device_name = ""
    return CapabilitySnapshot(
        operating_system=platform.system(),
        python_version=platform.python_version(),
        ffmpeg_available=shutil.which("ffmpeg") is not None or shutil.which("ffmpeg.exe") is not None,
        ffprobe_available=shutil.which("ffprobe") is not None or shutil.which("ffprobe.exe") is not None,
        cuda_available=cuda_available,
        cuda_device_name=device_name,
        torch_available=torch_available,
    )
