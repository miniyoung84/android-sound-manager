"""Thin wrapper around the `adb` command line for talking to a USB/Wi-Fi connected phone."""

from __future__ import annotations

import contextlib
import os
import posixpath
import re
import secrets
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .tools import find_tool

# Shared storage folders that Android's (and Samsung's) sound pickers scan.
SOUND_FOLDERS: dict[str, str] = {
    "Ringtones": "/sdcard/Ringtones",
    "Notifications": "/sdcard/Notifications",
    "Alarms": "/sdcard/Alarms",
}

# Uploads land under a hidden temporary name first and are renamed into place only once the
# whole file has arrived, so an unplugged cable never leaves a half-written sound behind.
PARTIAL_SUFFIX = ".asm-part"

# adb error text that means the phone went away (unplugged, rebooted, USB debugging revoked).
_DISCONNECT_MARKERS = (
    "not found",
    "no devices",
    "device offline",
    "device unauthorized",
    "closed",
    "protocol fault",
    "connection reset",
    "transport",
    "timed out",
)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AdbError(RuntimeError):
    pass


def is_disconnect_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, AdbError) and any(m in text for m in _DISCONNECT_MARKERS)


def is_in_sound_folder(remote: str) -> bool:
    """True only for a file directly inside one of SOUND_FOLDERS (no `..` tricks, no subdirs)."""
    if "\x00" in remote or "\n" in remote:
        return False
    normalized = posixpath.normpath(remote)
    return normalized == remote and posixpath.dirname(normalized) in SOUND_FOLDERS.values()


# --------------------------------------------------------------------------- local file names

_WINDOWS_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def safe_local_name(name: str) -> str:
    """Make a phone file name safe to create on Windows.

    Android allows characters such as `\\` and `:` in names. On Windows `\\` is a path
    separator, so a phone file named `..\\..\\x.mp3` could otherwise escape the target folder.
    """
    cleaned = _WINDOWS_BAD.sub("_", name).strip(" .") or "sound"
    if cleaned.split(".", 1)[0].lower() in _WINDOWS_RESERVED:
        cleaned = "_" + cleaned
    return cleaned[:200]


def unique_path(path: Path) -> Path:
    """*path*, or `name (2).ext`, `name (3).ext`, ... if it already exists."""
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate


# --------------------------------------------------------------------------- data types


@dataclass(frozen=True)
class Device:
    serial: str
    state: str  # "device", "unauthorized", "offline", ...
    model: str = ""
    product: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "device"

    @property
    def label(self) -> str:
        name = self.model.replace("_", " ") or self.serial
        return name if self.ready else f"{name} ({self.state})"


@dataclass(frozen=True)
class RemoteFile:
    path: str
    size: int
    mtime: int

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name


# --------------------------------------------------------------------------- adb plumbing


def _run(args: list[str], timeout: float = 60) -> str:
    cmd = [find_tool("adb"), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb timed out: {' '.join(args[:3])}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise AdbError(detail or "The connection to the phone was interrupted.")
    return proc.stdout


def parse_devices(output: str) -> list[Device]:
    """Parse the output of `adb devices -l`."""
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("List of devices", "*")):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        extras = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        devices.append(
            Device(parts[0], parts[1], extras.get("model", ""), extras.get("product", ""))
        )
    return devices


def list_devices() -> list[Device]:
    return parse_devices(_run(["devices", "-l"], timeout=15))


def parse_stat_listing(output: str) -> list[RemoteFile]:
    """Parse lines of `stat -c '%s|%Y|%n'` output, skipping hidden files."""
    files = []
    for line in output.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        if PurePosixPath(parts[2]).name.startswith("."):  # hidden, incl. unfinished uploads
            continue
        files.append(RemoteFile(path=parts[2], size=int(parts[0]), mtime=int(parts[1])))
    return sorted(files, key=lambda f: f.name.lower())


class AdbDevice:
    """Commands targeted at one device serial."""

    def __init__(self, serial: str):
        self.serial = serial

    def _adb(self, *args: str, timeout: float = 60) -> str:
        return _run(["-s", self.serial, *args], timeout=timeout)

    def shell(self, command: str, timeout: float = 60) -> str:
        return self._adb("shell", command, timeout=timeout)

    def getprop(self, key: str) -> str:
        return self.shell(f"getprop {shlex.quote(key)}").strip()

    def friendly_name(self) -> str:
        """The name the user gave the phone (Settings > About phone), else its marketing name."""
        for cmd in ("settings get global device_name", "getprop ro.product.marketname"):
            value = self.shell(cmd).strip()
            if value and value != "null":
                return value[:64]
        return ""

    def list_dir(self, remote_dir: str) -> list[RemoteFile]:
        d = shlex.quote(remote_dir)
        out = self.shell(
            f"[ -d {d} ] && find {d} -maxdepth 1 -type f -exec stat -c '%s|%Y|%n' {{}} + ; true"
        )
        return parse_stat_listing(out)

    def remote_size(self, remote: str) -> int | None:
        out = self.shell(f"stat -c %s {shlex.quote(remote)} 2>/dev/null; true").strip()
        return int(out) if out.isdigit() else None

    def push(self, local: Path, remote_dir: str) -> str:
        """Upload *local* into *remote_dir*, replacing any file of the same name.

        The file is copied to a hidden temporary name, its size is checked, and only then is it
        renamed over the final name (a rename is atomic). If the phone disconnects midway, any
        existing file is untouched and the leftover temp file is removed on the next connect.
        """
        remote = str(PurePosixPath(remote_dir) / local.name)
        if not is_in_sound_folder(remote):
            raise AdbError(f"Refusing to upload outside the sound folders: {remote}")
        size = local.stat().st_size
        temp = str(PurePosixPath(remote_dir) / f".{secrets.token_hex(6)}{PARTIAL_SUFFIX}")
        self.shell(f"mkdir -p {shlex.quote(remote_dir)}")
        try:
            self._adb("push", str(local), temp, timeout=600)
            if self.remote_size(temp) != size:
                raise AdbError(f"Upload of {local.name} was incomplete; nothing was changed.")
            self.shell(f"mv -f {shlex.quote(temp)} {shlex.quote(remote)}")
        except AdbError:
            with contextlib.suppress(AdbError):  # best effort: the phone may already be gone
                self.shell(f"rm -f {shlex.quote(temp)}", timeout=10)
            raise
        return remote

    def pull(self, remote: str, local_dir: Path) -> Path:
        """Download *remote* into *local_dir*, never overwriting or leaving a partial file."""
        local_dir.mkdir(parents=True, exist_ok=True)
        dest = unique_path(local_dir / safe_local_name(PurePosixPath(remote).name))
        part = dest.with_name(dest.name + ".part")
        try:
            self._adb("pull", remote, str(part), timeout=600)
            os.replace(part, dest)
        finally:
            part.unlink(missing_ok=True)
        return dest

    def cleanup_partial_uploads(self) -> None:
        """Remove temp files left behind by uploads that a disconnect interrupted."""
        pattern = shlex.quote(".*" + PARTIAL_SUFFIX)
        for folder in SOUND_FOLDERS.values():
            d = shlex.quote(folder)
            self.shell(f"[ -d {d} ] && find {d} -maxdepth 1 -type f -name {pattern} -delete; true")

    def delete(self, remote: str) -> None:
        if not is_in_sound_folder(remote):
            raise AdbError(f"Refusing to delete outside the sound folders: {remote}")
        self.shell(f"rm -f {shlex.quote(remote)}")
