"""Main desktop window: pick a connected phone and manage its sound folders."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import adb
from ..tools import ToolNotFoundError, tool_status

AUDIO_FILTER = "Audio files (*.mp3 *.ogg *.m4a *.wav *.opus *.flac);;All files (*)"
DEFAULT_LIBRARY = Path.home() / "Music" / "Android Sound Manager"


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


class _BusyCursor:
    def __enter__(self):
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def __exit__(self, *exc):
        QGuiApplication.restoreOverrideCursor()


class FolderPanel(QWidget):
    """One phone folder (e.g. /sdcard/Ringtones) shown as a table with actions."""

    def __init__(self, main: MainWindow, remote_dir: str):
        super().__init__()
        self.main = main
        self.remote_dir = remote_dir
        self.files: list[adb.RemoteFile] = []

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Size", "Modified"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 420)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()

        buttons = QHBoxLayout()
        for text, slot in (
            ("Uploadâ€¦", self.upload),
            ("Download", self.download),
            ("Delete", self.delete),
            ("Refresh", self.refresh),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        buttons.addStretch()
        buttons.addWidget(QLabel(remote_dir))

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        self.table.setRowCount(0)
        self.files = []
        dev = self.main.device()
        if not dev:
            return
        with _BusyCursor():
            self.files = self.main.guard(lambda: dev.list_dir(self.remote_dir)) or []
        self.table.setRowCount(len(self.files))
        for row, f in enumerate(self.files):
            when = datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M")
            for col, value in enumerate((f.name, _human_size(f.size), when)):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def _selected(self) -> list[adb.RemoteFile]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.files[r] for r in rows if r < len(self.files)]

    def upload(self) -> None:
        dev = self.main.device()
        if not dev:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Upload to phone", str(DEFAULT_LIBRARY), AUDIO_FILTER
        )
        with _BusyCursor():
            for p in paths:
                if self.main.guard(lambda p=p: dev.push(Path(p), self.remote_dir)) is None:
                    break
        self.refresh()

    def download(self) -> None:
        dev = self.main.device()
        selected = self._selected()
        if not dev or not selected:
            return
        target = QFileDialog.getExistingDirectory(self, "Download to", str(DEFAULT_LIBRARY))
        if not target:
            return
        with _BusyCursor():
            for f in selected:
                self.main.guard(lambda f=f: dev.pull(f.path, Path(target)))
        self.main.statusBar().showMessage(f"Downloaded {len(selected)} file(s) to {target}", 5000)

    def delete(self) -> None:
        dev = self.main.device()
        selected = self._selected()
        if not dev or not selected:
            return
        names = "\n".join(f.name for f in selected)
        answer = QMessageBox.question(
            self, "Delete from phone", f"Delete from the phone?\n\n{names}"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with _BusyCursor():
            for f in selected:
                self.main.guard(lambda f=f: dev.delete(f.path))
        self.refresh()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Android Sound Manager")
        self.resize(960, 600)
        self.devices: list[adb.Device] = []

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(320)
        self.device_combo.currentIndexChanged.connect(self.refresh_folders)
        refresh_btn = QPushButton("Rescan devices")
        refresh_btn.clicked.connect(self.refresh_devices)

        top = QHBoxLayout()
        top.addWidget(QLabel("Phone:"))
        top.addWidget(self.device_combo)
        top.addWidget(refresh_btn)
        top.addStretch()

        self.tabs = QTabWidget()
        self.panels = [FolderPanel(self, path) for path in adb.SOUND_FOLDERS.values()]
        for name, panel in zip(adb.SOUND_FOLDERS, self.panels, strict=True):
            self.tabs.addTab(panel, name)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        missing = [name for name, path in tool_status().items() if path is None]
        if missing:
            self.statusBar().showMessage("Missing tools: " + ", ".join(missing))
        self.refresh_devices()

    def guard(self, fn):
        """Run *fn*, showing errors in a dialog instead of crashing. Returns None on failure."""
        try:
            return fn()
        except (adb.AdbError, ToolNotFoundError, OSError) as exc:
            QMessageBox.warning(self, "Error", str(exc))
            return None

    def refresh_devices(self) -> None:
        with _BusyCursor():
            self.devices = self.guard(adb.list_devices) or []
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for d in self.devices:
            self.device_combo.addItem(d.label)
        if not self.devices:
            self.device_combo.addItem("No phone found - check USB debugging")
        self.device_combo.blockSignals(False)
        self.refresh_folders()

        unauthorized = [d for d in self.devices if d.state == "unauthorized"]
        if unauthorized:
            self.statusBar().showMessage(
                "Unlock the phone and tap 'Allow' on the USB debugging prompt, then Rescan."
            )

    def device(self) -> adb.AdbDevice | None:
        i = self.device_combo.currentIndex()
        if 0 <= i < len(self.devices) and self.devices[i].ready:
            return adb.AdbDevice(self.devices[i].serial)
        return None

    def refresh_folders(self) -> None:
        for panel in self.panels:
            panel.refresh()
