package dev.mrksvt.reelsdownloader.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Deteksi kandidat media (A17-5).
 *
 * Aturan yang diuji adalah yang paling mudah salah dan paling mahal efeknya:
 * membuang gambar/aset halaman, tetapi tetap menerima video dari URL yang
 * tidak punya ekstensi (mis. CDN berbasis query).
 */
class MediaSnifferTest {

    @Test
    fun `video mp4 dari ekstensi dikenali`() {
        val candidate = MediaSniffer.inspect("https://cdn.example.com/a/b/video.mp4")
        assertNotNull(candidate)
        assertEquals(ResultType.VIDEO, candidate!!.type)
        assertFalse(candidate.isStream)
    }

    @Test
    fun `audio m4a dikenali sebagai audio`() {
        val candidate = MediaSniffer.inspect("https://cdn.example.com/a.m4a")
        assertNotNull(candidate)
        assertEquals(ResultType.AUDIO, candidate!!.type)
    }

    @Test
    fun `mime video menang walau URL tanpa ekstensi`() {
        val candidate = MediaSniffer.inspect(
            "https://cdn.example.com/play?id=123",
            contentType = "video/mp4; codecs=\"avc1.4d401f\"",
        )
        assertNotNull(candidate)
        assertEquals(ResultType.VIDEO, candidate!!.type)
        assertEquals("video/mp4", candidate.mimeType)
    }

    @Test
    fun `hls m3u8 ditandai sebagai stream`() {
        val fromExt = MediaSniffer.inspect("https://cdn.example.com/live/index.m3u8")
        assertNotNull(fromExt)
        assertTrue(fromExt!!.isStream)

        val fromMime = MediaSniffer.inspect(
            "https://cdn.example.com/manifest",
            contentType = "application/vnd.apple.mpegurl",
        )
        assertNotNull(fromMime)
        assertTrue(fromMime!!.isStream)
    }

    @Test
    fun `gambar dan aset halaman ditolak`() {
        listOf(
            "https://cdn.example.com/img/thumb.jpg",
            "https://cdn.example.com/img/cover.PNG",
            "https://cdn.example.com/css/app.css",
            "https://cdn.example.com/js/app.js",
            "https://cdn.example.com/api/feed.json",
            "https://cdn.example.com/page.html",
        ).forEach { url ->
            assertNull("harus ditolak: $url", MediaSniffer.inspect(url))
        }
    }

    @Test
    fun `mime gambar ditolak walau URL berakhiran mp4`() {
        assertNull(
            MediaSniffer.inspect("https://cdn.example.com/x.mp4", "image/jpeg"),
        )
    }

    @Test
    fun `blob dan data uri ditolak`() {
        assertNull(MediaSniffer.inspect("blob:https://www.instagram.com/abc-123"))
        assertNull(MediaSniffer.inspect("data:video/mp4;base64,AAAA"))
    }

    @Test
    fun `url kosong ditolak`() {
        assertNull(MediaSniffer.inspect(""))
        assertNull(MediaSniffer.inspect("   "))
    }

    @Test
    fun `query string tidak mengganggu deteksi ekstensi`() {
        assertEquals("mp4", MediaSniffer.extensionOf("https://cdn.example.com/v.mp4?token=abc&x=1"))
        assertEquals("m3u8", MediaSniffer.extensionOf("https://cdn.example.com/l.m3u8#frag"))
    }

    @Test
    fun `content length nol diabaikan`() {
        val candidate = MediaSniffer.inspect("https://cdn.example.com/a.mp4", contentLength = 0)
        assertNotNull(candidate)
        assertNull(candidate!!.contentLength)
    }

    @Test
    fun `best memilih berkas utuh lebih dulu daripada stream`() {
        val candidates = listOf(
            MediaCandidate("https://cdn/live.m3u8", isStream = true, contentLength = 9_000_000),
            MediaCandidate("https://cdn/full.mp4", isStream = false, contentLength = 1_000_000),
        )
        assertEquals("https://cdn/full.mp4", MediaSniffer.best(candidates)?.url)
    }

    @Test
    fun `best memilih berkas terbesar di antara berkas utuh`() {
        val candidates = listOf(
            MediaCandidate("https://cdn/small.mp4", contentLength = 100),
            MediaCandidate("https://cdn/large.mp4", contentLength = 5000),
        )
        assertEquals("https://cdn/large.mp4", MediaSniffer.best(candidates)?.url)
    }

    @Test
    fun `best menghormati preferensi jenis`() {
        val candidates = listOf(
            MediaCandidate("https://cdn/v.mp4", type = ResultType.VIDEO, contentLength = 5000),
            MediaCandidate("https://cdn/a.m4a", type = ResultType.AUDIO, contentLength = 100),
        )
        assertEquals(
            "https://cdn/a.m4a",
            MediaSniffer.best(candidates, prefer = ResultType.AUDIO)?.url,
        )
    }

    @Test
    fun `best mengembalikan null untuk daftar kosong`() {
        assertNull(MediaSniffer.best(emptyList()))
    }
}
