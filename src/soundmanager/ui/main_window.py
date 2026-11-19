"""Main desktop window: pick a connected phone and manage its sound folders."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
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
from .tasks import TaskRunner

AUDIO_EXTENSIONS = (".mp3", ".ogg", ".m4a", ".wav", ".opus", ".flac", ".aac")
AUDIO_FILTER = "Audio files (" + " ".join(f"*{e}" for e in AUDIO_EXTENSIONS) + ");;All files (*)"
DEFAULT_LIBRARY = Path.home() / "Music" / "Android Sound Manager"
DEVICE_POLL_MS = 2500

# Phone folder tab -> sound type in phone_sounds.SOUND_KEYS, and its human name.
FOLDER_SOUND = {
    "Ringtones": ("ringtone", "ringtone"),
    "Notifications": ("notification", "notification sound"),
    "Alarms": ("alarm", "alarm"),
}


# --------------------------------------------------------------------------- helpers


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def _slot_label(key: str, keys: list[str]) -> str:
    return "Default" if len(keys) == 1 else f"SIM {keys.index(key) + 1}"


def _escape(text: str) -> str:
    """Escape text for a rich-text QLabel (file names come from the phone)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _message(parent, title: str, text: str, ask: bool = False, icon=None) -> bool:
    """Message box that always renders *text* as plain text (it may contain phone file names).

    With ask=True it is a Yes/Cancel question whose default (Enter) is Cancel.
    """
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(text)
    if ask:
        box.setIcon(QMessageBox.Icon.Question)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    else:
        box.setIcon(icon or QMessageBox.Icon.Information)
    return box.exec() == QMessageBox.StandardButton.Yes


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, (adb.AdbError, ToolNotFoundError, OSError)):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- widgets


class DropTable(QTableWidget):
    """Table that accepts local files dragged in from Explorer."""

    files_dropped = Signal(list)

    def __init__(self, rows: int, cols: int):
        super().__init__(rows, cols)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QTableWidget.DragDropMode.DropOnly)

    @staticmethod
    def _local_files(event) -> list[str]:
        data = event.mimeData()
        urls = data.urls() if data.hasUrls() else []
        return [
            u.toLocalFile() for u in urls if u.isLocalFile() and Path(u.toLocalFile()).is_file()
        ]

    def dragEnterEvent(self, event):
        if self.acceptDrops() and self._local_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        files = self._local_files(event) if self.acceptDrops() else []
        if files:
            event.acceptProposedAction()
            self.files_dropped.emit(files)
        else:
            event.ignore()


