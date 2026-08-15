from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class Cue:
    index: int
    start: float
    end: float
    text: str
    speaker: str = "SPEAKER_00"


@dataclass
class PipelineOptions:
    # Workflow
    output_root: str = ""
    do_transcribe: bool = True
    do_translate: bool = True
    do_voiceover: bool = True
    do_mux: bool = False

    # Transkription
    whisper_model: str = "small"
    whisper_language: str = "auto"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 5
    vad_filter: bool = True
    diarization: bool = False
    hf_token: str = ""

    # SRT / Übersetzung
    srt_language: str = "auto"
    translation_engine: str = "google"  # none, google, ollama
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"

    # KI-Sprachprüfung nach der Übersetzung
    quality_check: bool = True
    quality_model: str = "qwen3:8b"
    quality_batch_size: int = 10
    quality_max_chars: int = 5200
    quality_context_before: int = 2
    quality_context_after: int = 2
    quality_fail_mode: str = "stop"  # stop, use_raw

    # Voiceover
    voice_map: str = ""
    voice_rate: str = "+0%"
    voice_volume: str = "+0%"
    voice_pitch: str = "+0Hz"
    bitrate: str = "192k"
    sample_rate: int = 24000
    max_compress_seconds: float = 0.5
    gap_ms: int = 40
    skip_non_speech: bool = True
    keep_parts: bool = False
    keep_raw_tts: bool = False

    # Videoausgabe
    mux_mode: str = "replace"  # replace, mix
    original_volume: float = 0.22
    voiceover_volume: float = 1.0

    keep_temp: bool = False


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float, str], None]


@dataclass
class PipelineResult:
    source: Path
    output_dir: Path
    detected_language: str = ""
    transcript_srt: Optional[Path] = None
    raw_german_srt: Optional[Path] = None
    german_srt: Optional[Path] = None
    quality_report: Optional[Path] = None
    voiceover_mp3: Optional[Path] = None
    muxed_media: Optional[Path] = None
    extra: dict = field(default_factory=dict)
