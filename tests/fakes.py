"""In-memory fake phone for tests. Never touches a real device; all data is made up."""

from __future__ import annotations

import re
import shlex

from soundmanager import phone_contacts as pc
from soundmanager import phone_sounds as ps
from soundmanager.adb import AdbDevice, AdbError


class FakePhone:
    """Simulates the adb shell commands the app uses: settings, content, am.

    Set `disconnect_after_writes = n` to simulate the cable being pulled after n writes; every
    later command then fails like a vanished device until `reconnect()`.
    """

    serial = "FAKE1"
    rescan = AdbDevice.rescan  # real method, running against this fake shell

    def __init__(self, settings=None, media=None, samsung=True, contacts=None, internal=None):
        self.settings = dict(settings or {})
        self.media = list(media or [])  # external MediaItem list
        self.internal = list(internal or [])  # built-in sounds
        self.contacts = {c["id"]: dict(c) for c in (contacts or [])}
        self.commands: list[list[str]] = []
        self.reject_writes = False
        self.connected = True
        self.disconnect_after_writes: int | None = None
        self.rescanned: list[str] = []
        if samsung:
            for key in ("ringtone", "notification_sound", "alarm_alert"):
                self.settings.setdefault(key + "_CONSTANT_PATH", "?path=%2Fsystem%2Fx.ogg")
                self.settings.setdefault(key + "_set", "1")

    def reconnect(self):
        self.connected = True
        self.disconnect_after_writes = None

    def _gone(self):
        return AdbError(f"adb: device '{self.serial}' not found")

    def _wrote(self):
        if self.disconnect_after_writes is not None:
            self.disconnect_after_writes -= 1
            if self.disconnect_after_writes <= 0:
                self.connected = False
                raise self._gone()

    def shell(self, command: str, timeout: float = 60) -> str:
        if not self.connected:
            raise self._gone()
        argv = shlex.split(command)  # what the phone's sh would see
        segments, current = [], []
        for token in argv:
            if token == "&&":
                segments.append(current)
                current = []
            else:
                current.append(token)
        segments.append(current)
        return "".join(self._one(seg) for seg in segments)

    def _one(self, argv: list[str]) -> str:
        self.commands.append(argv)
        match argv:
            case ["settings", "get", "system", key]:
                return self.settings.get(key, "null") + "\n"
            case ["settings", "put", "system", key, value]:
                if not self.reject_writes:
                    self.settings[key] = value
                self._wrote()
                return ""
            case ["settings", "delete", "system", key]:
                self.settings.pop(key, None)
                self._wrote()
                return ""
            case ["am", "get-current-user"]:
                return "0\n"
            case ["am", "broadcast", "-a", _, "-d", uri]:
                self.rescanned.append(uri)
                return "Broadcast completed: result=0\n"
            case ["content", "query", "--uri", uri, "--projection", _, *rest]:
                if uri.startswith(pc.CONTACTS_URI):
                    return self._query_contacts(uri)
                return self._query_media(uri, rest)
            case ["content", "update", "--uri", uri, "--bind", binding]:
                contact_id = int(uri.rsplit("/", 1)[1])
                column, kind, value = binding.split(":", 2)
                assert column == "custom_ringtone"
                if contact_id in self.contacts and not self.reject_writes:
                    self.contacts[contact_id]["ringtone"] = None if kind == "n" else value
                self._wrote()
                return ""
        raise AssertionError(f"unexpected command: {argv}")

    def _query_media(self, uri, rest):
        rows = self.internal if "/internal/" in uri else self.media
        if m := re.search(r"/media/(\d+)$", uri):
            rows = [r for r in rows if r.id == int(m.group(1))]
        if rest[:1] == ["--where"]:
            where = rest[1]
            if m := re.fullmatch(r"_data='(.*)'", where, re.S):
                want = m.group(1).replace("''", "'")
                rows = [r for r in rows if r.path == want]
            elif m := re.fullmatch(r"_data LIKE '(.*)%' AND title LIKE '\.%'", where):
                rows = [r for r in rows if r.path.startswith(m.group(1)) and r.title[:1] == "."]
            elif m := re.fullmatch(r"_id IN \(([\d,]+)\)", where):
                ids = {int(x) for x in m.group(1).split(",")}
                rows = [r for r in rows if r.id in ids]
            else:
                raise AssertionError(f"unexpected where: {where}")
        if not rows:
            return "No result found.\n"
        return "".join(
            f"Row: {i} _id={r.id}, title={r.title}, _data={r.path}\n" for i, r in enumerate(rows)
        )

    def _query_contacts(self, uri):
        rows = list(self.contacts.values())
        if m := re.search(r"/contacts/(\d+)$", uri):
            rows = [c for c in rows if c["id"] == int(m.group(1))]
        if not rows:
            return "No result found.\n"
        return "".join(
            f"Row: {i} _id={c['id']}, has_phone_number={1 if c.get('phone', True) else 0}, "
            f"custom_ringtone={c.get('ringtone') or 'NULL'}, display_name={c['name']}\n"
            for i, c in enumerate(rows)
        )


TONE = ps.MediaItem(42, "My Tone, v2", "/storage/emulated/0/Ringtones/My Tone, v2.mp3")
OTHER = ps.MediaItem(43, "Second", "/storage/emulated/0/Ringtones/second.ogg")
