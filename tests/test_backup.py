"""Backup and restore, against in-memory fake phones (all names and data are made up)."""

from __future__ import annotations

import json
import posixpath
import zipfile
from pathlib import Path, PurePosixPath

import pytest
from fakes import FakePhone

from soundmanager import adb, backup, phone_contacts
from soundmanager import phone_sounds as ps
from soundmanager.journal import Journal


class PhoneWithFiles(FakePhone):
    """FakePhone plus sound files that can be listed, pulled and pushed."""

    def __init__(self, files: dict[str, bytes] | None = None, **kw):
        super().__init__(**kw)
        self.files: dict[str, bytes] = {}
        self.next_id = 100
        for path, data in (files or {}).items():
            self._store(path, data)

    def _store(self, remote: str, data: bytes) -> None:
        self.files[remote] = data
        storage = adb.to_storage_path(remote)
        if not any(m.path == storage for m in self.media):
            self.next_id += 1
            self.media.append(ps.MediaItem(self.next_id, PurePosixPath(remote).stem, storage))

    def list_dir(self, remote_dir):
        if not self.connected:
            raise self._gone()
        files = [
            adb.RemoteFile(p, len(b), 0)
            for p, b in self.files.items()
            if posixpath.dirname(p) == remote_dir
        ]
        return sorted(files, key=lambda f: f.name.lower())

    def pull(self, remote, local_dir: Path) -> Path:
        if not self.connected:
            raise self._gone()
        self._wrote()  # counts as a step for disconnect simulation
        dest = local_dir / adb.safe_local_name(PurePosixPath(remote).name)
        dest.write_bytes(self.files[remote])
        return dest

    def push(self, local: Path, remote_dir: str, name: str | None = None) -> str:
        if not self.connected:
            raise self._gone()
        remote = f"{remote_dir}/{name or local.name}"
        assert adb.is_in_sound_folder(remote)
        self._wrote()
        self._store(remote, local.read_bytes())
        return remote

    def ringtone_file(self, key: str) -> str | None:
        """File name the setting points at (via the Samsung path key the fake keeps)."""
        d = ps.get_default(self, key)
        return PurePosixPath(d.path).name if d.path else None

    def contact_file(self, contact_id: int) -> str | None:
        uri = self.contacts[contact_id].get("ringtone")
        return PurePosixPath(phone_contacts.ringtone_paths(self, {uri})[uri]).name if uri else None


ALPHA = b"alpha tone " * 50
BRAVO = b"bravo ping " * 20


def source_phone() -> PhoneWithFiles:
    phone = PhoneWithFiles(
        {
            "/sdcard/Ringtones/Alpha: theme.mp3": ALPHA,
            "/sdcard/Notifications/bravo.ogg": BRAVO,
        },
        contacts=[
            {"id": 7, "name": "Avery Example"},
            {"id": 8, "name": "Blake Sample"},
            {"id": 9, "name": "Casey Nobody"},
        ],
    )
    ps.set_default(phone, "ringtone", "/sdcard/Ringtones/Alpha: theme.mp3")
    ps.set_default(phone, "notification_sound", "/sdcard/Notifications/bravo.ogg")
    phone_contacts.set_contact_ringtone(phone, 7, "/sdcard/Notifications/bravo.ogg")
    phone_contacts.set_contact_ringtone(phone, 8, "/sdcard/Ringtones/Alpha: theme.mp3")
    return phone


@pytest.fixture
def saved(tmp_path) -> Path:
    dest = tmp_path / "backup.zip"
    summary = backup.create_backup(source_phone(), dest)
    assert (summary.files, summary.defaults, summary.contacts) == (2, 2, 2)
    assert summary.skipped_defaults == ["alarm_alert"]  # the fake's alarm is a built-in sound
    return dest


def test_backup_holds_sounds_and_settings_but_no_numbers(saved):
    with zipfile.ZipFile(saved) as zf:
        assert zf.read("Ringtones/Alpha: theme.mp3") == ALPHA
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["defaults"]["ringtone"] == {"folder": "Ringtones", "file": "Alpha: theme.mp3"}
    assert {c["name"] for c in manifest["contacts"]} == {"Avery Example", "Blake Sample"}
    assert all(set(c) == {"id", "name", "sound"} for c in manifest["contacts"])


def test_restore_to_a_new_phone(saved, tmp_path):
    # A new phone: different contact IDs, and a different file that happens to share a name.
    phone = PhoneWithFiles(
        {"/sdcard/Ringtones/Alpha: theme.mp3": b"someone else's tone"},
        contacts=[{"id": 70, "name": "avery example"}, {"id": 80, "name": "Blake Sample"}],
    )
    with backup.open_backup(saved) as zf:
        plan = backup.plan_restore(phone, backup.read_manifest(zf))
    text = backup.describe_plan(plan)
    assert "Copy 2 sound(s)" in text and "Give 2 contact(s)" in text

    backup.restore(phone, saved, plan, Journal(tmp_path / "j"))
    assert phone.files["/sdcard/Ringtones/Alpha: theme.mp3"] == b"someone else's tone"  # kept
    assert phone.files["/sdcard/Ringtones/Alpha: theme (2).mp3"] == ALPHA
    assert phone.files["/sdcard/Notifications/bravo.ogg"] == BRAVO
    assert phone.ringtone_file("ringtone") == "Alpha: theme (2).mp3"
    assert phone.ringtone_file("notification_sound") == "bravo.ogg"
    assert phone.contact_file(70) == "bravo.ogg"  # matched by name, ignoring case
    assert phone.contact_file(80) == "Alpha: theme (2).mp3"

    # Running it again finds nothing left to do.
    with backup.open_backup(saved) as zf:
        assert backup.plan_restore(phone, backup.read_manifest(zf)).is_empty()


