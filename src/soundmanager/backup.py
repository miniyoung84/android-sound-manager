"""Back up the phone's custom sounds and sound settings to one .zip on the PC, and restore it.

A backup holds:
  * every file in the phone's Ringtones, Notifications and Alarms folders;
  * which of them is the default ringtone (per SIM), notification sound and alarm;
  * which contacts have their own ringtone. Contacts are matched by name on restore, so the
    file contains those contacts' names (never phone numbers). It stays on the PC, wherever
    the user saves it, and is never logged.

Restoring treats the file as untrusted: names, folders, sizes and setting keys are all checked,
files are only ever written into the three sound folders (through the same atomic upload as
everything else), and nothing is changed until the user has seen the plan and agreed.
Every step is safe to repeat, so a restore cut short by a disconnect can simply be run again.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import phone_contacts, phone_sounds
from .adb import (
    SOUND_FOLDERS,
    STORAGE_ROOT,
    AdbDevice,
    is_in_sound_folder,
    safe_local_name,
    unique_remote_name,
    valid_phone_file_name,
)
from .journal import Journal

FORMAT = "sound-manager-backup"
VERSION = 1
MANIFEST = "manifest.json"
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
MAX_FILES = 5000
MAX_CONTACTS = 20000
MAX_NAME_CHARS = 500

# Sound type (phone_sounds.SOUND_KEYS) for each folder, and the reverse.
FOLDER_SOUND = {"Ringtones": "ringtone", "Notifications": "notification", "Alarms": "alarm"}


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class SoundRef:
    folder: str  # "Ringtones", "Notifications" or "Alarms"
    file: str

    @property
    def remote(self) -> str:
        return f"{SOUND_FOLDERS[self.folder]}/{self.file}"

    @property
    def entry(self) -> str:  # name inside the zip
        return f"{self.folder}/{self.file}"


def ref_for_path(path: str | None) -> SoundRef | None:
    """SoundRef for a phone path (/sdcard/... or /storage/emulated/0/...) in a sound folder."""
    if not path:
        return None
    if path.startswith(STORAGE_ROOT + "/"):
        path = "/sdcard" + path[len(STORAGE_ROOT) :]
    if not is_in_sound_folder(path):
        return None
    p = PurePosixPath(path)
    folder = next(name for name, d in SOUND_FOLDERS.items() if d == str(p.parent))
    return SoundRef(folder, p.name)


# --------------------------------------------------------------------------- manifest checks


def _ref(value) -> SoundRef:
    if not isinstance(value, dict):
        raise BackupError("The backup file is damaged (a sound entry isn't valid).")
    folder, file = value.get("folder"), value.get("file")
    if folder not in SOUND_FOLDERS or not isinstance(file, str):
        raise BackupError("The backup file is damaged (a sound entry isn't valid).")
    if not valid_phone_file_name(file):
        raise BackupError("The backup file contains a sound with an unusable name.")
    return SoundRef(folder, file)


@dataclass
class Manifest:
    created: str
    files: list[tuple[SoundRef, int]]  # (sound, size in bytes)
    defaults: dict[str, SoundRef | None]  # setting key -> sound (None: built-in or silent)
    contacts: list[tuple[int, str, SoundRef]]  # (contact id when backed up, name, sound)


def parse_manifest(data: dict) -> Manifest:
    """Validate a backup's manifest. Raises BackupError for anything unexpected."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("That isn't a Sound Manager backup.")
    if data.get("version") != VERSION:
        raise BackupError("This backup was made by a newer version of Sound Manager.")
    raw_files, raw_defaults = data.get("files"), data.get("defaults")
    raw_contacts = data.get("contacts")
    if not (
        isinstance(raw_files, list)
        and isinstance(raw_defaults, dict)
        and isinstance(raw_contacts, list)
    ):
        raise BackupError("The backup file is damaged.")
    if len(raw_files) > MAX_FILES or len(raw_contacts) > MAX_CONTACTS:
        raise BackupError("The backup file is too large to be genuine.")

    files: list[tuple[SoundRef, int]] = []
    seen: set[tuple[str, str]] = set()
    total = 0
    for f in raw_files:
        ref = _ref(f)
        size = f.get("size")
        if not isinstance(size, int) or not 0 <= size <= MAX_FILE_BYTES:
            raise BackupError(f"“{ref.file}” in the backup is too large.")
        key = (ref.folder, ref.file.lower())
        if key in seen:
            raise BackupError("The backup file is damaged (a sound is listed twice).")
        seen.add(key)
        total += size
        files.append((ref, size))
    if total > MAX_TOTAL_BYTES:
        raise BackupError("The backup is too large.")

    defaults: dict[str, SoundRef | None] = {}
    for key, value in raw_defaults.items():
        if key not in phone_sounds.ALLOWED_KEYS:
            raise BackupError("The backup file is damaged (unknown sound setting).")
        defaults[key] = None if value is None else _ref(value)

    contacts: list[tuple[int, str, SoundRef]] = []
    for c in raw_contacts:
        if not isinstance(c, dict):
            raise BackupError("The backup file is damaged (a contact entry isn't valid).")
        cid, name = c.get("id"), c.get("name")
        if not isinstance(cid, int) or not isinstance(name, str) or len(name) > MAX_NAME_CHARS:
            raise BackupError("The backup file is damaged (a contact entry isn't valid).")
        contacts.append((cid, name, _ref(c.get("sound"))))

    # Settings and contacts may only point at sounds that are in the backup.
    for ref in [*filter(None, defaults.values()), *(c[2] for c in contacts)]:
        if (ref.folder, ref.file.lower()) not in seen:
            raise BackupError("The backup file is damaged (it refers to a missing sound).")
    created = data.get("created")
    return Manifest(created if isinstance(created, str) else "", files, defaults, contacts)


