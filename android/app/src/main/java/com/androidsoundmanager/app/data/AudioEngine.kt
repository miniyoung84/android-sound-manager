package com.androidsoundmanager.app.data

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** A problem with the file or the edit, worded for the user. */
class EditError(message: String) : Exception(message)

private const val TIMEOUT_US = 10_000L
private const val MAX_IDLE_POLLS = 1_000 // ~10 s without progress means the codec is stuck
private const val AAC_BITRATE = 192_000
private const val MAX_AAC_SAMPLE_RATE = 48_000

private class PcmFormat(val sampleRate: Int, val channels: Int, val encoding: Int)

/**
 * Reads audio (from audio or video files) with the phone's own decoders and writes edited
 * copies as AAC in an .m4a file. Everything runs off the main thread and stops promptly when
 * the calling coroutine is cancelled.
 */
object AudioEngine {

    /** Decodes [uri] once to measure its length and loudness over time. */
    suspend fun analyze(context: Context, uri: Uri, onProgress: (Float) -> Unit = {}): Analysis =
        withContext(Dispatchers.Default) {
            var collector: PeakCollector? = null
            var sampleRate = 0
            var frames = 0L
            decode(context, uri, onProgress) { samples, count, fmt ->
                val peaks = collector ?: PeakCollector(fmt.sampleRate).also {
                    collector = it
                    sampleRate = fmt.sampleRate
                }
                var i = 0
                while (i + fmt.channels <= count) {
                    var loudest = 0f
                    for (c in 0 until fmt.channels) loudest = max(loudest, abs(samples[i + c]))
                    peaks.add(loudest)
                    i += fmt.channels
                }
                frames += count / fmt.channels
                if (frames > MAX_EDIT_DURATION_MS * sampleRate / 1000) throw tooLong()
                true
            }
            val peaks = collector?.finish()
            if (peaks == null || frames == 0L) throw EditError("Couldn't find any sound in that file.")
            Analysis(frames * 1000 / sampleRate, peaks)
        }

    /**
     * Writes the [edit] of [uri] to [out] as an .m4a file. [analysis] must come from [analyze]
     * on the same file (it provides the loudness used by "Normalize").
     */
    suspend fun render(
        context: Context,
        uri: Uri,
        edit: Edit,
        analysis: Analysis,
        out: File,
        onProgress: (Float) -> Unit = {},
    ) = withContext(Dispatchers.Default) {
        val e = edit.clamped(analysis.durationMs)
        val gain = e.linearGain(analysis.peakBetween(e.startMs, e.endMs))
        var encoder: AacEncoder? = null
        var frame = 0L // index of the next decoded frame in the whole file
        var startFrame = 0L
        var endFrame = 0L
        var fadeInFrames = 0L
        var fadeOutFrames = 0L
        try {
            decode(context, uri, onProgress = {}) { samples, count, fmt ->
                val enc = encoder ?: run {
                    if (fmt.sampleRate > MAX_AAC_SAMPLE_RATE) {
                        throw EditError("That file's sample rate is too high for the phone editor. Use the desktop app.")
                    }
                    startFrame = msToFrames(e.startMs, fmt.sampleRate)
                    endFrame = msToFrames(e.endMs, fmt.sampleRate)
                    fadeInFrames = msToFrames(e.fadeInMs, fmt.sampleRate)
                    fadeOutFrames = msToFrames(e.fadeOutMs, fmt.sampleRate)
                    AacEncoder(out, fmt.sampleRate, min(fmt.channels, 2)).also { encoder = it }
                }
                val inChannels = fmt.channels
                val frames = count / inChannels
                val pcm = ShortArray(frames * enc.channels)
                var written = 0
                val length = endFrame - startFrame
                for (f in 0 until frames) {
                    val g = frame + f
                    if (g < startFrame) continue
                    if (g >= endFrame) break
                    val k = envelope(g - startFrame, length, fadeInFrames, fadeOutFrames, gain)
                    val base = f * inChannels
                    if (inChannels <= 2) {
                        for (c in 0 until inChannels) pcm[written++] = toPcm16(samples[base + c] * k)
                    } else {
                        // Surround sound: fold left-side and right-side channels into stereo.
                        var left = 0f
                        var right = 0f
                        for (c in 0 until inChannels) {
                            if (c % 2 == 0) left += samples[base + c] else right += samples[base + c]
                        }
                        pcm[written++] = toPcm16(left / ((inChannels + 1) / 2) * k)
                        pcm[written++] = toPcm16(right / (inChannels / 2) * k)
                    }
                }
                enc.write(pcm, written)
                frame += frames
                onProgress(min(1f, frame.toFloat() / max(1L, endFrame)))
                frame < endFrame // stop decoding once past the selection
            }
            val enc = encoder ?: throw EditError("Couldn't find any sound in that file.")
            if (enc.framesWritten == 0L) throw EditError("The selection is empty.")
            enc.finish()
        } catch (t: Throwable) {
            encoder?.abort()
            out.delete()
            throw t
        }
    }

