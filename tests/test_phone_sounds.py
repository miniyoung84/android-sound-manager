"""Tests for phone_sounds using an in-memory fake phone (never touches a real device)."""

import pytest
from fakes import TONE, FakePhone

from soundmanager import phone_sounds as ps
from soundmanager.adb import AdbError, is_in_sound_folder
from soundmanager.journal import Journal

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


# --------------------------------------------------------------------------- disconnects


@pytest.fixture
def journal(tmp_path):
    return Journal(tmp_path / "journal")


def samsung_keys(phone):
    return {
        k: phone.settings.get(k) for k in ("ringtone", "ringtone_CONSTANT_PATH", "ringtone_set")
    }


def test_disconnect_mid_write_is_rolled_back_on_reconnect(journal):
    phone = FakePhone(settings={"ringtone": "content://old"}, media=[TONE])
    before = samsung_keys(phone)
    phone.disconnect_after_writes = 1  # cable pulled after the first of three writes

    with pytest.raises(AdbError):
        ps.set_default(phone, "ringtone", "/sdcard/Ringtones/My Tone, v2.mp3", journal)
    assert samsung_keys(phone) != before  # genuinely half-applied on the "phone"
    assert journal.load(phone.serial) is not None  # ...and remembered on the PC

    phone.reconnect()
    note = ps.recover_pending(phone, journal)
    assert note and "rolled back" in note
    assert samsung_keys(phone) == before
    assert journal.load(phone.serial) is None


def test_disconnect_after_all_writes_keeps_the_completed_change(journal):
    phone = FakePhone(settings={"ringtone": "content://old"}, media=[TONE])
    phone.disconnect_after_writes = 3  # every write landed, then the cable went
    with pytest.raises(AdbError):
        ps.set_default(phone, "ringtone", "/sdcard/Ringtones/My Tone, v2.mp3", journal)
    phone.reconnect()
    done = samsung_keys(phone)
    assert ps.recover_pending(phone, journal) is None  # complete: nothing to repair
    assert samsung_keys(phone) == done
    assert done["ringtone"].startswith("content://0@media/external/audio/media/42")


def test_disconnect_before_any_write_changes_nothing(journal):
    phone = FakePhone(settings={"ringtone": "content://old"}, media=[TONE])
    before = samsung_keys(phone)
    phone.connected = False
    with pytest.raises(AdbError):
        ps.set_default(phone, "ringtone", "/sdcard/Ringtones/My Tone, v2.mp3", journal)
    phone.reconnect()
    assert ps.recover_pending(phone, journal) is None
    assert samsung_keys(phone) == before


def test_successful_change_leaves_no_journal(journal):
    phone = FakePhone(settings={"ringtone": "content://old"}, media=[TONE])
    snapshot = ps.set_default(phone, "ringtone", "/sdcard/Ringtones/My Tone, v2.mp3", journal)
    assert journal.load(phone.serial) is None
    ps.restore(phone, snapshot, journal)
    assert phone.settings["ringtone"] == "content://old"
    assert journal.load(phone.serial) is None


def test_writes_go_out_as_one_command():
    phone = FakePhone(settings={"ringtone": "content://old"}, media=[TONE])
    sent = []
    real_shell = phone.shell
    phone.shell = lambda cmd, timeout=60: sent.append(cmd) or real_shell(cmd)
    ps.set_default(phone, "ringtone", "/sdcard/Ringtones/My Tone, v2.mp3")
    writes = [c for c in sent if "settings put" in c]
    assert len(writes) == 1 and writes[0].count("settings put") == 3


def test_tampered_journal_is_ignored(journal):
    phone = FakePhone(settings={"ringtone": "content://old"})
    journal.save(phone.serial, {"kind": "settings", "old": {"adb_enabled": "0"}, "new": {}})
    assert ps.recover_pending(phone, journal) is None
    assert "adb_enabled" not in phone.settings
    assert journal.load(phone.serial) is None


def test_repair_titles_rescans_only_stale_visible_sounds():
    stale = ps.MediaItem(50, ".3e6484e6cbef", "/storage/emulated/0/Notifications/chime.m4a")
    hidden = ps.MediaItem(51, ".x", "/storage/emulated/0/Notifications/.x.asm-part")
    fine = ps.MediaItem(52, "ok", "/storage/emulated/0/Notifications/ok.m4a")
    phone = FakePhone(media=[stale, hidden, fine, TONE])
    assert ps.repair_titles(phone) == 1
    assert phone.rescanned == ["file:///storage/emulated/0/Notifications/chime.m4a"]
