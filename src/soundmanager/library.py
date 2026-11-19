"""The local sound library: a folder on the PC holding sounds ready to send to the phone."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import audio
from .adb import safe_local_name, unique_path

DEFAULT_LIBRARY = Path.home() / "Music" / "Android Sound Manager"
AUDIO_EXTENSIONS = (".mp3", ".ogg", ".m4a", ".wav", ".opus", ".flac", ".aac")
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".wmv", ".flv", ".3gp", ".ts")
# Formats every Android phone plays as a ringtone; anything else is converted on import.
PHONE_READY = (".mp3", ".ogg", ".m4a")


@dataclass(frozen=True)
class LibraryItem:
    path: Path
    size: int
    mtime: float
    duration: float | None  # seconds; None if it couldn't be read

    @property
    def name(self) -> str:
        return self.path.name


def list_library(directory: Path, with_duration: bool = True) -> list[LibraryItem]:
    if not directory.is_dir():
        return []
    items = []
    for p in directory.iterdir():
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXTENSIONS or p.name.startswith("."):
            continue
        st = p.stat()
        duration = None
        if with_duration:
            with contextlib.suppress(audio.AudioError):
                duration = audio.probe_duration(p)
        items.append(LibraryItem(p, st.st_size, st.st_mtime, duration))
    return sorted(items, key=lambda i: i.name.casefold())


def import_file(src: Path, library: Path) -> Path:
    """Bring *src* into the library and return the new file.

    Phone-ready audio is copied as-is. Anything else (videos, FLAC, WAV, Opus...) has its audio
    extracted, untouched if the codec allows, else converted to AAC. The original is never
    modified, and nothing in the library is overwritten.
    """
    src = Path(src).resolve()
    library = Path(library).resolve()
    if not src.is_file():
        raise audio.AudioError(f"{src.name} isn't a file.")
    library.mkdir(parents=True, exist_ok=True)
    if src.parent == library:
        return src  # already in the library

    stem = safe_local_name(src.stem) or "sound"
    if src.suffix.lower() in PHONE_READY and audio.audio_codec(src) is not None:
        dest = unique_path(library / f"{stem}{src.suffix.lower()}")
        _atomic_copy(src, dest)
        return dest

    # Extract into a temp folder first so a failure never leaves a broken file in the library.
    with tempfile.TemporaryDirectory(prefix="asm-import-") as tmp:
        out = audio.extract_best(src, Path(tmp) / "audio")
        dest = unique_path(library / f"{stem}{out.suffix}")
        shutil.move(str(out), dest)
    return dest


def _atomic_copy(src: Path, dest: Path) -> None:
    part = dest.with_name(dest.name + ".part")
    try:
        shutil.copy2(src, part)
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"
