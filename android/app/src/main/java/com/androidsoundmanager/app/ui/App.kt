package com.androidsoundmanager.app.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.androidsoundmanager.app.data.SoundType

private val audioPermission =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) Manifest.permission.READ_MEDIA_AUDIO
    else Manifest.permission.READ_EXTERNAL_STORAGE

private fun granted(context: Context, permission: String) =
    ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

private val tabs = listOf("Ringtones", "Notifications", "Alarms", "Contacts")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App() {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    Scaffold(
        topBar = { TopAppBar(title = { Text("Sound Manager") }) },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            PrimaryTabRow(selectedTabIndex = tab) {
                tabs.forEachIndexed { i, title ->
                    Tab(selected = tab == i, onClick = { tab = i }, text = { Text(title) })
                }
            }
            when (tab) {
                0 -> PermissionGate(audioPermission, AUDIO_REASON) { SoundsScreen(SoundType.RINGTONE) }
                1 -> PermissionGate(audioPermission, AUDIO_REASON) { SoundsScreen(SoundType.NOTIFICATION) }
                2 -> PermissionGate(audioPermission, AUDIO_REASON) { SoundsScreen(SoundType.ALARM) }
                else -> PermissionGate(Manifest.permission.WRITE_CONTACTS, CONTACTS_REASON) {
                    PermissionGate(audioPermission, AUDIO_REASON) { ContactsScreen() }
                }
            }
        }
    }
}

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
    val extra = if (permission == Manifest.permission.WRITE_CONTACTS) {
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
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(reason, style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center)
            Button(onClick = { launcher.launch(extra) }) { Text("Allow access") }
        }
    }
}
