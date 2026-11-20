"""Installing the phone app from the desktop. No phone or Gradle build is touched."""

import os
from pathlib import Path

import pytest

from soundmanager import companion
from soundmanager.adb import AdbDevice, AdbError
from soundmanager.companion import Version

GRADLE = """
android {
    defaultConfig {
        minSdk = 26
        versionCode = 3
        versionName = "0.3.0"
    }
}
"""

DUMPSYS = """
Packages:
  Package [com.androidsoundmanager.app] (5f1c2a):
    userId=10345
    versionCode=2 minSdk=26 targetSdk=37
    versionName=0.2.0
"""


def test_versions_are_read_from_source_and_phone():
    assert companion.parse_source_version(GRADLE) == Version(3, "0.3.0")
    assert companion.parse_installed_version(DUMPSYS) == Version(2, "0.2.0")
    assert companion.parse_source_version("nothing") is None


class Dev(AdbDevice):
    def __init__(self, shell_out="", install_error=None):
        super().__init__("FAKE1")
        self.shell_out, self.install_error = shell_out, install_error
        self.calls = []

    def shell(self, command, timeout=60):
        self.calls.append(command)
        return self.shell_out

    def _adb(self, *args, timeout=60):
        self.calls.append(args)
        if args[0] == "install" and self.install_error:
            raise AdbError(self.install_error)
        return "Success\n"


def test_installed_version_on_phone():
    assert companion.installed_version(Dev(DUMPSYS)) == Version(2, "0.2.0")
    assert companion.installed_version(Dev("Dexopt state:\n")) is None  # not installed


def test_signature_mismatch_is_recognised():
    dev = Dev(install_error="Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures differ]")
    with pytest.raises(companion.SignatureMismatch):
        companion.install(dev, Path("app.apk"))
    other = Dev(install_error="Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]")
    with pytest.raises(AdbError):
        companion.install(other, Path("app.apk"))


def test_reinstall_uninstalls_only_this_app():
    dev = Dev()
    companion.reinstall(dev, Path("app.apk"))
    assert dev.calls == [
        ("uninstall", "com.androidsoundmanager.app"),
        ("install", "-r", "app.apk"),
    ]


def make_project(root: Path) -> Path:
    (root / "app" / "src" / "main").mkdir(parents=True)
    (root / "app" / "build.gradle.kts").write_text(GRADLE)
    (root / "app" / "src" / "main" / "Main.kt").write_text("fun main() {}")
    return root


def test_needs_build_when_apk_missing_or_older_than_source(tmp_path):
    root = make_project(tmp_path)
    assert companion.available(root)
    assert companion.needs_build(root)  # never built

    apk = root / companion.APK_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    source = root / "app" / "src" / "main" / "Main.kt"
    os.utime(source, (1_000_000, 1_000_000))
    os.utime(root / "app" / "build.gradle.kts", (1_000_000, 1_000_000))
    os.utime(apk, (2_000_000, 2_000_000))
    assert not companion.needs_build(root)

    os.utime(source, (3_000_000, 3_000_000))  # source edited after the build
    assert companion.needs_build(root)


def test_not_available_outside_the_repository(tmp_path):
    assert not companion.available(tmp_path)
    with pytest.raises(companion.CompanionError):
        companion.build(tmp_path)


def test_build_without_java_explains(monkeypatch, tmp_path):
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "nope"))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    with pytest.raises(companion.CompanionError, match="Android Studio"):
        companion.find_java_home()
