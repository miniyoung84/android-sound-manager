"""Waveform display with a draggable selection (start/end) and a playhead."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

HANDLE_GRAB_PX = 7
ACCENT = QColor("#3b9cff")  # readable on both light and dark backgrounds
MIN_SELECTION_S = 0.1


class WaveformView(QWidget):
    """Shows `peaks` (0..1) across `duration` seconds.

    Drag to select a region, drag a selection edge to adjust it, or Shift+drag inside the
    selection to slide it (keeping its length). `selection_changed` fires while dragging;
    `edit_finished` fires once on release (used for undo history).
    """

    selection_changed = Signal(float, float)
    edit_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peaks: list[float] = []
        self.duration = 0.0
        self.start = 0.0
        self.end = 0.0
        self.playhead: float | None = None
        self._drag: str | None = None  # "start", "end", "move", "new"
        self._anchor = 0.0
        self._move_offset = 0.0
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------ data

    def set_peaks(self, peaks: list[float], duration: float) -> None:
        self.peaks, self.duration = peaks, max(0.0, duration)
        self.set_selection(0.0, self.duration)

    def set_selection(self, start: float, end: float, emit: bool = False) -> None:
        start = min(max(0.0, start), self.duration)
        end = min(max(0.0, end), self.duration)
        if end < start:
            start, end = end, start
        self.start, self.end = start, end
        self.update()
        if emit:
            self.selection_changed.emit(self.start, self.end)

    def set_playhead(self, seconds: float | None) -> None:
        self.playhead = seconds
        self.update()

    # ------------------------------------------------------------------ geometry

    def _x(self, seconds: float) -> float:
        return 0.0 if self.duration <= 0 else seconds / self.duration * self.width()

    def _t(self, x: float) -> float:
        if self.width() <= 0:
            return 0.0
        return min(max(0.0, x / self.width() * self.duration), self.duration)

    # ------------------------------------------------------------------ painting

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        pal = self.palette()
        w, h = self.width(), self.height()
        mid = h / 2
        p.fillRect(self.rect(), pal.color(QPalette.ColorRole.Base))

        x0, x1 = self._x(self.start), self._x(self.end)
        if self.duration > 0 and self.end > self.start:
            band = QColor(ACCENT)
            band.setAlpha(40)
            p.fillRect(QRectF(x0, 0, x1 - x0, h), band)

        if self.peaks:
            # Selected audio in the accent colour; the rest dimmed, in light and dark themes.
            outside = QColor(pal.color(QPalette.ColorRole.Text))
            outside.setAlpha(70)
            inside_pen, outside_pen = QPen(ACCENT, 1), QPen(outside, 1)
            n = len(self.peaks)
            # Scale to the loudest point so quiet recordings are still easy to see.
            scale = 1.0 / max(max(self.peaks), 0.05)
            for x in range(w):
                i0 = int(x / w * n)
                i1 = max(i0 + 1, int((x + 1) / w * n))
                peak = max(self.peaks[i0:i1]) * scale
                half = max(0.5, peak * (mid - 6))
                p.setPen(inside_pen if x0 <= x + 0.5 <= x1 else outside_pen)
                p.drawLine(QPointF(x + 0.5, mid - half), QPointF(x + 0.5, mid + half))
        else:
            p.setPen(pal.color(QPalette.ColorRole.PlaceholderText))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Loading waveform…")

        if self.duration > 0:
            p.setPen(QPen(ACCENT, 2))
            p.setBrush(ACCENT)
            for x in (x0, x1):
                p.drawLine(QPointF(x, 0), QPointF(x, h))
                p.drawRect(QRectF(x - 4, 0, 8, 10))  # grab tabs make the edges easy to find
        if self.playhead is not None and self.duration > 0:
            p.setPen(QPen(QColor("#e8590c"), 2))
            x = self._x(self.playhead)
            p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.end()

    # ------------------------------------------------------------------ mouse

    def _hit(self, x: float, shift: bool) -> str | None:
        if abs(x - self._x(self.start)) <= HANDLE_GRAB_PX:
            return "start"
        if abs(x - self._x(self.end)) <= HANDLE_GRAB_PX:
            return "end"
        if shift and self._x(self.start) < x < self._x(self.end):
            return "move"  # Shift+drag slides the selection, keeping its length
        return None

    def mousePressEvent(self, event) -> None:
        if self.duration <= 0 or event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._drag = self._hit(x, shift) or "new"
        t = self._t(x)
        if self._drag == "new":
            self._anchor = t
            self.set_selection(t, t, emit=True)
        elif self._drag == "move":
            self._move_offset = t - self.start

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        if self._drag is None:
            hit = self._hit(x, bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            cursor = {
                "start": Qt.CursorShape.SizeHorCursor,
                "end": Qt.CursorShape.SizeHorCursor,
                "move": Qt.CursorShape.OpenHandCursor,
            }.get(hit, Qt.CursorShape.IBeamCursor)
            self.setCursor(cursor)
            return
        t = self._t(x)
        if self._drag == "start":
            self.set_selection(min(t, self.end - MIN_SELECTION_S), self.end, emit=True)
        elif self._drag == "end":
            self.set_selection(self.start, max(t, self.start + MIN_SELECTION_S), emit=True)
        elif self._drag == "move":
            length = self.end - self.start
            new_start = min(max(0.0, t - self._move_offset), self.duration - length)
            self.set_selection(new_start, new_start + length, emit=True)
        else:
            self.set_selection(self._anchor, t, emit=True)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is None:
            return
        if self._drag == "new" and self.end - self.start < MIN_SELECTION_S:
            # A plain click: keep a minimal selection starting there.
            self.set_selection(self.start, self.start + MIN_SELECTION_S, emit=True)
        self._drag = None
        self.edit_finished.emit()
