package com.androidsoundmanager.app.ui

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.annotation.RequiresApi
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Remove
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RangeSlider
import androidx.compose.material3.RangeSliderState
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.androidsoundmanager.app.data.Analysis
import com.androidsoundmanager.app.data.AudioEngine
import com.androidsoundmanager.app.data.Edit
import com.androidsoundmanager.app.data.EditError
import com.androidsoundmanager.app.data.MIN_SELECTION_MS
import com.androidsoundmanager.app.data.SoundRepository
import com.androidsoundmanager.app.data.SoundType
import com.androidsoundmanager.app.data.envelope
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.roundToLong

/** A file to edit: one the user picked (a new sound) or an existing sound (saved as a copy). */
data class EditorSource(val uri: Uri, val title: String, val isCopy: Boolean)

private const val NUDGE_MS = 100L
private const val MAX_FADE_MS = 5_000f
private const val WAVE_BARS = 360

/**
 * Full-screen editor: trim, fade in/out, volume or normalize, then save as a new sound into
 * Ringtones, Notifications or Alarms. The original file is never changed.
 */
@RequiresApi(Build.VERSION_CODES.Q)
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SoundEditor(
    source: EditorSource,
    initialType: SoundType,
    onDismiss: () -> Unit,
    onSaved: (type: SoundType, id: Long, title: String) -> Unit,
) {
    val context = LocalContext.current
    val repo = remember { SoundRepository(context.applicationContext) }
    val scope = rememberCoroutineScope()
    val player = remember { SelectionPlayer(context.applicationContext) }
    DisposableEffect(Unit) { onDispose { player.stop() } }

    var analysis by remember(source) { mutableStateOf<Analysis?>(null) }
    var loadProgress by remember(source) { mutableFloatStateOf(0f) }
    var error by remember(source) { mutableStateOf<String?>(null) }
    var title by rememberSaveable(source) {
        mutableStateOf(if (source.isCopy) "${source.title} (edit)" else source.title)
    }
    var startMs by remember(source) { mutableLongStateOf(0L) }
    var endMs by remember(source) { mutableLongStateOf(0L) }
    var fadeInMs by remember(source) { mutableLongStateOf(0L) }
    var fadeOutMs by remember(source) { mutableLongStateOf(0L) }
    var gainDb by remember(source) { mutableFloatStateOf(0f) }
    var normalize by remember(source) { mutableStateOf(false) }
    var type by remember(source) { mutableStateOf(initialType) }
    var saving by remember { mutableStateOf(false) }
    var saveProgress by remember { mutableFloatStateOf(0f) }
    var confirmClose by remember { mutableStateOf(false) }

    LaunchedEffect(source) {
        runCatching { AudioEngine.analyze(context, source.uri) { loadProgress = it } }
            .onSuccess {
                analysis = it
                endMs = it.durationMs
            }
            .onFailure { error = userMessage(it) }
    }

    val a = analysis
    val edit = Edit(startMs, endMs, fadeInMs, fadeOutMs, gainDb, normalize)
    val changed = a != null && !edit.isUntouched(a.durationMs)
    val close: () -> Unit = {
        if (!saving) {
            if (changed) {
                confirmClose = true
            } else {
                onDismiss()
            }
        }
    }

    val save: () -> Unit = save@{
        val an = a ?: return@save
        player.stop()
        saving = true
        saveProgress = 0f
        scope.launch {
            val name = title.trim().ifEmpty { source.title }
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    val plain = repo.audioType(source.uri)
                    if (edit.isUntouched(an.durationMs) && plain != null) {
                        // Nothing changed: keep the original audio exactly (no re-encoding).
                        repo.save(type, name, plain.first, plain.second) { repo.copy(source.uri, it) }
                    } else {
                        val temp = File.createTempFile("edit", ".m4a", context.cacheDir)
                        try {
                            AudioEngine.render(context, source.uri, edit, an, temp) { saveProgress = it }
                            repo.save(type, name, "audio/mp4", "m4a") { out ->
                                temp.inputStream().use { it.copyTo(out) }
                            }
                        } finally {
                            temp.delete()
                        }
                    }
                }
            }
            saving = false
            result.onSuccess { id -> onSaved(type, id, name) }
                .onFailure { error = "Couldn't save: ${userMessage(it)}" }
        }
    }

    Dialog(
        onDismissRequest = close,
        properties = DialogProperties(usePlatformDefaultWidth = false, dismissOnClickOutside = false),
    ) {
        BackHandler(onBack = close)
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.surface) {
            Column(Modifier.fillMaxSize()) {
                TopAppBar(
                    navigationIcon = {
                        IconButton(onClick = close, enabled = !saving) {
                            Icon(Icons.Rounded.Close, contentDescription = "Close")
                        }
                    },
                    title = { Text(if (source.isCopy) "Edit a copy" else "New sound") },
                    actions = {
                        Button(
                            onClick = save,
                            enabled = a != null && !saving && edit.lengthMs >= MIN_SELECTION_MS,
                            modifier = Modifier.padding(end = 12.dp),
                        ) { Text("Save") }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.surface,
                    ),
                )
                if (saving) {
                    LinearProgressIndicator(
                        progress = { saveProgress },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
                    when {
                        a != null -> EditorBody(
                            analysis = a,
                            source = source,
                            title = title,
                            onTitle = { title = it },
                            edit = edit,
                            onRange = { s, e ->
                                startMs = s
                                endMs = e
                            },
                            onFadeIn = { fadeInMs = it },
                            onFadeOut = { fadeOutMs = it },
                            onGain = { gainDb = it },
                            onNormalize = { normalize = it },
                            type = type,
                            onType = { type = it },
                            player = player,
                            onPreview = {
                                if (player.active) {
                                    player.stop()
                                } else {
                                    val gain = edit.linearGain(a.peakBetween(startMs, endMs))
                                    player.play(scope, source.uri, edit, gain)
                                }
                            },
                            enabled = !saving,
                        )
                        error == null -> Column(
                            Modifier.padding(32.dp).widthIn(max = 420.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(16.dp),
                        ) {
                            BakeryLogo(96.dp)
                            Text("Reading the sound…", style = MaterialTheme.typography.bodyLarge)
                            LinearProgressIndicator(
                                progress = { loadProgress },
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                }
            }
        }
    }

    error?.let { text ->
        AlertDialog(
            onDismissRequest = { error = null; if (analysis == null) onDismiss() },
            confirmButton = {
                TextButton(onClick = { error = null; if (analysis == null) onDismiss() }) { Text("OK") }
            },
            text = { Text(text) },
        )
    }
    if (confirmClose) {
        AlertDialog(
            onDismissRequest = { confirmClose = false },
            title = { Text("Discard changes?") },
            text = { Text("Your edits haven't been saved.") },
            confirmButton = {
                TextButton(onClick = { confirmClose = false; onDismiss() }) { Text("Discard") }
            },
            dismissButton = { TextButton(onClick = { confirmClose = false }) { Text("Keep editing") } },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EditorBody(
    analysis: Analysis,
    source: EditorSource,
    title: String,
    onTitle: (String) -> Unit,
    edit: Edit,
    onRange: (Long, Long) -> Unit,
    onFadeIn: (Long) -> Unit,
    onFadeOut: (Long) -> Unit,
    onGain: (Float) -> Unit,
    onNormalize: (Boolean) -> Unit,
    type: SoundType,
    onType: (SoundType) -> Unit,
    player: SelectionPlayer,
    onPreview: () -> Unit,
    enabled: Boolean,
) {
    val duration = analysis.durationMs
    val setRange = { s: Long, e: Long ->
        val start = s.coerceIn(0L, duration - MIN_SELECTION_MS)
        onRange(start, e.coerceIn(start + MIN_SELECTION_MS, duration))
    }
    val maxFade = minOf(MAX_FADE_MS, edit.lengthMs.toFloat())

    Column(
        Modifier
            .widthIn(max = 720.dp)
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        OutlinedTextField(
            value = title,
            onValueChange = { onTitle(it.take(80)) },
            label = { Text("Name") },
            singleLine = true,
            enabled = enabled,
            modifier = Modifier.fillMaxWidth(),
        )
        if (!source.isCopy) {
            Text(
                "From: ${source.title}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }

        Section("Trim") {
            Waveform(analysis, edit.startMs, edit.endMs, player.positionMs) { tappedMs ->
                // Tap moves whichever edge is closer.
                if (abs(tappedMs - edit.startMs) <= abs(tappedMs - edit.endMs)) {
                    setRange(tappedMs, edit.endMs)
                } else {
                    setRange(edit.startMs, tappedMs)
                }
            }
            val rangeState = remember(duration) {
                RangeSliderState(edit.startMs.toFloat(), edit.endMs.toFloat(), 0, 0f..duration.toFloat())
            }
            SideEffect {
                rangeState.startValue = edit.startMs.toFloat()
                rangeState.endValue = edit.endMs.toFloat()
            }
            RangeSlider(
                rangeState,
                { r -> setRange(r.start.roundToLong(), r.endInclusive.roundToLong()) },
                enabled = enabled,
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Nudger("Start", edit.startMs, enabled) { setRange(edit.startMs + it, edit.endMs) }
                Nudger("End", edit.endMs, enabled) { setRange(edit.startMs, edit.endMs + it) }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                FilledTonalButton(onClick = onPreview, enabled = enabled) {
                    Icon(
                        if (player.active) Icons.Rounded.Stop else Icons.Rounded.PlayArrow,
                        contentDescription = null,
                    )
                    Text(if (player.active) "  Stop" else "  Preview")
                }
                Text(
                    "   Length ${formatPrecise(edit.lengthMs)} of ${formatPrecise(duration)}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        Section("Fades") {
            LabeledSlider(
                "Fade in", "${"%.1f".format(edit.fadeInMs / 1000f)} s",
                edit.fadeInMs.toFloat().coerceAtMost(maxFade), 0f..maxFade, enabled,
            ) { onFadeIn((it / 100f).roundToLong() * 100) }
            LabeledSlider(
                "Fade out", "${"%.1f".format(edit.fadeOutMs / 1000f)} s",
                edit.fadeOutMs.toFloat().coerceAtMost(maxFade), 0f..maxFade, enabled,
            ) { onFadeOut((it / 100f).roundToLong() * 100) }
        }

        Section("Volume") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Normalize", style = MaterialTheme.typography.bodyLarge)
                    Text(
                        "As loud as it can be without distorting",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Switch(checked = edit.normalize, onCheckedChange = onNormalize, enabled = enabled)
            }
            LabeledSlider(
                "Volume", "%+.0f dB".format(edit.gainDb), edit.gainDb, -12f..12f,
                enabled && !edit.normalize,
            ) { onGain(it.roundToInt().toFloat()) } // whole decibels
        }

        Section("Save to") {
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                SoundType.entries.forEachIndexed { i, t ->
                    SegmentedButton(
                        selected = type == t,
                        onClick = { onType(t) },
                        shape = SegmentedButtonDefaults.itemShape(i, SoundType.entries.size),
                        enabled = enabled,
                        label = { Text(t.folder, maxLines = 1) },
                    )
                }
            }
            Text(
                "Saved as a new file. The original isn't changed.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Card(
        shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary)
            content()
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LabeledSlider(
    label: String,
    valueText: String,
    value: Float,
    range: ClosedFloatingPointRange<Float>,
    enabled: Boolean,
    onChange: (Float) -> Unit,
) {
    Column {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(label, style = MaterialTheme.typography.bodyLarge)
            Text(valueText, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        val state = remember(range) { SliderState(value, 0, range) }
        SideEffect { state.value = value }
        Slider(state, onChange, enabled = enabled)
    }
}

/** "Start 0:01.2" with − / + buttons that move it by a tenth of a second. */
@Composable
private fun Nudger(label: String, valueMs: Long, enabled: Boolean, onNudge: (Long) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = { onNudge(-NUDGE_MS) }, enabled = enabled) {
            Icon(Icons.Rounded.Remove, contentDescription = "$label earlier")
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(formatPrecise(valueMs), style = MaterialTheme.typography.titleMedium)
        }
        IconButton(onClick = { onNudge(NUDGE_MS) }, enabled = enabled) {
            Icon(Icons.Rounded.Add, contentDescription = "$label later")
        }
    }
}

@Composable
private fun Waveform(
    analysis: Analysis,
    startMs: Long,
    endMs: Long,
    playheadMs: Long?,
    onTap: (Long) -> Unit,
) {
    val bars = remember(analysis) { analysis.bars(WAVE_BARS) }
    val tap by rememberUpdatedState(onTap)
    val scale = remember(bars) { 1f / maxOf(bars.maxOrNull() ?: 0f, 0.05f) }
    val accent = MaterialTheme.colorScheme.primary
    val dim = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.35f)
    val band = MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
    val playColor = MaterialTheme.colorScheme.tertiary
    val duration = analysis.durationMs.coerceAtLeast(1)
    Canvas(
        Modifier
            .fillMaxWidth()
            .height(120.dp)
            .clip(MaterialTheme.shapes.medium)
            .background(MaterialTheme.colorScheme.surfaceContainerHighest)
            .pointerInput(duration) {
                detectTapGestures { pos -> tap((pos.x / size.width * duration).roundToLong()) }
            },
    ) {
        val w = size.width
        val h = size.height
        val x0 = startMs.toFloat() / duration * w
        val x1 = endMs.toFloat() / duration * w
        drawRect(band, topLeft = Offset(x0, 0f), size = Size(x1 - x0, h))
        val barWidth = w / bars.size
        bars.forEachIndexed { i, peak ->
            val x = i * barWidth + barWidth / 2
            val half = maxOf(1f, peak * scale * (h / 2 - 6f))
            drawLine(
                if (x in x0..x1) accent else dim,
                Offset(x, h / 2 - half),
                Offset(x, h / 2 + half),
                strokeWidth = maxOf(1f, barWidth * 0.6f),
            )
        }
        for (x in listOf(x0, x1)) drawLine(accent, Offset(x, 0f), Offset(x, h), strokeWidth = 3f)
        playheadMs?.let {
            val x = it.toFloat() / duration * w
            drawLine(playColor, Offset(x, 0f), Offset(x, h), strokeWidth = 3f)
        }
    }
}

/** Plays just the selection, with the fades applied, for previewing an edit. */
class SelectionPlayer(private val context: Context) {
    private var player: MediaPlayer? = null
    private var job: Job? = null
    var active by mutableStateOf(false)
        private set
    var positionMs by mutableStateOf<Long?>(null)
        private set

    fun play(scope: CoroutineScope, uri: Uri, edit: Edit, gain: Float) {
        stop()
        val p = runCatching {
            MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).build())
                setDataSource(context, uri)
                prepare()
            }
        }.getOrNull() ?: return
        player = p
        active = true
        val volumeAt = { ms: Long ->
            envelope(ms - edit.startMs, edit.lengthMs, edit.fadeInMs, edit.fadeOutMs, gain).coerceIn(0f, 1f)
        }
        p.setVolume(volumeAt(edit.startMs), volumeAt(edit.startMs))
        p.setOnSeekCompleteListener { it.start() }
        p.seekTo(edit.startMs, MediaPlayer.SEEK_CLOSEST)
        job = scope.launch {
            var waited = 0
            while (isActive && !p.isPlaying && waited++ < 100) delay(20) // wait for the seek
            while (isActive && p.isPlaying) {
                val pos = p.currentPosition.toLong()
                if (pos >= edit.endMs) break
                val v = volumeAt(pos)
                p.setVolume(v, v)
                positionMs = pos
                delay(25)
            }
            release()
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        release()
    }

    private fun release() {
        player?.run {
            runCatching { stop() }
            release()
        }
        player = null
        active = false
        positionMs = null
    }
}

private fun userMessage(t: Throwable): String = when (t) {
    is EditError -> t.message ?: "Something went wrong."
    is SecurityException -> "Sound Manager isn't allowed to read that file."
    else -> t.message ?: t.javaClass.simpleName
}

/** 83_400 ms -> "1:23.4". */
fun formatPrecise(ms: Long): String {
    val tenths = (ms + 50) / 100
    return "%d:%02d.%d".format(tenths / 600, tenths / 10 % 60, tenths % 10)
}
