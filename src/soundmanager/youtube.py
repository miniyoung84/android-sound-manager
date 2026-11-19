"""Download audio from YouTube (or another yt-dlp supported site) into the library.

Only download content you have the rights to use.

Safety limits: http(s) links only, one video per link (never a whole playlist), at most
MAX_DURATION_S long and MAX_FILESIZE bytes, partial files kept out of the library, and a
cancel button that stops the transfer.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .tools import ToolNotFoundError, find_tool

ProgressCallback = Callable[[float], None]  # 0.0 - 1.0
MAX_DURATION_S = 60 * 60  # ringtones don't need more than an hour of source
MAX_FILESIZE = 200 * 1024 * 1024
MAX_URL_LENGTH = 2048


class YoutubeError(RuntimeError):
    pass


class Cancelled(YoutubeError):
    pass


def validate_url(text: str) -> str:
    """Return a cleaned http(s) URL, or raise YoutubeError for anything else."""
    url = (text or "").strip()
    if not url:
        raise YoutubeError("Paste a link first.")
    if len(url) > MAX_URL_LENGTH or any(c.isspace() or ord(c) < 32 for c in url):
        raise YoutubeError("That doesn't look like a single web link.")
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise YoutubeError("Only http:// and https:// links can be downloaded.")
    return url


def _js_runtimes() -> dict[str, dict[str, str]]:
    # YouTube extraction needs a JS runtime (yt-dlp >= 2025.11). Prefer Node, else yt-dlp's default.
    try:
        return {"node": {"path": find_tool("node")}}
    except ToolNotFoundError:
        return {"deno": {}}


def build_options(
    out_dir: Path,
    temp_dir: Path,
    codec: str = "m4a",
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    import yt_dlp

    def hook(d: dict[str, Any]) -> None:
        if cancel is not None and cancel.is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled")
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    return {
        "format": "bestaudio/best",
        "paths": {"home": str(out_dir), "temp": str(temp_dir)},
        "outtmpl": "%(title).120B [%(id)s].%(ext)s",
        "windowsfilenames": True,
        "noplaylist": True,
        "playlist_items": "1",  # a bare playlist link still yields only its first video
        "max_filesize": MAX_FILESIZE,
        "match_filter": yt_dlp.utils.match_filter_func(f"duration <= {MAX_DURATION_S}"),
        "socket_timeout": 30,
        "retries": 3,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": str(Path(find_tool("ffmpeg")).parent),
        "js_runtimes": _js_runtimes(),
        # Trust the OS certificate store instead of certifi's bundle, so HTTPS works behind
        # antivirus TLS scanning (e.g. Avast Web Shield) and corporate proxies.
        "compat_opts": {"no-certifi"},
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": codec}],
        "progress_hooks": [hook],
    }


def installed_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("yt-dlp")
    except PackageNotFoundError:
        return "not installed"


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def update_downloader() -> tuple[str, str]:
    """Upgrade yt-dlp inside this app's own Python environment. Returns (old, new) versions.

    YouTube changes often, and an outdated yt-dlp is the usual reason downloads stop working.
    pip is run directly (no shell) with a fixed package name, over HTTPS with verification.
    The new version is used the next time the app starts.
    """
    old = installed_version()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--disable-pip-version-check",
            "--no-input",
            "yt-dlp[default]",
        ],  # fmt: skip
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=300,
        creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        raise YoutubeError("Couldn't update the downloader:\n" + "\n".join(tail))
    # Ask a fresh interpreter, since this process still has the old version loaded.
    new = subprocess.run(
        [sys.executable, "-c", "import importlib.metadata as m; print(m.version('yt-dlp'))"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        creationflags=_NO_WINDOW,
    ).stdout.strip()
    return old, new or "unknown"


def _clean_error(exc: Exception) -> str:
    text = str(exc).replace("ERROR: ", "").strip()
    return text.splitlines()[0][:300] if text else "The download failed."


def download_audio(
    url: str,
    out_dir: Path,
    codec: str = "m4a",
    progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download *url* as audio into *out_dir*; returns the final file path."""
    import yt_dlp  # imported lazily: it is slow to import

    url = validate_url(url)
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="asm-dl-"))
    try:
        with yt_dlp.YoutubeDL(build_options(out_dir, temp_dir, codec, progress, cancel)) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and info.get("entries") is not None:  # playlist wrapper: take its one entry
                entries = [e for e in info["entries"] if e]
                info = entries[0] if entries else None
            requested = (info or {}).get("requested_downloads") or []
            if requested and requested[0].get("filepath"):
                path = Path(requested[0]["filepath"])
                if path.is_file():
                    return path
            if info and (info.get("duration") or 0) > MAX_DURATION_S:
                raise YoutubeError("That video is longer than an hour; pick a shorter one.")
            raise YoutubeError("Nothing was downloaded (the video may be too large or private).")
    except yt_dlp.utils.DownloadCancelled as exc:
        raise Cancelled("Download cancelled.") from exc
    except yt_dlp.utils.YoutubeDLError as exc:
        if cancel is not None and cancel.is_set():
            raise Cancelled("Download cancelled.") from exc
        raise YoutubeError(_clean_error(exc)) from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)  # partial files never reach the library
