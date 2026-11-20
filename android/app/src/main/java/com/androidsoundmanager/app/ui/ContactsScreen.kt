package com.androidsoundmanager.app.ui

import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
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
            Column(modifier) {
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text("Search contacts") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(12.dp),
                )
                if (undo != null) {
                    TextButton(onClick = undoLast, modifier = Modifier.padding(horizontal = 8.dp)) {
                        Text("Undo last change")
                    }
                }
                LazyColumn(Modifier.fillMaxSize()) {
                    items(filtered, key = { it.id }) { c ->
                        ListItem(
                            headlineContent = { Text(c.name) },
                            supportingContent = c.ringtone?.let { uri ->
                                { Text(byUri[uri]?.title ?: "Custom ringtone") }
                            },
                            trailingContent = {
                                if (c.ringtone != null) Icon(Icons.Filled.MusicNote, "Has a custom ringtone")
                            },
                            colors = if (c.id == selected?.id) {
                                ListItemDefaults.colors(
                                    containerColor = MaterialTheme.colorScheme.secondaryContainer,
                                )
                            } else {
                                ListItemDefaults.colors()
                            },
                            modifier = Modifier.clickable { selected = c },
                        )
                        HorizontalDivider()
                    }
                }
            }
        }
        val detail = @Composable { c: Contact, modifier: Modifier, onBack: (() -> Unit)? ->
            ContactDetail(c, ringtones, byUri, player, modifier, onBack, apply) {
                openConversationSettings(context) { message = it }
            }
        }
        if (twoPane) {
            Row(Modifier.fillMaxSize()) {
                list(Modifier.weight(1f))
                VerticalDivider()
                Box(Modifier.weight(1f)) {
                    selected?.let { detail(it, Modifier.fillMaxSize(), null) }
                        ?: EmptyDetail("Pick a contact to give them their own ringtone.")
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
private fun ContactDetail(
    contact: Contact,
    ringtones: List<Sound>,
    byUri: Map<String, Sound>,
    player: PreviewPlayer,
    modifier: Modifier,
    onBack: (() -> Unit)?,
    onApply: (Contact, Sound?) -> Unit,
    onMessageSound: () -> Unit,
) {
    // null = phone's default ringtone
    var choice by remember(contact.id) { mutableStateOf(contact.ringtone?.let { byUri[it] }) }
    var confirm by remember { mutableStateOf(false) }
    val currentLabel = contact.ringtone?.let { byUri[it]?.title ?: "Custom ringtone" }
        ?: "Phone default"

    Column(modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (onBack != null) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
        }
        Text(contact.name, style = MaterialTheme.typography.headlineSmall)
        Text("Ringtone now: $currentLabel", style = MaterialTheme.typography.bodyMedium)

        LazyColumn(Modifier.weight(1f, fill = false).heightIn(max = 480.dp)) {
            item { ChoiceRow("Phone default", choice == null, onClick = { choice = null }) }
            items(ringtones, key = { it.id }) { s ->
                ChoiceRow(
                    s.title,
                    choice?.id == s.id,
                    onClick = { choice = s; player.toggle(s.uri) },
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = { confirm = true },
                enabled = choice?.uri?.toString() != contact.ringtone,
            ) { Text("Apply…") }
            OutlinedButton(onClick = { player.stop() }) { Text("Stop preview") }
        }
        HorizontalDivider(Modifier.padding(vertical = 8.dp))
        Text("Message sound", style = MaterialTheme.typography.titleMedium)
        Text(
            "Android keeps each conversation's sound in the messaging app's settings. This opens " +
                "your conversations list: tap ${contact.name}, then Sound.",
            style = MaterialTheme.typography.bodySmall,
        )
        OutlinedButton(onClick = onMessageSound) { Text("Open conversation settings") }
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
        Modifier.fillMaxWidth().selectable(selected = selected, onClick = onClick).padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = null)
        Text(label, Modifier.padding(start = 8.dp))
    }
}

private fun openConversationSettings(context: android.content.Context, onError: (String) -> Unit) {
    val action = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        Settings.ACTION_CONVERSATION_SETTINGS
    } else {
        Settings.ACTION_SOUND_SETTINGS
    }
    try {
        context.startActivity(Intent(action))
    } catch (_: ActivityNotFoundException) {
        onError("This phone doesn't have a conversation settings screen.")
    }
}
