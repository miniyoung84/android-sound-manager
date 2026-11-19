"""Main desktop window: pick a connected phone and manage its sounds and contact ringtones."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
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
    QVBoxLayout,
    QWidget,
)

from .. import adb, library, phone_sounds
from ..journal import Journal
from ..tools import tool_status
from .common import (
    AUDIO_EXTENSIONS,
    DropTable,
    PhonePanel,
    error_text,
    escape,
    human_size,
    message,
)
from .contacts_panel import ContactsPanel
from .library_panel import LibraryPanel
from .tasks import TaskRunner

AUDIO_FILTER = "Audio files (" + " ".join(f"*{e}" for e in AUDIO_EXTENSIONS) + ");;All files (*)"
DEFAULT_LIBRARY = library.DEFAULT_LIBRARY
DEVICE_POLL_MS = 2500

# Phone folder tab -> sound type in phone_sounds.SOUND_KEYS, and its human name.
FOLDER_SOUND = {
    "Ringtones": ("ringtone", "ringtone"),
    "Notifications": ("notification", "notification sound"),
    "Alarms": ("alarm", "alarm"),
}

# Kept as module attributes so tests can stub the dialogs.
_message = message


def _slot_label(key: str, keys: list[str]) -> str:
    return "Default" if len(keys) == 1 else f"SIM {keys.index(key) + 1}"


# --------------------------------------------------------------------------- widgets


class FolderPanel(PhonePanel):
    """One phone folder (e.g. /sdcard/Ringtones) shown as a table with actions."""

    def __init__(self, main: MainWindow, folder: str, remote_dir: str):
        super().__init__(main)
        self.folder = folder
        self.remote_dir = remote_dir
        self.sound, self.sound_name = FOLDER_SOUND[folder]
        self.files: list[adb.RemoteFile] = []
        self.keys: list[str] = []
        self.defaults: dict[str, phone_sounds.DefaultSound] = {}
        self.undo_snapshot: phone_sounds.Snapshot | None = None
        self.undo_serial = ""  # undo only ever applies to the phone it was made on
        self.undo_text = ""
        self._refresh_token = 0

        self.table = DropTable(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Default", "Size", "Modified"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 420)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.files_dropped.connect(self.upload_paths)

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
            self.action_widgets.append(btn)
        buttons.addStretch()

        # Changing a default is always: open menu -> pick an entry -> confirm. Never one click.
        self.set_button = QPushButton(f"Set as {self.sound_name}")
        self.set_menu = QMenu(self)
        self.set_menu.aboutToShow.connect(self._build_set_menu)
        self.set_button.setMenu(self.set_menu)
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        buttons.addWidget(self.set_button)
        buttons.addWidget(self.undo_button)
        self.action_widgets.append(self.set_button)

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
        self.set_busy(False)

    def has_undo(self) -> bool:
        return self.undo_snapshot is not None

    def undo_widget(self):
        return self.undo_button

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        self.table.setAcceptDrops(self.main.device() is not None and not busy)

    # ------------------------------------------------------------------ refresh

    def clear(self) -> None:
        self._refresh_token += 1
        self.files, self.keys, self.defaults = [], [], {}
        self.table.setRowCount(0)
        self.current_label.clear()
        self.set_busy(False)

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

        self.run(work, done)

    def _populate(self, files, keys, defaults) -> None:
        self.files, self.keys, self.defaults = files, keys, defaults
        parts = []
        for key, d in defaults.items():
            prefix = "" if len(keys) == 1 else f"{_slot_label(key, keys)}: "
            parts.append(f"{prefix}<b>{escape(d.title)}</b>")
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
            for col, value in enumerate((f.name, marker, human_size(f.size), when)):
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

        journal = self.main.journal
        snapshot: phone_sounds.Snapshot = {}  # filled as each key succeeds

        def work():
            for key in keys:
                for k, v in phone_sounds.set_default(dev, key, target.path, journal).items():
                    snapshot.setdefault(k, v)

        def remember_undo():
            if snapshot:
                self.undo_snapshot, self.undo_serial = dict(snapshot), dev.serial
                self.undo_text = f"{self.sound_name} change"

        def done(_):
            remember_undo()
            where = ""
            if len(self.keys) > 1:
                where = " (" + ", ".join(_slot_label(k, self.keys) for k in keys) + ")"
            self.main.status(f"{self.sound_name.capitalize()}{where} set to {target.name}.")
            self.refresh()

        self.run(work, done, lambda _exc: remember_undo())

    def undo(self) -> None:
        dev = self.main.device()
        if not dev or not self.undo_snapshot:
            return
        if dev.serial != self.undo_serial:
            _message(self, "Different phone", "That change was made on a different phone.")
            return
        snapshot, journal = self.undo_snapshot, self.main.journal

        def done(_):
            self.undo_snapshot = None
            self.main.status(f"Undid {self.undo_text}.")
            self.refresh()

        self.run(lambda: phone_sounds.restore(dev, snapshot, journal), done)

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
        uploaded: list[str] = []

        def work():
            for p in local:
                dev.push(p, remote_dir)
                uploaded.append(p.name)

        def done(_):
            self.main.status(f"Uploaded {len(uploaded)} file(s).")
            self.refresh()

        def failed(_exc):
            if uploaded:
                self.main.status(f"Uploaded {len(uploaded)} of {len(local)} file(s).", 0)

        self.run(work, done, failed)

    def download(self) -> None:
        dev = self.main.device()
        selected = self._selected()
        if not dev or not selected:
            return
        target = QFileDialog.getExistingDirectory(self, "Download to", str(DEFAULT_LIBRARY))
        if not target:
            return
        self.run(
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
        self.run(lambda: [dev.delete(f.path) for f in selected], lambda _: self.refresh())


# --------------------------------------------------------------------------- main window


class MainWindow(QMainWindow):
    def __init__(self, journal: Journal | None = None, library_dir: Path | None = None):
        super().__init__()
        self.setWindowTitle("Android Sound Manager")
        self.resize(1080, 660)
        self.devices: list[adb.Device] = []
        self.names: dict[str, str] = {}  # serial -> friendly name (in memory only, never logged)
        self.journal = journal or Journal()
        self._poll_error_shown = False
        self._devices_known = False  # becomes True after the first device poll
        self._last_disconnect_notice = 0.0

        self.runner = TaskRunner(self.show_error, self, name="phone")
        self.poller = TaskRunner(self._poll_failed, self, name="poll")
        # Downloads and conversions get their own thread so they never hold up phone actions.
        self.media_runner = TaskRunner(self.show_error, self, name="media")

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(360)
        self.device_combo.currentIndexChanged.connect(lambda _: self.refresh_panels())

        top = QHBoxLayout()
        top.addWidget(QLabel("Phone:"))
        top.addWidget(self.device_combo)
        top.addStretch()

        self.tabs = QTabWidget()
        self.library_panel = LibraryPanel(self, library_dir or library.DEFAULT_LIBRARY)
        self.tabs.addTab(self.library_panel, "Library (PC)")
        self.panels: list[PhonePanel] = []
        for name, path in adb.SOUND_FOLDERS.items():
            panel = FolderPanel(self, name, path)
            self.panels.append(panel)
            self.tabs.addTab(panel, name)
        self.contacts_panel = ContactsPanel(self)
        self.panels.append(self.contacts_panel)
        self.tabs.addTab(self.contacts_panel, "Contacts")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.busy_label = QLabel("Working…")
        self.busy_label.hide()
        self.statusBar().addPermanentWidget(self.busy_label)
        for r in (self.runner, self.media_runner):
            r.busy_changed.connect(self._update_busy)

        missing = [name for name, path in tool_status().items() if path is None]
        if missing:
            self.status("Missing tools: " + ", ".join(missing), 0)
        self.library_panel.refresh()

        # Watch for phones being plugged in, unplugged, or authorized.
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_devices)
        self.poll_timer.start(DEVICE_POLL_MS)
        self._poll_devices()

    # ------------------------------------------------------------------ helpers

    @property
    def folder_panels(self) -> list[FolderPanel]:
        return [p for p in self.panels if isinstance(p, FolderPanel)]

    def folder_panel(self, folder: str) -> FolderPanel | None:
        return next((p for p in self.folder_panels if p.folder == folder), None)

    def _update_busy(self, _=None) -> None:
        self.busy_label.setVisible(self.runner.busy or self.media_runner.busy)

    def status(self, text: str, ms: int = 8000) -> None:
        self.statusBar().showMessage(text, ms)

    def show_error(self, exc: BaseException) -> None:
        if adb.is_disconnect_error(exc):
            # One calm notice instead of a stack of dialogs from every queued task.
            now = time.monotonic()
            if now - self._last_disconnect_notice > 5:
                self._last_disconnect_notice = now
                self.status(
                    "Phone disconnected. No file or setting was left half-written; anything "
                    "interrupted is cleaned up when it reconnects.",
                    0,
                )
            return
        _message(self, "Error", error_text(exc), icon=QMessageBox.Icon.Warning)

    def device(self) -> adb.AdbDevice | None:
        i = self.device_combo.currentIndex() if hasattr(self, "device_combo") else -1
        if 0 <= i < len(self.devices) and self.devices[i].ready:
            return adb.AdbDevice(self.devices[i].serial)
        return None

    def refresh_panels(self) -> None:
        for panel in self.panels:
            panel.refresh()

    # ------------------------------------------------------------------ device polling

    def _poll_devices(self) -> None:
        if not self.poller.busy:
            self.poller.submit(adb.list_devices, self._on_devices)

    def _poll_failed(self, exc: BaseException) -> None:
        if not self._poll_error_shown:  # don't nag every few seconds
            self._poll_error_shown = True
            self.status(f"Can't list phones: {error_text(exc)}", 0)

    def _label(self, d: adb.Device) -> str:
        name = self.names.get(d.serial)
        if name and d.ready:
            model = d.model.replace("_", "-")
            return f"{name} ({model})" if model else name
        return d.label

    def _on_devices(self, devices: list[adb.Device]) -> None:
        self._poll_error_shown = False
        same = [(d.serial, d.state) for d in devices] == [(d.serial, d.state) for d in self.devices]
        if same and self._devices_known:
            return
        self._devices_known = True
        newly_ready = {d.serial for d in devices if d.ready} - {
            d.serial for d in self.devices if d.ready
        }
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

        # Repair anything a previous disconnect interrupted before showing fresh data.
        for serial in newly_ready:
            self._run_maintenance(serial)
        current = self.device()
        if (current.serial if current else None) != prev_serial:
            self.refresh_panels()
        for d in ready:
            if d.serial not in self.names:
                self._fetch_name(d.serial)

    def _run_maintenance(self, serial: str) -> None:
        dev, journal = adb.AdbDevice(serial), self.journal

        def work():
            dev.cleanup_partial_uploads()
            return phone_sounds.recover_pending(dev, journal)

        def done(note):
            if note:
                self.status(note, 0)
                for panel in self.folder_panels:
                    panel.refresh()

        self.runner.submit(work, done, lambda _exc: None)

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
        self.library_panel.shutdown()  # cancels a running download
        self.runner.shutdown()
        self.poller.shutdown()
        self.media_runner.shutdown()
        super().closeEvent(event)
