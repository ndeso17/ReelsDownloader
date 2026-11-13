package dev.mrksvt.reelsdownloader.domain

import java.net.URI
import java.net.URISyntaxException
import java.util.Locale

/**
 * Port dari `bot/app/services/validator.py` (FR-102, FR-103).
 *
 * Sumber kebenaran host: 10 entri exact-match, sama persis dengan bot.
 * Perbedaan yang disengaja: kelas ini tidak melempar exception ke UI, tetapi
 * mengembalikan [ValidationResult] supaya pesan error bisa dipetakan ke string
 * resource lewat [DownloadError].
 */
object UrlValidator {

    /** 10 host yang sama dengan `ALLOWED_HOSTS` di bot. */
    val ALLOWED_HOSTS: Set<String> = setOf(
        "instagram.com",
        "www.instagram.com",
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
        "fb.watch",
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
    )

    private val URL_REGEX = Regex("""https?://\S+""", RegexOption.IGNORE_CASE)

    /** Ambil URL http/https pertama dari teks berbalut (FR-101, share sheet). */
    fun extractUrl(text: String?): String? {
        if (text.isNullOrBlank()) return null
        return URL_REGEX.find(text)?.value?.trimEnd('.', ',', ')', ']', '"', '\'')
    }

    /** Validasi + normalisasi URL. */
    fun validate(rawUrl: String?): ValidationResult {
        val input = rawUrl?.trim().orEmpty()
        if (input.isEmpty()) return ValidationResult.Invalid(DownloadError.InvalidUrl)

        val extracted = extractUrl(input)
        val candidate = extracted ?: input
        val uri = try {
            URI(candidate)
        } catch (_: URISyntaxException) {
            return ValidationResult.Invalid(DownloadError.InvalidUrl)
        }

        val scheme = uri.scheme?.lowercase(Locale.ROOT)
        if (scheme != "http" && scheme != "https") {
            return ValidationResult.Invalid(DownloadError.InvalidUrl)
        }
        val host = uri.host?.lowercase(Locale.ROOT)
        if (host.isNullOrEmpty()) return ValidationResult.Invalid(DownloadError.InvalidUrl)

        if (host !in ALLOWED_HOSTS) {
            return ValidationResult.Unsupported(host)
        }

        val platform = detectPlatform(host)
            ?: return ValidationResult.Unsupported(host)

        return ValidationResult.Valid(
            url = normalize(uri, host, scheme),
            platform = platform,
        )
    }

    private fun normalize(uri: URI, host: String, scheme: String): String {
        val netloc = buildString {
            uri.userInfo?.let { append(it).append('@') }
            append(host)
            if (uri.port != -1) append(':').append(uri.port)
        }
        return buildString {
            append(scheme).append("://").append(netloc).append(uri.rawPath.orEmpty())
            uri.rawQuery?.let { append('?').append(it) }
            uri.rawFragment?.let { append('#').append(it) }
        }
    }

    /** Deteksi platform dari hostname (FR-103). */
    fun detectPlatform(host: String): Platform? = when (host.lowercase(Locale.ROOT)) {
        "instagram.com", "www.instagram.com" -> Platform.INSTAGRAM
        "facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch" -> Platform.FACEBOOK
        "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be" -> Platform.YOUTUBE
        else -> null
    }

    sealed interface ValidationResult {
        data class Valid(val url: String, val platform: Platform) : ValidationResult
        data class Invalid(val error: DownloadError) : ValidationResult
        data class Unsupported(val host: String) : ValidationResult
    }
}