    /**
     * Decodes the first audio track of [uri] into float samples (-1..1, interleaved), calling
     * [onBlock] for each block. [onBlock] returns false to stop early.
     */
    private suspend fun decode(
        context: Context,
        uri: Uri,
        onProgress: (Float) -> Unit,
        onBlock: (FloatArray, Int, PcmFormat) -> Boolean,
    ) {
        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        try {
            try {
                extractor.setDataSource(context, uri, null)
            } catch (_: Exception) {
                throw EditError("Couldn't open that file.")
            }
            val track = (0 until extractor.trackCount).firstOrNull {
                extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true
            } ?: throw EditError("That file has no sound in it.")
            val format = extractor.getTrackFormat(track)
            val durationUs = if (format.containsKey(MediaFormat.KEY_DURATION)) format.getLong(MediaFormat.KEY_DURATION) else 0L
            if (durationUs > MAX_EDIT_DURATION_MS * 1000) throw tooLong()
            extractor.selectTrack(track)

            val decoder = try {
                MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME)!!).also {
                    it.configure(format, null, null, 0)
                    it.start()
                }
            } catch (_: Exception) {
                throw EditError("This phone can't read that kind of audio.")
            }
            codec = decoder
            var pcm = PcmFormat(
                format.getInteger(MediaFormat.KEY_SAMPLE_RATE),
                format.getInteger(MediaFormat.KEY_CHANNEL_COUNT),
                AudioFormat.ENCODING_PCM_16BIT,
            )
            val info = MediaCodec.BufferInfo()
            var inputDone = false
            var idle = 0
            while (true) {
                currentCoroutineContext().ensureActive()
                if (!inputDone) {
                    val i = decoder.dequeueInputBuffer(TIMEOUT_US)
                    if (i >= 0) {
                        val size = extractor.readSampleData(decoder.getInputBuffer(i)!!, 0)
                        if (size < 0) {
                            decoder.queueInputBuffer(i, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inputDone = true
                        } else {
                            val time = extractor.sampleTime
                            decoder.queueInputBuffer(i, 0, size, time, 0)
                            if (durationUs > 0) onProgress((time.toFloat() / durationUs).coerceIn(0f, 1f))
                            extractor.advance()
                        }
                    }
                }
                val o = decoder.dequeueOutputBuffer(info, TIMEOUT_US)
                when {
                    o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        val f = decoder.outputFormat
                        pcm = PcmFormat(
                            f.getInteger(MediaFormat.KEY_SAMPLE_RATE),
                            f.getInteger(MediaFormat.KEY_CHANNEL_COUNT),
                            if (f.containsKey(MediaFormat.KEY_PCM_ENCODING)) {
                                f.getInteger(MediaFormat.KEY_PCM_ENCODING)
                            } else {
                                AudioFormat.ENCODING_PCM_16BIT
                            },
                        )
                    }
                    o >= 0 -> {
                        idle = 0
                        var keepGoing = true
                        if (info.size > 0 && pcm.channels > 0) {
                            val buf = decoder.getOutputBuffer(o)!!
                            buf.position(info.offset)
                            buf.limit(info.offset + info.size)
                            val samples = toFloats(buf.slice().order(ByteOrder.nativeOrder()), pcm.encoding)
                            keepGoing = onBlock(samples, samples.size, pcm)
                        }
                        decoder.releaseOutputBuffer(o, false)
                        if (!keepGoing || info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                    }
                    else -> if (inputDone && ++idle > MAX_IDLE_POLLS) throw EditError("The phone's audio decoder stopped responding.")
                }
            }
        } finally {
            codec?.run {
                runCatching { stop() }
                release()
            }
            extractor.release()
        }
    }

    private fun tooLong() = EditError("That's longer than 20 minutes. Trim it in the desktop app instead.")

    private fun toPcm16(v: Float): Short = (v.coerceIn(-1f, 1f) * 32767f).roundToInt().toShort()

    @SuppressLint("InlinedApi") // only the integer values of the newer encodings are compared
    private fun toFloats(buf: ByteBuffer, encoding: Int): FloatArray = when (encoding) {
        AudioFormat.ENCODING_PCM_16BIT -> {
            val s = buf.asShortBuffer()
            FloatArray(s.remaining()) { s.get() / 32768f }
        }
        AudioFormat.ENCODING_PCM_FLOAT -> {
            val f = buf.asFloatBuffer()
            FloatArray(f.remaining()).also { f.get(it) }
        }
        AudioFormat.ENCODING_PCM_8BIT -> FloatArray(buf.remaining()) { ((buf.get().toInt() and 0xFF) - 128) / 128f }
        AudioFormat.ENCODING_PCM_32BIT -> {
            val ints = buf.asIntBuffer()
            FloatArray(ints.remaining()) { ints.get() / 2147483648f }
        }
        AudioFormat.ENCODING_PCM_24BIT_PACKED -> FloatArray(buf.remaining() / 3) {
            val b0 = buf.get().toInt() and 0xFF
            val b1 = buf.get().toInt() and 0xFF
            val b2 = buf.get().toInt()
            ((b2 shl 16) or (b1 shl 8) or b0) / 8388608f
        }
        else -> throw EditError("This phone decoded that file in a format the editor doesn't know.")
    }
}

