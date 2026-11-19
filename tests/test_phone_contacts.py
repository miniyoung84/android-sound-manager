"""Per-contact ringtone tests against the fake phone. All names are made up."""

import pytest
from fakes import OTHER, TONE, FakePhone

from soundmanager import phone_contacts as pc
from soundmanager import phone_sounds as ps
from soundmanager.adb import AdbError

BELL = ps.MediaItem(7, "Bell", "/system/media/audio/ringtones/Bell.ogg")


def make_phone():
    return FakePhone(
        media=[TONE, OTHER],
        internal=[BELL],
        contacts=[
            {"id": 1, "name": "Avery Example", "ringtone": f"{ps.MEDIA_URI}/42"},
            {"id": 2, "name": "Smith, Jordan (work)", "ringtone": None},
            {"id": 3, "name": "No Number Org", "phone": False},
            {"id": 4, "name": "Casey Sample", "ringtone": "content://media/internal/audio/media/7"},
            {"id": 5, "name": "Gone File", "ringtone": f"{ps.MEDIA_URI}/999"},
        ],
    )


def test_list_contacts_parses_names_with_commas_and_nulls():
    contacts = pc.list_contacts(make_phone())
    by_id = {c.id: c for c in contacts}
    assert by_id[2].name == "Smith, Jordan (work)" and by_id[2].ringtone is None
    assert by_id[3].has_phone is False
    assert [c.name for c in contacts] == sorted((c.name for c in contacts), key=str.casefold)


def test_describe_ringtones_handles_shared_builtin_and_missing():
    phone = make_phone()
    uris = {c.ringtone for c in pc.list_contacts(phone) if c.ringtone}
    labels = pc.describe_ringtones(phone, uris)
    assert labels[f"{ps.MEDIA_URI}/42"] == "My Tone, v2.mp3"
    assert labels["content://media/internal/audio/media/7"] == "Bell"
    assert labels[f"{ps.MEDIA_URI}/999"] == "(missing sound file)"


def test_set_and_restore_contact_ringtone():
    phone = make_phone()
    old = pc.set_contact_ringtone(phone, 2, "/sdcard/Ringtones/second.ogg")
    assert old is None
    assert phone.contacts[2]["ringtone"] == f"{ps.MEDIA_URI}/43"

    pc.restore_contact_ringtone(phone, 2, old)
    assert phone.contacts[2]["ringtone"] is None


def test_clear_to_phone_default():
    phone = make_phone()
    old = pc.set_contact_ringtone(phone, 1, None)
    assert old == f"{ps.MEDIA_URI}/42" and phone.contacts[1]["ringtone"] is None


def test_rejects_files_outside_sound_folders_and_bad_restore_values():
    phone = make_phone()
    with pytest.raises(AdbError):
        pc.set_contact_ringtone(phone, 2, "/sdcard/Download/x.mp3")
    with pytest.raises(AdbError):
        pc.restore_contact_ringtone(phone, 2, "x'; reboot")
    assert phone.contacts[2]["ringtone"] is None


def test_missing_contact_and_rejected_write_raise():
    phone = make_phone()
    with pytest.raises(AdbError, match="no longer exists"):
        pc.set_contact_ringtone(phone, 99, "/sdcard/Ringtones/second.ogg")
    phone.reject_writes = True
    with pytest.raises(AdbError, match="did not accept"):
        pc.set_contact_ringtone(phone, 2, "/sdcard/Ringtones/second.ogg")


def test_disconnect_during_update_never_half_applies():
    phone = make_phone()
    phone.disconnect_after_writes = 1  # the single update lands, then the cable goes
    with pytest.raises(AdbError):
        pc.set_contact_ringtone(phone, 2, "/sdcard/Ringtones/second.ogg")
    phone.reconnect()
    # A contact update is one atomic write: it's either the old value or the new one.
    assert phone.contacts[2]["ringtone"] in (None, f"{ps.MEDIA_URI}/43")
