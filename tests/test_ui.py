"""Headless UI tests. ADB is replaced with fakes; no phone is touched."""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from soundmanager import adb, phone_contacts, phone_sounds  # noqa: E402
from soundmanager.journal import Journal  # noqa: E402
from soundmanager.ui import contacts_panel as cp  # noqa: E402
from soundmanager.ui import main_window as mw  # noqa: E402
from soundmanager.ui.tasks import TaskRunner  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(predicate, timeout_ms=3000):
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start(10)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return predicate()


# --------------------------------------------------------------------------- TaskRunner


def test_runner_delivers_results_on_ui_thread(app):
    errors, results = [], []
    runner = TaskRunner(errors.append)
    ui_thread = threading.current_thread()

    runner.submit(lambda: threading.current_thread(), lambda t: results.append(t))
    runner.submit(lambda: 1 / 0)

    assert wait_until(lambda: results and errors)
    assert results[0] is not ui_thread  # work ran in the background...
    assert isinstance(errors[0], ZeroDivisionError)  # ...errors came back to the default handler
    assert not runner.busy
    runner.shutdown()


# --------------------------------------------------------------------------- main window

FILE = adb.RemoteFile("/sdcard/Ringtones/tone.mp3", 1000, 1_700_000_000)
CONTACTS = [
    phone_contacts.Contact(1, "Avery Example", True, None),
    phone_contacts.Contact(2, "Blake Sample", True, "content://media/external/audio/media/1"),
    phone_contacts.Contact(3, "Front Desk Org", False, None),
]


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(adb, "list_devices", lambda: [adb.Device("FAKE1", "device", "SM_X1")])
    monkeypatch.setattr(adb.AdbDevice, "friendly_name", lambda self: "Test Phone")
    monkeypatch.setattr(
        adb.AdbDevice,
        "list_dir",
        lambda self, d: [FILE] if d.endswith("Ringtones") else [],
    )
    monkeypatch.setattr(
        phone_sounds,
        "available_keys",
        lambda dev, s: ["ringtone", "ringtone_2"] if s == "ringtone" else [s],
    )
    monkeypatch.setattr(
        phone_sounds,
        "get_default",
        lambda dev, k: phone_sounds.DefaultSound(k, "content://x", "Old", None),
    )

    def fake_set(dev, key, path, journal=None):
        calls.append((key, path))
        return {key: "content://x"}

    monkeypatch.setattr(phone_sounds, "set_default", fake_set)
    monkeypatch.setattr(phone_sounds, "recover_pending", lambda dev, journal: None)
    monkeypatch.setattr(adb.AdbDevice, "cleanup_partial_uploads", lambda self: None)
    monkeypatch.setattr(phone_contacts, "list_contacts", lambda dev: list(CONTACTS))
    monkeypatch.setattr(
        phone_contacts, "describe_ringtones", lambda dev, uris: {u: "tone.mp3" for u in uris}
    )
    contact_calls = []
    monkeypatch.setattr(
        phone_contacts,
        "set_contact_ringtone",
        lambda dev, cid, path: contact_calls.append((cid, path)) or None,
    )
    w = mw.MainWindow(journal=Journal(tmp_path / "journal"), library_dir=tmp_path / "lib")
    w.calls, w.contact_calls = calls, contact_calls
    assert wait_until(
        lambda: (
            w.panels[0].table.rowCount() == 1
            and w.contacts_panel.table.rowCount() == len(CONTACTS)
            and not w.runner.busy
        )
    )
    yield w
    w.close()


def test_window_lists_phone_and_files(window):
    assert window.device_combo.currentText() == "Test Phone (SM-X1)"
    panel = window.panels[0]
    assert panel.table.item(0, 0).text() == "tone.mp3"
    assert "SIM 1" in panel.current_label.text() and "SIM 2" in panel.current_label.text()


def test_unplug_and_replug_updates_window(window):
    panel = window.panels[0]
    window._on_devices([])  # unplugged
    assert window.device() is None
    assert panel.table.rowCount() == 0 and not panel.set_button.isEnabled()
    assert "No phone found" in window.device_combo.currentText()

    window._on_devices([adb.Device("FAKE1", "unauthorized")])  # replugged, not yet allowed
    assert window.device() is None
    assert "Allow" in window.statusBar().currentMessage()

    window._on_devices([adb.Device("FAKE1", "device", "SM_X1")])  # allowed
    assert wait_until(lambda: panel.table.rowCount() == 1 and not window.runner.busy)
    assert window.device_combo.currentText() == "Test Phone (SM-X1)"


def test_set_menu_requires_selection_and_confirmation(window, monkeypatch):
    panel = window.panels[0]

    panel._build_set_menu()  # nothing selected: only a disabled hint
    actions = panel.set_menu.actions()
    assert len(actions) == 1 and not actions[0].isEnabled()

    panel.table.selectRow(0)
    panel._build_set_menu()
    labels = [a.text() for a in panel.set_menu.actions() if not a.isSeparator()]
    assert labels == ["SIM 1…", "SIM 2…", "All SIMs…"]

    # Declining the confirmation must not change anything.
    monkeypatch.setattr(mw, "_message", lambda *a, **k: False)
    panel.set_menu.actions()[0].trigger()
    QCoreApplication.processEvents()
    assert window.calls == []

    # Confirming applies it and enables Undo.
    monkeypatch.setattr(mw, "_message", lambda *a, **k: True)
    panel.set_menu.actions()[0].trigger()
    assert wait_until(lambda: window.calls and not window.runner.busy)
    assert window.calls == [("ringtone", FILE.path)]
    assert wait_until(lambda: panel.undo_button.isEnabled())


