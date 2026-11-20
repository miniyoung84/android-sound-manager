package com.androidsoundmanager.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.IntentCompat
import androidx.core.os.BundleCompat
import com.androidsoundmanager.app.data.acceptsShare
import com.androidsoundmanager.app.ui.App
import com.androidsoundmanager.app.ui.SoundManagerTheme

class MainActivity : ComponentActivity() {
    /** A file another app shared with us, waiting in the editor. */
    private var shared by mutableStateOf<Uri?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        shared = if (savedInstanceState == null) {
            sharedSound(this, intent)
        } else {
            BundleCompat.getParcelable(savedInstanceState, KEY_SHARED, Uri::class.java)
        }
        enableEdgeToEdge()
        setContent {
            SoundManagerTheme {
                App(
                    shared = shared,
                    onShareClosed = { saved ->
                        shared = null
                        // Cancelled: go straight back to the app the file came from.
                        if (!saved) finish()
                    },
                )
            }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        shared?.let { outState.putParcelable(KEY_SHARED, it) }
    }

    private companion object {
        const val KEY_SHARED = "shared"
    }
}

/**
 * The file in a Share intent, if the editor should open it. Another app chose everything in the
 * intent, so it's checked: one audio/video file, a content:// link, and not one of this app's
 * own content providers (which would let another app read our files through us).
 */
private fun sharedSound(context: Context, intent: Intent?): Uri? {
    if (intent == null) return null
    val uri = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
        ?: intent.clipData?.takeIf { it.itemCount == 1 }?.getItemAt(0)?.uri
        ?: return null
    if (!acceptsShare(intent.action, intent.type, uri.scheme)) return null
    val authority = uri.authority ?: return null
    val owner = runCatching { context.packageManager.resolveContentProvider(authority, 0) }.getOrNull()
    return uri.takeIf { owner?.packageName != context.packageName }
}
