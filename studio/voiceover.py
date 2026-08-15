from __future__ import annotations

import asyncio
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Optional

from .models import Cue, LogCallback, PipelineOptions, ProgressCallback
from .subtitles import is_non_speech
from .utils import (
    atempo_filters,
    check_cancel,
    probe_duration,
    require_exe,
    run_process,
)


PREFERRED_DE_VOICES = [
    "de-DE-ConradNeural",
    "de-DE-KatjaNeural",
    "de-DE-BerndNeural",
    "de-DE-AmalaNeural",
    "de-DE-ChristophNeural",
    "de-DE-ElkeNeural",
    "de-DE-FlorianMultilingualNeural",
    "de-DE-SeraphinaMultilingualNeural",
]


def _parse_voice_map(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in re.split(r"[,;\n]+", raw or ""):
        if "=" not in item:
            continue
        speaker, voice = item.split("=", 1)
        speaker, voice = speaker.strip(), voice.strip()
        if speaker and voice:
            result[speaker] = voice
    return result


async def _available_german_voices() -> list[str]:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError(
            "edge-tts fehlt. Führe INSTALLIEREN.cmd aus."
        ) from exc

    voices = await edge_tts.list_voices()
    result = [
        str(item.get("ShortName"))
        for item in voices
        if str(item.get("Locale", "")).lower().startswith("de-")
        and item.get("ShortName")
    ]
    if not result:
        raise RuntimeError("Edge-TTS hat keine deutschen Stimmen geliefert.")
    return result


async def _choose_voices(
    cues: list[Cue],
    raw_map: str,
) -> dict[str, str]:
    available = await _available_german_voices()
    available_set = set(available)
    preferred = [voice for voice in PREFERRED_DE_VOICES if voice in available_set]
    pool = preferred or available
    manual = _parse_voice_map(raw_map)

    speakers = sorted({cue.speaker for cue in cues})
    result: dict[str, str] = {}
    for index, speaker in enumerate(speakers):
        selected = manual.get(speaker)
        if selected and selected in available_set:
            result[speaker] = selected
        elif selected:
            result[speaker] = pool[index % len(pool)]
        else:
            result[speaker] = pool[index % len(pool)]
    return result


async def _tts_save(
    text: str,
    voice: str,
    output: Path,
    options: PipelineOptions,
) -> None:
    import edge_tts

    communicator = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=options.voice_rate,
        volume=options.voice_volume,
        pitch=options.voice_pitch,
    )
    await communicator.save(str(output))


def _create_silence(
    output: Path,
    duration: float,
    sample_rate: int,
    *,
    log: LogCallback,
    cancel_event: Optional[threading.Event],
) -> None:
    ffmpeg = require_exe("ffmpeg")
    run_process(
        [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl=mono",
            "-t", f"{max(duration, 0.01):.3f}",
            "-c:a", "pcm_s16le",
            str(output),
        ],
        log=log,
        cancel_event=cancel_event,
    )


def _make_timed_wav(
    source_mp3: Path,
    output_wav: Path,
    source_duration: float,
    target_duration: float,
    sample_rate: int,
    *,
    log: LogCallback,
    cancel_event: Optional[threading.Event],
) -> dict:
    ffmpeg = require_exe("ffmpeg")
    speed_factor = source_duration / max(target_duration, 0.1)
    filters = atempo_filters(speed_factor)
    filters.extend(
        [
            f"aresample={sample_rate}",
            "aformat=sample_fmts=s16:channel_layouts=mono",
            "apad",
            f"atrim=0:{max(target_duration, 0.10):.3f}",
        ]
    )
    run_process(
        [
            ffmpeg, "-y",
            "-i", str(source_mp3),
            "-af", ",".join(filters),
            "-ar", str(sample_rate),
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(output_wav),
        ],
        log=log,
        cancel_event=cancel_event,
    )
    return {
        "original_tts_duration": round(source_duration, 3),
        "target_duration": round(target_duration, 3),
        "speed_factor": round(speed_factor, 3),
    }


def _concat_wavs(
    parts_dir: Path,
    ordered_files: list[Path],
    output: Path,
    bitrate: str,
    *,
    log: LogCallback,
    cancel_event: Optional[threading.Event],
) -> None:
    ffmpeg = require_exe("ffmpeg")
    concat_file = parts_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{path.name}'" for path in ordered_files) + "\n",
        encoding="utf-8",
    )
    run_process(
        [
            ffmpeg, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file.name,
            "-c:a", "libmp3lame",
            "-b:a", bitrate,
            str(output.resolve()),
        ],
        cwd=parts_dir,
        log=log,
        cancel_event=cancel_event,
    )