def test_upload_rejects_non_audio_and_confirms_overwrite(window, monkeypatch, tmp_path):
    panel = window.panels[0]
    pushed, prompts = [], []
    monkeypatch.setattr(adb.AdbDevice, "push", lambda self, p, d: pushed.append(p.name))
    monkeypatch.setattr(mw, "_message", lambda _p, title, *a, **k: prompts.append(title) or False)

    doc = tmp_path / "notes.txt"
    doc.write_text("x")
    clash = tmp_path / "TONE.mp3"  # same name, different case: still a clash on the phone
    clash.write_bytes(b"x")

    panel.upload_paths([str(doc), str(clash)])
    QCoreApplication.processEvents()
    assert prompts == ["Not audio", "Replace files?"]
    assert pushed == []  # user declined the overwrite


# --------------------------------------------------------------------------- contacts tab


def visible_names(panel):
    return [
        panel.table.item(r, 0).text()
        for r in range(panel.table.rowCount())
        if not panel.table.isRowHidden(r)
    ]


def test_contacts_tab_filters(window):
    panel = window.contacts_panel
    assert visible_names(panel) == ["Avery Example", "Blake Sample"]  # hides no-number contact
    panel.only_custom.setChecked(True)
    assert visible_names(panel) == ["Blake Sample"]
    panel.only_custom.setChecked(False)
    panel.search.setText("aver")
    assert visible_names(panel) == ["Avery Example"]
    assert panel.table.item(1, 1).text() == "♪ tone.mp3"


def test_contact_change_needs_confirmation(window, monkeypatch):
    panel = window.contacts_panel
    panel.table.selectRow(0)
    panel.sound_combo.setCurrentIndex(panel.sound_combo.findText("tone.mp3"))

    monkeypatch.setattr(cp, "message", lambda *a, **k: False)
    panel.apply()
    QCoreApplication.processEvents()
    assert window.contact_calls == []

    monkeypatch.setattr(cp, "message", lambda *a, **k: True)
    panel.apply()
    assert wait_until(lambda: window.contact_calls and not window.runner.busy)
    assert window.contact_calls == [(1, FILE.path)]
    assert wait_until(lambda: panel.undo_button.isEnabled())


def test_disconnect_errors_dont_pop_dialogs(window, monkeypatch):
    dialogs = []
    monkeypatch.setattr(mw, "_message", lambda *a, **k: dialogs.append(a) or False)
    for _ in range(3):  # several queued tasks failing at once
        window.show_error(adb.AdbError("adb: device 'FAKE1' not found"))
    assert dialogs == []
    assert "disconnected" in window.statusBar().currentMessage().lower()
    window.show_error(adb.AdbError("Refusing to upload outside the sound folders"))
    assert len(dialogs) == 1  # real errors still get a dialog


# --------------------------------------------------------------------------- library tab


def test_library_lists_and_sends_to_phone(window, tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    (lib / "chime.mp3").write_bytes(b"x")
    panel = window.library_panel
    panel.refresh()
    assert wait_until(lambda: panel.table.rowCount() == 1 and not window.media_runner.busy)
    assert panel.table.item(0, 0).text() == "chime.mp3"

    panel._build_send_menu()  # nothing selected yet
    assert not panel.send_menu.actions()[0].isEnabled()

    panel.table.selectRow(0)
    panel._build_send_menu()
    assert [a.text() for a in panel.send_menu.actions()] == [
        "To Ringtones",
        "To Notifications",
        "To Alarms",
    ]
    sent = []
    target = window.folder_panel("Notifications")
    monkeypatch.setattr(target, "upload_paths", lambda paths: sent.extend(paths))
    panel.send_menu.actions()[1].trigger()
    assert sent == [str(lib / "chime.mp3")]


def test_library_send_needs_phone(window):
    window._on_devices([])
    window.library_panel._build_send_menu()
    actions = window.library_panel.send_menu.actions()
    assert len(actions) == 1 and "Connect your phone" in actions[0].text()


def test_library_rejects_bad_links_without_downloading(window, monkeypatch):
    shown = []
    monkeypatch.setattr(
        "soundmanager.ui.library_panel.message", lambda _p, _t, text, **k: shown.append(text)
    )
    monkeypatch.setattr(
        "soundmanager.youtube.download_audio",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    window.library_panel.url.setText("file:///C:/Windows/win.ini")
    window.library_panel.download()
    assert shown and "http" in shown[0]


def test_no_phone_at_startup_says_so(app, monkeypatch, tmp_path):
    monkeypatch.setattr(adb, "list_devices", lambda: [])
    w = mw.MainWindow(journal=Journal(tmp_path / "j"), library_dir=tmp_path / "lib")
    assert wait_until(lambda: "No phone found" in w.device_combo.currentText())
    w.close()
