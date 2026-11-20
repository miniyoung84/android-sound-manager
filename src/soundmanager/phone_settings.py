"""Open specific Android settings screens on the phone (for things the desktop can't set itself).

Per-conversation message sounds belong to the messaging app's "conversation" notification
channels. Android doesn't let other apps (or ADB on retail phones, which masks conversation IDs)
change them, so the desktop opens the right settings screen and the user picks the sound there.
"""

from __future__ import annotations

import re
import shlex

from .adb import AdbDevice, AdbError

_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
FALLBACK_MESSAGING_APP = "com.google.android.apps.messaging"


def valid_package(name: str | None) -> bool:
    return bool(name) and len(name) <= 200 and bool(_PACKAGE.match(name))


def default_messaging_app(dev: AdbDevice) -> str:
    """The phone's default SMS/RCS app package (e.g. Google Messages or Samsung Messages)."""
    value = dev.shell("settings get secure sms_default_application").strip()
    return value if valid_package(value) else FALLBACK_MESSAGING_APP


def start_settings(dev: AdbDevice, *args: str) -> None:
    """Wake the phone and run `am start` with *args* (each one quoted for the phone's shell)."""
    dev.shell("input keyevent KEYCODE_WAKEUP")  # turn the screen on; the user still unlocks
    out = dev.shell("am start --user current " + " ".join(shlex.quote(a) for a in args))
    if "Error" in out or "unable to resolve" in out.lower():
        raise AdbError("The phone couldn't open that settings screen.")


def open_conversation_settings(dev: AdbDevice) -> None:
    """Settings > Notifications > Conversations (recent and priority conversations)."""
    start_settings(dev, "-a", "android.settings.CONVERSATION_SETTINGS")


def open_app_notification_settings(dev: AdbDevice, package: str) -> None:
    """An app's notification settings page (all its categories)."""
    if not valid_package(package):
        raise AdbError("Not a valid app package name.")
    start_settings(
        dev,
        "-a",
        "android.settings.APP_NOTIFICATION_SETTINGS",
        "--es",
        "android.provider.extra.APP_PACKAGE",
        package,
    )
