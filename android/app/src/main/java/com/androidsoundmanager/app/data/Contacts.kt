package com.androidsoundmanager.app.data

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.provider.ContactsContract.Contacts

/**
 * Per-contact ringtones. Only each contact's ID, display name and ringtone are read; phone
 * numbers are never queried. Nothing is stored or sent anywhere.
 */
data class Contact(val id: Long, val name: String, val ringtone: String?)

class ContactRepository(private val context: Context) {

    fun list(): List<Contact> {
        val projection = arrayOf(Contacts._ID, Contacts.DISPLAY_NAME_PRIMARY, Contacts.CUSTOM_RINGTONE)
        val contacts = mutableListOf<Contact>()
        context.contentResolver.query(
            Contacts.CONTENT_URI,
            projection,
            "${Contacts.HAS_PHONE_NUMBER} = 1",
            null,
            "${Contacts.DISPLAY_NAME_PRIMARY} COLLATE NOCASE ASC",
        )?.use { c ->
            val id = c.getColumnIndexOrThrow(Contacts._ID)
            val name = c.getColumnIndexOrThrow(Contacts.DISPLAY_NAME_PRIMARY)
            val ringtone = c.getColumnIndexOrThrow(Contacts.CUSTOM_RINGTONE)
            while (c.moveToNext()) {
                contacts += Contact(
                    id = c.getLong(id),
                    name = c.getString(name) ?: "(no name)",
                    ringtone = c.getString(ringtone),
                )
            }
        }
        return contacts
    }

    /** Set (or with null, clear) a contact's ringtone. Returns the previous value for undo. */
    fun setRingtone(contact: Contact, sound: Sound?): String? {
        val values = ContentValues().apply {
            if (sound == null) putNull(Contacts.CUSTOM_RINGTONE)
            else put(Contacts.CUSTOM_RINGTONE, sound.uri.toString())
        }
        val uri = ContentUris.withAppendedId(Contacts.CONTENT_URI, contact.id)
        val updated = context.contentResolver.update(uri, values, null, null)
        check(updated > 0) { "That contact no longer exists" }
        return contact.ringtone
    }

    /** Undo: put back a previous ringtone value exactly as it was. */
    fun restoreRingtone(contactId: Long, previous: String?) {
        val values = ContentValues().apply {
            if (previous == null) putNull(Contacts.CUSTOM_RINGTONE)
            else put(Contacts.CUSTOM_RINGTONE, previous)
        }
        context.contentResolver.update(
            ContentUris.withAppendedId(Contacts.CONTENT_URI, contactId), values, null, null,
        )
    }
}
