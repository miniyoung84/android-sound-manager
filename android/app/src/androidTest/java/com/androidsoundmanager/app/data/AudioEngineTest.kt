package com.androidsoundmanager.app.data

import android.content.ContentUris
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.sin

/**
 * Runs the real decoders and encoder on a device. Uses generated tones in the app's cache;
 * the one save test removes its file again.
 */
@RunWith(AndroidJUnit4::class)
class AudioEngineTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val files = mutableListOf<File>()

    @After
    fun cleanUp() {
        files.forEach { it.delete() }
    }

    private fun temp(name: String) = File(context.cacheDir, name).also { files += it }

    /** A 440 Hz tone as a 16-bit PCM WAV file. */
    private fun toneWav(seconds: Double, rate: Int = 44_100, channels: Int = 2, amplitude: Double = 0.5): Uri {
        val frames = (seconds * rate).toInt()
        val data = ByteBuffer.allocate(frames * channels * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (f in 0 until frames) {
            val v = (amplitude * sin(2 * PI * 440 * f / rate) * 32767).toInt().toShort()
            repeat(channels) { data.putShort(v) }
        }
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray()); putInt(36 + data.capacity()); put("WAVE".toByteArray())
            put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(channels.toShort())
            putInt(rate); putInt(rate * channels * 2); putShort((channels * 2).toShort()); putShort(16)
            put("data".toByteArray()); putInt(data.capacity())
        }
        val file = temp("tone-$seconds-$channels.wav")
        file.outputStream().use {
            it.write(header.array())
            it.write(data.array())
        }
        return Uri.fromFile(file)
    }

    @Test
    fun analyzeMeasuresLengthAndLoudness() = runBlocking {
        val a = AudioEngine.analyze(context, toneWav(3.0))
        assertEquals(3000.0, a.durationMs.toDouble(), 20.0)
        assertEquals(0.5f, a.peakBetween(0, 3000), 0.02f)
    }

    @Test
    fun renderTrimsFadesAndNormalizes() = runBlocking {
        val uri = toneWav(3.0)
        val a = AudioEngine.analyze(context, uri)
        val out = temp("out.m4a")
        val edit = Edit(500, 2500, fadeInMs = 300, fadeOutMs = 300, normalize = true)
        AudioEngine.render(context, uri, edit, a, out)
        val b = AudioEngine.analyze(context, Uri.fromFile(out))
        assertEquals(2000.0, b.durationMs.toDouble(), 80.0) // AAC adds a few ms of padding
        assertEquals(NORMALIZE_TARGET, b.peakBetween(800, 1500), 0.06f)
        assertTrue("fades in", b.windowPeaks.take(3).max() < 0.15f)
        assertTrue("fades out", b.windowPeaks.takeLast(4).max() < 0.2f)
    }

    @Test
    fun monoAndQuietGain() = runBlocking {
        val uri = toneWav(1.0, rate = 22_050, channels = 1)
        val a = AudioEngine.analyze(context, uri)
        val out = temp("mono.m4a")
        AudioEngine.render(context, uri, Edit(0, 1000, gainDb = -6.0206f), a, out)
        val b = AudioEngine.analyze(context, Uri.fromFile(out))
        assertEquals(0.25f, b.peakBetween(200, 800), 0.03f)
    }

    @Test
    fun cancellingStopsAndRemovesThePartialFile() = runBlocking {
        val uri = toneWav(60.0)
        val a = AudioEngine.analyze(context, uri)
        val out = temp("cancelled.m4a")
        val job = launch(Dispatchers.Default) { AudioEngine.render(context, uri, Edit(0, 60_000, gainDb = 1f), a, out) }
        delay(100)
        job.cancelAndJoin()
        assertFalse(out.exists())
    }

    @Test
    fun badFilesGiveAFriendlyError() = runBlocking {
        val junk = temp("junk.mp3").apply { writeText("not audio") }
        try {
            AudioEngine.analyze(context, Uri.fromFile(junk))
            fail("expected an error")
        } catch (e: EditError) {
            assertTrue(e.message!!.isNotBlank())
        }
    }

    @Test
    fun saveIsAllOrNothing() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return
        val repo = SoundRepository(context)
        val title = "sound-manager-selftest"
        try {
            repo.save(SoundType.NOTIFICATION, title, "audio/mp4", "m4a") { throw IOException("cable pulled") }
            fail("expected the write error")
        } catch (_: IOException) {
        }
        assertEquals("failed save leaves nothing behind", 0, countOwn(title))

        val id = repo.save(SoundType.NOTIFICATION, title, "audio/mp4", "m4a") { it.write(ByteArray(64)) }
        val uri = ContentUris.withAppendedId(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, id)
        try {
            assertEquals(1, countOwn(title))
            context.contentResolver.query(uri, arrayOf(MediaStore.Audio.Media.IS_PENDING), null, null, null)!!.use {
                assertTrue(it.moveToFirst())
                assertEquals("finished saves are visible", 0, it.getInt(0))
            }
        } finally {
            context.contentResolver.delete(uri, null, null)
        }
        assertEquals(0, countOwn(title))
    }

    /** Rows (pending or not) whose file name starts with [prefix]. */
    private fun countOwn(prefix: String): Int {
        val args = Bundle().apply {
            putString(android.content.ContentResolver.QUERY_ARG_SQL_SELECTION, "${MediaStore.Audio.Media.DISPLAY_NAME} LIKE ?")
            putStringArray(android.content.ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS, arrayOf("$prefix%"))
            putInt(MediaStore.QUERY_ARG_MATCH_PENDING, MediaStore.MATCH_INCLUDE)
        }
        return context.contentResolver.query(
            MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, arrayOf(MediaStore.Audio.Media._ID), args, null,
        )?.use { it.count } ?: 0
    }
}
