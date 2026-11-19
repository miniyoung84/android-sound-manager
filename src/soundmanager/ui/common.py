"""Helpers shared by the window's tabs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMessageBox, QTableWidget, QWidget

from .. import adb
from ..audio import AudioError
from ..tools import ToolNotFoundError
from ..youtube import YoutubeError

if TYPE_CHECKING:
    from .main_window import MainWindow

AUDIO_EXTENSIONS = (".mp3", ".ogg", ".m4a", ".wav", ".opus", ".flac", ".aac")


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def escape(text: str) -> str:
    """Escape text for a rich-text QLabel (names come from the phone)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def message(parent, title: str, text: str, ask: bool = False, icon=None) -> bool:
    """Message box that always renders *text* as plain text (it may contain phone data).

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


def error_text(exc: BaseException) -> str:
    if isinstance(exc, (adb.AdbError, AudioError, YoutubeError, ToolNotFoundError, OSError)):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def summarize(lines: list[str], limit: int = 12) -> str:
    shown = lines[:limit]
    if len(lines) > limit:
        shown.append(f"… and {len(lines) - limit} more")
    return "\n".join(shown)


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


class PhonePanel(QWidget):
    """Base for tabs that act on the selected phone in the background.

    While a task runs, the panel's action widgets are disabled so the same action can't be
    queued twice, and results are delivered back on the UI thread.
    """

    def __init__(self, main: MainWindow):
        super().__init__()
        self.main = main
        self.action_widgets: list[QWidget] = []
        self._busy = False

    def has_undo(self) -> bool:
        return False

    def undo_widget(self) -> QWidget | None:
        return None

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        enabled = self.main.device() is not None and not busy
        for w in self.action_widgets:
            w.setEnabled(enabled)
        if (undo := self.undo_widget()) is not None:
            undo.setEnabled(enabled and self.has_undo())

    def run(
        self,
        fn: Callable[[], Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        """Run *fn* in the background with this panel's actions disabled meanwhile."""
        self.set_busy(True)

        def done(result):
            self.set_busy(False)
            if on_done:
                on_done(result)

        def failed(exc):
            self.set_busy(False)
            self.main.show_error(exc)
            if on_error:  # runs last so its more specific status message wins
                on_error(exc)

        self.main.runner.submit(fn, done, failed)

    def refresh(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError
