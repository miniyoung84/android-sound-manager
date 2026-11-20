"""Other apps' notification categories ("channels") and the sound each one plays.

Android doesn't let anything but the owning app (or the user, in Settings) change a channel's
sound. What the desktop can do is read the channels from `dumpsys notification`, show which
sound each one uses, and open that exact channel's settings screen on the phone.

The notification dump also contains recent notification text, so its raw output is parsed in
memory only and never logged or saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .adb import AdbDevice, AdbError
from .phone_contacts import describe_ringtones
from .phone_settings import start_settings, valid_package

DEFAULT_NOTIFICATION_URI = "content://settings/system/notification_sound"
MAX_CHANNEL_ID = 1000  # Android's own limit for channel IDs
MAIN_USER = 0  # channels of work profiles, Secure Folder, Dual Messenger, etc. are skipped
IMPORTANCE_DEFAULT = 3  # channels below this never make a sound

_APP_RE = re.compile(r"^\s+AppSettings: (\S+) \((\d+)\)(.*)$")
_CHANNEL_RE = re.compile(r"^\s+NotificationChannel\{mId='(.*?)', mName=(.*?), mDescription=(.*)$")
_GROUP_RE = re.compile(r"^\s+NotificationChannelGroup\{mId='(.*?)', mName=(.*?), mDescription=")

# Friendly names for common apps; others are derived from the package name.
KNOWN_APPS = {
    "com.google.android.apps.messaging": "Messages",
    "com.samsung.android.messaging": "Samsung Messages",
    "com.google.android.gm": "Gmail",
    "com.google.android.apps.dynamite": "Google Chat",
    "com.google.android.calendar": "Google Calendar",
    "com.google.android.youtube": "YouTube",
    "com.google.android.apps.youtube.music": "YouTube Music",
    "com.google.android.apps.photos": "Google Photos",
    "com.google.android.dialer": "Phone by Google",
    "com.samsung.android.dialer": "Phone",
    "com.samsung.android.calendar": "Samsung Calendar",
    "com.sec.android.app.clockpackage": "Clock",
    "com.android.chrome": "Chrome",
    "com.android.vending": "Play Store",
    "com.discord": "Discord",
    "com.instagram.android": "Instagram",
    "com.facebook.katana": "Facebook",
    "com.facebook.orca": "Messenger",
    "com.whatsapp": "WhatsApp",
    "com.snapchat.android": "Snapchat",
    "com.zhiliaoapp.musically": "TikTok",
    "com.reddit.frontpage": "Reddit",
    "com.twitter.android": "X",
    "com.Slack": "Slack",
    "com.microsoft.teams": "Teams",
    "com.microsoft.office.outlook": "Outlook",
    "org.telegram.messenger": "Telegram",
    "org.thoughtcrime.securesms": "Signal",
    "com.spotify.music": "Spotify",
    "us.zoom.videomeetings": "Zoom",
}
_GENERIC = {
    "com", "org", "net", "io", "co", "us", "uk", "de", "me", "tv", "app", "apps", "android",
    "mobile", "client", "main", "sec", "free",
}  # fmt: skip


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    importance: int  # 0 blocked, 1-2 silent, 3+ makes a sound; -1000 = not set
    sound: str | None  # None = silent
    group: str = ""
    conversation: bool = False

    @property
    def silent(self) -> bool:
        return self.sound is None or 0 <= self.importance < IMPORTANCE_DEFAULT


@dataclass
class App:
    package: str
    blocked: bool = False  # the user turned off all of this app's notifications
    channels: list[Channel] = field(default_factory=list)

    @property
    def name(self) -> str:
        return app_label(self.package)


def app_label(package: str) -> str:
    if package in KNOWN_APPS:
        return KNOWN_APPS[package]
    words = [w for w in package.split(".") if w.lower() not in _GENERIC]
    word = words[0] if words else package.rsplit(".", 1)[-1]
    return word[:1].upper() + word[1:]


def _field(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _parse_channel(line: str, groups: dict[str, str]) -> Channel | None:
    m = _CHANNEL_RE.match(line)
    if not m:
        return None
    channel_id, name, rest = m.groups()
    if _field(rest, r", mDeleted=(true|false)") == "true":
        return None
    importance = _field(rest, r", mImportance=(-?\d+)")
    sound = _field(rest, r", mSound=(.*?), mLights=")
    conversation = _field(rest, r", mConversationId=(.*?)[,}]")
    group = _field(rest, r", mGroup='(.*?)'")
    return Channel(
        id=channel_id,
        name=name or channel_id,
        importance=int(importance) if importance else -1000,
        sound=None if sound in (None, "", "null") else sound,
        group=groups.get(group or "", ""),
        conversation=conversation not in (None, "null"),
    )


def parse_channels(dump: str, user: int = MAIN_USER) -> list[App]:
    """Apps with at least one notification channel, from `dumpsys notification --noredact`."""
    apps: list[App] = []
    current: App | None = None
    pending: list[str] = []  # an app's channel lines; groups may be listed after them
    groups: dict[str, str] = {}
    in_prefs = False

    def finish() -> None:
        if current is None:
            return
        current.channels = [c for line in pending if (c := _parse_channel(line, groups))]
        if current.channels:
            apps.append(current)

    for line in dump.splitlines():
        if line.strip() == "PackagePreferences:":
            in_prefs = True
            continue
        if not in_prefs:
            continue
        if line and not line[0].isspace():
            break  # end of the preferences section
        if m := _APP_RE.match(line):
            finish()
            package, uid, extra = m.group(1), int(m.group(2)), m.group(3)
            pending, groups = [], {}
            current = None
            if uid // 100000 == user and valid_package(package):
                current = App(package, blocked="importance=NONE" in extra)
        elif current is not None:
            if "NotificationChannel{" in line:
                pending.append(line)
            elif g := _GROUP_RE.match(line):
                groups[g.group(1)] = g.group(2)
    finish()
    return apps


def parse_launcher_packages(output: str) -> set[str]:
    """Packages from `cmd package query-activities --components` (one pkg/activity per line)."""
    found = set()
    for line in output.splitlines():
        package = line.strip().split("/", 1)[0]
        if "/" in line and valid_package(package):
            found.add(package)
    return found


def list_apps(dev: AdbDevice, launcher_only: bool = True) -> list[App]:
    """Apps (sorted by name) whose notification channels the user can change."""
    apps = parse_channels(dev.shell("dumpsys notification --noredact", timeout=60))
    if launcher_only:
        launcher = parse_launcher_packages(
            dev.shell(
                "cmd package query-activities --components --user 0 "
                "-a android.intent.action.MAIN -c android.intent.category.LAUNCHER"
            )
        )
        if launcher:  # if the query isn't supported, show everything rather than nothing
            apps = [a for a in apps if a.package in launcher]
    return sorted(apps, key=lambda a: (a.name.casefold(), a.package))


def describe_sounds(dev: AdbDevice, apps: list[App]) -> dict[str, str]:
    """Readable labels for every channel sound URI in *apps*."""
    uris = {c.sound for a in apps for c in a.channels if c.sound}
    media = {u for u in uris if u.startswith("content://") and "media/" in u}
    labels = describe_ringtones(dev, media) if media else {}
    for uri in uris - media:
        labels[uri] = sound_label(uri)
    return labels


def sound_label(uri: str | None) -> str:
    if uri is None:
        return "Silent"
    if uri == DEFAULT_NOTIFICATION_URI:
        return "Default notification sound"
    if uri.startswith("content://settings/system/"):
        return "Phone's " + uri.rsplit("/", 1)[-1].replace("_", " ")
    if uri.startswith("android.resource://"):
        return "App's own sound"
    if uri.startswith("file://"):
        name = uri.rsplit("/", 1)[-1]
        return name.rsplit(".", 1)[0] or "Custom sound"
    return "Custom sound"


def valid_channel_id(channel_id: str) -> bool:
    return 0 < len(channel_id) <= MAX_CHANNEL_ID and not any(ch in channel_id for ch in "\n\r\0")


def open_channel_settings(dev: AdbDevice, package: str, channel_id: str) -> None:
    """Open one notification category's settings screen (where its sound is chosen)."""
    if not valid_package(package) or not valid_channel_id(channel_id):
        raise AdbError("That notification category can't be opened.")
    # Channel IDs are chosen by the app; start_settings quotes each argument for the phone's shell.
    start_settings(
        dev,
        "-a",
        "android.settings.CHANNEL_NOTIFICATION_SETTINGS",
        "--es",
        "android.provider.extra.APP_PACKAGE",
        package,
        "--es",
        "android.provider.extra.CHANNEL_ID",
        channel_id,
    )
