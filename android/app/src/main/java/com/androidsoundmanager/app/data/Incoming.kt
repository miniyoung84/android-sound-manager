package com.androidsoundmanager.app.data

import java.io.InputStream
import java.io.OutputStream

/*
 * Rules for files that come from other apps (Share, or the file picker). Anything another app
 * hands us is untrusted: it decides the type, the name, and what the stream contains.
 */

/** Largest file copied as-is. Real ringtones are a few MB; this stops endless streams. */
const val MAX_COPY_BYTES = 200L * 1024 * 1024

/**
 * Whether a share is one the editor should open: a single audio or video file, sent as a
 * content:// link. Never file:// links, which could point into this app's private files.
 */
fun acceptsShare(action: String?, mime: String?, scheme: String?): Boolean =
    action == "android.intent.action.SEND" &&
        mime != null && (mime.startsWith("audio/") || mime.startsWith("video/")) &&
        scheme == "content"

/** Copies [input] to [output], failing once more than [limit] bytes have come through. */
fun copyAtMost(input: InputStream, output: OutputStream, limit: Long = MAX_COPY_BYTES): Long {
    val buffer = ByteArray(64 * 1024)
    var total = 0L
    while (true) {
        val n = input.read(buffer)
        if (n < 0) return total
        total += n
        if (total > limit) throw EditError("That file is too big to save as a sound.")
        output.write(buffer, 0, n)
    }
}
