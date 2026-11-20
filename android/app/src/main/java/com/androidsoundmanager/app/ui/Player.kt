package com.androidsoundmanager.app.ui

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext

/** Plays one sound at a time for previewing. Released automatically with the screen. */
class PreviewPlayer(private val context: Context) {
    private var player: MediaPlayer? = null
    var playing by mutableStateOf<Uri?>(null)
        private set

    fun toggle(uri: Uri) {
        if (playing == uri) stop() else play(uri)
    }

    private fun play(uri: Uri) {
        stop()
        player = runCatching {
            MediaPlayer().apply {
                setAudioAttributes(
                    AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).build(),
                )
                setDataSource(context, uri)
                setOnCompletionListener { stop() }
                prepare()
                start()
            }
        }.getOrNull()
        playing = if (player != null) uri else null
    }

    fun stop() {
        player?.run { runCatching { stop() }; release() }
        player = null
        playing = null
    }
}

@Composable
fun rememberPreviewPlayer(): PreviewPlayer {
    val context = LocalContext.current
    val player = remember { PreviewPlayer(context.applicationContext) }
    DisposableEffect(Unit) { onDispose { player.stop() } }
    return player
}
