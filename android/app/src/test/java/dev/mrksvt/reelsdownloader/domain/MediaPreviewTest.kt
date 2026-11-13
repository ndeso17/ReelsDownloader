package dev.mrksvt.reelsdownloader.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Penyusunan pratinjau dari format mentah (A18).
 *
 * Yang diuji adalah bagian yang tidak bisa dilihat mata di layar: dari mana
 * angka "≈ 12 MB" berasal, dan kapan lebih baik mengaku tidak tahu.
 */
class MediaPreviewTest {

    /** Berkas video; default sudah lengkap dengan audio (seperti hasil muxed). */
    private fun video(height: Int, bytes: Long, audio: Boolean = true) =
        PreviewAssembler.RawFormat(
            height = height,
            videoCodec = "avc1",
            audioCodec = if (audio) "mp4a" else "none",
            bytes = bytes,
            bitrateKbps = 0,
        )

    private fun audioOnly(bytes: Long, bitrateKbps: Int = 0) = PreviewAssembler.RawFormat(
        height = 0,
        videoCodec = "none",
        audioCodec = "mp4a",
        bytes = bytes,
        bitrateKbps = bitrateKbps,
    )

    private fun assemble(
        formats: List<PreviewAssembler.RawFormat>,
        duration: Int? = 60,
    ) = PreviewAssembler.assemble(
        url = "https://www.instagram.com/reel/abc",
        title = "Contoh",
        uploader = "seseorang",
        durationSeconds = duration,
        thumbnailUrl = null,
        extractor = "instagram",
        formats = formats,
    )

    @Test
    fun `resolusi diurutkan menurun`() {
        val preview = assemble(listOf(video(720, 5_000), video(1080, 9_000), video(480, 2_000)))
        assertEquals(listOf(1080, 720, 480), preview.heights)
    }

    @Test
    fun `Kualitas BEST memakai resolusi tertinggi`() {
        val preview = assemble(listOf(video(720, 5_000), video(1080, 9_000)))
        assertEquals(9_000L, preview.estimateBytes(ResultType.VIDEO, Quality.BEST))
    }

    @Test
    fun `batas kualitas memilih resolusi tertinggi di bawahnya`() {
        val preview = assemble(
            listOf(video(1080, 9_000), video(720, 5_000), video(480, 2_000))
        )
        assertEquals(5_000L, preview.estimateBytes(ResultType.VIDEO, Quality.P720))
        assertEquals(2_000L, preview.estimateBytes(ResultType.VIDEO, Quality.P480))
    }

    @Test
    fun `batas kualitas yang tidak tersedia memakai resolusi terkecil`() {
        // Sumber hanya 1080p; pengguna minta 480p. Menampilkan ukuran 1080p
        // akan menyesatkan, jadi pakai yang paling dekat dengan harapannya.
        val preview = assemble(listOf(video(1080, 9_000)))
        assertEquals(9_000L, preview.estimateBytes(ResultType.VIDEO, Quality.P360))
    }

    @Test
    fun `format video-only ditambah ukuran audio`() {
        val preview = assemble(
            listOf(video(1080, 9_000, audio = false), audioOnly(bytes = 1_000))
        )
        // 9000 video + 1000 audio: itulah yang benar-benar tersimpan di galeri.
        assertEquals(10_000L, preview.estimateBytes(ResultType.VIDEO, Quality.BEST))
    }

    @Test
    fun `format video dengan audio tidak ditambah lagi`() {
        val preview = assemble(
            listOf(video(1080, 9_000, audio = true), audioOnly(bytes = 1_000))
        )
        assertEquals(9_000L, preview.estimateBytes(ResultType.VIDEO, Quality.BEST))
    }

    @Test
    fun `tanpa ukuran audio total video-only tidak diketahui`() {
        // Lebih baik "ukuran tidak diketahui" daripada angka yang terlalu kecil.
        val preview = assemble(listOf(video(1080, 9_000, audio = false)))
        assertNull(preview.estimateBytes(ResultType.VIDEO, Quality.BEST))
    }

