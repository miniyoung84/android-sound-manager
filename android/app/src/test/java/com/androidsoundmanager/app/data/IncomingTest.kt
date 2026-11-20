package com.androidsoundmanager.app.data

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream

class IncomingTest {
    private val send = "android.intent.action.SEND"

    @Test
    fun acceptsSharedAudioAndVideo() {
        assertTrue(acceptsShare(send, "audio/mpeg", "content"))
        assertTrue(acceptsShare(send, "video/mp4", "content"))
    }

    @Test
    fun rejectsEverythingElse() {
        assertFalse("file links could reach private files", acceptsShare(send, "audio/mpeg", "file"))
        assertFalse(acceptsShare(send, "audio/mpeg", null))
        assertFalse(acceptsShare(send, "audio/mpeg", "http"))
        assertFalse(acceptsShare(send, "image/png", "content"))
        assertFalse(acceptsShare(send, "*/*", "content"))
        assertFalse(acceptsShare(send, null, "content"))
        assertFalse(acceptsShare("android.intent.action.SEND_MULTIPLE", "audio/mpeg", "content"))
        assertFalse(acceptsShare(null, "audio/mpeg", "content"))
    }

    @Test
    fun copiesSmallFilesExactly() {
        val data = ByteArray(200_000) { it.toByte() }
        val out = ByteArrayOutputStream()
        assertEquals(data.size.toLong(), copyAtMost(ByteArrayInputStream(data), out, limit = 200_000))
        assertArrayEquals(data, out.toByteArray())
    }

    @Test
    fun stopsEndlessStreams() {
        val endless = object : InputStream() {
            override fun read() = 0
            override fun read(b: ByteArray, off: Int, len: Int) = len
        }
        try {
            copyAtMost(endless, ByteArrayOutputStream(), limit = 1_000_000)
            fail("expected the size limit")
        } catch (e: EditError) {
            assertTrue(e.message!!.contains("too big"))
        }
    }
}
