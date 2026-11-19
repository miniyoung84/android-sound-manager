"""Thin wrapper around the `adb` command line for talking to a USB/Wi-Fi connected phone."""

from __future__ import annotations

import posixpath
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

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AdbError(RuntimeError):
    pass


def is_in_sound_folder(remote: str) -> bool:
    """True only for a file directly inside one of SOUND_FOLDERS (no `..` tricks, no subdirs)."""
    if "\x00" in remote or "\n" in remote:
        return False
    normalized = posixpath.normpath(remote)
    return normalized == remote and posixpath.dirname(normalized) in SOUND_FOLDERS.values()


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
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"adb timed out: {' '.join(args)}") from exc
    if proc.returncode != 0:
        raise AdbError((proc.stderr or proc.stdout).strip() or f"adb exited {proc.returncode}")
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
    """Parse lines of `stat -c '%s|%Y|%n'` output."""
    files = []
    for line in output.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3 or not parts[0].isdigit():
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

    def push(self, local: Path, remote_dir: str) -> str:
        remote = str(PurePosixPath(remote_dir) / local.name)
        if not is_in_sound_folder(remote):
            raise AdbError(f"Refusing to upload outside the sound folders: {remote}")
        self.shell(f"mkdir -p {shlex.quote(remote_dir)}")
        self._adb("push", str(local), remote, timeout=600)
        return remote

    def pull(self, remote: str, local_dir: Path) -> Path:
        local_dir.mkdir(parents=True, exist_ok=True)
        dest = local_dir / PurePosixPath(remote).name
        self._adb("pull", remote, str(dest), timeout=600)
        return dest

    def delete(self, remote: str) -> None:
        if not is_in_sound_folder(remote):
            raise AdbError(f"Refusing to delete outside the sound folders: {remote}")
        self.shell(f"rm -f {shlex.quote(remote)}")
