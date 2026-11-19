"""Run blocking work (adb, ffmpeg) off the UI thread and deliver results back on it."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

OnDone = Callable[[Any], None]
OnError = Callable[[BaseException], None]


class TaskRunner(QObject):
    """Runs submitted callables one at a time on a background thread.

    Callbacks always run on the UI thread (the signal is queued across threads), so they may
    touch widgets. Running one job at a time keeps phone operations in a predictable order.
    """

    busy_changed = Signal(bool)
    _finished = Signal(object, object, object)  # (on_done, on_error), result, error

    def __init__(self, on_error: OnError, parent: QObject | None = None, name: str = "worker"):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self._default_on_error = on_error
        self._pending = 0
        self._closed = False
        self._finished.connect(self._deliver)

    @property
    def busy(self) -> bool:
        return self._pending > 0

    def submit(
        self, fn: Callable[[], Any], on_done: OnDone | None = None, on_error: OnError | None = None
    ) -> None:
        if self._closed:
            return
        self._pending += 1
        if self._pending == 1:
            self.busy_changed.emit(True)
        future = self._pool.submit(fn)
        future.add_done_callback(lambda f: self._emit((on_done, on_error), f))

    def _emit(self, callbacks: tuple, future: Future) -> None:
        if self._closed or future.cancelled():
            return
        error = future.exception()
        with contextlib.suppress(RuntimeError):  # window already destroyed during shutdown
            self._finished.emit(callbacks, None if error else future.result(), error)

    def _deliver(self, callbacks: tuple, result: Any, error: BaseException | None) -> None:
        self._pending -= 1
        if self._pending == 0:
            self.busy_changed.emit(False)
        on_done, on_error = callbacks
        if error is not None:
            log.warning("Background task failed: %s", error)
            (on_error or self._default_on_error)(error)
        elif on_done is not None:
            on_done(result)

    def shutdown(self) -> None:
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
