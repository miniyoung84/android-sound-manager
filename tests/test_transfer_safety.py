"""Upload/download behave safely when the phone disconnects, and phone file names can't escape."""

from pathlib import Path

import pytest

from soundmanager import adb
from soundmanager.journal import Journal


class FakeTransport(adb.AdbDevice):
    """AdbDevice whose adb calls hit an in-memory 'phone' filesystem."""

    def __init__(self, files=None):
        super().__init__("FAKE1")
        self.files: dict[str, bytes] = dict(files or {})
        self.fail_on: str | None = None  # "push", "pull", "mv" -> simulate a disconnect there
        self.truncate_push = False
        self.rescanned: list[str] = []

    def _gone(self):
        return adb.AdbError("adb: device 'FAKE1' not found")

    def _adb(self, *args, timeout=60):
        cmd = args[0]
        if cmd == "push":
            if self.fail_on == "push":
                self.files[args[2]] = b"partial"  # half a file arrived, then the cable went
                raise self._gone()
            data = Path(args[1]).read_bytes()
            self.files[args[2]] = data[: len(data) // 2] if self.truncate_push else data
            return ""
        if cmd == "pull":
            if self.fail_on == "pull":
                Path(args[2]).write_bytes(b"partial")
                raise self._gone()
            Path(args[2]).write_bytes(self.files[args[1]])
            return ""
        raise AssertionError(args)

    def shell(self, command, timeout=60):
        import shlex

        argv = shlex.split(command)
        if argv[0] == "mkdir":
            return ""
        if argv[0] == "stat":
            data = self.files.get(argv[3])
            return f"{len(data)}\n" if data is not None else ""
        if argv[0] == "mv":
            if self.fail_on == "mv":
                raise self._gone()
            self.files[argv[3]] = self.files.pop(argv[2])
            return ""
        if argv[:2] == ["am", "broadcast"]:
            if self.fail_on:
                raise self._gone()
            self.rescanned.append(argv[-1])
            return "Broadcast completed: result=0"
        if argv[0] == "rm":
            if self.fail_on:
                raise self._gone()  # still disconnected: cleanup can't happen yet
            self.files.pop(argv[2], None)
            return ""
        raise AssertionError(argv)


FINAL = "/sdcard/Ringtones/tone.mp3"


@pytest.fixture
def song(tmp_path):
    p = tmp_path / "tone.mp3"
    p.write_bytes(b"NEW SONG DATA" * 100)
    return p


def test_upload_success_replaces_atomically(song):
    phone = FakeTransport({FINAL: b"old"})
    phone.push(song, "/sdcard/Ringtones")
    assert phone.files == {FINAL: song.read_bytes()}  # no temp file left
    # Android is told to re-read the final file so pickers show its real name, not the temp one.
    assert phone.rescanned == ["file:///storage/emulated/0/Ringtones/tone.mp3"]


def test_rescan_uri_encodes_awkward_names(tmp_path):
    odd = tmp_path / "Tone #1 50% (v2).mp3"
    odd.write_bytes(b"x")
    phone = FakeTransport()
    phone.push(odd, "/sdcard/Ringtones")
    assert phone.rescanned == [
        "file:///storage/emulated/0/Ringtones/Tone%20%231%2050%25%20%28v2%29.mp3"
    ]


@pytest.mark.parametrize("where", ["push", "mv"])
def test_upload_interrupted_keeps_original_file(song, where):
    phone = FakeTransport({FINAL: b"old"})
    phone.fail_on = where
    with pytest.raises(adb.AdbError):
        phone.push(song, "/sdcard/Ringtones")
    assert phone.files[FINAL] == b"old"  # original untouched
    leftovers = [p for p in phone.files if p != FINAL]
    assert all(Path(p).name.startswith(".") and p.endswith(adb.PARTIAL_SUFFIX) for p in leftovers)


def test_truncated_upload_is_rejected(song):
    phone = FakeTransport({FINAL: b"old"})
    phone.truncate_push = True
    with pytest.raises(adb.AdbError, match="incomplete"):
        phone.push(song, "/sdcard/Ringtones")
    assert phone.files == {FINAL: b"old"}


def test_unfinished_uploads_are_hidden_from_listings():
    out = f"10|1|/sdcard/Ringtones/.abc{adb.PARTIAL_SUFFIX}\n20|1|/sdcard/Ringtones/ok.mp3\n"
    assert [f.name for f in adb.parse_stat_listing(out)] == ["ok.mp3"]


def test_download_interrupted_leaves_no_partial_file(tmp_path):
    phone = FakeTransport({FINAL: b"data"})
    phone.fail_on = "pull"
    with pytest.raises(adb.AdbError):
        phone.pull(FINAL, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_never_overwrites(tmp_path):
    phone = FakeTransport({FINAL: b"data"})
    (tmp_path / "tone.mp3").write_bytes(b"mine")
    dest = phone.pull(FINAL, tmp_path)
    assert dest.name == "tone (2).mp3"
    assert (tmp_path / "tone.mp3").read_bytes() == b"mine"


@pytest.mark.parametrize(
    "phone_name",
    ["..\\..\\evil.mp3", "a\\..\\..\\b.mp3", "CON.mp3", "what?:*.mp3", "...", "nul"],
)
def test_phone_file_names_cannot_escape_download_folder(tmp_path, phone_name):
    phone = FakeTransport({f"/sdcard/Ringtones/{phone_name}": b"x"})
    dest = phone.pull(f"/sdcard/Ringtones/{phone_name}", tmp_path)
    assert dest.parent == tmp_path
    assert dest.read_bytes() == b"x"


def test_journal_survives_restart_and_hides_serial(tmp_path):
    j = Journal(tmp_path)
    j.save("SERIAL123", {"kind": "settings", "old": {}, "new": {}})
    assert Journal(tmp_path).load("SERIAL123") is not None  # a new instance (app restart)
    assert all("SERIAL123" not in p.name for p in tmp_path.iterdir())
    (next(tmp_path.iterdir())).write_text("{corrupt")
    assert j.load("SERIAL123") is None  # unreadable entries are discarded, not trusted
