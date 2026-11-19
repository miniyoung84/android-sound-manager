"""Contacts tab: see and change per-contact ringtones.

Contact names are shown on screen only. They are never logged or written anywhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import adb, phone_contacts
from .common import PhonePanel, message, summarize

if TYPE_CHECKING:
    from .main_window import MainWindow

RINGTONE_FOLDER = adb.SOUND_FOLDERS["Ringtones"]
DEFAULT_LABEL = "Phone's default ringtone"


class ContactsPanel(PhonePanel):
    def __init__(self, main: MainWindow):
        super().__init__(main)
        self.contacts: list[phone_contacts.Contact] = []
        self.labels: dict[str, str] = {}  # ringtone URI -> file name / title
        self.sounds: list[adb.RemoteFile] = []
        self.undo_changes: list[tuple[int, str | None]] = []  # (contact id, old ringtone)
        self.undo_serial = ""
        self._refresh_token = 0

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search contacts")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.only_phone = QCheckBox("Only contacts with a phone number")
        self.only_phone.setChecked(True)
        self.only_phone.toggled.connect(self._apply_filter)
        self.only_custom = QCheckBox("Only contacts with a custom ringtone")
        self.only_custom.toggled.connect(self._apply_filter)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.only_phone)
        top.addWidget(self.only_custom)
        top.addWidget(refresh)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Contact", "Ringtone"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 380)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()

        self.sound_combo = QComboBox()
        self.sound_combo.setMinimumWidth(320)
        self.apply_button = QPushButton("Apply to selected contacts…")
        self.apply_button.clicked.connect(self.apply)
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Ringtone:"))
        bottom.addWidget(self.sound_combo)
        bottom.addWidget(self.apply_button)
        bottom.addStretch()
        bottom.addWidget(self.undo_button)

        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: gray;")
        hint = QLabel(
            "Sounds come from the phone's Ringtones folder. Upload one there first to use it."
        )
        hint.setStyleSheet("color: gray;")

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table)
        layout.addWidget(self.count_label)
        layout.addLayout(bottom)
        layout.addWidget(hint)

        self.action_widgets = [refresh, self.apply_button, self.sound_combo]
        self.set_busy(False)

    def has_undo(self) -> bool:
        return bool(self.undo_changes)

    def undo_widget(self):
        return self.undo_button

    # ------------------------------------------------------------------ loading

    def clear(self) -> None:
        self._refresh_token += 1
        self.contacts, self.labels, self.sounds = [], {}, []
        self.table.setRowCount(0)
        self.sound_combo.clear()
        self.count_label.clear()
        self.set_busy(False)

    def refresh(self) -> None:
        dev = self.main.device()
        if not dev:
            self.clear()
            return
        self._refresh_token += 1
        token = self._refresh_token

        def work():
            contacts = phone_contacts.list_contacts(dev)
            sounds = dev.list_dir(RINGTONE_FOLDER)
            uris = {c.ringtone for c in contacts if c.ringtone}
            labels = phone_contacts.describe_ringtones(dev, uris) if uris else {}
            return contacts, sounds, labels

        def done(result):
            if token == self._refresh_token:
                self._populate(*result)

        self.run(work, done)

    def _populate(self, contacts, sounds, labels) -> None:
        self.contacts, self.sounds, self.labels = contacts, sounds, labels
        selected_ids = {c.id for c in self._selected()}

        current_sound = self.sound_combo.currentData()
        self.sound_combo.clear()
        self.sound_combo.addItem(DEFAULT_LABEL, None)
        for f in sounds:
            self.sound_combo.addItem(f.name, f.path)
        if current_sound is not None and (i := self.sound_combo.findData(current_sound)) >= 0:
            self.sound_combo.setCurrentIndex(i)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(contacts))
        for row, c in enumerate(contacts):
            name_item = QTableWidgetItem(c.name)
            name_item.setData(Qt.ItemDataRole.UserRole, c.id)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(self._ringtone_label(c)))
            if c.id in selected_ids:
                self.table.selectRow(row)
        self._apply_filter()

    def _ringtone_label(self, c: phone_contacts.Contact) -> str:
        if not c.ringtone:
            return ""
        return "♪ " + self.labels.get(c.ringtone, "(custom)")

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().casefold()
        shown = 0
        for row, c in enumerate(self.contacts):
            hidden = (
                (needle and needle not in c.name.casefold())
                or (self.only_phone.isChecked() and not c.has_phone)
                or (self.only_custom.isChecked() and not c.ringtone)
            )
            self.table.setRowHidden(row, bool(hidden))
            shown += not hidden
        custom = sum(1 for c in self.contacts if c.ringtone)
        self.count_label.setText(
            f"Showing {shown} of {len(self.contacts)} contacts · {custom} with a custom ringtone"
            if self.contacts
            else ""
        )

    # ------------------------------------------------------------------ changes

    def _selected(self) -> list[phone_contacts.Contact]:
        by_id = {c.id: c for c in self.contacts}
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        ids = [
            self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            for r in rows
            if not self.table.isRowHidden(r) and self.table.item(r, 0)
        ]
        return [by_id[i] for i in ids if i in by_id]

    def apply(self) -> None:
        dev = self.main.device()
        selected = self._selected()
        if not dev:
            return
        if not selected:
            message(self, "Pick contacts", "Select one or more contacts in the list first.")
            return
        path = self.sound_combo.currentData()
        new_label = self.sound_combo.currentText()
        lines = [
            f"{c.name}:  {self._ringtone_label(c) or DEFAULT_LABEL}  →  {new_label}"
            for c in selected
        ]
        noun = "contact" if len(selected) == 1 else f"{len(selected)} contacts"
        question = f"Change the ringtone for {noun}?\n\n{summarize(lines)}\n\nYou can undo this."
        if not message(self, "Change contact ringtone", question, ask=True):
            return

        progress: list[tuple[int, str | None]] = []  # survives a mid-batch disconnect

        def work():
            for c in selected:
                old = phone_contacts.set_contact_ringtone(dev, c.id, path)
                progress.append((c.id, old))

        def remember_undo():
            if progress:
                self.undo_changes, self.undo_serial = list(progress), dev.serial

        def done(_):
            remember_undo()
            self.main.status(f"Ringtone set for {len(progress)} {noun.split()[-1]}.")
            self.refresh()

        def failed(_exc):
            remember_undo()
            if progress:
                self.main.status(
                    f"Only {len(progress)} of {len(selected)} contacts were changed before the "
                    "error. Undo will revert those.",
                    0,
                )

        self.run(work, done, failed)

    def undo(self) -> None:
        dev = self.main.device()
        if not dev or not self.undo_changes:
            return
        if dev.serial != self.undo_serial:
            message(self, "Different phone", "That change was made on a different phone.")
            return
        remaining = list(self.undo_changes)

        def work():
            while remaining:  # pop as we go so a disconnect leaves an accurate remainder
                contact_id, old = remaining[-1]
                phone_contacts.restore_contact_ringtone(dev, contact_id, old)
                remaining.pop()

        def done(_):
            self.undo_changes = []
            self.main.status("Contact ringtone change undone.")
            self.refresh()

        def failed(_exc):
            self.undo_changes = list(remaining)

        self.run(work, done, failed)
