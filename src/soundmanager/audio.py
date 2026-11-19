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

# Source codecs we can keep as-is (no quality loss) and the container to put them in.
COPYABLE: dict[str, str] = {"aac": ".m4a", "mp3": ".mp3", "vorbis": ".ogg"}


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


def _file_arg(path: Path) -> str:
    """Force ffmpeg to treat *path* as a plain local file.

    Without the `file:` prefix, a name like `concat:...` or `http:...` would be interpreted as an
    ffmpeg protocol instead of a file.
    """
    return "file:" + str(Path(path).resolve())


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        raise AudioError(f"{Path(cmd[0]).stem} failed: {tail}")
    return proc


def _ffmpeg(*args: str) -> None:
    _run([find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", *args])


def _probe(path: Path, *args: str) -> dict:
    out = _run([find_tool("ffprobe"), "-v", "error", *args, "-of", "json", _file_arg(path)]).stdout
    try:
        return json.loads(out)
    except ValueError as exc:
        raise AudioError(f"Couldn't read {Path(path).name}") from exc


def probe_duration(path: Path) -> float:
    try:
        return float(_probe(path, "-show_entries", "format=duration")["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AudioError(f"No duration found for {Path(path).name}") from exc


def audio_codec(path: Path) -> str | None:
    """Codec name of the first audio stream, or None if the file has no audio."""
    streams = _probe(path, "-select_streams", "a:0", "-show_entries", "stream=codec_name")
    streams = streams.get("streams") or []
    return streams[0].get("codec_name") if streams else None


def _encoder_args(dst: Path) -> list[str]:
    try:
        return ENCODERS[dst.suffix.lower()]
    except KeyError:
        raise AudioError(
            f"Unsupported output format {dst.suffix!r}; use {sorted(ENCODERS)}"
        ) from None


def extract_audio(src: Path, dst: Path) -> Path:
    """Strip the audio track out of a video (or re-encode any audio file) into *dst*."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-i", _file_arg(src), "-vn", "-map", "0:a:0", *_encoder_args(dst), _file_arg(dst))
    return dst


def best_audio_suffix(src: Path) -> tuple[str, bool]:
    """Pick an output container for *src*'s audio: (suffix, can_copy_without_re_encoding)."""
    codec = audio_codec(src)
    if codec is None:
        raise AudioError(f"{Path(src).name} has no audio track.")
    if codec in COPYABLE:
        return COPYABLE[codec], True
    return ".m4a", False


def extract_best(src: Path, dst_without_suffix: Path) -> Path:
    """Extract *src*'s audio, copying it untouched when the codec allows, else as AAC (.m4a)."""
    suffix, copy = best_audio_suffix(src)
    dst = dst_without_suffix.with_name(dst_without_suffix.name + suffix)
    dst.parent.mkdir(parents=True, exist_ok=True)
    codec_args = ["-c:a", "copy"] if copy else _encoder_args(dst)
    _ffmpeg("-i", _file_arg(src), "-vn", "-map", "0:a:0", *codec_args, _file_arg(dst))
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

    args = ["-ss", f"{spec.start:.3f}", "-to", f"{end:.3f}", "-i", _file_arg(src)]
    args += ["-vn", "-map", "0:a:0"]
    filters = build_filters(spec, end - spec.start)
    if filters:
        args += ["-af", ",".join(filters)]
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(*args, *_encoder_args(dst), _file_arg(dst))
    return dst
