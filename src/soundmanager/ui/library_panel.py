"""Library tab: sounds on the PC. Import from YouTube or video/audio files, preview, send to phone.

Works without a phone; only "Send to phone" needs one.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QFile, QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import adb, library, youtube
from .common import DropTable, human_size, message

if TYPE_CHECKING:
    from .main_window import MainWindow

IMPORT_FILTER = (
    "Audio or video ("
    + " ".join(f"*{e}" for e in library.AUDIO_EXTENSIONS + library.VIDEO_EXTENSIONS)
    + ");;All files (*)"
)


class _Progress(QObject):
    """Carries download progress from the worker thread to the UI thread."""

    changed = Signal(float)


class LibraryPanel(QWidget):
    def __init__(self, main: MainWindow, directory: Path):
        super().__init__()
        self.main = main
        self.directory = directory
        self.items: list[library.LibraryItem] = []
        self._cancel: threading.Event | None = None
        self._busy = False
        self._player = None
        self._audio_out = None
        self._progress = _Progress(self)

        # --- YouTube row
        self.url = QLineEdit()
        self.url.setPlaceholderText(
            "Paste a YouTube link (or another video site) and press Download"
        )
        self.url.returnPressed.connect(self.download)
        self.download_button = QPushButton("Download audio")
        self.download_button.clicked.connect(self.download)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setMaximumWidth(160)
        self.bar.hide()
        self._progress.changed.connect(lambda f: self.bar.setValue(int(f * 1000)))
        self.update_button = QPushButton("Update downloader")
        self.update_button.setToolTip(
            "Get the latest yt-dlp. Try this if YouTube downloads stop working."
        )
        self.update_button.clicked.connect(self.update_downloader)
        yt_row = QHBoxLayout()
        yt_row.addWidget(self.url, 1)
        yt_row.addWidget(self.download_button)
        yt_row.addWidget(self.bar)
        yt_row.addWidget(self.cancel_button)
        yt_row.addWidget(self.update_button)

        # --- actions row
        import_button = QPushButton("Import file…")
        import_button.setToolTip("Add an audio file, or extract the audio from a video")
        import_button.clicked.connect(self.import_dialog)
        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.play)
        stop_button = QPushButton("■ Stop")
        stop_button.clicked.connect(self.stop)
        edit_button = QPushButton("Edit…")
        edit_button.setToolTip("Trim, fade, and adjust volume (saves a new copy)")
        edit_button.clicked.connect(self.edit)
        self.send_button = QPushButton("Send to phone")
        self.send_menu = QMenu(self)
        self.send_menu.aboutToShow.connect(self._build_send_menu)
        self.send_button.setMenu(self.send_menu)
        folder_button = QPushButton("Open folder")
        folder_button.clicked.connect(self.open_folder)
        trash_button = QPushButton("Move to Recycle Bin")
        trash_button.clicked.connect(self.trash)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        actions = QHBoxLayout()
        for w in (import_button, self.play_button, stop_button, edit_button, self.send_button):
            actions.addWidget(w)
        actions.addStretch()
        for w in (folder_button, trash_button, refresh_button):
            actions.addWidget(w)
        self.busy_widgets = [
            import_button,
            self.download_button,
            self.update_button,
            trash_button,
            refresh_button,
        ]

        # --- table
        self.table = DropTable(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Length", "Size", "Added"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 460)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.files_dropped.connect(self.import_paths)
        self.table.doubleClicked.connect(lambda _: self.play())

        hint = QLabel(
            f"{directory}  ·  drag audio or video files here to import  ·  "
            "only download audio you have the rights to use"
        )
        hint.setStyleSheet("color: gray;")
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(yt_row)
        layout.addLayout(actions)
        layout.addWidget(self.table)
        layout.addWidget(hint)

    # ------------------------------------------------------------------ state

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for w in self.busy_widgets:
            w.setEnabled(not busy)
        self.table.setAcceptDrops(not busy)

    def _run(self, fn, on_done=None, on_error=None) -> None:
        self._set_busy(True)

        def done(result):
            self._set_busy(False)
            if on_done:
                on_done(result)

        def failed(exc):
            self._set_busy(False)
            if on_error:
                on_error(exc)
            else:
                self.main.show_error(exc)

        self.main.media_runner.submit(fn, done, failed)

    def _selected(self) -> list[library.LibraryItem]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.items[r] for r in rows if r < len(self.items)]

    # ------------------------------------------------------------------ listing

    def refresh(self, select: Path | None = None) -> None:
        directory = self.directory
        self._run(
            lambda: library.list_library(directory), lambda items: self._populate(items, select)
        )

    def _populate(self, items, select: Path | None = None) -> None:
        self.items = items
        self.table.setRowCount(len(items))
        for row, it in enumerate(items):
            added = datetime.fromtimestamp(it.mtime).strftime("%Y-%m-%d %H:%M")
            values = (it.name, library.format_duration(it.duration), human_size(it.size), added)
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
            if select is not None and it.path == select:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0))

    # ------------------------------------------------------------------ import

    def download(self) -> None:
        if self._busy:
            return
        try:
            url = youtube.validate_url(self.url.text())
        except youtube.YoutubeError as exc:
            message(self, "Download", str(exc))
            return
        self._cancel = threading.Event()
        cancel, directory, progress = self._cancel, self.directory, self._progress
        self.bar.setValue(0)
        self.bar.show()
        self.cancel_button.show()
        self.main.status("Downloading…", 0)

        def finish():
            self.bar.hide()
            self.cancel_button.hide()
            self._cancel = None

        def done(path: Path):
            finish()
            self.url.clear()
            self.main.status(f"Added {path.name} to the library.")
            self.refresh(select=path)

        def failed(exc):
            finish()
            if isinstance(exc, youtube.Cancelled):
                self.main.status("Download cancelled.")
                return
            self.main.statusBar().clearMessage()
            if isinstance(exc, youtube.YoutubeError):
                hint = "If downloads keep failing, try “Update downloader”."
                exc = youtube.YoutubeError(f"{exc}\n\n{hint}")
            self.main.show_error(exc)

        self._run(
            lambda: youtube.download_audio(
                url, directory, progress=progress.changed.emit, cancel=cancel
            ),
            done,
            failed,
        )

    def update_downloader(self) -> None:
        if self._busy:
            return
        current = youtube.installed_version()
        question = (
            f"Update the YouTube downloader (yt-dlp {current}) to the latest version?\n\n"
            "This downloads it from the Python Package Index. The new version is used after "
            "you restart the app."
        )
        if not message(self, "Update downloader", question, ask=True):
            return
        self.main.status("Updating the downloader…", 0)

        def done(versions):
            old, new = versions
            if old == new:
                self.main.status(f"The downloader is already up to date ({new}).")
            else:
                self.main.status(f"Downloader updated {old} → {new}. Restart the app to use it.", 0)

        self._run(youtube.update_downloader, done)

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
            self.main.status("Cancelling…", 0)

    def import_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Import audio or video", "", IMPORT_FILTER)
        self.import_paths(paths)

    def import_paths(self, paths: list[str]) -> None:
        if not paths or self._busy:
            return
        allowed = library.AUDIO_EXTENSIONS + library.VIDEO_EXTENSIONS
        files = [Path(p) for p in paths]
        skipped = [p.name for p in files if p.suffix.lower() not in allowed]
        files = [p for p in files if p.suffix.lower() in allowed]
        if skipped:
            message(self, "Not audio or video", "Skipping:\n\n" + "\n".join(skipped))
        if not files:
            return
        directory = self.directory
        added: list[Path] = []

        def work():
            for p in files:
                added.append(library.import_file(p, directory))

        def done(_):
            self.main.status(f"Imported {len(added)} file(s) into the library.")
            self.refresh(select=added[-1] if added else None)

        def failed(exc):
            self.main.show_error(exc)
            if added:
                self.refresh(select=added[-1])

        self.main.status("Importing…", 0)
        self._run(work, done, failed)

    # ------------------------------------------------------------------ actions

    def _build_send_menu(self) -> None:
        self.send_menu.clear()
        selected = self._selected()
        if self.main.device() is None:
            self.send_menu.addAction("Connect your phone first").setEnabled(False)
            return
        if not selected:
            self.send_menu.addAction("Select sounds in the list first").setEnabled(False)
            return
        for name in adb.SOUND_FOLDERS:
            self.send_menu.addAction(f"To {name}", lambda n=name: self.send_to(n))

    def send_to(self, folder: str) -> None:
        selected = self._selected()
        panel = self.main.folder_panel(folder)
        if not selected or panel is None:
            return
        panel.upload_paths([str(it.path) for it in selected])
        self.main.status(f"Sending {len(selected)} file(s) to the phone's {folder} folder…")

    def edit(self) -> None:
        from .editor_dialog import EditorDialog

        selected = self._selected()
        if not selected:
            message(self, "Edit", "Select a sound in the list first.")
            return
        self.stop()
        dialog = EditorDialog(self.main, selected[0].path, self.directory, self)
        if dialog.exec() and dialog.saved_path is not None:
            self.main.status(f"Saved {dialog.saved_path.name} to the library.")
            self.refresh(select=dialog.saved_path)

    def open_folder(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory)))

    def trash(self) -> None:
        selected = self._selected()
        if not selected:
            return
        names = "\n".join(it.name for it in selected)
        if not message(
            self, "Move to Recycle Bin", f"Move to the Recycle Bin?\n\n{names}", ask=True
        ):
            return
        self.stop()
        failed = [it.name for it in selected if not QFile.moveToTrash(str(it.path))]
        if failed:
            message(self, "Couldn't move", "These couldn't be moved:\n\n" + "\n".join(failed))
        self.refresh()

    # ------------------------------------------------------------------ preview

    def play(self) -> None:
        selected = self._selected()
        if not selected:
            return
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_out)
        self._player.setSource(QUrl.fromLocalFile(str(selected[0].path)))
        self._player.play()
        self.main.status(f"Playing {selected[0].name}")

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())  # release the file so it can be moved/deleted

    def shutdown(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        self.stop()