def read_manifest(zf: zipfile.ZipFile) -> Manifest:
    try:
        info = zf.getinfo(MANIFEST)
    except KeyError as exc:
        raise BackupError("That isn't a Sound Manager backup.") from exc
    if info.file_size > MAX_MANIFEST_BYTES:
        raise BackupError("The backup file is damaged (its index is too large).")
    with zf.open(info) as f:
        raw = f.read(MAX_MANIFEST_BYTES + 1)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BackupError("The backup file is damaged (its index can't be read).") from exc
    return parse_manifest(data)


def open_backup(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BackupError("That file isn't a readable backup (.zip).") from exc


def extract_sound(zf: zipfile.ZipFile, ref: SoundRef, size: int, dest: Path) -> None:
    """Copy one sound out of the backup into *dest*, enforcing the size from the manifest.

    The zip member is looked up by its exact expected name; member names are never used to
    build paths on the PC.
    """
    try:
        info = zf.getinfo(ref.entry)
    except KeyError as exc:
        raise BackupError(f"“{ref.file}” is missing from the backup.") from exc
    if info.file_size != size:
        raise BackupError(f"“{ref.file}” in the backup is damaged.")
    written = 0
    with zf.open(info) as src, open(dest, "wb") as out:
        while chunk := src.read(1024 * 1024):
            written += len(chunk)
            if written > size:
                raise BackupError(f"“{ref.file}” in the backup is damaged.")
            out.write(chunk)
    if written != size:
        raise BackupError(f"“{ref.file}” in the backup is damaged.")


# --------------------------------------------------------------------------- backup


@dataclass
class BackupSummary:
    files: int = 0
    bytes: int = 0
    defaults: int = 0
    contacts: int = 0
    skipped_contacts: int = 0  # ringtone outside the sound folders or built in
    skipped_defaults: list[str] = field(default_factory=list)  # keys using built-in sounds


def create_backup(dev: AdbDevice, dest: Path) -> BackupSummary:
    """Write a backup of *dev* to *dest* (written to a temp file, then moved into place)."""
    summary = BackupSummary()
    files: list[dict] = []
    defaults: dict[str, dict | None] = {}
    contacts: list[dict] = []
    part = dest.with_name(dest.name + ".part")
    with tempfile.TemporaryDirectory(prefix="asm-backup-") as tmp:
        try:
            with zipfile.ZipFile(part, "w") as zf:
                for folder, remote_dir in SOUND_FOLDERS.items():
                    for f in dev.list_dir(remote_dir):
                        ref = ref_for_path(f.path)
                        if ref is None or not valid_phone_file_name(ref.file):
                            continue
                        local = dev.pull(f.path, Path(tmp))
                        size = local.stat().st_size
                        if size > MAX_FILE_BYTES:
                            local.unlink()
                            continue
                        # Audio is already compressed: store it as-is.
                        zf.write(local, ref.entry, compress_type=zipfile.ZIP_STORED)
                        local.unlink()
                        files.append({"folder": folder, "file": ref.file, "size": size})
                        summary.files += 1
                        summary.bytes += size
                saved = {(f["folder"], f["file"].lower()) for f in files}

                def in_backup(ref: SoundRef | None) -> bool:
                    return ref is not None and (ref.folder, ref.file.lower()) in saved

                for sound in phone_sounds.SOUND_KEYS:
                    for key in phone_sounds.available_keys(dev, sound):
                        ref = ref_for_path(phone_sounds.get_default(dev, key).path)
                        if in_backup(ref):
                            defaults[key] = {"folder": ref.folder, "file": ref.file}
                            summary.defaults += 1
                        else:
                            summary.skipped_defaults.append(key)

                with_ringtone = [c for c in phone_contacts.list_contacts(dev) if c.ringtone]
                paths = phone_contacts.ringtone_paths(dev, {c.ringtone for c in with_ringtone})
                for c in with_ringtone:
                    ref = ref_for_path(paths.get(c.ringtone))
                    if in_backup(ref):
                        contacts.append(
                            {
                                "id": c.id,
                                "name": c.name,
                                "sound": {"folder": ref.folder, "file": ref.file},
                            }
                        )
                        summary.contacts += 1
                    else:
                        summary.skipped_contacts += 1

                manifest = {
                    "format": FORMAT,
                    "version": VERSION,
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "files": files,
                    "defaults": defaults,
                    "contacts": contacts,
                }
                zf.writestr(
                    MANIFEST,
                    json.dumps(manifest, ensure_ascii=False, indent=1),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
            os.replace(part, dest)
        finally:
            part.unlink(missing_ok=True)
    return summary


# --------------------------------------------------------------------------- restore


@dataclass
class RestorePlan:
    manifest: Manifest
    uploads: list[tuple[SoundRef, int, str]]  # (sound in backup, size, name to use on phone)
    already_there: int  # sounds the phone already has (same name and size)
    remote: dict[tuple[str, str], str]  # (folder, file.lower()) -> path on the phone
    defaults: list[tuple[str, str, SoundRef]]  # (key, current title, sound from the backup)
    skipped_defaults: list[str]  # keys this phone doesn't have (e.g. SIM 2)
    contacts: list[tuple[int, SoundRef]]  # (contact id on this phone, sound from the backup)
    unmatched_contacts: int  # contacts not found (or whose name isn't unique) on this phone

    def phone_path(self, ref: SoundRef) -> str:
        return self.remote[(ref.folder, ref.file.lower())]

    def phone_name(self, ref: SoundRef) -> str:
        return PurePosixPath(self.phone_path(ref)).name

    def is_empty(self) -> bool:
        return not (self.uploads or self.defaults or self.contacts)


def _same_or_renamed(original: str, name: str) -> bool:
    """True for `tone.mp3` itself or a copy saved as `tone (2).mp3` (ignoring case)."""
    stem, dot, ext = original.rpartition(".")
    if not dot:
        stem, ext = original, ""
    pattern = re.escape(stem) + r"( \(\d+\))?" + re.escape(dot + ext)
    return re.fullmatch(pattern, name, re.IGNORECASE) is not None


def plan_restore(dev: AdbDevice, manifest: Manifest) -> RestorePlan:
    """Work out what a restore would change, without changing anything."""
    uploads: list[tuple[SoundRef, int, str]] = []
    remote: dict[tuple[str, str], str] = {}
    already = 0
    for folder, remote_dir in SOUND_FOLDERS.items():
        on_phone = dev.list_dir(remote_dir)
        taken = {f.name.lower() for f in on_phone}
        for ref, size in (x for x in manifest.files if x[0].folder == folder):
            existing = next(
                (f for f in on_phone if f.size == size and _same_or_renamed(ref.file, f.name)),
                None,
            )
            if existing is not None:  # restored before (perhaps renamed to "name (2)")
                remote[(folder, ref.file.lower())] = existing.path
                already += 1
                continue
            name = unique_remote_name(ref.file, taken)  # never replace a different file
            taken.add(name.lower())
            uploads.append((ref, size, name))
            remote[(folder, ref.file.lower())] = f"{remote_dir}/{name}"

    available = {
        k for sound in phone_sounds.SOUND_KEYS for k in phone_sounds.available_keys(dev, sound)
    }
    defaults, skipped = [], []
    for key, ref in manifest.defaults.items():
        if ref is None:
            continue
        if key not in available:
            skipped.append(key)
            continue
        current = phone_sounds.get_default(dev, key)
        new_path = remote[(ref.folder, ref.file.lower())]
        if current.path and phone_sounds.to_storage_path(new_path) == current.path:
            continue  # already set
        defaults.append((key, current.title, ref))

    phone = phone_contacts.list_contacts(dev)
    current = phone_contacts.ringtone_paths(dev, {c.ringtone for c in phone if c.ringtone})
    by_id = {c.id: c for c in phone}
    by_name: dict[str, list[phone_contacts.Contact]] = {}
    for c in phone:
        by_name.setdefault(c.name.casefold(), []).append(c)
    contacts: list[tuple[int, SoundRef]] = []
    unmatched = 0
    for cid, name, ref in manifest.contacts:
        same = by_id.get(cid)
        if same is not None and same.name == name:
            match = same
        elif len(by_name.get(name.casefold(), [])) == 1:
            match = by_name[name.casefold()][0]
        else:
            unmatched += 1
            continue
        new_path = phone_sounds.to_storage_path(remote[(ref.folder, ref.file.lower())])
        if match.ringtone and current.get(match.ringtone) == new_path:
            continue  # already set
        contacts.append((match.id, ref))
    return RestorePlan(manifest, uploads, already, remote, defaults, skipped, contacts, unmatched)


def describe_plan(plan: RestorePlan) -> str:
    """Plain-text summary for the confirmation dialog."""
    lines = []
    if plan.uploads:
        lines.append(f"Copy {len(plan.uploads)} sound(s) to the phone.")
    if plan.already_there:
        lines.append(f"{plan.already_there} sound(s) are already on the phone.")
    for key, old, ref in plan.defaults:
        lines.append(f"{_key_label(key)}:  {old}  →  {plan.phone_name(ref)}")
    if plan.contacts:
        lines.append(f"Give {len(plan.contacts)} contact(s) their ringtone back.")
    if plan.unmatched_contacts:
        lines.append(
            f"{plan.unmatched_contacts} contact(s) from the backup aren't on this phone "
            "(or share a name with another contact) and are skipped."
        )
    if plan.skipped_defaults:
        lines.append("Settings this phone doesn't have (e.g. a second SIM) are skipped.")
    return "\n".join(lines)


_KEY_LABELS = {
    "ringtone": "Ringtone",
    "ringtone_2": "Ringtone (SIM 2)",
    "notification_sound": "Notification sound",
    "notification_sound_2": "Notification sound (SIM 2)",
    "alarm_alert": "Alarm",
}


def _key_label(key: str) -> str:
    return _KEY_LABELS.get(key, key)


def restore(
    dev: AdbDevice, backup: Path, plan: RestorePlan, journal: Journal | None = None
) -> None:
    """Carry out *plan*: upload sounds, then set defaults, then contact ringtones."""
    with open_backup(backup) as zf, tempfile.TemporaryDirectory(prefix="asm-restore-") as tmp:
        for ref, size, name in plan.uploads:
            local = Path(tmp) / safe_local_name(name)
            extract_sound(zf, ref, size, local)
            dev.push(local, SOUND_FOLDERS[ref.folder], name=name)
            local.unlink()
    for key, _old, ref in plan.defaults:
        phone_sounds.set_default(dev, key, plan.phone_path(ref), journal)
    for contact_id, ref in plan.contacts:
        phone_contacts.set_contact_ringtone(dev, contact_id, plan.phone_path(ref))


def default_backup_name() -> str:
    return f"Sound Manager backup {datetime.now():%Y-%m-%d}.zip"
