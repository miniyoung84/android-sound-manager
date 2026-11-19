"""Write-ahead journal for multi-step changes on the phone.

Before a change that touches several settings, the old and new values are saved here. If the
phone disconnects midway, the entry survives (even an app restart), and when that phone comes
back the change is either confirmed complete or rolled back - never left half-applied.

Stored locally in %LOCALAPPDATA%\\AndroidSoundManager\\journal (never in the repo).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def default_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "AndroidSoundManager" / "journal"


class Journal:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or default_dir()

    def _path(self, serial: str) -> Path:
        # Hash the serial so the file name doesn't reveal it.
        digest = hashlib.sha256(serial.encode()).hexdigest()[:16]
        return self.directory / f"{digest}.json"

    def save(self, serial: str, entry: dict[str, Any]) -> None:
        """Atomically write the pending entry for *serial* (write temp file, then rename)."""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(serial)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, serial: str) -> dict[str, Any] | None:
        path = self._path(serial)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            path.unlink(missing_ok=True)  # unreadable entry: nothing safe to do with it
            return None

    def clear(self, serial: str) -> None:
        self._path(serial).unlink(missing_ok=True)
