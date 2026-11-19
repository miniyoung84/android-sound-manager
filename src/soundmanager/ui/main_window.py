"""Main desktop window: pick a connected phone and manage its sound folders."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import adb, phone_sounds
from ..tools import ToolNotFoundError, tool_status

AUDIO_FILTER = "Audio files (*.mp3 *.ogg *.m4a *.wav *.opus *.flac);;All files (*)"
DEFAULT_LIBRARY = Path.home() / "Music" / "Android Sound Manager"

# Phone folder tab -> sound type in phone_sounds.SOUND_KEYS, and its human name.
FOLDER_SOUND = {
    "Ringtones": ("ringtone", "ringtone"),
    "Notifications": ("notification", "notification sound"),
    "Alarms": ("alarm", "alarm"),
}


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def _slot_label(key: str, keys: list[str]) -> str:
    if len(keys) == 1:
        return "Default"
    return f"SIM {keys.index(key) + 1}"


class _BusyCursor:
    def __enter__(self):
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def __exit__(self, *exc):
        QGuiApplication.restoreOverrideCursor()


class FolderPanel(QWidget):
    """One phone folder (e.g. /sdcard/Ringtones) shown as a table with actions."""

    def __init__(self, main: MainWindow, folder: str, remote_dir: str):
        super().__init__()
        self.main = main
        self.remote_dir = remote_dir
        self.sound, self.sound_name = FOLDER_SOUND[folder]
        self.files: list[adb.RemoteFile] = []
        self.keys: list[str] = []
        self.undo_snapshot: phone_sounds.Snapshot | None = None
        self.undo_serial = ""  # undo only ever applies to the phone it was made on
        self.undo_text = ""

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Default", "Size", "Modified"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 420)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()

        buttons = QHBoxLayout()
        for text, slot in (
            ("Upload…", self.upload),
            ("Download", self.download),
            ("Delete", self.delete),
            ("Refresh", self.refresh),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        buttons.addSpacing(16)

        self.set_button = QToolButton()
        self.set_button.setText(f"Set as {self.sound_name}")
        self.set_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.set_button.clicked.connect(lambda: self.set_default(self.keys[:1]))
        buttons.addWidget(self.set_button)

        self.undo_button = QPushButton("Undo")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo)
        buttons.addWidget(self.undo_button)
        buttons.addStretch()
        buttons.addWidget(QLabel(remote_dir))

        self.current_label = QLabel()
        self.current_label.setTextFormat(Qt.TextFormat.RichText)
        self.current_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.current_label)
        layout.addWidget(self.table)

    # ------------------------------------------------------------------ refresh

    def refresh(self) -> None:
        self.table.setRowCount(0)
        self.files = []
        self.current_label.clear()
        dev = self.main.device()
        self.set_button.setEnabled(dev is not None)
        if not dev:
            self.undo_snapshot = None
            self.undo_button.setEnabled(False)
            return
        with _BusyCursor():
            self.files = self.main.guard(lambda: dev.list_dir(self.remote_dir)) or []
            self.keys = self.main.guard(lambda: phone_sounds.available_keys(dev, self.sound)) or []
            defaults = [
                d
                for k in self.keys
                if (d := self.main.guard(lambda k=k: phone_sounds.get_default(dev, k)))
            ]
        self._update_set_menu()
        self._show_defaults(defaults)

        default_slots: dict[str, list[str]] = {}
        for d in defaults:
            if d.path:
                default_slots.setdefault(d.path, []).append(_slot_label(d.key, self.keys))

        bold = QFont()
        bold.setBold(True)
        self.table.setRowCount(len(self.files))
        for row, f in enumerate(self.files):
            when = datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M")
            slots = default_slots.get(phone_sounds.to_storage_path(f.path), [])
            marker = ("★ " + ", ".join(slots)) if slots else ""
            for col, value in enumerate((f.name, marker, _human_size(f.size), when)):
                item = QTableWidgetItem(value)
                if slots:
                    item.setFont(bold)
                self.table.setItem(row, col, item)

    def _show_defaults(self, defaults: list[phone_sounds.DefaultSound]) -> None:
        if not defaults:
            return
        parts = []
        for d in defaults:
            prefix = "" if len(self.keys) == 1 else f"{_slot_label(d.key, self.keys)}: "
            parts.append(f"{prefix}<b>{_escape(d.title)}</b>")
        self.current_label.setText(f"Current {self.sound_name}: " + "  ·  ".join(parts))

    def _update_set_menu(self) -> None:
        if len(self.keys) <= 1:
            self.set_button.setMenu(None)
            self.set_button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
            return
        menu = QMenu(self)
        for key in self.keys:
            menu.addAction(_slot_label(key, self.keys), lambda k=key: self.set_default([k]))
        menu.addAction("All SIMs", lambda: self.set_default(list(self.keys)))
        self.set_button.setMenu(menu)
        self.set_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

    # ------------------------------------------------------------------ actions

    def _selected(self) -> list[adb.RemoteFile]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.files[r] for r in rows if r < len(self.files)]

    def set_default(self, keys: list[str]) -> None:
        dev = self.main.device()
        selected = self._selected()
        if not dev or not keys:
            return
        if len(selected) != 1:
            _message(self, "Pick one sound", "Select exactly one sound first.")
            return
        target = selected[0]
        snapshot: phone_sounds.Snapshot = {}
        with _BusyCursor():
            for key in keys:
                prev = self.main.guard(lambda k=key: phone_sounds.set_default(dev, k, target.path))
                if prev is None:
                    break
                for k, v in prev.items():
                    snapshot.setdefault(k, v)
        if snapshot:
            self.undo_snapshot = snapshot
            self.undo_serial = dev.serial
            self.undo_text = f"{self.sound_name} change"
            self.undo_button.setEnabled(True)
            where = (
                ""
                if len(self.keys) == 1
                else f" ({', '.join(_slot_label(k, self.keys) for k in keys)})"
            )
            self.main.statusBar().showMessage(
                f"{self.sound_name.capitalize()}{where} set to {target.name}.", 8000
            )
        self.refresh()

    def undo(self) -> None:
        dev = self.main.device()
        if not dev or not self.undo_snapshot:
            return
        if dev.serial != self.undo_serial:
            _message(self, "Different phone", "That change was made on a different phone.")
            return
        with _BusyCursor():
            ok = self.main.guard(lambda: phone_sounds.restore(dev, self.undo_snapshot) or True)
        if ok:
            self.main.statusBar().showMessage(f"Undid {self.undo_text}.", 5000)
            self.undo_snapshot = None
            self.undo_button.setEnabled(False)
        self.refresh()

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
        if not _message(self, "Delete from phone", f"Delete from the phone?\n\n{names}", ask=True):
            return
        with _BusyCursor():
            for f in selected:
                self.main.guard(lambda f=f: dev.delete(f.path))
        self.refresh()


def _message(parent, title: str, text: str, ask: bool = False, icon=None) -> bool:
    """Message box that always renders *text* as plain text (it may contain phone file names)."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(text)
    if ask:
        box.setIcon(QMessageBox.Icon.Question)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
    else:
        box.setIcon(icon or QMessageBox.Icon.Information)
    return box.exec() == QMessageBox.StandardButton.Yes


def _escape(text: str) -> str:
    """Escape text for a rich-text QLabel (file names come from the phone)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Android Sound Manager")
        self.resize(1000, 620)
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
        self.panels = [FolderPanel(self, name, path) for name, path in adb.SOUND_FOLDERS.items()]
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
            _message(self, "Error", str(exc), icon=QMessageBox.Icon.Warning)
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