class FolderPanel(QWidget):
    """One phone folder (e.g. /sdcard/Ringtones) shown as a table with actions."""

    def __init__(self, main: MainWindow, folder: str, remote_dir: str):
        super().__init__()
        self.main = main
        self.remote_dir = remote_dir
        self.sound, self.sound_name = FOLDER_SOUND[folder]
        self.files: list[adb.RemoteFile] = []
        self.keys: list[str] = []
        self.defaults: dict[str, phone_sounds.DefaultSound] = {}
        self.undo_snapshot: phone_sounds.Snapshot | None = None
        self.undo_serial = ""  # undo only ever applies to the phone it was made on
        self.undo_text = ""
        self._refresh_token = 0
        self._busy = False

        self.table = DropTable(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Default", "Size", "Modified"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 420)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.files_dropped.connect(self.upload_paths)

        buttons = QHBoxLayout()
        self.action_buttons: list[QWidget] = []
        for text, slot in (
            ("Upload…", self.upload),
            ("Download", self.download),
            ("Delete", self.delete),
            ("Refresh", self.refresh),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
            self.action_buttons.append(btn)
        buttons.addStretch()

        # Changing a default is always: open menu -> pick an entry -> confirm. Never one click.
        self.set_button = QToolButton()
        self.set_button.setText(f"Set as {self.sound_name}…")
        self.set_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.set_menu = QMenu(self)
        self.set_menu.aboutToShow.connect(self._build_set_menu)
        self.set_button.setMenu(self.set_menu)
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        buttons.addWidget(self.set_button)
        buttons.addWidget(self.undo_button)
        self.action_buttons.append(self.set_button)

        self.current_label = QLabel()
        self.current_label.setTextFormat(Qt.TextFormat.RichText)
        self.current_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        hint = QLabel(f"{remote_dir}  ·  drag audio files here to upload")
        hint.setStyleSheet("color: gray;")

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.current_label)
        layout.addWidget(self.table)
        layout.addWidget(hint)
        self._set_busy(False)

    # ------------------------------------------------------------------ state

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        enabled = self.main.device() is not None and not busy
        for w in self.action_buttons:
            w.setEnabled(enabled)
        self.undo_button.setEnabled(enabled and self.undo_snapshot is not None)
        self.table.setAcceptDrops(enabled)

    def _run(self, fn, on_done=None) -> None:
        """Run *fn* in the background with this panel's buttons disabled meanwhile."""
        self._set_busy(True)

        def done(result):
            self._set_busy(False)
            if on_done:
                on_done(result)

        def failed(exc):
            self._set_busy(False)
            self.main.show_error(exc)

        self.main.runner.submit(fn, done, failed)

    # ------------------------------------------------------------------ refresh

    def clear(self) -> None:
        self._refresh_token += 1
        self.files, self.keys, self.defaults = [], [], {}
        self.table.setRowCount(0)
        self.current_label.clear()
        self._set_busy(False)

    def refresh(self) -> None:
        dev = self.main.device()
        if not dev:
            self.clear()
            return
        self._refresh_token += 1
        token = self._refresh_token
        remote_dir, sound = self.remote_dir, self.sound

        def work():
            files = dev.list_dir(remote_dir)
            keys = phone_sounds.available_keys(dev, sound)
            defaults = {k: phone_sounds.get_default(dev, k) for k in keys}
            return files, keys, defaults

        def done(result):
            if token == self._refresh_token:  # ignore results from an older refresh
                self._populate(*result)

        self._run(work, done)

    def _populate(self, files, keys, defaults) -> None:
        self.files, self.keys, self.defaults = files, keys, defaults
        parts = []
        for key, d in defaults.items():
            prefix = "" if len(keys) == 1 else f"{_slot_label(key, keys)}: "
            parts.append(f"{prefix}<b>{_escape(d.title)}</b>")
        text = f"Current {self.sound_name}: " + "  ·  ".join(parts) if parts else ""
        self.current_label.setText(text)

        slots_by_path: dict[str, list[str]] = {}
        for key, d in defaults.items():
            if d.path:
                slots_by_path.setdefault(d.path, []).append(_slot_label(key, keys))

        bold = QFont()
        bold.setBold(True)
        self.table.setRowCount(len(files))
        for row, f in enumerate(files):
            when = datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M")
            slots = slots_by_path.get(phone_sounds.to_storage_path(f.path), [])
            marker = ("★ " + ", ".join(slots)) if slots else ""
            for col, value in enumerate((f.name, marker, _human_size(f.size), when)):
                item = QTableWidgetItem(value)
                if slots:
                    item.setFont(bold)
                self.table.setItem(row, col, item)

    # ------------------------------------------------------------------ defaults

    def _selected(self) -> list[adb.RemoteFile]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.files[r] for r in rows if r < len(self.files)]

    def _build_set_menu(self) -> None:
        self.set_menu.clear()
        selected = self._selected()
        if len(selected) != 1 or not self.keys:
            self.set_menu.addAction("Select one sound in the list first").setEnabled(False)
            return
        name = selected[0].name
        if len(self.keys) == 1:
            self.set_menu.addAction(
                f"Use “{name}” as {self.sound_name}…",
                lambda: self.set_default(list(self.keys)),
            )
            return
        for key in self.keys:
            self.set_menu.addAction(
                f"{_slot_label(key, self.keys)}…", lambda k=key: self.set_default([k])
            )
        self.set_menu.addSeparator()
        self.set_menu.addAction("All SIMs…", lambda: self.set_default(list(self.keys)))

    def set_default(self, keys: list[str]) -> None:
        dev = self.main.device()
        selected = self._selected()
        if not dev or not keys or len(selected) != 1:
            return
        target = selected[0]
        lines = []
        for k in keys:
            old = self.defaults[k].title if k in self.defaults else "?"
            lines.append(f"  {_slot_label(k, self.keys)}:  {old}  →  {target.name}")
        question = (
            f"Change your {self.sound_name}?\n\n" + "\n".join(lines) + "\n\nYou can undo this."
        )
        if not _message(self, f"Change {self.sound_name}", question, ask=True):
            return

        def work():
            snapshot: phone_sounds.Snapshot = {}
            for key in keys:
                for k, v in phone_sounds.set_default(dev, key, target.path).items():
                    snapshot.setdefault(k, v)
            return snapshot

        def done(snapshot):
            self.undo_snapshot, self.undo_serial = snapshot, dev.serial
            self.undo_text = f"{self.sound_name} change"
            where = ""
            if len(self.keys) > 1:
                where = " (" + ", ".join(_slot_label(k, self.keys) for k in keys) + ")"
            self.main.status(f"{self.sound_name.capitalize()}{where} set to {target.name}.")
            self.refresh()

        self._run(work, done)

    def undo(self) -> None:
        dev = self.main.device()
        if not dev or not self.undo_snapshot:
            return
        if dev.serial != self.undo_serial:
            _message(self, "Different phone", "That change was made on a different phone.")
            return
        snapshot = self.undo_snapshot

        def done(_):
            self.undo_snapshot = None
            self.main.status(f"Undid {self.undo_text}.")
            self.refresh()

        self._run(lambda: phone_sounds.restore(dev, snapshot), done)

    # ------------------------------------------------------------------ files

    def upload(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Upload to phone", str(DEFAULT_LIBRARY), AUDIO_FILTER
        )
        self.upload_paths(paths)

    def upload_paths(self, paths: list[str]) -> None:
        dev = self.main.device()
        if not dev or not paths or self._busy:
            return
        local = [Path(p) for p in paths]
        skipped = [p.name for p in local if p.suffix.lower() not in AUDIO_EXTENSIONS]
        local = [p for p in local if p.suffix.lower() in AUDIO_EXTENSIONS]
        if skipped:
            _message(
                self, "Not audio", "Skipping files that aren't audio:\n\n" + "\n".join(skipped)
            )
        if not local:
            return
        # Phone storage is case-insensitive, so compare names that way.
        existing = {f.name.lower() for f in self.files}
        clashes = [p.name for p in local if p.name.lower() in existing]
        if clashes:
            text = "These already exist on the phone and will be replaced:\n\n" + "\n".join(clashes)
            if not _message(self, "Replace files?", text, ask=True):
                return

        remote_dir = self.remote_dir

        def done(_):
            self.main.status(f"Uploaded {len(local)} file(s).")
            self.refresh()

        self._run(lambda: [dev.push(p, remote_dir) for p in local], done)

    def download(self) -> None:
        dev = self.main.device()
        selected = self._selected()
        if not dev or not selected:
            return
        target = QFileDialog.getExistingDirectory(self, "Download to", str(DEFAULT_LIBRARY))
        if not target:
            return
        self._run(
            lambda: [dev.pull(f.path, Path(target)) for f in selected],
            lambda _: self.main.status(f"Downloaded {len(selected)} file(s) to {target}"),
        )

    def delete(self) -> None:
        dev = self.main.device()
        selected = self._selected()
        if not dev or not selected:
            return
        names = "\n".join(f.name for f in selected)
        if not _message(self, "Delete from phone", f"Delete from the phone?\n\n{names}", ask=True):
            return
        self._run(lambda: [dev.delete(f.path) for f in selected], lambda _: self.refresh())


