package dev.mrksvt.reelsdownloader.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Port dari `bot/tests/test_validator.py` (FR-102, FR-103).
 */
class UrlValidatorTest {

    private val validUrls = listOf(
        "https://www.instagram.com/reel/ABC123/" to Platform.INSTAGRAM,
        "https://instagram.com/p/XYZ/" to Platform.INSTAGRAM,
        "https://www.facebook.com/watch?v=123456" to Platform.FACEBOOK,
        "https://facebook.com/reel/9876" to Platform.FACEBOOK,
        "https://m.facebook.com/story.php?id=1" to Platform.FACEBOOK,
        "https://fb.watch/abcDEF/" to Platform.FACEBOOK,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ" to Platform.YOUTUBE,
        "https://youtube.com/shorts/abcdef" to Platform.YOUTUBE,
        "https://m.youtube.com/watch?v=abc" to Platform.YOUTUBE,
        "https://youtu.be/dQw4w9WgXcQ" to Platform.YOUTUBE,
    )

    private val unsupportedHosts = listOf(
        "https://www.tiktok.com/@user/video/123",
        "https://vt.tiktok.com/ZS123/",
        "https://vimeo.com/123456",
        "https://twitter.com/user/status/1",
        "https://example.com/video",
        "https://instagram.com.evil.test/reel/1",
    )

    @Test
    fun `hanya url yang menunjuk konten yang diprobe`() {
        // Semua URL valid di atas menunjuk konten.
        validUrls.forEach { (url, _) ->
            assertTrue("harus punya konten: $url", UrlValidator.pointsToContent(url))
        }
        // Beranda platform lolos validasi, tetapi bukan media.
        assertTrue(!UrlValidator.pointsToContent("https://www.instagram.com"))
        assertTrue(!UrlValidator.pointsToContent("https://www.instagram.com/"))
        assertTrue(!UrlValidator.pointsToContent("https://youtube.com"))
        assertTrue(!UrlValidator.pointsToContent("bukan url"))
    }

    @Test
    fun `accepts the 10 allowed hosts`() {
        validUrls.forEach { (url, expected) ->
            val result = UrlValidator.validate(url)
            assertTrue("harus valid: $url", result is UrlValidator.ValidationResult.Valid)
            assertEquals(expected, (result as UrlValidator.ValidationResult.Valid).platform)
        }
    }

    @Test
    fun `rejects unsupported hosts`() {
        unsupportedHosts.forEach { url ->
            val result = UrlValidator.validate(url)
            assertTrue(
                "harus ditolak: $url",
                result is UrlValidator.ValidationResult.Unsupported,
            )
        }
    }

    @Test
    fun `rejects blank and malformed input`() {
        listOf("", "   ", "bukan url", "ftp://instagram.com/reel/1").forEach { input ->
            val result = UrlValidator.validate(input)
            assertTrue(
                "harus invalid: '$input'",
                result is UrlValidator.ValidationResult.Invalid,
            )
        }
    }

    @Test
    fun `extracts url from wrapped text`() {
        assertEquals(
            "https://www.instagram.com/reel/ABC123/",
            UrlValidator.extractUrl("Cek ini https://www.instagram.com/reel/ABC123/ keren"),
        )
        assertNull(UrlValidator.extractUrl("tanpa tautan"))
        assertNull(UrlValidator.extractUrl(null))
    }

    @Test
    fun `normalizes host and scheme`() {
        val result = UrlValidator.validate("HTTPS://WWW.Instagram.COM/reel/ABC123/?x=1")
        assertTrue(result is UrlValidator.ValidationResult.Valid)
        assertEquals(
            "https://www.instagram.com/reel/ABC123/?x=1",
            (result as UrlValidator.ValidationResult.Valid).url,
        )
    }

    @Test
    fun `engine error messages are mapped`() {
        assertEquals(
            DownloadError.Private,
            DownloadError.fromEngineMessage("ERROR: This video is private"),
        )
        assertEquals(
            DownloadError.NotFound,
            DownloadError.fromEngineMessage("ERROR: Video unavailable"),
        )
        assertEquals(
            DownloadError.FfmpegFailed,
            DownloadError.fromEngineMessage("ERROR: ffmpeg not found"),
        )
        assertEquals(
            DownloadError.DownloadFailed,
            DownloadError.fromEngineMessage(null),
        )
    }
}
