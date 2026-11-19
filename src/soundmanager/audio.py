"""Audio extraction and editing via ffmpeg/ffprobe."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .tools import find_tool

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Output container -> ffmpeg encoder arguments. All of these play on Android.
ENCODERS: dict[str, list[str]] = {
    ".ogg": ["-c:a", "libvorbis", "-q:a", "6"],
    ".mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    ".m4a": ["-c:a", "aac", "-b:a", "192k"],
    ".wav": ["-c:a", "pcm_s16le"],
}


class AudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class EditSpec:
    """A non-destructive edit applied when exporting."""

    start: float = 0.0  # seconds
    end: float | None = None  # seconds; None = until the end
    fade_in: float = 0.0
    fade_out: float = 0.0
    gain_db: float = 0.0
    normalize: bool = False  # EBU R128 loudness normalization


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        raise AudioError(f"{Path(cmd[0]).stem} failed: {tail}")
    return proc


def probe_duration(path: Path) -> float:
    out = _run(
        [
            find_tool("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
    ).stdout
    try:
        return float(json.loads(out)["format"]["duration"])
    except (KeyError, ValueError) as exc:
        raise AudioError(f"No duration found for {path}") from exc


def _encoder_args(dst: Path) -> list[str]:
    try:
        return ENCODERS[dst.suffix.lower()]
    except KeyError:
        raise AudioError(
            f"Unsupported output format {dst.suffix!r}; use {sorted(ENCODERS)}"
        ) from None


def extract_audio(src: Path, dst: Path) -> Path:
    """Strip the audio track out of a video (or re-encode any audio file)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            find_tool("ffmpeg"),
            "-y",
            "-i",
            str(src),
            "-vn",
            "-map",
            "0:a:0",
            *_encoder_args(dst),
            str(dst),
        ]
    )
    return dst


def build_filters(spec: EditSpec, clip_duration: float) -> list[str]:
    filters = []
    if spec.gain_db:
        filters.append(f"volume={spec.gain_db}dB")
    if spec.normalize:
        filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    if spec.fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={spec.fade_in}")
    if spec.fade_out > 0:
        start = max(0.0, clip_duration - spec.fade_out)
        filters.append(f"afade=t=out:st={start:.3f}:d={spec.fade_out}")
    return filters


def export(src: Path, dst: Path, spec: EditSpec) -> Path:
    """Render *src* with *spec* applied into *dst* (format chosen from its extension)."""
    total = probe_duration(src)
    end = min(spec.end, total) if spec.end is not None else total
    if end <= spec.start:
        raise AudioError("Edit end must be after start")

    cmd = [
        find_tool("ffmpeg"),
        "-y",
        "-ss",
        f"{spec.start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        str(src),
        "-vn",
        "-map",
        "0:a:0",
    ]
    filters = build_filters(spec, end - spec.start)
    if filters:
        cmd += ["-af", ",".join(filters)]
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([*cmd, *_encoder_args(dst), str(dst)])
    return dst
