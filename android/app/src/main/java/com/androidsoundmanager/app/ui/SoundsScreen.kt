package com.androidsoundmanager.app.ui

import android.content.Intent
import android.provider.Settings
import androidx.core.net.toUri
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import com.androidsoundmanager.app.data.CurrentDefault
import com.androidsoundmanager.app.data.Sound
import com.androidsoundmanager.app.data.SoundRepository
import com.androidsoundmanager.app.data.SoundType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Width at which list and details sit side by side (the Fold's inner screen, tablets). */
val TwoPaneWidth = 600.dp

@Composable
fun SoundsScreen(type: SoundType) {
    val context = LocalContext.current
    val repo = remember { SoundRepository(context.applicationContext) }
    val player = rememberPreviewPlayer()
    val scope = rememberCoroutineScope()

    var sounds by remember(type) { mutableStateOf<List<Sound>>(emptyList()) }
    var current by remember(type) { mutableStateOf<CurrentDefault?>(null) }
    var selected by remember(type) { mutableStateOf<Sound?>(null) }
    var canChange by remember { mutableStateOf(repo.canChangeDefaults()) }
    var reload by remember { mutableIntStateOf(0) }
    var message by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(type, reload) {
        val (list, def) = withContext(Dispatchers.IO) { repo.list(type) to repo.currentDefault(type) }
        sounds = list
        current = def
        selected = selected?.let { s -> list.firstOrNull { it.id == s.id } }
    }
    // Re-check after returning from Settings (permission) or another app (new files).
    LifecycleResumeEffect(Unit) {
        canChange = repo.canChangeDefaults()
        reload++
        onPauseOrDispose { player.stop() }
    }

    val setDefault: (Sound) -> Unit = { sound ->
        scope.launch {
            val result = withContext(Dispatchers.IO) { runCatching { repo.setDefault(type, sound) } }
            message = result.fold(
                onSuccess = { "“${sound.title}” is now your ${type.label}." },
                onFailure = { "Couldn't change the ${type.label}: ${it.message}" },
            )
            reload++
        }
    }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val twoPane = maxWidth >= TwoPaneWidth
        val list = @Composable { modifier: Modifier ->
            SoundList(sounds, current, selected?.id, player, modifier) { selected = it }
        }
        val detail = @Composable { sound: Sound, modifier: Modifier, onBack: (() -> Unit)? ->
            SoundDetail(
                sound, type, isDefault = current?.mediaId == sound.id, canChange = canChange,
                player = player, modifier = modifier, onBack = onBack,
                onSetDefault = setDefault,
                onGrantAccess = {
                    context.startActivity(
                        Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS)
                            .setData("package:${context.packageName}".toUri()),
                    )
                },
            )
        }
        if (twoPane) {
            Row(Modifier.fillMaxSize()) {
                list(Modifier.weight(1f))
                VerticalDivider()
                Box(Modifier.weight(1f)) {
                    selected?.let { detail(it, Modifier.fillMaxSize(), null) }
                        ?: EmptyDetail("Pick a sound to preview it or make it your ${type.label}.")
                }
            }
        } else {
            val sel = selected
            if (sel == null) {
                list(Modifier.fillMaxSize())
            } else {
                BackHandler { selected = null }
                detail(sel, Modifier.fillMaxSize()) { selected = null }
            }
        }
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
private fun SoundList(
    sounds: List<Sound>,
    current: CurrentDefault?,
    selectedId: Long?,
    player: PreviewPlayer,
    modifier: Modifier,
    onSelect: (Sound) -> Unit,
) {
    Column(modifier) {
        current?.let {
            Text(
                "Current: ${it.title}",
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(16.dp, 12.dp),
            )
        }
        if (sounds.isEmpty()) {
            EmptyDetail("No sounds in this folder yet. Send some from the desktop app.")
            return@Column
        }
        LazyColumn(Modifier.fillMaxSize()) {
            items(sounds, key = { it.id }) { s ->
                ListItem(
                    headlineContent = { Text(s.title) },
                    supportingContent = { Text(formatDuration(s.durationMs)) },
                    leadingContent = {
                        IconButton(onClick = { player.toggle(s.uri) }) {
                            Icon(
                                if (player.playing == s.uri) Icons.Filled.Stop else Icons.Filled.PlayArrow,
                                contentDescription = if (player.playing == s.uri) "Stop" else "Play",
                            )
                        }
                    },
                    trailingContent = {
                        if (current?.mediaId == s.id) Icon(Icons.Filled.Star, "Current default")
                    },
                    colors = if (s.id == selectedId) {
                        ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.secondaryContainer)
                    } else {
                        ListItemDefaults.colors()
                    },
                    modifier = Modifier.clickable { onSelect(s) },
                )
                HorizontalDivider()
            }
        }
    }
}

@Composable
private fun SoundDetail(
    sound: Sound,
    type: SoundType,
    isDefault: Boolean,
    canChange: Boolean,
    player: PreviewPlayer,
    modifier: Modifier,
    onBack: (() -> Unit)?,
    onSetDefault: (Sound) -> Unit,
    onGrantAccess: () -> Unit,
) {
    var confirm by remember { mutableStateOf(false) }
    var explainAccess by remember { mutableStateOf(false) }

    Column(modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        if (onBack != null) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
        }
        Text(sound.title, style = MaterialTheme.typography.headlineSmall)
        Text(
            "${sound.fileName} · ${formatDuration(sound.durationMs)} · ${formatSize(sound.sizeBytes)}",
            style = MaterialTheme.typography.bodyMedium,
        )
        OutlinedButton(onClick = { player.toggle(sound.uri) }) {
            Text(if (player.playing == sound.uri) "Stop" else "Play")
        }
        if (isDefault) {
            Text("This is your current ${type.label}.", color = MaterialTheme.colorScheme.primary)
        } else {
            // Two steps (button, then confirmation) so it can't be changed by accident.
            Button(onClick = { if (canChange) confirm = true else explainAccess = true }) {
                Text("Set as ${type.label}…")
            }
        }
        if (type == SoundType.RINGTONE) {
            Text(
                "On dual-SIM phones this sets SIM 1. Use the desktop app for SIM 2.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }

    if (confirm) {
        AlertDialog(
            onDismissRequest = { confirm = false },
            title = { Text("Change ${type.label}?") },
            text = { Text("Use “${sound.title}” as your ${type.label}?") },
            confirmButton = {
                TextButton(onClick = { confirm = false; onSetDefault(sound) }) { Text("Change") }
            },
            dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } },
        )
    }
    if (explainAccess) {
        AlertDialog(
            onDismissRequest = { explainAccess = false },
            title = { Text("One-time permission") },
            text = {
                Text(
                    "Android asks you to allow “Modify system settings” before an app " +
                        "can change your ${type.label}. Sound Manager only uses it for your " +
                        "ringtone, notification and alarm sounds.",
                )
            },
            confirmButton = {
                TextButton(onClick = { explainAccess = false; onGrantAccess() }) {
                    Text("Open settings")
                }
            },
            dismissButton = { TextButton(onClick = { explainAccess = false }) { Text("Not now") } },
        )
    }
}

@Composable
fun EmptyDetail(text: String) {
    Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
    }
}

fun formatDuration(ms: Long): String {
    val s = (ms + 500) / 1000
    return "%d:%02d".format(s / 60, s % 60)
}

fun formatSize(bytes: Long): String = when {
    bytes >= 1_048_576 -> "%.1f MB".format(bytes / 1_048_576.0)
    bytes >= 1024 -> "%.0f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}
