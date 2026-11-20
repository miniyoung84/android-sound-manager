"""Install or update the phone app (the Android companion in `android/`) from the desktop.

The app is built from the source in this repository with Gradle (using the Java that comes with
Android Studio) and installed with `adb install -r`. Nothing is downloaded from the internet
except what Gradle itself fetches for the build, and no permissions are granted automatically:
the phone app still asks for each one itself.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .adb import AdbDevice, AdbError

PACKAGE = "com.androidsoundmanager.app"
ANDROID_DIR = Path(__file__).resolve().parents[2] / "android"
APK_PATH = Path("app/build/outputs/apk/debug/app-debug.apk")
# Files whose changes mean the APK has to be rebuilt.
SOURCE_PATHS = (
    Path("app/src/main"),
    Path("app/build.gradle.kts"),
    Path("build.gradle.kts"),
    Path("settings.gradle.kts"),
    Path("gradle/libs.versions.toml"),
)
BUILD_TIMEOUT = 30 * 60

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class CompanionError(RuntimeError):
    pass


class SignatureMismatch(CompanionError):
    """The phone has a copy signed with a different key, so Android refuses the update."""


@dataclass(frozen=True, order=True)
class Version:
    code: int
    name: str


def available(android_dir: Path = ANDROID_DIR) -> bool:
    """True when the app's source is here (running from the repository)."""
    return (android_dir / "app" / "build.gradle.kts").is_file()


def parse_source_version(gradle_text: str) -> Version | None:
    code = re.search(r"^\s*versionCode\s*=\s*(\d+)", gradle_text, re.M)
    name = re.search(r'^\s*versionName\s*=\s*"([^"\n]+)"', gradle_text, re.M)
    return Version(int(code.group(1)), name.group(1)) if code and name else None


def source_version(android_dir: Path = ANDROID_DIR) -> Version | None:
    try:
        text = (android_dir / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_source_version(text)


def parse_installed_version(dumpsys: str) -> Version | None:
    """Read versionCode / versionName from `dumpsys package <name>` output."""
    code = re.search(r"\bversionCode=(\d+)", dumpsys)
    name = re.search(r"\bversionName=(\S+)", dumpsys)
    return Version(int(code.group(1)), name.group(1)) if code and name else None


def installed_version(dev: AdbDevice) -> Version | None:
    """The phone app's version on *dev*, or None if it isn't installed."""
    out = dev.shell(f"dumpsys package {PACKAGE}")
    # dumpsys prints the package's section only when it's installed.
    if f"Package [{PACKAGE}]" not in out:
        return None
    return parse_installed_version(out)


def _newest_mtime(paths: list[Path]) -> float:
    newest = 0.0
    for p in paths:
        if p.is_file():
            newest = max(newest, p.stat().st_mtime)
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    newest = max(newest, f.stat().st_mtime)
    return newest


def needs_build(android_dir: Path = ANDROID_DIR) -> bool:
    """True if the APK is missing or older than the app's source."""
    apk = android_dir / APK_PATH
    if not apk.is_file():
        return True
    sources = [android_dir / p for p in SOURCE_PATHS]
    return _newest_mtime(sources) > apk.stat().st_mtime


def find_java_home() -> Path:
    """The Java to build with: JAVA_HOME, else the one bundled with Android Studio."""
    java = "java.exe" if os.name == "nt" else "java"
    candidates = []
    if env := os.environ.get("JAVA_HOME"):
        candidates.append(Path(env))
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    candidates.append(program_files / "Android" / "Android Studio" / "jbr")
    for c in candidates:
        if (c / "bin" / java).is_file():
            return c
    raise CompanionError(
        "Building the phone app needs Android Studio (for its Java). Install it, or set "
        "JAVA_HOME to a Java 17+ installation."
    )


def build(android_dir: Path = ANDROID_DIR) -> Path:
    """Build the APK. Runs Gradle at low priority without leaving a background daemon."""
    if not available(android_dir):
        raise CompanionError("The phone app's source isn't here, so it can't be built.")
    gradlew = android_dir / ("gradlew.bat" if os.name == "nt" else "gradlew")
    env = dict(os.environ, JAVA_HOME=str(find_java_home()))
    cmd = [
        str(gradlew),
        "assembleDebug",
        "--no-daemon",
        "--priority",
        "low",
        # Compile Kotlin inside the build too, so no Kotlin daemon stays behind afterwards.
        "-Pkotlin.compiler.execution.strategy=in-process",
        "--console=plain",
        "-q",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=android_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=BUILD_TIMEOUT,
            stdin=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise CompanionError("Building the phone app took too long and was stopped.") from exc
    except OSError as exc:
        raise CompanionError(f"Couldn't start the build: {exc}") from exc
    apk = android_dir / APK_PATH
    if proc.returncode != 0 or not apk.is_file():
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-12:])
        raise CompanionError(f"Building the phone app failed:\n\n{tail}")
    return apk


def install(dev: AdbDevice, apk: Path) -> None:
    """Install or update the phone app. Android keeps its data and permissions on update."""
    try:
        dev.install(apk)
    except AdbError as exc:
        if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in str(exc):
            raise SignatureMismatch(
                "The phone has a copy of the app that was signed on a different computer, so "
                "Android won't update it in place."
            ) from exc
        raise


def reinstall(dev: AdbDevice, apk: Path) -> None:
    """Uninstall, then install. Only after the user agreed: the app's permissions are reset."""
    dev.uninstall(PACKAGE)
    dev.install(apk)