/** AAC encoder writing into an .m4a (MPEG-4) file. */
private class AacEncoder(out: File, private val sampleRate: Int, val channels: Int) {
    private val codec: MediaCodec
    private val muxer: MediaMuxer
    private val info = MediaCodec.BufferInfo()
    private var track = -1
    private var muxing = false
    var framesWritten = 0L
        private set

    init {
        val format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, sampleRate, channels).apply {
            setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
            setInteger(MediaFormat.KEY_BIT_RATE, AAC_BITRATE)
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 64 * 1024)
        }
        muxer = MediaMuxer(out.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        codec = try {
            MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC).also {
                it.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                it.start()
            }
        } catch (_: Exception) {
            muxer.release()
            throw EditError("This phone couldn't start its audio encoder for that sound.")
        }
    }

    private fun timeUs() = framesWritten * 1_000_000L / sampleRate

    fun write(pcm: ShortArray, count: Int) {
        var offset = 0
        var idle = 0
        while (offset < count) {
            val i = codec.dequeueInputBuffer(TIMEOUT_US)
            if (i >= 0) {
                idle = 0
                val buf = codec.getInputBuffer(i)!!.order(ByteOrder.nativeOrder())
                buf.clear()
                val n = min(count - offset, buf.remaining() / 2 / channels * channels)
                if (n <= 0) throw EditError("The phone's audio encoder has no room for data.")
                buf.asShortBuffer().put(pcm, offset, n)
                codec.queueInputBuffer(i, 0, n * 2, timeUs(), 0)
                offset += n
                framesWritten += n / channels
            } else if (++idle > MAX_IDLE_POLLS) {
                throw EditError("The phone's audio encoder stopped responding.")
            }
            drain(untilEnd = false)
        }
    }

    fun finish() {
        var idle = 0
        while (true) {
            val i = codec.dequeueInputBuffer(TIMEOUT_US)
            if (i >= 0) {
                codec.queueInputBuffer(i, 0, 0, timeUs(), MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                break
            }
            if (++idle > MAX_IDLE_POLLS) throw EditError("The phone's audio encoder stopped responding.")
            drain(untilEnd = false)
        }
        drain(untilEnd = true)
        codec.stop()
        codec.release()
        if (!muxing) throw EditError("The phone's audio encoder produced nothing.")
        muxer.stop() // writes the file's index; the file is only valid after this
        muxer.release()
    }

    fun abort() {
        runCatching { codec.stop() }
        runCatching { codec.release() }
        if (muxing) runCatching { muxer.stop() }
        runCatching { muxer.release() }
    }

    private fun drain(untilEnd: Boolean) {
        var idle = 0
        while (true) {
            val o = codec.dequeueOutputBuffer(info, if (untilEnd) TIMEOUT_US else 0)
            when {
                o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    track = muxer.addTrack(codec.outputFormat)
                    muxer.start()
                    muxing = true
                }
                o >= 0 -> {
                    idle = 0
                    if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) info.size = 0
                    if (info.size > 0 && muxing) {
                        val buf = codec.getOutputBuffer(o)!!
                        buf.position(info.offset)
                        buf.limit(info.offset + info.size)
                        muxer.writeSampleData(track, buf, info)
                    }
                    codec.releaseOutputBuffer(o, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) return
                }
                !untilEnd -> return
                ++idle > MAX_IDLE_POLLS -> throw EditError("The phone's audio encoder stopped responding.")
            }
        }
    }
}
