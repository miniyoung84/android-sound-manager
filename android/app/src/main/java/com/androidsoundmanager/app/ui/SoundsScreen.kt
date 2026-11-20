package com.androidsoundmanager.app.ui

import android.content.Intent
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
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
    val grantAccess = {
        context.startActivity(
            Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS)
                .setData("package:${context.packageName}".toUri()),
        )
    }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val twoPane = maxWidth >= TwoPaneWidth
        val list = @Composable { modifier: Modifier ->
            SoundList(type, sounds, current, selected?.id, player, modifier) { selected = it }
        }
        val detail = @Composable { sound: Sound, onBack: (() -> Unit)? ->
            SoundDetail(
                sound, type, isDefault = current?.mediaId == sound.id, canChange = canChange,
                player = player, onBack = onBack, onSetDefault = setDefault,
                onGrantAccess = grantAccess,
            )
        }
        if (twoPane) {
            Row(Modifier.fillMaxSize()) {
                list(Modifier.weight(1f))
                Box(Modifier.weight(1f).fillMaxSize().padding(end = 16.dp, bottom = 16.dp)) {
                    selected?.let { detail(it, null) }
                        ?: EmptyState("Pick a sound to preview it or make it your ${type.label}.")
                }
            }
        } else {
            val sel = selected
            if (sel == null) {
                list(Modifier.fillMaxSize())
            } else {
                BackHandler { selected = null }
                detail(sel) { selected = null }
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
    type: SoundType,
    sounds: List<Sound>,
    current: CurrentDefault?,
    selectedId: Long?,
    player: PreviewPlayer,
    modifier: Modifier,
    onSelect: (Sound) -> Unit,
) {
    val currentSound = current?.mediaId?.let { id -> sounds.firstOrNull { it.id == id } }
    LazyColumn(
        modifier,
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (current != null) {
            item(key = "current") { CurrentCard(type, current, currentSound, player) }
        }
        if (sounds.isEmpty()) {
            item(key = "empty") {
                EmptyState(
                    "No sounds in this folder yet. Send some from the desktop app.",
                    Modifier.padding(top = 24.dp),
                )
            }
        }
        items(sounds, key = { it.id }) { s ->
            RowCard(
                selected = s.id == selectedId,
                onClick = { onSelect(s) },
                leading = { PlayButton(player.playing == s.uri) { player.toggle(s.uri) } },
                title = s.title,
                subtitle = formatDuration(s.durationMs),
                trailing = if (current?.mediaId == s.id) ({ Pill("Current") }) else null,
            )
        }
    }
}

/** Highlighted card showing what's set right now, with its own play button. */
@Composable
private fun CurrentCard(
    type: SoundType,
    current: CurrentDefault,
    sound: Sound?,
    player: PreviewPlayer,
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.tertiaryContainer,
            contentColor = MaterialTheme.colorScheme.onTertiaryContainer,
        ),
        shape = MaterialTheme.shapes.large,
        modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp),
    ) {
        Row(
            Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            BakeryLogo(48.dp)
            Column(Modifier.weight(1f)) {
                Text(
                    "Your ${type.label}",
                    style = MaterialTheme.typography.labelLarge,
                )
                Text(
                    current.title,
                    style = MaterialTheme.typography.titleLarge,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (sound != null) PlayButton(player.playing == sound.uri) { player.toggle(sound.uri) }
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
    onBack: (() -> Unit)?,
    onSetDefault: (Sound) -> Unit,
    onGrantAccess: () -> Unit,
) {
    var confirm by remember { mutableStateOf(false) }
    var explainAccess by remember { mutableStateOf(false) }
    val playing = player.playing == sound.uri

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        if (onBack != null) {
            IconButton(onClick = onBack, modifier = Modifier.padding(8.dp)) {
                Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "Back")
            }
        }
        Card(
            shape = MaterialTheme.shapes.large,
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
            ),
            modifier = Modifier.fillMaxWidth().padding(16.dp),
        ) {
            Column(
                Modifier.padding(24.dp).fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                BakeryLogo(96.dp)
                Text(
                    sound.title,
                    style = MaterialTheme.typography.headlineSmall,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    "${formatDuration(sound.durationMs)} · ${formatSize(sound.sizeBytes)}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    sound.fileName,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                FilledTonalButton(
                    onClick = { player.toggle(sound.uri) },
                    modifier = Modifier.widthIn(min = 200.dp),
                ) {
                    Icon(
                        if (playing) Icons.Rounded.Stop else Icons.Rounded.PlayArrow,
                        contentDescription = null,
                    )
                    Text(if (playing) "  Stop" else "  Play preview")
                }
                if (isDefault) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            Icons.Rounded.CheckCircle,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Text(
                            "  This is your ${type.label}",
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                } else {
                    // Two steps (button, then confirmation) so it can't be changed by accident.
                    Button(
                        onClick = { if (canChange) confirm = true else explainAccess = true },
                        modifier = Modifier.widthIn(min = 200.dp),
                    ) { Text("Set as ${type.label}…") }
                }
                if (type == SoundType.RINGTONE) {
                    Text(
                        "On dual-SIM phones this sets SIM 1. Use the desktop app for SIM 2.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
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

fun formatDuration(ms: Long): String {
    val s = (ms + 500) / 1000
    return "%d:%02d".format(s / 60, s % 60)
}

fun formatSize(bytes: Long): String = when {
    bytes >= 1_048_576 -> "%.1f MB".format(bytes / 1_048_576.0)
    bytes >= 1024 -> "%.0f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}
