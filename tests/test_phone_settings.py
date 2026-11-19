"""Opening settings screens on the phone (fake phone; nothing is launched for real)."""

import pytest
from fakes import FakePhone

from soundmanager import phone_settings as st
from soundmanager.adb import AdbError


def test_open_conversation_settings_wakes_and_starts():
    phone = FakePhone()
    st.open_conversation_settings(phone)
    assert ["input", "keyevent", "KEYCODE_WAKEUP"] in phone.commands
    assert phone.started == [["-a", "android.settings.CONVERSATION_SETTINGS"]]


def test_open_app_settings_for_default_messaging_app():
    phone = FakePhone()
    phone.sms_app = "com.samsung.android.messaging"
    st.open_app_notification_settings(phone, st.default_messaging_app(phone))
    assert phone.started[-1][-1] == "com.samsung.android.messaging"


@pytest.mark.parametrize("bad", ["com.x; reboot", "null", "", "x", "com.$(id).y", "a.b c"])
def test_untrusted_package_names_are_never_used(bad):
    phone = FakePhone()
    phone.sms_app = bad
    assert st.default_messaging_app(phone) == st.FALLBACK_MESSAGING_APP
    with pytest.raises(AdbError):
        st.open_app_notification_settings(phone, bad)
    assert phone.started == []
