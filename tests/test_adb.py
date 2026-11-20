from pathlib import Path

from soundmanager.adb import parse_devices, parse_stat_listing


def test_parse_devices_handles_ready_and_unauthorized():
    out = (
        "List of devices attached\n"
        "R5XX00TEST1            device usb:1-1 product:testprod model:SM_F966U device:q7q "
        "transport_id:2\n"
        "emulator-5554          unauthorized transport_id:1\n"
    )
    devices = parse_devices(out)
    assert [d.serial for d in devices] == ["R5XX00TEST1", "emulator-5554"]
    assert devices[0].ready and devices[0].label == "SM F966U"
    assert not devices[1].ready and devices[1].label == "emulator-5554 (unauthorized)"


def test_parse_devices_ignores_daemon_noise():
    out = "* daemon not running; starting now at tcp:5037\n* daemon started successfully\n"
    assert parse_devices(out) == []


def test_parse_stat_listing_sorts_and_keeps_pipes_in_names():
    out = (
        "2048|1700000000|/sdcard/Ringtones/b tone.ogg\n"
        "1024|1700000001|/sdcard/Ringtones/A|weird.mp3\n"
        "find: bad\n"
    )
    files = parse_stat_listing(out)
    assert [f.name for f in files] == ["A|weird.mp3", "b tone.ogg"]
    assert files[1].size == 2048


def test_unique_remote_name_ignores_case_like_the_phone():
    from soundmanager.adb import unique_remote_name

    assert unique_remote_name("tone.mp3", set()) == "tone.mp3"
    assert unique_remote_name("Tone.mp3", {"tone.mp3"}) == "Tone (2).mp3"
    assert unique_remote_name("tone.mp3", {"tone.mp3", "tone (2).mp3"}) == "tone (3).mp3"
    assert unique_remote_name("noext", {"noext"}) == "noext (2)"


def test_valid_phone_file_name_rejects_paths_and_hidden_files():
    from soundmanager.adb import valid_phone_file_name

    assert valid_phone_file_name("My tone: v2?.mp3")  # fine on Android
    for bad in ("", ".hidden.mp3", "../x.mp3", "a/b.mp3", "a\\b.mp3", "a\nb.mp3", "a\x00.mp3"):
        assert not valid_phone_file_name(bad), bad
    assert not valid_phone_file_name("x" * 201)


def test_install_and_uninstall_are_checked():
    import pytest

    from soundmanager.adb import AdbDevice, AdbError

    class Dev(AdbDevice):
        def __init__(self, out):
            super().__init__("FAKE1")
            self.out, self.calls = out, []

        def _adb(self, *args, timeout=60):
            self.calls.append(args)
            return self.out

    ok = Dev("Performing Streamed Install\nSuccess\n")
    ok.install(Path("app.apk"))
    assert ok.calls == [("install", "-r", "app.apk")]  # no -g (grant all) and no -d (downgrade)
    with pytest.raises(AdbError):
        Dev("Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]").install(Path("app.apk"))
    with pytest.raises(AdbError):
        ok.uninstall("com.example; rm -rf /")
