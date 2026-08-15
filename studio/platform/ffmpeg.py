"""Central FFmpeg discovery with a single actionable failure mode."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from .errors import DependencyUnavailableError


@dataclass(frozen=True)
class FFmpegStatus:
    ffmpeg: str | None
    ffprobe: str | None

    @property
    def available(self) -> bool:
        return self.ffmpeg is not None and self.ffprobe is not None


class FFmpegManager:
    def inspect(self) -> FFmpegStatus:
        return FFmpegStatus(
            ffmpeg=shutil.which("ffmpeg") or shutil.which("ffmpeg.exe"),
            ffprobe=shutil.which("ffprobe") or shutil.which("ffprobe.exe"),
        )

    def require(self) -> FFmpegStatus:
        status = self.inspect()
        if not status.available:
            missing = ", ".join(name for name, value in (("ffmpeg", status.ffmpeg), ("ffprobe", status.ffprobe)) if value is None)
            raise DependencyUnavailableError(
                "ffmpeg_missing",
                f"FFmpeg ist nicht vollständig verfügbar (fehlt: {missing}).",
                "Installiere FFmpeg und füge ffmpeg sowie ffprobe zum PATH hinzu.",
            )
        return status
