package com.androidsoundmanager.app.ui

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ContentCut
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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

/** Saving new sounds needs Android 10+ (scoped storage); trash needs Android 11+. */
private val canSave = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
private val canTrash = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R

/** [selectOnLoad]: a sound saved from elsewhere (a share) to open once the list has loaded. */
@Composable
fun SoundsScreen(type: SoundType, selectOnLoad: Long? = null, onSelectedOnLoad: () -> Unit = {}) {
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
    var editor by remember { mutableStateOf<EditorSource?>(null) }
    var selectId by remember { mutableStateOf<Long?>(null) } // select a just-saved sound

    val pickFile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) editor = EditorSource(uri, repo.displayTitle(uri), isCopy = false)
    }
    val trash = rememberLauncherForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult(),
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            selected = null
            reload++
        }
    }
    val addSound = {
        player.stop()
        pickFile.launch(arrayOf("audio/*", "video/*"))
    }

    LaunchedEffect(selectOnLoad) {
        if (selectOnLoad != null) {
            selectId = selectOnLoad
            reload++
            onSelectedOnLoad()
        }
    }
    LaunchedEffect(type, reload) {
        val (list, def) = withContext(Dispatchers.IO) { repo.list(type) to repo.currentDefault(type) }
        sounds = list
        current = def
        val wanted = selectId ?: selected?.id
        selected = wanted?.let { id -> list.firstOrNull { it.id == id } }
        selectId = null
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
    val grantAccess = { openWriteSettings(context) }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val twoPane = maxWidth >= TwoPaneWidth
        val list = @Composable { modifier: Modifier ->
            Box(modifier) {
                SoundList(type, sounds, current, selected?.id, player, Modifier.fillMaxSize()) {
                    selected = it
                }
                if (canSave) {
                    ExtendedFloatingActionButton(
                        onClick = addSound,
                        icon = { Icon(Icons.Rounded.Add, contentDescription = null) },
                        text = { Text("Add sound") },
                        modifier = Modifier.align(Alignment.BottomEnd).padding(20.dp),
                    )
                }
            }
        }
        val detail = @Composable { sound: Sound, onBack: (() -> Unit)? ->
            SoundDetail(
                sound, type, isDefault = current?.mediaId == sound.id, canChange = canChange,
                player = player, onBack = onBack, onSetDefault = setDefault,
                onGrantAccess = grantAccess,
                onEdit = if (canSave) {
                    {
                        player.stop()
                        editor = EditorSource(sound.uri, sound.title, isCopy = true)
                    }
                } else {
                    null
                },
                onDelete = if (canTrash) {
                    {
                        player.stop()
                        runCatching { repo.trashRequest(sound) }
                            .onSuccess { trash.launch(IntentSenderRequest.Builder(it).build()) }
                            .onFailure { message = "Couldn't delete it: ${it.message}" }
                    }
                } else {
                    null
                },
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

    editor?.let { src ->
        if (canSave) {
            SoundEditor(
                source = src,
                initialType = type,
                onDismiss = { editor = null },
                onSaved = { savedType, id, title, madeDefault ->
                    editor = null
                    if (savedType == type) selectId = id
                    reload++
                    message = savedMessage(savedType, title, madeDefault)
                },
            )
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
        contentPadding = PaddingValues(start = 16.dp, top = 16.dp, end = 16.dp, bottom = 96.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (current != null) {
            item(key = "current") { CurrentCard(type, current, currentSound, player) }
        }
        if (sounds.isEmpty()) {
            item(key = "empty") {
                EmptyState(
                    "No sounds in this folder yet. Tap Add sound, or send some from the " +
                        "desktop app.",
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
    onEdit: (() -> Unit)?,
    onDelete: (() -> Unit)?,
) {
    var confirm by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
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
                if (onEdit != null) {
                    OutlinedButton(onClick = onEdit, modifier = Modifier.widthIn(min = 200.dp)) {
                        Icon(Icons.Rounded.ContentCut, contentDescription = null)
                        Text("  Edit a copy")
                    }
                }
                if (onDelete != null) {
                    TextButton(
                        onClick = { if (isDefault) confirmDelete = true else onDelete() },
                        colors = ButtonDefaults.textButtonColors(
                            contentColor = MaterialTheme.colorScheme.error,
                        ),
                    ) {
                        Icon(Icons.Rounded.Delete, contentDescription = null)
                        Text("  Delete")
                    }
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
    if (confirmDelete && onDelete != null) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Delete your ${type.label}?") },
            text = {
                Text(
                    "“${sound.title}” is your ${type.label} right now. If you delete it, the " +
                        "phone goes back to its built-in sound.",
                )
            },
            confirmButton = {
                TextButton(onClick = { confirmDelete = false; onDelete() }) { Text("Continue") }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancel") } },
        )
    }
    if (explainAccess) {
        WriteSettingsDialog(type, onOpen = onGrantAccess) { explainAccess = false }
    }
}

/** Opens the "Modify system settings" page for this app. */
fun openWriteSettings(context: Context) {
    context.startActivity(
        Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS).setData("package:${context.packageName}".toUri()),
    )
}

/** Explains the one-time "Modify system settings" access before sending the user there. */
@Composable
fun WriteSettingsDialog(type: SoundType, onOpen: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("One-time permission") },
        text = {
            Text(
                "Android asks you to allow “Modify system settings” before an app " +
                    "can change your ${type.label}. Sound Manager only uses it for your " +
                    "ringtone, notification and alarm sounds.",
            )
        },
        confirmButton = {
            TextButton(onClick = { onDismiss(); onOpen() }) { Text("Open settings") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Not now") } },
    )
}

/** What to tell the user after the editor saved a sound (and maybe made it a default). */
fun savedMessage(type: SoundType, title: String, madeDefault: Boolean?): String = when (madeDefault) {
    true -> "Saved “$title” to ${type.folder} and made it your ${type.label}."
    false -> "Saved “$title” to ${type.folder}, but couldn't make it your ${type.label}. " +
        "Open the sound and use Set as ${type.label}."
    null -> "Saved “$title” to ${type.folder}."
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
