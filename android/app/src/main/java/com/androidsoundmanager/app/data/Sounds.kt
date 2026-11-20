package com.androidsoundmanager.app.data

import android.content.ContentUris
import android.content.Context
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.provider.Settings

/** The three shared folders Android's sound pickers read from. */
enum class SoundType(val folder: String, val ringtoneType: Int, val label: String) {
    RINGTONE(Environment.DIRECTORY_RINGTONES, RingtoneManager.TYPE_RINGTONE, "ringtone"),
    NOTIFICATION(
        Environment.DIRECTORY_NOTIFICATIONS,
        RingtoneManager.TYPE_NOTIFICATION,
        "notification sound",
    ),
    ALARM(Environment.DIRECTORY_ALARMS, RingtoneManager.TYPE_ALARM, "alarm"),
}

data class Sound(
    val id: Long,
    val title: String,
    val fileName: String,
    val durationMs: Long,
    val sizeBytes: Long,
) {
    val uri: Uri get() = ContentUris.withAppendedId(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, id)
}

data class CurrentDefault(val title: String, val mediaId: Long?)

class SoundRepository(private val context: Context) {

    private val resolver get() = context.contentResolver

    /** Sounds in one of the three folders, sorted by title. Hidden files (".x") are skipped. */
    fun list(type: SoundType): List<Sound> {
        val projection = arrayOf(
            MediaStore.Audio.Media._ID,
            MediaStore.Audio.Media.TITLE,
            MediaStore.Audio.Media.DISPLAY_NAME,
            MediaStore.Audio.Media.DURATION,
            MediaStore.Audio.Media.SIZE,
        )
        val (selection, args) = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            "${MediaStore.Audio.Media.RELATIVE_PATH} = ?" to arrayOf("${type.folder}/")
        } else {
            @Suppress("DEPRECATION")
            val root = Environment.getExternalStorageDirectory().absolutePath
            @Suppress("DEPRECATION")
            "${MediaStore.Audio.Media.DATA} LIKE ? AND ${MediaStore.Audio.Media.DATA} NOT LIKE ?" to
                arrayOf("$root/${type.folder}/%", "$root/${type.folder}/%/%")
        }
        val sounds = mutableListOf<Sound>()
        resolver.query(
            MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, projection, selection, args, null,
        )?.use { c ->
            val id = c.getColumnIndexOrThrow(MediaStore.Audio.Media._ID)
            val title = c.getColumnIndexOrThrow(MediaStore.Audio.Media.TITLE)
            val name = c.getColumnIndexOrThrow(MediaStore.Audio.Media.DISPLAY_NAME)
            val duration = c.getColumnIndexOrThrow(MediaStore.Audio.Media.DURATION)
            val size = c.getColumnIndexOrThrow(MediaStore.Audio.Media.SIZE)
            while (c.moveToNext()) {
                val fileName = c.getString(name) ?: continue
                if (fileName.startsWith(".")) continue
                sounds += Sound(
                    id = c.getLong(id),
                    title = c.getString(title)?.takeIf { it.isNotBlank() } ?: fileName,
                    fileName = fileName,
                    durationMs = c.getLong(duration),
                    sizeBytes = c.getLong(size),
                )
            }
        }
        return sounds.sortedBy { it.title.lowercase() }
    }

    fun currentDefault(type: SoundType): CurrentDefault {
        val uri = RingtoneManager.getActualDefaultRingtoneUri(context, type.ringtoneType)
            ?: return CurrentDefault("Silent", null)
        val title = runCatching { RingtoneManager.getRingtone(context, uri)?.getTitle(context) }
            .getOrNull() ?: "Unknown"
        // Strip a "content://0@media/..." user prefix and query string to get the media ID.
        val mediaId = uri.lastPathSegment?.toLongOrNull()
            ?.takeIf { uri.toString().contains("/external/") }
        return CurrentDefault(title, mediaId)
    }

    /** "Modify system settings" special access, needed to change the default sounds. */
    fun canChangeDefaults(): Boolean = Settings.System.canWrite(context)

    fun setDefault(type: SoundType, sound: Sound) {
        check(canChangeDefaults()) { "Permission to modify system settings is missing" }
        RingtoneManager.setActualDefaultRingtoneUri(context, type.ringtoneType, sound.uri)
    }
}