def test_restore_skips_contacts_it_cant_match_for_sure(saved):
    phone = PhoneWithFiles(
        contacts=[
            {"id": 1, "name": "Avery Example"},
            {"id": 2, "name": "Avery Example"},  # two with the same name: don't guess
        ],
    )
    with backup.open_backup(saved) as zf:
        plan = backup.plan_restore(phone, backup.read_manifest(zf))
    assert plan.contacts == [] and plan.unmatched_contacts == 2


def test_restore_interrupted_by_disconnect_can_be_finished(saved, tmp_path):
    phone = PhoneWithFiles(contacts=[{"id": 7, "name": "Avery Example"}])
    journal = Journal(tmp_path / "j")
    with backup.open_backup(saved) as zf:
        plan = backup.plan_restore(phone, backup.read_manifest(zf))
    phone.disconnect_after_writes = 2  # cable pulled after the first upload
    with pytest.raises(adb.AdbError):
        backup.restore(phone, saved, plan, journal)
    assert not any(".asm-part" in p for p in phone.files)

    phone.reconnect()
    ps.recover_pending(phone, journal)
    with backup.open_backup(saved) as zf:
        plan = backup.plan_restore(phone, backup.read_manifest(zf))
    backup.restore(phone, saved, plan, journal)
    assert phone.ringtone_file("ringtone") == "Alpha: theme.mp3"
    assert phone.contact_file(7) == "bravo.ogg"
    assert len(phone.files) == 2  # nothing uploaded twice


def test_backup_interrupted_leaves_no_file(tmp_path):
    phone = source_phone()
    phone.disconnect_after_writes = 2
    dest = tmp_path / "backup.zip"
    with pytest.raises(adb.AdbError):
        backup.create_backup(phone, dest)
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- hostile files


def manifest(**over):
    data = {
        "format": backup.FORMAT,
        "version": backup.VERSION,
        "created": "2026-01-01T00:00:00",
        "files": [{"folder": "Ringtones", "file": "a.mp3", "size": 3}],
        "defaults": {"ringtone": {"folder": "Ringtones", "file": "a.mp3"}},
        "contacts": [],
    }
    data.update(over)
    return data


def test_valid_manifest_parses():
    m = backup.parse_manifest(manifest())
    assert m.defaults["ringtone"] == backup.SoundRef("Ringtones", "a.mp3")


@pytest.mark.parametrize(
    "bad",
    [
        {"format": "something-else"},
        {"version": 99},
        {"files": [{"folder": "Ringtones", "file": "../../evil.mp3", "size": 3}]},
        {"files": [{"folder": "Ringtones", "file": "..\\evil.mp3", "size": 3}]},
        {"files": [{"folder": "Download", "file": "a.mp3", "size": 3}]},
        {"files": [{"folder": "Ringtones", "file": ".hidden", "size": 3}]},
        {"files": [{"folder": "Ringtones", "file": "a.mp3", "size": 10**12}]},
        {"files": [{"folder": "Ringtones", "file": "a.mp3", "size": -1}]},
        {"files": [{"folder": "Ringtones", "file": "a.mp3", "size": 3}] * 2},
        {"defaults": {"adb_enabled": {"folder": "Ringtones", "file": "a.mp3"}}},
        {"defaults": {"ringtone": {"folder": "Ringtones", "file": "missing.mp3"}}},
        {"contacts": [{"id": "7", "name": "x", "sound": {"folder": "Ringtones", "file": "a.mp3"}}]},
        {"contacts": [{"id": 7, "name": "x", "sound": "/sdcard/Ringtones/a.mp3"}]},
        {"files": "nope"},
    ],
)
def test_hostile_manifests_are_refused(bad):
    with pytest.raises(backup.BackupError):
        backup.parse_manifest(manifest(**bad))


def test_sound_bigger_than_its_manifest_entry_is_refused(tmp_path):
    zpath = tmp_path / "b.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest()))
        zf.writestr("Ringtones/a.mp3", b"much more than three bytes")
    with backup.open_backup(zpath) as zf:
        m = backup.read_manifest(zf)
        ref, size = m.files[0]
        with pytest.raises(backup.BackupError):
            backup.extract_sound(zf, ref, size, tmp_path / "out.mp3")


def test_not_a_backup(tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(backup.BackupError):
        backup.open_backup(junk)
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("other.txt", "hi")
    with backup.open_backup(empty) as zf, pytest.raises(backup.BackupError):
        backup.read_manifest(zf)
