package com.androidsoundmanager.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AudioEditTest {

    @Test
    fun untouchedOnlyWhenNothingChanges() {
        assertTrue(Edit(0, 5000).isUntouched(5000))
        assertFalse(Edit(100, 5000).isUntouched(5000))
        assertFalse(Edit(0, 5000, fadeInMs = 500).isUntouched(5000))
        assertFalse(Edit(0, 5000, gainDb = 3f).isUntouched(5000))
        assertFalse(Edit(0, 5000, normalize = true).isUntouched(5000))
    }

    @Test
    fun clampedKeepsAValidSelection() {
        val e = Edit(-50, 99_999, fadeInMs = 9_999, fadeOutMs = -3, gainDb = 99f).clamped(2_000)
        assertEquals(0L, e.startMs)
        assertEquals(2_000L, e.endMs)
        assertEquals(2_000L, e.fadeInMs)
        assertEquals(0L, e.fadeOutMs)
        assertEquals(24f, e.gainDb)
        val tiny = Edit(1_990, 1_995).clamped(2_000)
        assertTrue(tiny.lengthMs >= MIN_SELECTION_MS)
        assertTrue(tiny.endMs <= 2_000)
    }

    @Test
    fun gainFromDecibelsOrNormalize() {
        assertEquals(1f, Edit(0, 1).linearGain(0.5f), 1e-6f)
        assertEquals(2f, Edit(0, 1, gainDb = 6.0206f).linearGain(0.5f), 1e-3f)
        assertEquals(NORMALIZE_TARGET / 0.25f, Edit(0, 1, normalize = true).linearGain(0.25f), 1e-6f)
        assertEquals(1f, Edit(0, 1, normalize = true).linearGain(0f), 1e-6f) // silence stays silent
    }

    @Test
    fun envelopeRampsInAndOut() {
        val len = 1000L
        assertEquals(0f, envelope(0, len, 100, 100, 1f), 1e-6f)
        assertEquals(0.5f, envelope(50, len, 100, 100, 1f), 1e-6f)
        assertEquals(2f, envelope(500, len, 100, 100, 2f), 1e-6f)
        assertEquals(0f, envelope(len - 1, len, 100, 100, 1f), 1e-6f)
        assertEquals(0.5f, envelope(len - 51, len, 100, 100, 1f), 1e-6f)
        assertEquals(1f, envelope(0, len, 0, 0, 1f), 1e-6f)
    }

    @Test
    fun analysisPeaksAndBars() {
        val a = Analysis(50, floatArrayOf(0.1f, 0.9f, 0.2f, 0.4f, 0.3f))
        assertEquals(0.9f, a.peakBetween(0, 50), 1e-6f)
        assertEquals(0.4f, a.peakBetween(20, 40), 1e-6f)
        val bars = a.bars(2)
        assertEquals(0.9f, bars[0], 1e-6f)
        assertEquals(0.4f, bars[1], 1e-6f)
        assertEquals(10, a.bars(10).size)
    }

    @Test
    fun peakCollectorWindows() {
        val c = PeakCollector(sampleRate = 1000) // 10 frames per 10 ms window
        repeat(25) { c.add(if (it == 12) -0.75f else 0.1f) }
        val peaks = c.finish()
        assertEquals(3, peaks.size)
        assertEquals(0.75f, peaks[1], 1e-6f)
    }

    @Test
    fun safeFileNames() {
        assertEquals("My tone", safeFileName("  My   tone "))
        assertEquals("a b c", safeFileName("a/b\\c"))
        assertEquals("hidden", safeFileName("...hidden"))
        assertEquals("Sound", safeFileName("???"))
        assertEquals(80, safeFileName("x".repeat(200)).length)
    }
}