async def build_voiceover_async(
    cues: list[Cue],
    output: Path,
    work_dir: Path,
    options: PipelineOptions,
    *,
    log: LogCallback,
    progress: ProgressCallback,
    cancel_event: Optional[threading.Event] = None,
) -> tuple[Path, dict[str, str]]:
    require_exe("ffmpeg")
    require_exe("ffprobe")
    work_dir.mkdir(parents=True, exist_ok=True)
    parts_dir = work_dir / "voice_parts"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True)

    voices = await _choose_voices(cues, options.voice_map)
    log("Stimmen: " + ", ".join(f"{k}={v}" for k, v in voices.items()))

    ordered: list[Path] = []
    manifest: list[dict] = []
    cursor = 0.0
    earliest_next_start = 0.0
    part_number = 0
    gap = max(options.gap_ms, 0) / 1000.0
    total = len(cues)

    for position, cue in enumerate(cues):
        check_cancel(cancel_event)
        effective_start = max(cue.start, earliest_next_start, cursor)

        if effective_start > cursor + 0.005:
            part_number += 1
            silence = parts_dir / f"{part_number:06d}_silence.wav"
            _create_silence(
                silence,
                effective_start - cursor,
                options.sample_rate,
                log=log,
                cancel_event=cancel_event,
            )
            ordered.append(silence)
            cursor = effective_start

        if options.skip_non_speech and is_non_speech(cue.text):
            log(f"Überspringe Geräusch/Musik: {cue.index} | {cue.text[:70]}")
            manifest.append(
                {
                    "index": cue.index,
                    "speaker": cue.speaker,
                    "text": cue.text,
                    "skipped_non_speech": True,
                    "effective_start": round(effective_start, 3),
                }
            )
            progress(
                0.90 + 0.08 * (position + 1) / max(total, 1),
                f"Voiceover {position + 1}/{total}",
            )
            continue

        voice = voices[cue.speaker]
        raw_mp3 = parts_dir / f"tts_{position + 1:06d}.mp3"
        await _tts_save(cue.text, voice, raw_mp3, options)
        source_duration = max(
            probe_duration(raw_mp3, cancel_event=cancel_event),
            0.1,
        )

        next_original_start = (
            cues[position + 1].start if position + 1 < total else None
        )
        if next_original_start is not None:
            available_before_next = max(
                next_original_start - gap - effective_start,
                0.1,
            )
        else:
            available_before_next = max(cue.end - effective_start, 0.1)

        required_compression = max(
            0.0,
            source_duration - available_before_next,
        )
        compressed_seconds = min(
            required_compression,
            max(options.max_compress_seconds, 0.0),
        )
        target_duration = max(source_duration - compressed_seconds, 0.1)
        effective_end = effective_start + target_duration

        part_number += 1
        timed_wav = parts_dir / f"{part_number:06d}_speech.wav"
        timing = _make_timed_wav(
            raw_mp3,
            timed_wav,
            source_duration,
            target_duration,
            options.sample_rate,
            log=log,
            cancel_event=cancel_event,
        )
        ordered.append(timed_wav)
        cursor = effective_end
        earliest_next_start = effective_end + gap

        remaining_shift = 0.0
        if next_original_start is not None:
            remaining_shift = max(
                0.0,
                earliest_next_start - next_original_start,
            )
            if remaining_shift > 0.005:
                log(
                    f"Block {cue.index}: nächster Block verschiebt sich um "
                    f"{remaining_shift:.3f} s."
                )

        manifest.append(
            {
                "index": cue.index,
                "start": cue.start,
                "end": cue.end,
                "effective_start": round(effective_start, 3),
                "effective_end": round(effective_end, 3),
                "speaker": cue.speaker,
                "voice": voice,
                "text": cue.text,
                "compressed_seconds": round(compressed_seconds, 3),
                "remaining_shift": round(remaining_shift, 3),
                "skipped_non_speech": False,
                **timing,
            }
        )
        if not options.keep_raw_tts:
            raw_mp3.unlink(missing_ok=True)

        progress(
            0.90 + 0.08 * (position + 1) / max(total, 1),
            f"Voiceover {position + 1}/{total}",
        )

    final_end = max((cue.end for cue in cues), default=cursor)
    if final_end > cursor + 0.005:
        part_number += 1
        silence = parts_dir / f"{part_number:06d}_tail.wav"
        _create_silence(
            silence,
            final_end - cursor,
            options.sample_rate,
            log=log,
            cancel_event=cancel_event,
        )
        ordered.append(silence)

    if not ordered:
        part_number += 1
        silence = parts_dir / f"{part_number:06d}_silence.wav"
        _create_silence(
            silence,
            max(final_end, 1.0),
            options.sample_rate,
            log=log,
            cancel_event=cancel_event,
        )
        ordered.append(silence)

    output.parent.mkdir(parents=True, exist_ok=True)
    _concat_wavs(
        parts_dir,
        ordered,
        output,
        options.bitrate,
        log=log,
        cancel_event=cancel_event,
    )
    (work_dir / "speaker_voice_map.json").write_text(
        json.dumps(voices, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (work_dir / "voiceover_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not options.keep_parts:
        shutil.rmtree(parts_dir, ignore_errors=True)
    return output, voices


def build_voiceover(
    cues: list[Cue],
    output: Path,
    work_dir: Path,
    options: PipelineOptions,
    *,
    log: LogCallback,
    progress: ProgressCallback,
    cancel_event: Optional[threading.Event] = None,
) -> tuple[Path, dict[str, str]]:
    return asyncio.run(
        build_voiceover_async(
            cues,
            output,
            work_dir,
            options,
            log=log,
            progress=progress,
            cancel_event=cancel_event,
        )
    )