# --------------------------------------------------------------------------- main window


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Android Sound Manager")
        self.resize(1040, 640)
        self.devices: list[adb.Device] = []
        self.names: dict[str, str] = {}  # serial -> friendly name (in memory only, never logged)
        self._poll_error_shown = False

        self.runner = TaskRunner(self.show_error, self, name="phone")
        self.poller = TaskRunner(self._poll_failed, self, name="poll")

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(360)
        self.device_combo.currentIndexChanged.connect(lambda _: self.refresh_folders())

        top = QHBoxLayout()
        top.addWidget(QLabel("Phone:"))
        top.addWidget(self.device_combo)
        top.addStretch()

        self.tabs = QTabWidget()
        self.panels: list[FolderPanel] = []
        for name, path in adb.SOUND_FOLDERS.items():
            panel = FolderPanel(self, name, path)
            self.panels.append(panel)
            self.tabs.addTab(panel, name)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.busy_label = QLabel("Working…")
        self.busy_label.hide()
        self.statusBar().addPermanentWidget(self.busy_label)
        self.runner.busy_changed.connect(self.busy_label.setVisible)

        missing = [name for name, path in tool_status().items() if path is None]
        if missing:
            self.status("Missing tools: " + ", ".join(missing), 0)

        # Watch for phones being plugged in, unplugged, or authorized.
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_devices)
        self.poll_timer.start(DEVICE_POLL_MS)
        self._poll_devices()

    # ------------------------------------------------------------------ helpers

    def status(self, text: str, ms: int = 8000) -> None:
        self.statusBar().showMessage(text, ms)

    def show_error(self, exc: BaseException) -> None:
        _message(self, "Error", _error_text(exc), icon=QMessageBox.Icon.Warning)

    def device(self) -> adb.AdbDevice | None:
        i = self.device_combo.currentIndex() if hasattr(self, "device_combo") else -1
        if 0 <= i < len(self.devices) and self.devices[i].ready:
            return adb.AdbDevice(self.devices[i].serial)
        return None

    def refresh_folders(self) -> None:
        for panel in self.panels:
            panel.refresh()

    # ------------------------------------------------------------------ device polling

    def _poll_devices(self) -> None:
        if not self.poller.busy:
            self.poller.submit(adb.list_devices, self._on_devices)

    def _poll_failed(self, exc: BaseException) -> None:
        if not self._poll_error_shown:  # don't nag every few seconds
            self._poll_error_shown = True
            self.status(f"Can't list phones: {_error_text(exc)}", 0)

    def _label(self, d: adb.Device) -> str:
        name = self.names.get(d.serial)
        if name and d.ready:
            model = d.model.replace("_", "-")
            return f"{name} ({model})" if model else name
        return d.label

    def _on_devices(self, devices: list[adb.Device]) -> None:
        self._poll_error_shown = False
        if [(d.serial, d.state) for d in devices] == [(d.serial, d.state) for d in self.devices]:
            return
        previous = self.device()
        prev_serial = previous.serial if previous else None
        self.devices = devices

        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for d in devices:
            self.device_combo.addItem(self._label(d))
        if not devices:
            self.device_combo.addItem("No phone found - plug it in and allow USB debugging")
        serials = [d.serial for d in devices]
        ready = [d for d in devices if d.ready]
        if prev_serial in serials:
            self.device_combo.setCurrentIndex(serials.index(prev_serial))
        elif ready:
            self.device_combo.setCurrentIndex(serials.index(ready[0].serial))
        self.device_combo.blockSignals(False)

        if any(d.state == "unauthorized" for d in devices):
            self.status("Unlock the phone and tap 'Allow' on the USB debugging prompt.", 0)
        elif not devices:
            self.status("Phone disconnected.", 0)
        else:
            self.statusBar().clearMessage()

        current = self.device()
        if (current.serial if current else None) != prev_serial:
            self.refresh_folders()
        for d in ready:
            if d.serial not in self.names:
                self._fetch_name(d.serial)

    def _fetch_name(self, serial: str) -> None:
        self.names[serial] = ""  # mark as requested

        def done(name: str) -> None:
            self.names[serial] = name
            for i, d in enumerate(self.devices):
                if d.serial == serial:
                    self.device_combo.setItemText(i, self._label(d))

        self.runner.submit(lambda: adb.AdbDevice(serial).friendly_name(), done, lambda _: None)

    def closeEvent(self, event) -> None:
        self.poll_timer.stop()
        self.runner.shutdown()
        self.poller.shutdown()
        super().closeEvent(event)
