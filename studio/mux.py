from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from .models import LogCallback, PipelineOptions
from .utils import require_exe, run_process


MEDIA_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


def find_matching_media(srt: Path) -> Optional[Path]:
    stems = {
        srt.stem,
        srt.stem.removesuffix("_de"),
        srt.stem.removesuffix("_transcript"),
        srt.stem.removesuffix("_de_speaker"),
    }
    candidates: list[Path] = []
    for path in srt.parent.iterdir():
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            if path.stem in stems or any(
                path.stem.startswith(stem) or stem.startswith(path.stem)
                for stem in stems
            ):
                candidates.append(path)
    return sorted(candidates)[0] if candidates else None


def mux_voiceover(
    media: Path,
    voiceover: Path,
    output: Path,
    options: PipelineOptions,
    *,
    log: LogCallback,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    ffmpeg = require_exe("ffmpeg")
    output.parent.mkdir(parents=True, exist_ok=True)

    if options.mux_mode == "mix":
        filter_complex = (
            f"[0:a:0]volume={options.original_volume:.3f}[orig];"
            f"[1:a:0]volume={options.voiceover_volume:.3f}[voice];"
            "[orig][voice]amix=inputs=2:duration=longest:normalize=0[aout]"
        )
        command = [
            ffmpeg, "-y",
            "-i", str(media),
            "-i", str(voiceover),
            "-filter_complex", filter_complex,
            "-map", "0:v?",
            "-map", "[aout]",
            "-map", "0:s?",
            "-map_metadata", "0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "256k",
            "-c:s", "copy",
            str(output),
        ]
    else:
        command = [
            ffmpeg, "-y",
            "-i", str(media),
            "-i", str(voiceover),
            "-map", "0:v?",
            "-map", "1:a:0",
            "-map", "0:s?",
            "-map_metadata", "0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "256k",
            "-c:s", "copy",
            str(output),
        ]

    run_process(
        command,
        log=log,
        cancel_event=cancel_event,
    )
    return output
