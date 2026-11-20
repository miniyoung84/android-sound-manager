package com.androidsoundmanager.app.data

import android.app.PendingIntent
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.provider.Settings
import android.webkit.MimeTypeMap
import androidx.annotation.RequiresApi
import java.io.IOException
import java.io.OutputStream

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

    /**
     * Saves a new sound into [type]'s folder and returns its ID. [write] fills the file.
     *
     * The file stays "pending" (invisible to every other app and to the sound pickers) until it
     * is completely written, and is removed if anything fails, so an interrupted save never
     * leaves a broken sound behind. Android picks a free name if one is taken.
     */
    @RequiresApi(Build.VERSION_CODES.Q)
    fun save(
        type: SoundType,
        title: String,
        mimeType: String,
        extension: String,
        write: (OutputStream) -> Unit,
    ): Long {
        val values = ContentValues().apply {
            put(MediaStore.Audio.Media.DISPLAY_NAME, "${safeFileName(title)}.$extension")
            put(MediaStore.Audio.Media.TITLE, title.trim().ifEmpty { "Sound" })
            put(MediaStore.Audio.Media.MIME_TYPE, mimeType)
            put(MediaStore.Audio.Media.RELATIVE_PATH, "${type.folder}/")
            put(MediaStore.Audio.Media.IS_PENDING, 1)
            put(
                when (type) {
                    SoundType.RINGTONE -> MediaStore.Audio.Media.IS_RINGTONE
                    SoundType.NOTIFICATION -> MediaStore.Audio.Media.IS_NOTIFICATION
                    SoundType.ALARM -> MediaStore.Audio.Media.IS_ALARM
                },
                1,
            )
        }
        val collection = MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val uri = resolver.insert(collection, values)
            ?: throw IOException("Android didn't allow a new file in ${type.folder}.")
        try {
            resolver.openOutputStream(uri, "w")?.use(write)
                ?: throw IOException("Couldn't write the new file.")
            val done = ContentValues().apply { put(MediaStore.Audio.Media.IS_PENDING, 0) }
            resolver.update(uri, done, null, null)
        } catch (t: Throwable) {
            runCatching { resolver.delete(uri, null, null) }
            throw t
        }
        return ContentUris.parseId(uri)
    }

    /** Asks Android to move [sound] to the trash (recoverable for 30 days) after the user agrees. */
    @RequiresApi(Build.VERSION_CODES.R)
    fun trashRequest(sound: Sound): PendingIntent =
        MediaStore.createTrashRequest(resolver, listOf(sound.uri), true)

    /** The file name of a picked document, without its extension (for a default title). */
    fun displayTitle(uri: Uri): String {
        val name = runCatching {
            resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        }.getOrNull() ?: return "New sound"
        return name.substringBeforeLast('.', name).ifBlank { "New sound" }
    }

    /** MIME type and file extension of [uri], when it's a plain audio file. */
    fun audioType(uri: Uri): Pair<String, String>? {
        val mime = resolver.getType(uri)?.takeIf { it.startsWith("audio/") } ?: return null
        val ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(mime) ?: return null
        return mime to ext
    }

    fun copy(from: Uri, to: OutputStream) {
        resolver.openInputStream(from)?.use { it.copyTo(to) }
            ?: throw IOException("Couldn't read the original file.")
    }
}