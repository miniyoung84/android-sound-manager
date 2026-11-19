"""Sound editor: pick a region on the waveform, add fades / volume / normalize, save a copy.

The original file is never modified. Edits are saved as a new file in the library.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import audio
from ..adb import safe_local_name, unique_path
from .waveform import WaveformView

if TYPE_CHECKING:
    from .main_window import MainWindow

OUTPUT_FORMATS = (".m4a", ".mp3", ".ogg")
TIP = (
    "Drag on the waveform to select, drag the edges to adjust, Shift+drag to slide the "
    "selection. Space plays the preview. Ringtones usually work best at 20–40 s (they "
    "loop), notification sounds at 1–3 s, alarms at 30–60 s."
)


@dataclass(frozen=True)
class EditState:
    start: float = 0.0
    end: float = 0.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    gain_db: float = 0.0
    normalize: bool = False

    def spec(self) -> audio.EditSpec:
        return audio.EditSpec(**asdict(self))


class History:
    """Simple undo/redo stack of EditStates."""

    def __init__(self, initial: EditState):
        self.states = [initial]
        self.index = 0

    @property
    def current(self) -> EditState:
        return self.states[self.index]

    def push(self, state: EditState) -> None:
        if state == self.current:
            return
        del self.states[self.index + 1 :]
        self.states.append(state)
        self.index += 1

    def can_undo(self) -> bool:
        return self.index > 0

    def can_redo(self) -> bool:
        return self.index < len(self.states) - 1

    def undo(self) -> EditState:
        if self.can_undo():
            self.index -= 1
        return self.current

    def redo(self) -> EditState:
        if self.can_redo():
            self.index += 1
        return self.current


def _seconds_box(maximum: float, step: float = 0.1, decimals: int = 2) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0.0, max(0.0, maximum))
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setSuffix(" s")
    box.setKeyboardTracking(False)
    return box


class EditorDialog(QDialog):
    def __init__(self, main: MainWindow, source: Path, library_dir: Path, parent=None):
        super().__init__(parent)
        self.main = main
        self.source = source
        self.library_dir = library_dir
        self.duration = 0.0
        self.saved_path: Path | None = None
        self.history = History(EditState())
        self._loading = True
        self._preview_dir = Path(tempfile.mkdtemp(prefix="asm-preview-"))
        self._preview_offset = 0.0
        self._player = None
        self._audio_out = None

        self.setWindowTitle(f"Edit – {source.name}")
        self.resize(980, 520)

        self.wave = WaveformView()
        self.wave.selection_changed.connect(self._wave_moved)
        self.wave.edit_finished.connect(self._commit)

        # --- region
        self.start_box = _seconds_box(0)
        self.end_box = _seconds_box(0)
        self.length_label = QLabel()
        for box in (self.start_box, self.end_box):
            box.valueChanged.connect(self._boxes_changed)
        self.preview_button = QPushButton("▶ Preview edit")
        self.preview_button.clicked.connect(self.preview)
        self.stop_button = QPushButton("■ Stop")
        self.stop_button.clicked.connect(self.stop)
        region = QHBoxLayout()
        region.addWidget(QLabel("Start"))
        region.addWidget(self.start_box)
        region.addWidget(QLabel("End"))
        region.addWidget(self.end_box)
        region.addWidget(self.length_label)
        region.addStretch()
        region.addWidget(self.preview_button)
        region.addWidget(self.stop_button)

        # --- effects
        self.fade_in_box = _seconds_box(10)
        self.fade_out_box = _seconds_box(10)
        self.gain_box = QDoubleSpinBox()
        self.gain_box.setRange(-20.0, 20.0)
        self.gain_box.setSingleStep(0.5)
        self.gain_box.setSuffix(" dB")
        self.gain_box.setKeyboardTracking(False)
        self.normalize_box = QCheckBox("Normalize loudness (even volume, like streaming apps)")
        for box in (self.fade_in_box, self.fade_out_box, self.gain_box):
            box.valueChanged.connect(self._commit)
        self.normalize_box.toggled.connect(self._commit)
        effects = QFormLayout()
        fades = QHBoxLayout()
        fades.addWidget(QLabel("Fade in"))
        fades.addWidget(self.fade_in_box)
        fades.addWidget(QLabel("Fade out"))
        fades.addWidget(self.fade_out_box)
        fades.addWidget(QLabel("Volume"))
        fades.addWidget(self.gain_box)
        fades.addStretch()
        effects.addRow(fades)
        effects.addRow(self.normalize_box)

        # --- save row
        self.name_edit = QLineEdit(f"{source.stem} (edit)")
        self.format_combo = QComboBox()
        for ext in OUTPUT_FORMATS:
            self.format_combo.addItem(ext, ext)
        if (i := self.format_combo.findData(source.suffix.lower())) >= 0:
            self.format_combo.setCurrentIndex(i)
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("Redo")
        self.redo_button.clicked.connect(self.redo)
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("Save to library")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        save_row = QHBoxLayout()
        save_row.addWidget(QLabel("Save as"))
        save_row.addWidget(self.name_edit, 1)
        save_row.addWidget(self.format_combo)
        save_row.addSpacing(16)
        save_row.addWidget(self.undo_button)
        save_row.addWidget(self.redo_button)
        save_row.addSpacing(16)
        save_row.addWidget(cancel)
        save_row.addWidget(self.save_button)

        tip = QLabel(TIP + "  The original file is never changed.")
        tip.setStyleSheet("color: gray;")
        tip.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.wave, 1)
        layout.addLayout(region)
        layout.addLayout(effects)
        layout.addLayout(save_row)
        layout.addWidget(tip)

        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_preview)

        self._set_enabled(False)
        self._load()

    # ------------------------------------------------------------------ loading

    def _set_enabled(self, enabled: bool) -> None:
        for w in (
            self.start_box,
            self.end_box,
            self.fade_in_box,
            self.fade_out_box,
            self.gain_box,
            self.normalize_box,
            self.preview_button,
            self.save_button,
        ):
            w.setEnabled(enabled)
        self._update_undo_buttons()

    def _load(self) -> None:
        src = self.source

        def done(result):
            peaks, duration = result
            self.duration = duration
            self.wave.set_peaks(peaks, duration)
            for box in (self.start_box, self.end_box):
                box.blockSignals(True)
                box.setMaximum(duration)
                box.blockSignals(False)
            # Default selection: whole file, capped at 30 s (a typical ringtone length).
            state = EditState(start=0.0, end=min(duration, 30.0))
            self.history = History(state)
            self._loading = False
            self._show(state)
            self._set_enabled(True)

        def failed(exc):
            self.main.show_error(exc)
            self.reject()

        self.main.media_runner.submit(lambda: audio.waveform_peaks(src), done, failed)

    # ------------------------------------------------------------------ state <-> widgets

    def _read(self) -> EditState:
        return EditState(
            start=self.start_box.value(),
            end=self.end_box.value(),
            fade_in=self.fade_in_box.value(),
            fade_out=self.fade_out_box.value(),
            gain_db=self.gain_box.value(),
            normalize=self.normalize_box.isChecked(),
        )

    def _show(self, s: EditState) -> None:
        widgets = (
            self.start_box,
            self.end_box,
            self.fade_in_box,
            self.fade_out_box,
            self.gain_box,
            self.normalize_box,
        )
        for w in widgets:
            w.blockSignals(True)
        self.start_box.setValue(s.start)
        self.end_box.setValue(s.end)
        self.fade_in_box.setValue(s.fade_in)
        self.fade_out_box.setValue(s.fade_out)
        self.gain_box.setValue(s.gain_db)
        self.normalize_box.setChecked(s.normalize)
        for w in widgets:
            w.blockSignals(False)
        self.wave.set_selection(s.start, s.end)
        self.length_label.setText(f"Length {max(0.0, s.end - s.start):.2f} s")
        self._update_undo_buttons()

    def _update_undo_buttons(self) -> None:
        self.undo_button.setEnabled(not self._loading and self.history.can_undo())
        self.redo_button.setEnabled(not self._loading and self.history.can_redo())

    def _wave_moved(self, start: float, end: float) -> None:
        for box, value in ((self.start_box, start), (self.end_box, end)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        self.length_label.setText(f"Length {end - start:.2f} s")

    def _boxes_changed(self) -> None:
        start, end = self.start_box.value(), self.end_box.value()
        if end - start < 0.1:  # keep a valid region whichever box was edited
            end = min(self.duration, start + 0.1)
            start = max(0.0, end - 0.1)
        self._show(replace(self._read(), start=start, end=end))
        self._commit()

    def _commit(self, *_args) -> None:
        if self._loading:
            return
        self.history.push(self._read())
        self.length_label.setText(f"Length {self.end_box.value() - self.start_box.value():.2f} s")
        self._update_undo_buttons()

    def undo(self) -> None:
        if not self._loading:
            self._show(self.history.undo())

    def redo(self) -> None:
        if not self._loading:
            self._show(self.history.redo())

    # ------------------------------------------------------------------ preview

    def toggle_preview(self) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        playing = self._player is not None and (
            self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        if playing:
            self.stop()
        else:
            self.preview()

    def preview(self) -> None:
        """Render the edit (with fades/volume) to a temp file and play it."""
        if self._loading:
            return
        state, src = self._read(), self.source
        out = self._preview_dir / f"preview-{len(self.history.states)}.wav"
        self.preview_button.setEnabled(False)

        def done(path: Path):
            self.preview_button.setEnabled(True)
            self._play(path, offset=state.start)

        def failed(exc):
            self.preview_button.setEnabled(True)
            self.main.show_error(exc)

        self.main.media_runner.submit(lambda: audio.export(src, out, state.spec()), done, failed)

    def _play(self, path: Path, offset: float) -> None:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_out)
            self._player.positionChanged.connect(
                lambda ms: self.wave.set_playhead(self._preview_offset + ms / 1000)
            )
            self._player.playbackStateChanged.connect(
                lambda st: (
                    self.wave.set_playhead(None)
                    if st == QMediaPlayer.PlaybackState.StoppedState
                    else None
                )
            )
        self._preview_offset = offset
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())
        self.wave.set_playhead(None)

    # ------------------------------------------------------------------ save

    def output_path(self) -> Path:
        name = safe_local_name(self.name_edit.text().strip()) or safe_local_name(self.source.stem)
        return unique_path(self.library_dir / f"{name}{self.format_combo.currentData()}")

    def save(self) -> None:
        if self._loading:
            return
        state, src = self._read(), self.source
        dest = self.output_path()
        self._set_enabled(False)

        def work() -> Path:
            # Render into a temp folder first; only a finished file is moved into the library.
            with tempfile.TemporaryDirectory(prefix="asm-edit-") as tmp:
                rendered = audio.export(src, Path(tmp) / f"out{dest.suffix}", state.spec())
                self.library_dir.mkdir(parents=True, exist_ok=True)
                final = unique_path(dest)
                shutil.move(str(rendered), final)
                return final

        def done(path: Path):
            self.saved_path = path
            self.accept()

        def failed(exc):
            self._set_enabled(True)
            self.main.show_error(exc)

        self.main.media_runner.submit(work, done, failed)

    def done(self, result: int) -> None:  # called by accept()/reject()
        self.stop()
        shutil.rmtree(self._preview_dir, ignore_errors=True)
        super().done(result)
