"""Per-contact ringtones over ADB (the adb shell user is granted contacts access on Android).

Privacy: only each contact's ID, display name, "has a phone number" flag, and custom ringtone are
read; phone numbers are never fetched. Names are kept in memory for display and must never be
logged, written to files, or included in error messages.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from .adb import AdbDevice, AdbError, is_in_sound_folder
from .phone_sounds import MEDIA_URI, find_media, parse_media_rows

CONTACTS_URI = "content://com.android.contacts/contacts"
INTERNAL_MEDIA_URI = "content://media/internal/audio/media"

# display_name is projected last so commas inside names can't confuse the parser.
_PROJECTION = "_id:has_phone_number:custom_ringtone:display_name"
_ROW = re.compile(
    r"^Row: \d+ _id=(\d+), has_phone_number=(\w*), custom_ringtone=(.*?), display_name=(.*)$"
)
_MEDIA_URI_RE = re.compile(r"^content://(?:\d+@)?media/(external|internal)/audio/media/(\d+)")


@dataclass(frozen=True)
class Contact:
    id: int
    name: str
    has_phone: bool
    ringtone: str | None  # content URI, or None for "use the phone's default ringtone"


def _null(value: str) -> str | None:
    return None if value in ("", "NULL") else value


def parse_contacts(output: str) -> list[Contact]:
    contacts = []
    for line in output.splitlines():
        m = _ROW.match(line.strip())
        if m:
            contacts.append(
                Contact(
                    id=int(m.group(1)),
                    name=_null(m.group(4)) or "(no name)",
                    has_phone=m.group(2) == "1",
                    ringtone=_null(m.group(3)),
                )
            )
    return sorted(contacts, key=lambda c: c.name.casefold())


def list_contacts(dev: AdbDevice) -> list[Contact]:
    return parse_contacts(
        dev.shell(f"content query --uri {CONTACTS_URI} --projection {_PROJECTION}")
    )


def get_contact_ringtone(dev: AdbDevice, contact_id: int) -> str | None:
    rows = parse_contacts(
        dev.shell(
            f"content query --uri {CONTACTS_URI}/{int(contact_id)} --projection {_PROJECTION}"
        )
    )
    if not rows:
        raise AdbError("That contact no longer exists on the phone.")
    return rows[0].ringtone


def ringtone_uri(media_id: int) -> str:
    """Same form the phone's Contacts app stores."""
    return f"{MEDIA_URI}/{int(media_id)}"


def describe_ringtones(dev: AdbDevice, uris: set[str]) -> dict[str, str]:
    """Map ringtone URIs to file names (shared storage) or titles (built-in sounds)."""
    ids: dict[str, set[int]] = {"external": set(), "internal": set()}
    for uri in uris:
        if m := _MEDIA_URI_RE.match(uri):
            ids[m.group(1)].add(int(m.group(2)))

    found: dict[tuple[str, int], str] = {}
    for volume, base in (("external", MEDIA_URI), ("internal", INTERNAL_MEDIA_URI)):
        if not ids[volume]:
            continue
        where = "_id IN (" + ",".join(str(i) for i in sorted(ids[volume])) + ")"
        out = dev.shell(
            f"content query --uri {base} --projection _id:title:_data --where {shlex.quote(where)}"
        )
        for row in parse_media_rows(out):
            label = row.path.rsplit("/", 1)[-1] if volume == "external" else row.title
            found[(volume, row.id)] = label

    names = {}
    for uri in uris:
        m = _MEDIA_URI_RE.match(uri)
        key = (m.group(1), int(m.group(2))) if m else None
        names[uri] = found.get(key, "(missing sound file)") if key else "(unknown sound)"
    return names


def _write_ringtone(dev: AdbDevice, contact_id: int, uri: str | None) -> None:
    binding = "custom_ringtone:n:" if uri is None else f"custom_ringtone:s:{uri}"
    dev.shell(
        f"content update --uri {CONTACTS_URI}/{int(contact_id)} --bind {shlex.quote(binding)}"
    )
    if get_contact_ringtone(dev, contact_id) != uri:
        raise AdbError("The phone did not accept the contact ringtone change.")


def set_contact_ringtone(dev: AdbDevice, contact_id: int, remote_path: str | None) -> str | None:
    """Give a contact the sound at *remote_path* (None = phone's default). Returns the old URI.

    A single `content update` is atomic on the phone, so a disconnect can't half-apply it.
    """
    uri = None
    if remote_path is not None:
        if not is_in_sound_folder(remote_path):
            raise AdbError("Only files in the phone's sound folders can be used.")
        uri = ringtone_uri(find_media(dev, remote_path).id)
    old = get_contact_ringtone(dev, contact_id)
    if old != uri:
        _write_ringtone(dev, contact_id, uri)
    return old


def restore_contact_ringtone(dev: AdbDevice, contact_id: int, old_uri: str | None) -> None:
    """Undo: put back a previous custom_ringtone value (validated before writing)."""
    if old_uri is not None and (
        not old_uri.startswith(("content://", "file://")) or "\n" in old_uri
    ):
        raise AdbError("Refusing to restore an unexpected ringtone value.")
    if get_contact_ringtone(dev, contact_id) != old_uri:
        _write_ringtone(dev, contact_id, old_uri)
