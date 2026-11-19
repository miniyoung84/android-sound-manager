"""Locate the external command-line tools the app drives (adb, ffmpeg, ffprobe, node).

Each tool can be overridden with an environment variable, e.g. SOUNDMANAGER_ADB=C:\\path\\adb.exe.
"""

from __future__ import annotations

import os
import shutil
from functools import cache
from pathlib import Path


class ToolNotFoundError(RuntimeError):
    pass


def _fallback_locations(name: str) -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if name == "adb":
        sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        candidates = [Path(sdk) / "platform-tools"] if sdk else []
        candidates.append(local / "Android" / "Sdk" / "platform-tools")
        return [c / "adb.exe" for c in candidates] + [c / "adb" for c in candidates]
    if name in ("ffmpeg", "ffprobe"):
        # winget's Gyan.FFmpeg package lives under a versioned folder.
        pkgs = local / "Microsoft" / "WinGet" / "Packages"
        return sorted(pkgs.glob(f"Gyan.FFmpeg*/*/bin/{name}.exe"), reverse=True)
    if name == "node":
        return [Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "nodejs" / "node.exe"]
    return []


@cache
def find_tool(name: str) -> str:
    """Return an absolute path to *name*, or raise ToolNotFoundError."""
    override = os.environ.get(f"SOUNDMANAGER_{name.upper()}")
    if override:
        if Path(override).is_file():
            return override
        raise ToolNotFoundError(f"SOUNDMANAGER_{name.upper()} points to a missing file: {override}")

    found = shutil.which(name)
    if found:
        return found
    for candidate in _fallback_locations(name):
        if candidate.is_file():
            return str(candidate)
    raise ToolNotFoundError(
        f"Could not find '{name}'. Install it or set SOUNDMANAGER_{name.upper()}."
    )


def tool_status() -> dict[str, str | None]:
    """Map each tool name to its path, or None if missing. Used by the UI and setup checks."""
    status: dict[str, str | None] = {}
    for name in ("adb", "ffmpeg", "ffprobe", "node"):
        try:
            status[name] = find_tool(name)
        except ToolNotFoundError:
            status[name] = None
    return status


if __name__ == "__main__":
    for tool, path in tool_status().items():
        print(f"  {tool:8} {path or 'MISSING'}")
