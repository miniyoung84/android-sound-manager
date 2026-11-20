"""App sounds tab: every app's notification categories and the sound each one plays.

Android only lets a category's sound be changed on the phone itself, so this tab shows what
each category currently plays and opens that exact category's settings screen on the phone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .. import phone_apps, phone_settings
from .common import PhonePanel

if TYPE_CHECKING:
    from .main_window import MainWindow

ROLE = Qt.ItemDataRole.UserRole


def channel_note(app: phone_apps.App, c: phone_apps.Channel) -> str:
    notes = []
    if app.blocked or c.importance == 0:
        notes.append("Notifications off")
    elif c.silent and c.sound is not None:
        notes.append("Silent category")
    if c.conversation:
        notes.append("Conversation")
    if c.group:
        notes.append(c.group)
    return " · ".join(notes)


class AppSoundsPanel(PhonePanel):
    def __init__(self, main: MainWindow):
        super().__init__(main)
        self.apps: list[phone_apps.App] = []
        self.labels: dict[str, str] = {}
        self._stale = True
        self._token = 0

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search apps or categories")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.only_sound = QCheckBox("Only categories that make a sound")
        self.only_sound.toggled.connect(self._apply_filter)
        self.all_apps = QCheckBox("Include background system apps")
        self.all_apps.toggled.connect(self.reload)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.only_sound)
        top.addWidget(self.all_apps)
        top.addWidget(refresh)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["App / category", "Sound", "Notes"])
        self.tree.setColumnWidth(0, 380)
        self.tree.setColumnWidth(1, 260)
        self.tree.setUniformRowHeights(True)
        # Double-click opens a category; on an app row it just expands/collapses as usual.
        self.tree.itemDoubleClicked.connect(
            lambda item, _col: item.parent() is not None and self.open_selected()
        )
        self.tree.itemSelectionChanged.connect(self._update_open_button)

        self.open_button = QPushButton("Change sound on phone…")
        self.open_button.setToolTip("Opens this category's settings on the phone")
        self.open_button.clicked.connect(self.open_selected)
        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: gray;")

        bottom = QHBoxLayout()
        bottom.addWidget(self.count_label, 1)
        bottom.addWidget(self.open_button)

        hint = QLabel(
            "Android only lets each app's categories be changed on the phone. Pick one, press "
            "“Change sound on phone…”, unlock the phone, tap Sound, and choose your sound. "
            "Put it in the Notifications folder first so it shows up there."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree)
        layout.addLayout(bottom)
        layout.addWidget(hint)

        self.action_widgets = [refresh, self.all_apps]
        self.set_busy(False)

    # ------------------------------------------------------------------ loading

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        self._update_open_button()

    def clear(self) -> None:
        self._token += 1
        self.apps, self.labels = [], {}
        self.tree.clear()
        self.count_label.clear()
        self.set_busy(False)

    def refresh(self) -> None:
        """Called when the phone changes. The dump is large, so load only when this tab shows."""
        self.clear()
        self._stale = True
        if self.isVisible():
            self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self.reload()

    def reload(self) -> None:
        dev = self.main.device()
        if not dev:
            self.clear()
            return
        self._stale = False
        self._token += 1
        token = self._token
        launcher_only = not self.all_apps.isChecked()
        self.count_label.setText("Reading notification categories from the phone…")

        def work():
            apps = phone_apps.list_apps(dev, launcher_only=launcher_only)
            return apps, phone_apps.describe_sounds(dev, apps)

        def done(result):
            if token == self._token:
                self._populate(*result)

        self.run(work, done)

    def _populate(self, apps, labels) -> None:
        self.apps, self.labels = apps, labels
        dim = QBrush(self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
        self.tree.clear()
        for app in apps:
            top = QTreeWidgetItem([app.name, "", "Notifications off" if app.blocked else ""])
            top.setToolTip(0, app.package)
            top.setData(0, ROLE, (app.package, None))
            for c in app.channels:
                sound = "Silent" if c.sound is None else labels.get(c.sound, "Custom sound")
                child = QTreeWidgetItem([c.name, sound, channel_note(app, c)])
                child.setData(0, ROLE, (app.package, c.id))
                child.setData(1, ROLE, c.silent or app.blocked)
                if c.silent or app.blocked:
                    for col in range(3):
                        child.setForeground(col, dim)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().casefold()
        only_sound = self.only_sound.isChecked()
        apps_shown = channels_shown = 0
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            app_match = (
                not needle
                or needle in top.text(0).casefold()
                or needle in (top.toolTip(0).casefold())
            )
            visible_children = 0
            for j in range(top.childCount()):
                child = top.child(j)
                hidden = (only_sound and child.data(1, ROLE)) or (
                    not app_match and needle not in child.text(0).casefold()
                )
                child.setHidden(bool(hidden))
                visible_children += not hidden
            top.setHidden(visible_children == 0)
            top.setExpanded(bool(needle) and visible_children > 0)
            apps_shown += visible_children > 0
            channels_shown += visible_children
        self.count_label.setText(
            f"{apps_shown} apps · {channels_shown} notification categories" if self.apps else ""
        )
        self._update_open_button()

    # ------------------------------------------------------------------ actions

    def _selected(self) -> tuple[str, str | None] | None:
        items = self.tree.selectedItems()
        return items[0].data(0, ROLE) if items else None

    def _update_open_button(self) -> None:
        if hasattr(self, "open_button"):
            ready = self.main.device() is not None and not self._busy
            self.open_button.setEnabled(ready and self._selected() is not None)
            selected = self._selected()
            self.open_button.setText(
                "Open app's notification settings on phone…"
                if selected and selected[1] is None
                else "Change sound on phone…"
            )

    def open_selected(self) -> None:
        dev = self.main.device()
        selected = self._selected()
        if dev is None or selected is None:
            return
        package, channel_id = selected
        item = self.tree.selectedItems()[0]
        what = item.text(0) if channel_id is None else f"{item.parent().text(0)} › {item.text(0)}"

        def work():
            if channel_id is None:
                phone_settings.open_app_notification_settings(dev, package)
            else:
                phone_apps.open_channel_settings(dev, package, channel_id)

        def done(_):
            self.main.status(f"Opened {what} on the phone. Unlock it, tap Sound, and pick one.")

        self.run(work, done)
