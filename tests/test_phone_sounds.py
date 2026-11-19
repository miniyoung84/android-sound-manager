"""Tests for phone_sounds using an in-memory fake phone (never touches a real device)."""

import re
import shlex

import pytest

from soundmanager import phone_sounds as ps
from soundmanager.adb import AdbError, is_in_sound_folder


class FakePhone:
    """Simulates `settings`, `content query`, and `am get-current-user` over adb shell."""

    def __init__(self, settings=None, media=None, samsung=True):
        self.settings = dict(settings or {})
        self.media = list(media or [])  # MediaItem list
        self.commands: list[list[str]] = []
        self.reject_writes = False
        if samsung:
            for key in ("ringtone", "notification_sound", "alarm_alert"):
                self.settings.setdefault(key + "_CONSTANT_PATH", "?path=%2Fsystem%2Fx.ogg")
                self.settings.setdefault(key + "_set", "1")

    def shell(self, command: str, timeout: float = 60) -> str:
        argv = shlex.split(command)  # what the phone's sh would see
        self.commands.append(argv)
        match argv:
            case ["settings", "get", "system", key]:
                return self.settings.get(key, "null") + "\n"
            case ["settings", "put", "system", key, value]:
                if not self.reject_writes:
                    self.settings[key] = value
                return ""
            case ["settings", "delete", "system", key]:
                self.settings.pop(key, None)
                return ""
            case ["am", "get-current-user"]:
                return "0\n"
            case ["content", "query", "--uri", uri, "--projection", _, *rest]:
                return self._query(uri, rest)
        raise AssertionError(f"unexpected command: {argv}")

    def _query(self, uri, rest):
        rows = self.media
        if m := re.search(r"/media/(\d+)$", uri):
            rows = [r for r in rows if r.id == int(m.group(1))]
        if rest[:1] == ["--where"]:
            want = re.fullmatch(r"_data='(.*)'", rest[1], re.S).group(1).replace("''", "'")
            rows = [r for r in rows if r.path == want]
        if not rows:
            return "No result found.\n"
        return "".join(
            f"Row: {i} _id={r.id}, title={r.title}, _data={r.path}\n" for i, r in enumerate(rows)
        )


TONE = ps.MediaItem(42, "My Tone, v2", "/storage/emulated/0/Ringtones/My Tone, v2.mp3")


# --------------------------------------------------------------------------- pure helpers


def test_is_in_sound_folder_blocks_traversal_and_subdirs():
    assert is_in_sound_folder("/sdcard/Ringtones/a.mp3")
    assert not is_in_sound_folder("/sdcard/Ringtones/../DCIM/a.jpg")
    assert not is_in_sound_folder("/sdcard/Ringtones/sub/a.mp3")
    assert not is_in_sound_folder("/sdcard/DCIM/a.jpg")
    assert not is_in_sound_folder("/sdcard/Ringtones/a\n.mp3")


def test_parse_media_rows_keeps_commas_in_titles():
    out = f"Row: 0 _id=42, title={TONE.title}, _data={TONE.path}\n"
    assert ps.parse_media_rows(out) == [TONE]
    assert ps.parse_media_rows("No result found.") == []


def test_build_sound_uri_encodes_title():
    uri = ps.build_sound_uri(0, 42, "Rock & Roll?")
    assert (
        uri
        == "content://0@media/external/audio/media/42?highlight_offset=0&title=Rock%20%26%20Roll%3F"
    )


def test_parse_default_reads_title_and_samsung_path():
    d = ps.parse_default(
        "ringtone",
        "content://0@media/external/audio/media/7?highlight_offset=0&title=sample-tone",
        "?path=%2Fstorage%2Femulated%2F0%2FRingtones%2Fsample-tone.mp3",
    )
    assert d.title == "sample-tone"
    assert d.path == "/storage/emulated/0/Ringtones/sample-tone.mp3"
    assert ps.parse_default("alarm_alert", None, None).title == "(silent)"


def test_sql_quote_escapes_single_quotes():
    assert ps.sql_quote("it's") == "'it''s'"


# --------------------------------------------------------------------------- phone access


def test_set_default_writes_samsung_keys_and_can_undo():
    phone = FakePhone(settings={"ringtone": "content://old"}, media=[TONE])
    before = dict(phone.settings)

    snapshot = ps.set_default(phone, "ringtone", "/sdcard/Ringtones/My Tone, v2.mp3")

    assert phone.settings["ringtone"].startswith("content://0@media/external/audio/media/42?")
    assert phone.settings["ringtone_CONSTANT_PATH"] == ps.build_constant_path(TONE.path)
    assert phone.settings["ringtone_set"] == "1"
    assert snapshot["ringtone"] == "content://old"

    ps.restore(phone, snapshot)
    assert phone.settings == before


def test_set_default_skips_companion_keys_on_non_samsung():
    phone = FakePhone(media=[TONE], samsung=False)
    ps.set_default(phone, "ringtone", "/sdcard/Ringtones/My Tone, v2.mp3")
    assert set(phone.settings) == {"ringtone"}


def test_get_default_resolves_path_by_id_on_non_samsung():
    phone = FakePhone(
        settings={"ringtone": "content://media/external/audio/media/42"},
        media=[TONE],
        samsung=False,
    )
    d = ps.get_default(phone, "ringtone")
    assert d.path == TONE.path
    assert d.title == TONE.title


def test_hostile_file_name_is_passed_as_one_argument():
    evil = ps.MediaItem(9, "x", "/storage/emulated/0/Ringtones/a'; rm -rf ~ #$(reboot).mp3")
    phone = FakePhone(media=[evil])
    ps.set_default(phone, "ringtone", "/sdcard/Ringtones/a'; rm -rf ~ #$(reboot).mp3")
    # Every command parsed back into the expected argv: nothing leaked into extra args.
    for argv in phone.commands:
        assert argv[0] in ("settings", "content", "am")
        assert "rm" not in argv and "reboot" not in argv


def test_rejects_unknown_keys_and_outside_files():
    phone = FakePhone(media=[TONE])
    with pytest.raises(AdbError):
        ps.set_default(phone, "adb_enabled", "/sdcard/Ringtones/My Tone, v2.mp3")
    with pytest.raises(AdbError):
        ps.set_default(phone, "ringtone", "/sdcard/Download/other.mp3")
    with pytest.raises(AdbError):
        ps.restore(phone, {"adb_enabled": "0"})
    assert phone.commands == []


def test_rolls_back_if_phone_rejects_the_write():
    phone = FakePhone(settings={"ringtone": "content://old"}, media=[TONE])
    phone.reject_writes = True
    with pytest.raises(AdbError, match="nothing was changed"):
        ps.set_default(phone, "ringtone", "/sdcard/Ringtones/My Tone, v2.mp3")
    assert phone.settings["ringtone"] == "content://old"


def test_available_keys_includes_sim2_only_when_present():
    assert ps.available_keys(FakePhone(), "ringtone") == ["ringtone"]
    dual = FakePhone(settings={"ringtone_2": "content://x"})
    assert ps.available_keys(dual, "ringtone") == ["ringtone", "ringtone_2"]
