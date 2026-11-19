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
