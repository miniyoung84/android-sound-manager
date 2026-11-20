package com.androidsoundmanager.app.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.os.Build
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
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
import com.androidsoundmanager.app.data.Contact
import com.androidsoundmanager.app.data.ContactRepository
import com.androidsoundmanager.app.data.Sound
import com.androidsoundmanager.app.data.SoundRepository
import com.androidsoundmanager.app.data.SoundType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private data class Undo(val contactId: Long, val previous: String?, val name: String)

@Composable
fun ContactsScreen() {
    val context = LocalContext.current
    val contactsRepo = remember { ContactRepository(context.applicationContext) }
    val soundsRepo = remember { SoundRepository(context.applicationContext) }
    val player = rememberPreviewPlayer()
    val scope = rememberCoroutineScope()

    var contacts by remember { mutableStateOf<List<Contact>>(emptyList()) }
    var ringtones by remember { mutableStateOf<List<Sound>>(emptyList()) }
    var query by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf<Contact?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var undo by remember { mutableStateOf<Undo?>(null) }
    var message by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(reload) {
        val (c, r) = withContext(Dispatchers.IO) {
            contactsRepo.list() to soundsRepo.list(SoundType.RINGTONE)
        }
        contacts = c
        ringtones = r
        selected = selected?.let { s -> c.firstOrNull { it.id == s.id } }
    }

    val apply: (Contact, Sound?) -> Unit = { contact, sound ->
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { contactsRepo.setRingtone(contact, sound) }
            }
            result.onSuccess { previous -> undo = Undo(contact.id, previous, contact.name) }
            message = result.fold(
                onSuccess = { "Ringtone for ${contact.name}: ${sound?.title ?: "phone default"}." },
                onFailure = { "Couldn't change the ringtone: ${it.message}" },
            )
            reload++
        }
    }
    val undoLast: () -> Unit = {
        undo?.let { u ->
            scope.launch {
                withContext(Dispatchers.IO) {
                    runCatching { contactsRepo.restoreRingtone(u.contactId, u.previous) }
                }
                message = "Undid the ringtone change for ${u.name}."
                undo = null
                reload++
            }
        }
    }

    val filtered = contacts.filter { query.isBlank() || it.name.contains(query.trim(), ignoreCase = true) }
    val byUri = ringtones.associateBy { it.uri.toString() }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val twoPane = maxWidth >= TwoPaneWidth
        val list = @Composable { modifier: Modifier ->
            LazyColumn(
                modifier,
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item(key = "search") {
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        placeholder = { Text("Search contacts") },
                        leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null) },
                        singleLine = true,
                        shape = MaterialTheme.shapes.large,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                if (undo != null) {
                    item(key = "undo") {
                        TextButton(onClick = undoLast) { Text("Undo last change") }
                    }
                }
                items(filtered, key = { it.id }) { c ->
                    RowCard(
                        selected = c.id == selected?.id,
                        onClick = { selected = c },
                        leading = { InitialAvatar(c.name) },
                        title = c.name,
                        subtitle = c.ringtone?.let { "♪ " + (byUri[it]?.title ?: "Custom ringtone") },
                        trailing = if (c.ringtone != null) ({ Pill("Custom") }) else null,
                    )
                }
            }
        }
        val detail = @Composable { c: Contact, onBack: (() -> Unit)? ->
            ContactDetail(c, ringtones, byUri, player, onBack, apply) {
                openConversationSettings(context) { message = it }
            }
        }
        if (twoPane) {
            Row(Modifier.fillMaxSize()) {
                list(Modifier.weight(1f))
                Box(Modifier.weight(1f).fillMaxSize().padding(end = 16.dp, bottom = 16.dp)) {
                    selected?.let { detail(it, null) }
                        ?: EmptyState("Pick a contact to give them their own ringtone.")
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
private fun ContactDetail(
    contact: Contact,
    ringtones: List<Sound>,
    byUri: Map<String, Sound>,
    player: PreviewPlayer,
    onBack: (() -> Unit)?,
    onApply: (Contact, Sound?) -> Unit,
    onMessageSound: () -> Unit,
) {
    // null = phone's default ringtone
    var choice by remember(contact.id) { mutableStateOf(contact.ringtone?.let { byUri[it] }) }
    var confirm by remember { mutableStateOf(false) }
    val currentLabel = contact.ringtone?.let { byUri[it]?.title ?: "Custom ringtone" }
        ?: "Phone default"

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (onBack != null) {
            item(key = "back") {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "Back")
                }
            }
        }
        item(key = "header") {
            Card(
                shape = MaterialTheme.shapes.large,
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                ),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    Modifier.padding(20.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    InitialAvatar(contact.name)
                    Column(Modifier.weight(1f)) {
                        Text(
                            contact.name,
                            style = MaterialTheme.typography.headlineSmall,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            "Ringtone: $currentLabel",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        item(key = "choose") {
            Text("Choose a ringtone", style = MaterialTheme.typography.titleMedium)
        }
        item(key = "choices") {
            Card(
                shape = MaterialTheme.shapes.large,
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceContainer,
                ),
            ) {
                Column(Modifier.padding(vertical = 6.dp)) {
                    ChoiceRow("Phone default", choice == null) { choice = null; player.stop() }
                    ringtones.forEach { s ->
                        HorizontalDivider(
                            Modifier.padding(horizontal = 16.dp),
                            color = MaterialTheme.colorScheme.outlineVariant,
                        )
                        ChoiceRow(s.title, choice?.id == s.id) {
                            choice = s
                            player.toggle(s.uri)
                        }
                    }
                }
            }
        }
        item(key = "actions") {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = { confirm = true },
                    enabled = choice?.uri?.toString() != contact.ringtone,
                ) { Text("Apply…") }
                OutlinedButton(onClick = { player.stop() }) { Text("Stop preview") }
            }
        }
        item(key = "message") {
            Card(
                shape = MaterialTheme.shapes.large,
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.secondaryContainer,
                ),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Message sound", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Android keeps each conversation's sound in your messaging app's " +
                            "settings. This opens your conversations: tap ${contact.name}, then Sound.",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    OutlinedButton(onClick = onMessageSound) { Text("Open conversation settings") }
                }
            }
        }
    }

    if (confirm) {
        AlertDialog(
            onDismissRequest = { confirm = false },
            title = { Text("Change ringtone?") },
            text = {
                Text("${contact.name}: $currentLabel → ${choice?.title ?: "Phone default"}")
            },
            confirmButton = {
                TextButton(onClick = { confirm = false; onApply(contact, choice) }) { Text("Change") }
            },
            dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun ChoiceRow(label: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .selectable(selected = selected, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = null)
        Text(
            label,
            Modifier.padding(start = 12.dp),
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/** Settings > Notifications > Conversations. Not a public SDK constant, but present since 11. */
private const val ACTION_CONVERSATION_SETTINGS = "android.settings.CONVERSATION_SETTINGS"

private fun openConversationSettings(context: Context, onError: (String) -> Unit) {
    val actions = buildList {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) add(ACTION_CONVERSATION_SETTINGS)
        add(Settings.ACTION_SOUND_SETTINGS)
    }
    for (action in actions) {
        try {
            context.startActivity(Intent(action))
            return
        } catch (_: ActivityNotFoundException) {
            // try the next, more general screen
        }
    }
    onError("This phone doesn't have a conversation settings screen.")
}
