"""Download audio from YouTube (or any yt-dlp supported site).

Only download content you have the rights to use.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .tools import ToolNotFoundError, find_tool

ProgressCallback = Callable[[float], None]  # 0.0 - 1.0


def _js_runtimes() -> dict[str, dict[str, str]]:
    # YouTube extraction needs a JS runtime (yt-dlp >= 2025.11). Prefer Node, else yt-dlp's default.
    try:
        return {"node": {"path": find_tool("node")}}
    except ToolNotFoundError:
        return {"deno": {}}


def build_options(
    out_dir: Path,
    codec: str = "vorbis",
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    def hook(d: dict[str, Any]) -> None:
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    return {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(title).120B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": str(Path(find_tool("ffmpeg")).parent),
        "js_runtimes": _js_runtimes(),
        # Trust the OS certificate store instead of certifi's bundle, so HTTPS works behind
        # antivirus TLS scanning (e.g. Avast Web Shield) and corporate proxies.
        "compat_opts": {"no-certifi"},
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": codec}],
        "progress_hooks": [hook],
    }


def download_audio(
    url: str, out_dir: Path, codec: str = "vorbis", progress: ProgressCallback | None = None
) -> Path:
    """Download *url* as audio into *out_dir*; returns the final file path."""
    import yt_dlp  # imported lazily: it is slow to import

    out_dir.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL(build_options(out_dir, codec, progress)) as ydl:
        info = ydl.extract_info(url, download=True)
        requested = info.get("requested_downloads") or []
        if requested and requested[0].get("filepath"):
            return Path(requested[0]["filepath"])
        return Path(ydl.prepare_filename(info)).with_suffix(
            ".ogg" if codec == "vorbis" else f".{codec}"
        )
