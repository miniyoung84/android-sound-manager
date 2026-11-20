"""Reading other apps' notification categories and opening one on the phone (all data made up)."""

import pytest
from fakes import TONE, FakePhone

from soundmanager import phone_apps as pa
from soundmanager.adb import AdbError


def channel(cid, name, importance=3, sound=pa.DEFAULT_NOTIFICATION_URI, group="null", **extra):
    fields = {"mDeleted": "false", "mConversationId": "null", **extra}
    tail = ", ".join(f"{k}={v}" for k, v in fields.items())
    return (
        f"        NotificationChannel{{mId='{cid}', mName={name}, mDescription=, "
        f"mImportance={importance}, mBypassDnd=false, mLockscreenVisibility=-1000, "
        f"mSound={sound}, mLights=false, mLightColor=0, mGroup='{group}', {tail}, "
        "mDemoted=false}"
    )


DUMP = "\n".join(
    [
        "  Notification List:",
        "    NotificationRecord(0x1: pkg=com.example.chat ... text=some private message)",
        " Notification Preferences:",
        "PackagePreferences:",
        "      AppSettings: com.example.chat (10200) importance=DEFAULT userSet=false",
        "        Delegate: com.example.helper (10300) enabled=true",
        channel("dm", "Direct messages", importance=4, group="g1"),
        channel(
            "calls", "Calls, and more", sound=f"content://media/external/audio/media/{TONE.id}"
        ),
        channel("quiet", "Promotions", importance=2),
        channel("muted", "Muted", sound="null"),
        channel("old", "Deleted one", mDeleted="true"),
        channel("convo", "Someone", mConversationId="abc"),
        "        NotificationChannelGroup{mId='g1', mName=Friends, mDescription=, mBlocked=false}",
        "      AppSettings: com.example.nochannels (10201)",
        "      AppSettings: com.example.off (10202) importance=NONE userSet=true",
        channel("x", "Everything"),
        "      AppSettings: com.example.chat (1010200)",  # Dual Messenger copy (user 10)
        channel("dm", "Direct messages"),
        "      AppSettings: com.zhiliaoapp.musically (10203)",
        channel("res", "Likes", sound="android.resource://com.zhiliaoapp.musically/raw/tone"),
        "      AppSettings: bad;name (10204)",
        channel("y", "Nope"),
        "Restored without uid:",
        "      AppSettings: com.example.restored (0)",
        channel("z", "Not installed"),
    ]
)


def apps_by_package():
    return {a.package: a for a in pa.parse_channels(DUMP)}


def test_parses_main_user_apps_and_channels():
    apps = apps_by_package()
    assert set(apps) == {"com.example.chat", "com.example.off", "com.zhiliaoapp.musically"}
    chat = apps["com.example.chat"]
    assert [c.id for c in chat.channels] == ["dm", "calls", "quiet", "muted", "convo"]
    dm, calls, quiet, muted, convo = chat.channels
    assert dm.name == "Direct messages" and dm.group == "Friends" and not dm.silent
    assert calls.name == "Calls, and more" and calls.sound.endswith(f"/{TONE.id}")
    assert quiet.silent and muted.silent and muted.sound is None
    assert convo.conversation and not dm.conversation
    assert apps["com.example.off"].blocked and not chat.blocked


def test_app_labels():
    assert pa.app_label("com.zhiliaoapp.musically") == "TikTok"
    assert pa.app_label("com.example.chat") == "Example"
    assert pa.app_label("org.coolapps.android.mobile") == "Coolapps"


def test_launcher_filter_and_sound_labels():
    phone = FakePhone(media=[TONE])
    phone.notification_dump = DUMP
    phone.launcher_apps = ["com.example.chat", "com.example.nochannels"]
    apps = pa.list_apps(phone)
    assert [a.package for a in apps] == ["com.example.chat"]
    labels = pa.describe_sounds(phone, apps)
    chat = apps[0]
    assert labels[chat.channels[0].sound] == "Default notification sound"
    assert labels[chat.channels[1].sound] == TONE.path.rsplit("/", 1)[-1]


def test_launcher_filter_skipped_when_query_unsupported():
    phone = FakePhone()
    phone.notification_dump = DUMP
    assert len(pa.list_apps(phone)) == 3


def test_sound_label_fallbacks():
    assert pa.sound_label(None) == "Silent"
    assert pa.sound_label("android.resource://x.y/raw/z") == "App's own sound"
    assert pa.sound_label("file:///system/media/audio/ui/LowBattery.ogg") == "LowBattery"
    assert pa.sound_label("content://settings/system/ringtone") == "Phone's ringtone"


def test_open_channel_settings_quotes_untrusted_ids():
    phone = FakePhone()
    tricky = "dm'; reboot; echo '$(id) x"
    pa.open_channel_settings(phone, "com.example.chat", tricky)
    assert phone.started[-1] == [
        "-a",
        "android.settings.CHANNEL_NOTIFICATION_SETTINGS",
        "--es",
        "android.provider.extra.APP_PACKAGE",
        "com.example.chat",
        "--es",
        "android.provider.extra.CHANNEL_ID",
        tricky,  # arrived as one literal argument, nothing executed
    ]


@pytest.mark.parametrize(
    ("package", "cid"), [("bad;pkg", "dm"), ("com.example.chat", ""), ("com.a.b", "x\ny")]
)
def test_open_channel_settings_rejects_invalid(package, cid):
    phone = FakePhone()
    with pytest.raises(AdbError):
        pa.open_channel_settings(phone, package, cid)
    assert phone.started == []
