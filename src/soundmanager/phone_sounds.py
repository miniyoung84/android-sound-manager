"""Read and change the phone's default ringtone, notification, and alarm sounds over ADB.

Android stores each default as a MediaStore content URI in `Settings.System` (e.g. `ringtone`).
Samsung (One UI) also keeps companion keys next to it, which its own Settings app writes:

    ringtone                  content://0@media/external/audio/media/<id>?highlight_offset=0&title=<t>
    ringtone_CONSTANT_PATH    ?path=<url-encoded file path>   (survives MediaStore ID changes)
    ringtone_set              1
    ringtone_2 ...            the same for SIM 2 on dual-SIM phones

We write the companion keys only when the phone already has them, so other phones just get the
standard key. Every command sent to the phone is built from validated values and shell-quoted.
"""

from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit

from .adb import AdbDevice, AdbError, is_in_sound_folder

# Standard Settings.System keys per sound type (index 0 = SIM 1 / only SIM).
SOUND_KEYS: dict[str, tuple[str, ...]] = {
    "ringtone": ("ringtone", "ringtone_2"),
    "notification": ("notification_sound", "notification_sound_2"),
    "alarm": ("alarm_alert",),
}
ALLOWED_KEYS = frozenset(k for keys in SOUND_KEYS.values() for k in keys)
COMPANION_SUFFIXES = ("_CONSTANT_PATH", "_set")

STORAGE_ROOT = "/storage/emulated/0"
MEDIA_URI = "content://media/external/audio/media"
_ROW = re.compile(r"^Row: \d+ _id=(\d+), title=(.*), _data=(.*)$")


@dataclass(frozen=True)
class MediaItem:
    id: int
    title: str
    path: str  # absolute path on the phone, e.g. /storage/emulated/0/Ringtones/x.mp3


@dataclass(frozen=True)
class DefaultSound:
    key: str
    uri: str | None
    title: str
    path: str | None  # known for Samsung (from *_CONSTANT_PATH); None otherwise


# ---------------------------------------------------------------------------- pure helpers


def to_storage_path(remote: str) -> str:
    """/sdcard/... -> /storage/emulated/0/... (the form MediaStore uses in _data)."""
    if remote.startswith("/sdcard/"):
        return STORAGE_ROOT + remote[len("/sdcard") :]
    return remote


def sql_quote(value: str) -> str:
    """Quote a string literal for a SQLite WHERE clause."""
    return "'" + value.replace("'", "''") + "'"


def parse_media_rows(output: str) -> list[MediaItem]:
    items = []
    for line in output.splitlines():
        m = _ROW.match(line.strip())
        if m:
            items.append(MediaItem(int(m.group(1)), m.group(2), m.group(3)))
    return items


def build_sound_uri(user_id: int, media_id: int, title: str) -> str:
    """Same shape Samsung's sound picker writes for a file in shared storage."""
    return (
        f"content://{user_id}@media/external/audio/media/{media_id}"
        f"?highlight_offset=0&title={quote(title, safe='')}"
    )


def build_constant_path(storage_path: str) -> str:
    return "?path=" + quote(storage_path, safe="")


def parse_default(key: str, uri: str | None, constant_path: str | None) -> DefaultSound:
    title, path = "", None
    if uri:
        title = parse_qs(urlsplit(uri).query).get("title", [""])[0]
    if constant_path:
        path = parse_qs(urlsplit(constant_path).query).get("path", [None])[0]
    if not title and path:
        title = path.rsplit("/", 1)[-1]
    if uri is None:
        title = "(silent)"
    return DefaultSound(key, uri, title, path)  # title may be "" until resolved


def _check_key(key: str) -> None:
    if key not in ALLOWED_KEYS:
        raise AdbError(f"Not a sound setting: {key!r}")


# ---------------------------------------------------------------------------- phone access


def _settings_get(dev: AdbDevice, key: str) -> str | None:
    value = dev.shell(f"settings get system {shlex.quote(key)}").strip()
    return None if value in ("", "null") else value


