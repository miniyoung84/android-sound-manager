package com.androidsoundmanager.app.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Alarm
import androidx.compose.material.icons.rounded.Contacts
import androidx.compose.material.icons.rounded.MusicNote
import androidx.compose.material.icons.rounded.NotificationsActive
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.androidsoundmanager.app.data.SoundRepository
import com.androidsoundmanager.app.data.SoundType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private val audioPermission =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) Manifest.permission.READ_MEDIA_AUDIO
    else Manifest.permission.READ_EXTERNAL_STORAGE

private fun granted(context: Context, permission: String) =
    ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

private data class Destination(val label: String, val icon: ImageVector)

private val destinations = listOf(
    Destination("Ringtones", Icons.Rounded.MusicNote),
    Destination("Notifications", Icons.Rounded.NotificationsActive),
    Destination("Alarms", Icons.Rounded.Alarm),
    Destination("Contacts", Icons.Rounded.Contacts),
)

/** Tabs 0-2 show these folders, in this order. */
private val soundTabs = listOf(SoundType.RINGTONE, SoundType.NOTIFICATION, SoundType.ALARM)

/**
 * The whole app. [shared] is a file another app shared with us: it opens in the editor on top
 * of everything (no permission needed to edit it), and [onShareClosed] is told whether it was
 * saved.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App(shared: Uri? = null, onShareClosed: (saved: Boolean) -> Unit = {}) {
    val context = LocalContext.current
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var shareSource by remember { mutableStateOf<EditorSource?>(null) }
    var savedId by remember { mutableStateOf<Long?>(null) } // select a just-saved sound
    var message by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(shared) {
        shareSource = shared?.let { uri ->
            // The name comes from the other app's provider: read it off the main thread.
            val repo = SoundRepository(context.applicationContext)
            EditorSource(uri, withContext(Dispatchers.IO) { repo.displayTitle(uri) }, isCopy = false)
        }
    }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        // Inner screen of the Fold (and tablets): navigation rail on the side.
        // Cover screen (and phones): navigation bar at the bottom.
        val wide = maxWidth >= TwoPaneWidth
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { BrandTitle(showLogo = !wide) },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.surface,
                    ),
                )
            },
            bottomBar = {
                if (!wide) {
                    NavigationBar(containerColor = MaterialTheme.colorScheme.surfaceContainer) {
                        destinations.forEachIndexed { i, d ->
                            NavigationBarItem(
                                selected = tab == i,
                                onClick = { tab = i },
                                icon = { Icon(d.icon, contentDescription = null) },
                                label = { Text(d.label, maxLines = 1) },
                            )
                        }
                    }
                }
            },
        ) { padding ->
            Row(Modifier.padding(padding).fillMaxSize()) {
                if (wide) {
                    NavigationRail(
                        containerColor = MaterialTheme.colorScheme.surface,
                        header = {
                            BakeryLogo(48.dp, Modifier.padding(top = 4.dp, bottom = 12.dp))
                        },
                    ) {
                        Spacer(Modifier.height(8.dp))
                        destinations.forEachIndexed { i, d ->
                            NavigationRailItem(
                                selected = tab == i,
                                onClick = { tab = i },
                                icon = { Icon(d.icon, contentDescription = null) },
                                label = { Text(d.label, maxLines = 1) },
                            )
                        }
                    }
                }
                Box(Modifier.weight(1f).fillMaxSize()) {
                    when (tab) {
                        in soundTabs.indices -> AudioGate {
                            SoundsScreen(soundTabs[tab], selectOnLoad = savedId) { savedId = null }
                        }
                        else -> PermissionGate(Manifest.permission.WRITE_CONTACTS, CONTACTS_REASON) {
                            AudioGate { ContactsScreen() }
                        }
                    }
                }
            }
        }
    }

    val src = shareSource
    if (src != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        SoundEditor(
            source = src,
            initialType = soundTabs.getOrElse(tab) { SoundType.RINGTONE },
            onDismiss = {
                shareSource = null
                onShareClosed(false)
            },
            onSaved = { type, id, title ->
                shareSource = null
                tab = soundTabs.indexOf(type)
                savedId = id
                message = "Saved “$title” to ${type.folder}."
                onShareClosed(true)
            },
        )
    }
    message?.let {
        AlertDialog(
            onDismissRequest = { message = null },
            confirmButton = { TextButton(onClick = { message = null }) { Text("OK") } },
            text = { Text(it) },
        )
    }
}

@Composable
private fun AudioGate(content: @Composable () -> Unit) =
    PermissionGate(audioPermission, AUDIO_REASON, content)

private const val AUDIO_REASON =
    "To list the sounds in your Ringtones, Notifications and Alarms folders, Sound Manager needs " +
        "access to audio files on this phone."
private const val CONTACTS_REASON =
    "To give contacts their own ringtone, Sound Manager needs access to your contacts. It only " +
        "reads names and ringtones (never phone numbers) and never sends anything off the phone."

/** Shows [content] once [permission] is granted; otherwise explains why and asks. */
@Composable
fun PermissionGate(permission: String, reason: String, content: @Composable () -> Unit) {
    val context = LocalContext.current
    var ok by remember(permission) { mutableStateOf(granted(context, permission)) }
    val request = if (permission == Manifest.permission.WRITE_CONTACTS) {
        arrayOf(Manifest.permission.READ_CONTACTS, permission)
    } else {
        arrayOf(permission)
    }
    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { results -> ok = results.values.all { it } }

    if (ok) {
        content()
    } else {
        Column(
            Modifier.fillMaxSize().padding(32.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp, Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            BakeryLogo(96.dp)
            Text(
                reason,
                style = MaterialTheme.typography.bodyLarge,
                textAlign = TextAlign.Center,
                modifier = Modifier.widthIn(max = 420.dp),
            )
            Button(onClick = { launcher.launch(request) }) { Text("Allow access") }
        }
    }
}