    @Test
    fun `pilihan audio memakai ukuran audio`() {
        val preview = assemble(listOf(video(1080, 9_000), audioOnly(bytes = 1_500)))
        assertEquals(1_500L, preview.estimateBytes(ResultType.AUDIO, Quality.BEST))
    }

    @Test
    fun `audio tanpa format audio saja tidak diketahui`() {
        val preview = assemble(listOf(video(1080, 9_000, audio = true)))
        assertNull(preview.estimateBytes(ResultType.AUDIO, Quality.BEST))
    }

    @Test
    fun `ukuran dihitung dari bitrate bila server tidak melaporkan`() {
        // 1000 kbit/s selama 60 detik = 7.5 MB.
        val format = PreviewAssembler.RawFormat(
            height = 720,
            videoCodec = "avc1",
            audioCodec = "unknown",
            bytes = 0,
            bitrateKbps = 1_000,
        )
        val preview = assemble(listOf(format), duration = 60)
        assertEquals(7_500_000L, preview.estimateBytes(ResultType.VIDEO, Quality.P720))
    }

    @Test
    fun `bitrate tanpa durasi tidak dipakai`() {
        // Tanpa durasi, bitrate tidak bisa dikonversi menjadi ukuran.
        val format = PreviewAssembler.RawFormat(
            height = 720,
            videoCodec = "avc1",
            audioCodec = "unknown",
            bytes = 0,
            bitrateKbps = 1_000,
        )
        val preview = assemble(listOf(format), duration = null)
        assertNull(preview.estimateBytes(ResultType.VIDEO, Quality.P720))
    }

    @Test
    fun `format audio saja tidak dianggap video`() {
        val preview = assemble(listOf(audioOnly(bytes = 1_000)))
        assertTrue(preview.heights.isEmpty())
        assertNull(preview.estimateBytes(ResultType.VIDEO, Quality.BEST))
        assertEquals(1_000L, preview.estimateBytes(ResultType.AUDIO, Quality.BEST))
    }

    @Test
    fun `pada tinggi yang sama dipilih berkas terbesar`() {
        val preview = assemble(listOf(video(720, 3_000), video(720, 6_000)))
        assertEquals(listOf(720), preview.heights)
        assertEquals(6_000L, preview.estimateBytes(ResultType.VIDEO, Quality.P720))
    }

    @Test
    fun `jumlah resolusi tidak berlipat`() {
        // Banyak format 720p (beda codec/bitrate) tetap satu pilihan 720p.
        val preview = assemble(
            listOf(video(720, 3_000), video(720, 4_000), video(720, 5_000))
        )
        assertEquals(1, preview.variants.size)
    }

    @Test
    fun `pratinjau kosong dikenali`() {
        val empty = PreviewAssembler.assemble(
            url = "https://youtu.be/x",
            title = null,
            uploader = null,
            durationSeconds = null,
            thumbnailUrl = null,
            extractor = null,
            formats = emptyList(),
        )
        assertTrue(empty.isEmpty)
    }

    @Test
    fun `judul kosong dianggap tidak ada`() {
        val preview = PreviewAssembler.assemble(
            url = "https://youtu.be/x",
            title = "   ",
            uploader = "",
            durationSeconds = 0,
            thumbnailUrl = "  ",
            extractor = null,
            formats = listOf(video(720, 1_000)),
        )
        assertNull(preview.title)
        assertNull(preview.uploader)
        assertNull(preview.durationSeconds)
        assertNull(preview.thumbnailUrl)
        assertFalse(preview.isEmpty)
    }

    @Test
    fun `durasi diformat ringkas`() {
        assertEquals("0:00", formatDuration(0))
        assertEquals("0:07", formatDuration(7))
        assertEquals("1:23", formatDuration(83))
        assertEquals("1:02:03", formatDuration(3723))
    }
}
