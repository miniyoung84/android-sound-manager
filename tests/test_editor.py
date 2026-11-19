"""Editor tests: waveform data, waveform mouse editing, undo/redo, and saving a copy."""

import hashlib
import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from test_ui import wait_until  # noqa: E402

from soundmanager import audio  # noqa: E402
from soundmanager.journal import Journal  # noqa: E402
from soundmanager.tools import ToolNotFoundError, find_tool  # noqa: E402
from soundmanager.ui import main_window as mw  # noqa: E402
from soundmanager.ui.editor_dialog import EditorDialog, EditState, History  # noqa: E402
from soundmanager.ui.waveform import WaveformView  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tone(tmp_path):
    """4 s file: loud tone for 2 s, then 2 s of silence."""
    try:
        ffmpeg = find_tool("ffmpeg")
    except ToolNotFoundError:
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "tone.m4a"
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=44100",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=2",
         "-filter_complex", "[0][1]concat=n=2:v=0:a=1,volume=4", "-c:a", "aac", str(path)],
        check=True,
    )  # fmt: skip
    return path


def test_waveform_peaks_follow_the_audio(tone):
    peaks, duration = audio.waveform_peaks(tone, buckets=100)
    assert duration == pytest.approx(4, abs=0.1)
    assert 90 <= len(peaks) <= 110
    loud, quiet = peaks[5 : len(peaks) // 2 - 5], peaks[len(peaks) // 2 + 5 :]
    assert min(loud) > 0.2 and max(quiet) < 0.02
    assert all(0 <= p <= 1 for p in peaks)


def test_history_undo_redo():
    h = History(EditState(end=1))
    h.push(EditState(end=2))
    h.push(EditState(end=2))  # duplicate ignored
    h.push(EditState(end=3))
    assert h.undo().end == 2 and h.undo().end == 1 and h.undo().end == 1
    assert h.redo().end == 2
    h.push(EditState(end=9))  # new edit drops the redo branch
    assert not h.can_redo() and h.current.end == 9


def test_waveform_mouse_selection(app):
    view = WaveformView()
    view.resize(1000, 150)
    view.set_peaks([0.5] * 1000, 10.0)  # 100 px per second
    finished = []
    view.edit_finished.connect(lambda: finished.append(True))

    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(200, 75))  # 2 s
    QTest.mouseMove(view, QPoint(500, 75))  # 5 s
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(500, 75))
    assert view.start == pytest.approx(2, abs=0.02) and view.end == pytest.approx(5, abs=0.02)

    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(500, 75))  # grab end handle
    QTest.mouseMove(view, QPoint(800, 75))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(800, 75))
    assert view.start == pytest.approx(2, abs=0.02) and view.end == pytest.approx(8, abs=0.02)

    shift = Qt.KeyboardModifier.ShiftModifier  # Shift+drag inside slides the whole region
    QTest.mousePress(view, Qt.MouseButton.LeftButton, shift, QPoint(400, 75))
    QTest.mouseMove(view, QPoint(5000, 75))  # way past the end: clamps
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, shift, QPoint(5000, 75))
    assert view.end == pytest.approx(10, abs=0.02) and view.end - view.start == pytest.approx(6)

    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(600, 75))  # plain drag inside
    QTest.mouseMove(view, QPoint(700, 75))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(700, 75))
    assert view.start == pytest.approx(6, abs=0.02) and view.end == pytest.approx(7, abs=0.02)
    assert len(finished) == 4


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setattr(mw.adb, "list_devices", lambda: [])
    w = mw.MainWindow(journal=Journal(tmp_path / "j"), library_dir=tmp_path / "lib")
    yield w
    w.close()


def test_editor_saves_trimmed_copy_and_keeps_original(window, tone, tmp_path):
    original_hash = hashlib.sha256(tone.read_bytes()).hexdigest()
    lib = tmp_path / "lib"
    dlg = EditorDialog(window, tone, lib)
    assert wait_until(lambda: not dlg._loading, 10000)
    assert dlg.end_box.value() == pytest.approx(4, abs=0.1)  # whole file (under 30 s)

    dlg.start_box.setValue(0.5)
    dlg.end_box.setValue(2.0)
    dlg.fade_out_box.setValue(0.3)
    assert dlg.history.can_undo()
    dlg.undo()
    assert dlg.fade_out_box.value() == 0
    dlg.redo()
    assert dlg.fade_out_box.value() == pytest.approx(0.3)

    dlg.name_edit.setText("..\\..\\escape attempt")
    dlg.format_combo.setCurrentIndex(dlg.format_combo.findData(".mp3"))
    dlg.save()
    assert wait_until(lambda: dlg.saved_path is not None, 15000)

    saved = dlg.saved_path
    assert saved.parent == lib and saved.suffix == ".mp3"  # name can't escape the library
    assert audio.probe_duration(saved) == pytest.approx(1.5, abs=0.1)
    assert hashlib.sha256(tone.read_bytes()).hexdigest() == original_hash


def test_editor_rejects_invalid_region(window, tone, tmp_path):
    dlg = EditorDialog(window, tone, tmp_path / "lib")
    assert wait_until(lambda: not dlg._loading, 10000)
    dlg.start_box.setValue(3.0)
    dlg.end_box.setValue(1.0)  # end before start: corrected to a tiny valid region
    assert dlg.end_box.value() - dlg.start_box.value() >= 0.099
    dlg.reject()
