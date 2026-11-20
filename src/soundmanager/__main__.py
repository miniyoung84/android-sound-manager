"""Entry point: `python -m soundmanager`, the `soundmanager` command, or the desktop shortcut."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

# Must match the AppUserModelID written into the shortcuts (scripts/install_shortcuts.ps1) so
# Windows groups the window under our icon and taskbar pinning relaunches the app correctly.
APP_ID = "ChaseChoi.AndroidSoundManager"
ASSETS = Path(__file__).resolve().parent / "assets"
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AndroidSoundManager"

log = logging.getLogger("soundmanager")


def _setup_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "app.log"
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return log_file


def _set_windows_app_id() -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def main() -> int:
    log_file = _setup_logging()
    _set_windows_app_id()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Sound Manager by The Bakery")
    icon_path = ASSETS / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # With no console (pythonw / shortcut), unhandled errors would vanish. Log and show them.
    def excepthook(exc_type, exc, tb):
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Unhandled exception:\n%s", details)
        QMessageBox.critical(
            None, "Unexpected error", f"{exc}\n\nDetails were saved to:\n{log_file}"
        )

    sys.excepthook = excepthook

    log.info("Starting Android Sound Manager")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
