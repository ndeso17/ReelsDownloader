package dev.mrksvt.reelsdownloader.domain

/**
 * Kandidat media yang ditemukan saat menjelajah (A17).
 *
 * [url] adalah tautan media langsung, bukan halaman. Ini yang membuat engine
 * cadangan tahan terhadap perubahan ekstraktor: kita tidak perlu memahami API
 * platform, cukup mengenali tautan berkasnya.
 */
data class MediaCandidate(
    val url: String,
    /** MIME dari server; `null` bila tidak dikirim. */
    val mimeType: String? = null,
    val contentLength: Long? = null,
    /** Hasil deteksi jenis media untuk menentukan folder MediaStore. */
    val type: ResultType = ResultType.VIDEO,
    val isStream: Boolean = false,
)

/**
 * Pengenal tautan media (murni, tanpa Android) — A17-5.
 *
 * Aturan sengaja konservatif: lebih baik melewatkan kandidat daripada
 * menawarkan gambar/iklan sebagai video.
 */
object MediaSniffer {

    /** Ekstensi berkas yang dianggap media utuh. */
    private val VIDEO_EXT = setOf("mp4", "m4v", "mov", "webm", "mkv", "flv", "3gp")
    private val AUDIO_EXT = setOf("m4a", "mp3", "aac", "ogg", "opus", "wav")
    private val STREAM_EXT = setOf("m3u8", "mpd", "ts")

    private val VIDEO_MIME = setOf(
        "video/mp4", "video/webm", "video/quicktime", "video/x-matroska", "video/3gpp",
    )
    private val AUDIO_MIME = setOf(
        "audio/mp4", "audio/mpeg", "audio/aac", "audio/ogg", "audio/opus", "audio/wav",
        "audio/x-m4a",
    )
    private val STREAM_MIME = setOf(
        "application/vnd.apple.mpegurl", "application/x-mpegurl",
        "application/dash+xml",
    )

    /** Ekstensi gambar/iklan yang harus selalu ditolak. */
    private val REJECT_EXT = setOf(
        "jpg", "jpeg", "png", "gif", "webp", "svg", "ico", "css", "js", "json",
        "html", "htm", "woff", "woff2", "ttf", "map",
    )

    /** Prefiks MIME yang tidak mungkin media, apa pun ekstensi URL-nya. */
    private val REJECT_MIME_PREFIX = listOf(
        "image/", "text/", "font/", "application/json", "application/javascript",
        "application/x-javascript", "application/x-font", "application/wasm",
    )

    /**
     * Nilai kandidat, atau `null` bila URL/MIME ini bukan media.
     *
     * [contentType] boleh berisi parameter (`video/mp4; codecs=...`).
     */
    fun inspect(
        url: String,
        contentType: String? = null,
        contentLength: Long? = null,
    ): MediaCandidate? {
        if (url.isBlank()) return null
        // Blob/MSE tidak bisa diunduh ulang di luar sesi halaman.
        if (url.startsWith("blob:") || url.startsWith("data:")) return null

        val mime = contentType
            ?.substringBefore(';')
            ?.trim()
            ?.lowercase()
            ?.takeIf { it.isNotEmpty() }

        val ext = extensionOf(url)
        if (ext != null && ext in REJECT_EXT) return null

        // Server adalah sumber kebenaran: MIME non-media tidak boleh diloloskan
        // hanya karena URL kebetulan berakhiran `.mp4`.
        if (mime != null && REJECT_MIME_PREFIX.any { mime.startsWith(it) }) return null

        val type = when {
            mime != null && mime in STREAM_MIME -> ResultType.VIDEO
            mime != null && mime in VIDEO_MIME -> ResultType.VIDEO
            mime != null && mime in AUDIO_MIME -> ResultType.AUDIO
            ext != null && ext in VIDEO_EXT -> ResultType.VIDEO
            ext != null && ext in AUDIO_EXT -> ResultType.AUDIO
            ext != null && ext in STREAM_EXT -> ResultType.VIDEO
            else -> return null
        }

        val isStream = (mime != null && mime in STREAM_MIME) || (ext != null && ext in STREAM_EXT)

        return MediaCandidate(
            url = url,
            mimeType = mime,
            contentLength = contentLength?.takeIf { it > 0 },
            type = type,
            isStream = isStream,
        )
    }

    /** Ekstensi huruf kecil tanpa titik, atau `null`. */
    fun extensionOf(url: String): String? {
        val path = url.substringBefore('#').substringBefore('?')
        val last = path.substringAfterLast('/', "")
        if (last.isEmpty()) return null
        val ext = last.substringAfterLast('.', "")
        return ext.lowercase().takeIf { it.isNotEmpty() && it.length <= 5 }
    }

    /** Pilih kandidat terbaik: berkas utuh lebih baik daripada stream. */
    fun best(candidates: List<MediaCandidate>, prefer: ResultType? = null): MediaCandidate? =
        candidates
            .filter { prefer == null || it.type == prefer }
            .sortedWith(
                compareBy<MediaCandidate> { it.isStream }
                    .thenByDescending { it.contentLength ?: 0L }
            )
            .firstOrNull()
}