def _settings_put(dev: AdbDevice, key: str, value: str | None) -> None:
    if value is None:
        dev.shell(f"settings delete system {shlex.quote(key)}")
    else:
        dev.shell(f"settings put system {shlex.quote(key)} {shlex.quote(value)}")


def current_user(dev: AdbDevice) -> int:
    out = dev.shell("am get-current-user").strip()
    if not out.isdigit():
        raise AdbError(f"Unexpected user id from phone: {out!r}")
    return int(out)


def find_media(dev: AdbDevice, remote_path: str, wait: float = 5.0) -> MediaItem:
    """Look up a file in MediaStore, waiting briefly for a fresh upload to be indexed."""
    storage_path = to_storage_path(remote_path)
    where = f"_data={sql_quote(storage_path)}"
    cmd = (
        f"content query --uri {MEDIA_URI} --projection _id:title:_data --where {shlex.quote(where)}"
    )
    deadline = time.monotonic() + wait
    while True:
        rows = [r for r in parse_media_rows(dev.shell(cmd)) if r.path == storage_path]
        if rows:
            return rows[0]
        if time.monotonic() >= deadline:
            raise AdbError(f"The phone hasn't indexed {remote_path} yet. Try again in a moment.")
        time.sleep(0.5)


def available_keys(dev: AdbDevice, sound: str) -> list[str]:
    """Keys for this sound type that exist on the phone (e.g. SIM 2 only on dual-SIM phones)."""
    keys = SOUND_KEYS[sound]
    return [keys[0], *(k for k in keys[1:] if _settings_get(dev, k) is not None)]


_EXTERNAL_ID = re.compile(r"^content://(?:\d+@)?media/external/audio/media/(\d+)(?:[?#]|$)")


def get_default(dev: AdbDevice, key: str) -> DefaultSound:
    _check_key(key)
    uri = _settings_get(dev, key)
    sound = parse_default(key, uri, _settings_get(dev, key + "_CONSTANT_PATH"))
    if sound.path is None and uri and (m := _EXTERNAL_ID.match(uri)):
        # Non-Samsung phones: resolve the file path from the MediaStore ID.
        out = dev.shell(
            f"content query --uri {MEDIA_URI}/{m.group(1)} --projection _id:title:_data"
        )
        rows = parse_media_rows(out)
        if rows:
            sound = DefaultSound(key, uri, sound.title or rows[0].title, rows[0].path)
    if not sound.title:
        sound = DefaultSound(key, uri, uri or "(silent)", sound.path)
    return sound


Snapshot = dict[str, str | None]


def set_default(dev: AdbDevice, key: str, remote_path: str) -> Snapshot:
    """Make the file at *remote_path* the default for *key*. Returns the old values for undo."""
    _check_key(key)
    if not is_in_sound_folder(remote_path):
        raise AdbError(f"Only files in the phone's sound folders can be used: {remote_path}")

    media = find_media(dev, remote_path)
    uri = build_sound_uri(current_user(dev), media.id, media.title)
    values: dict[str, str] = {key: uri}

    # Samsung companion keys, only if the phone already uses them.
    for suffix in COMPANION_SUFFIXES:
        if _settings_get(dev, key + suffix) is not None:
            values[key + suffix] = (
                build_constant_path(media.path) if suffix == "_CONSTANT_PATH" else "1"
            )

    previous: Snapshot = {k: _settings_get(dev, k) for k in values}
    for k, v in values.items():
        _settings_put(dev, k, v)

    if _settings_get(dev, key) != uri:
        restore(dev, previous)
        raise AdbError("The phone did not accept the new setting; nothing was changed.")
    return previous


def restore(dev: AdbDevice, snapshot: Snapshot) -> None:
    """Undo a set_default() using the snapshot it returned."""
    for k, v in snapshot.items():
        base = k.removesuffix("_CONSTANT_PATH").removesuffix("_set")
        _check_key(base)
        _settings_put(dev, k, v)
