from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Iterable, Optional

from .models import LogCallback


CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class CancelledError(RuntimeError):
    pass


def check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event and cancel_event.is_set():
        raise CancelledError("Vorgang wurde abgebrochen.")


def require_exe(name: str) -> str:
    path = shutil.which(name) or shutil.which(name + ".exe")
    if not path:
        raise RuntimeError(
            f"'{name}' wurde nicht gefunden. Installiere FFmpeg und stelle sicher, "
            "dass ffmpeg.exe und ffprobe.exe im PATH liegen."
        )
    return path


def command_text(command: Iterable[object]) -> str:
    result = []
    for item in command:
        value = str(item)
        result.append(f'"{value}"' if " " in value else value)
    return " ".join(result)


def run_process(
    command: list[str],
    *,
    cwd: Optional[Path] = None,
    log: Optional[LogCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    capture: bool = False,
) -> str:
    check_cancel(cancel_event)
    if log:
        log("$ " + command_text(command))

    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )

    lines: list[str] = []
    assert process.stdout is not None
    while True:
        if cancel_event and cancel_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise CancelledError("Vorgang wurde abgebrochen.")

        line = process.stdout.readline()
        if line:
            line = line.rstrip()
            lines.append(line)
            if log and not capture:
                log(line)
        elif process.poll() is not None:
            break

    return_code = process.wait()
    output = "\n".join(lines)
    if return_code != 0:
        tail = "\n".join(lines[-20:])
        raise RuntimeError(
            f"Befehl fehlgeschlagen ({return_code}): {command_text(command)}"
            + (f"\n{tail}" if tail else "")
        )
    return output


def probe_duration(
    path: Path,
    *,
    cancel_event: Optional[threading.Event] = None,
) -> float:
    ffprobe = require_exe("ffprobe")
    output = run_process(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        cancel_event=cancel_event,
        capture=True,
    ).strip()
    try:
        return max(float(output.splitlines()[-1]), 0.0)
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"Audiodauer konnte nicht bestimmt werden: {path}") from exc


def extract_audio(
    source: Path,
    output_wav: Path,
    *,
    log: Optional[LogCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    ffmpeg = require_exe("ffmpeg")
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    run_process(
        [
            ffmpeg, "-y",
            "-i", str(source),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            str(output_wav),
        ],
        log=log,
        cancel_event=cancel_event,
    )
    return output_wav


def atempo_filters(speed_factor: float) -> list[str]:
    factor = max(float(speed_factor), 0.01)
    filters: list[str] = []
    while factor > 100.0:
        filters.append("atempo=100.0")
        factor /= 100.0
    while factor < 0.5:
        filters.append("atempo=0.5")
        factor /= 0.5
    if abs(factor - 1.0) > 0.0001:
        filters.append(f"atempo={factor:.8f}")
    return filters


def open_in_explorer(path: Path) -> None:
    target = path if path.is_dir() else path.parent
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
