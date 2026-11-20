package com.androidsoundmanager.app.data

import kotlin.math.abs
import kotlin.math.pow
import kotlin.math.roundToLong

/** Longest file the phone editor accepts (decoding is done in memory-light passes). */
const val MAX_EDIT_DURATION_MS = 20 * 60 * 1000L

/** Shortest selection that can be saved. */
const val MIN_SELECTION_MS = 100L

/** Loudest point after "Normalize": -1 dBFS, leaving a little headroom. */
const val NORMALIZE_TARGET = 0.891f

/** What to do to the source: keep [startMs]..[endMs], fade the edges, change the volume. */
data class Edit(
    val startMs: Long,
    val endMs: Long,
    val fadeInMs: Long = 0,
    val fadeOutMs: Long = 0,
    val gainDb: Float = 0f,
    val normalize: Boolean = false,
) {
    val lengthMs: Long get() = endMs - startMs

    /** True when saving would produce the original audio, so the file can be copied as-is. */
    fun isUntouched(durationMs: Long): Boolean =
        startMs <= 0 && endMs >= durationMs && fadeInMs == 0L && fadeOutMs == 0L &&
            !normalize && gainDb == 0f

    /** Clamp everything into a valid edit of a [durationMs]-long source. */
    fun clamped(durationMs: Long): Edit {
        val start = startMs.coerceIn(0, (durationMs - MIN_SELECTION_MS).coerceAtLeast(0))
        val end = endMs.coerceIn(start + MIN_SELECTION_MS, durationMs.coerceAtLeast(start + MIN_SELECTION_MS))
        val length = end - start
        return copy(
            startMs = start,
            endMs = end,
            fadeInMs = fadeInMs.coerceIn(0, length),
            fadeOutMs = fadeOutMs.coerceIn(0, length),
            gainDb = gainDb.coerceIn(-24f, 24f),
        )
    }

    /** Linear gain for the whole selection, given the loudest sample in it (0..1). */
    fun linearGain(selectionPeak: Float): Float =
        if (normalize) {
            if (selectionPeak > 1e-4f) NORMALIZE_TARGET / selectionPeak else 1f
        } else {
            10f.pow(gainDb / 20f)
        }
}

/** Volume multiplier for one frame of the selection: fades and gain, as linear ramps. */
fun envelope(frame: Long, lengthFrames: Long, fadeInFrames: Long, fadeOutFrames: Long, gain: Float): Float {
    var factor = gain
    if (fadeInFrames > 0 && frame < fadeInFrames) {
        factor *= frame.toFloat() / fadeInFrames
    }
    val fromEnd = lengthFrames - 1 - frame
    if (fadeOutFrames > 0 && fromEnd < fadeOutFrames) {
        factor *= fromEnd.coerceAtLeast(0).toFloat() / fadeOutFrames
    }
    return factor
}

fun msToFrames(ms: Long, sampleRate: Int): Long = (ms * sampleRate / 1000.0).roundToLong()

/**
 * Loudness overview of a sound: [windowPeaks] holds the loudest sample (0..1) of each
 * [WINDOW_MS]-long slice, which is enough to draw a waveform and to normalize a selection.
 */
class Analysis(val durationMs: Long, val windowPeaks: FloatArray) {

    /** Loudest sample between [startMs] and [endMs]. */
    fun peakBetween(startMs: Long, endMs: Long): Float {
        if (windowPeaks.isEmpty()) return 0f
        val from = (startMs / WINDOW_MS).toInt().coerceIn(0, windowPeaks.size - 1)
        val to = ((endMs + WINDOW_MS - 1) / WINDOW_MS).toInt().coerceIn(from + 1, windowPeaks.size)
        var peak = 0f
        for (i in from until to) peak = maxOf(peak, windowPeaks[i])
        return peak
    }

    /** [count] bars for drawing, each the loudest point of its slice. */
    fun bars(count: Int): FloatArray {
        if (windowPeaks.isEmpty() || count <= 0) return FloatArray(count)
        val out = FloatArray(count)
        for (i in 0 until count) {
            val from = (i.toLong() * windowPeaks.size / count).toInt()
            val to = maxOf(from + 1, ((i + 1).toLong() * windowPeaks.size / count).toInt())
            var peak = 0f
            for (j in from until minOf(to, windowPeaks.size)) peak = maxOf(peak, windowPeaks[j])
            out[i] = peak
        }
        return out
    }

    companion object {
        const val WINDOW_MS = 10L
    }
}

/** Collects per-window peaks while samples stream through. */
class PeakCollector(sampleRate: Int) {
    private val framesPerWindow = maxOf(1, (sampleRate * Analysis.WINDOW_MS / 1000).toInt())
    private var peaks = FloatArray(1024)
    private var count = 0
    private var framesInWindow = 0
    private var current = 0f

    fun add(frameMax: Float) {
        current = maxOf(current, abs(frameMax))
        if (++framesInWindow == framesPerWindow) flush()
    }

    private fun flush() {
        if (count == peaks.size) peaks = peaks.copyOf(peaks.size * 2)
        peaks[count++] = current.coerceAtMost(1f)
        current = 0f
        framesInWindow = 0
    }

    fun finish(): FloatArray {
        if (framesInWindow > 0) flush()
        return peaks.copyOf(count)
    }
}

/** A file name Android's folders will accept, from whatever the user typed. */
fun safeFileName(title: String, fallback: String = "Sound"): String {
    val cleaned = title
        .replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), " ")
        .replace(Regex("\\s+"), " ")
        .trim()
        .trimStart('.')
        .take(80)
        .trim()
    return cleaned.ifEmpty { fallback }
}
