package dev.mrksvt.reelsdownloader.domain

/**
 * Satu pilihan resolusi yang tersedia di sumber (A18).
 *
 * [approxBytes] `null` berarti ukuran tidak bisa diperkirakan — lebih baik
 * mengaku tidak tahu daripada menampilkan angka yang salah.
 */
data class PreviewVariant(
    val height: Int,
    val approxBytes: Long?,
)

/**
 * Ringkasan media yang diambil **sebelum** pengguna menekan Unduh (A18).
 *
 * Tujuannya menjawab tiga pertanyaan yang selama ini baru terjawab setelah
 * unduhan berjalan: ini video apa, berapa lama, dan kira-kira berapa besar.
 */
data class MediaPreview(
    val url: String,
    val title: String?,
    val uploader: String?,
    val durationSeconds: Int?,
    val thumbnailUrl: String?,
    val extractor: String?,
    /** Resolusi video yang tersedia, menurun (tertinggi lebih dulu). */
    val variants: List<PreviewVariant> = emptyList(),
    /** Perkiraan ukuran bila hanya audio yang diunduh. */
    val audioBytes: Long? = null,
) {

    val heights: List<Int> get() = variants.map { it.height }

    /** Tidak ada apa pun yang bisa ditampilkan; UI sebaiknya diam saja. */
    val isEmpty: Boolean
        get() = title == null && thumbnailUrl == null && durationSeconds == null && variants.isEmpty()

    /**
     * Perkiraan ukuran untuk pilihan pengguna saat ini.
     *
     * Untuk video, ambil resolusi tertinggi yang **tidak melebihi** batas
     * kualitas; bila semua resolusi lebih tinggi dari batas (mis. sumber hanya
     * 1080p sementara pengguna memilih 720p), pakai yang terkecil — itu yang
     * paling dekat dengan harapan pengguna.
     */
    fun estimateBytes(type: ResultType, quality: Quality): Long? {
        if (type == ResultType.AUDIO) return audioBytes
        if (variants.isEmpty()) return null
        val limit = quality.height
        val variant = if (limit == null) {
            variants.first()
        } else {
            variants.firstOrNull { it.height <= limit } ?: variants.minByOrNull { it.height }
        }
        return variant?.approxBytes
    }
}

/** Format durasi ringkas: `1:23` atau `1:02:03`. */
fun formatDuration(seconds: Int): String {
    if (seconds <= 0) return "0:00"
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val secs = seconds % 60
    return if (hours > 0) {
        "%d:%02d:%02d".format(hours, minutes, secs)
    } else {
        "%d:%02d".format(minutes, secs)
    }
}

/**
 * Menyusun [MediaPreview] dari daftar format mentah (A18).
 *
 * Murni dan tanpa API Android supaya bisa diuji di JVM: seluruh keputusan
 * "berapa besar kira-kira" ada di sini, dan itulah bagian yang paling mudah
 * salah tanpa terlihat.
 */
object PreviewAssembler {

    /** Satu format seperti yang dilaporkan yt-dlp, sudah dinormalkan. */
    data class RawFormat(
        /** 0 untuk format audio saja. */
        val height: Int,
        val videoCodec: String?,
        val audioCodec: String?,
        /** Ukuran pasti dari server; 0 bila tidak dilaporkan. */
        val bytes: Long,
        /** Total bitrate (kbit/s); 0 bila tidak dilaporkan. */
        val bitrateKbps: Int,
    ) {
        /** Hanya `none` eksplisit yang menandakan bukan video. */
        val isVideo: Boolean
            get() = height > 0 && !videoCodec.equals("none", ignoreCase = true)

        val hasAudio: Boolean
            get() = !audioCodec.isNullOrBlank() && !audioCodec.equals("none", ignoreCase = true)
    }

    fun assemble(
        url: String,
        title: String?,
        uploader: String?,
        durationSeconds: Int?,
        thumbnailUrl: String?,
        extractor: String?,
        formats: List<RawFormat>,
    ): MediaPreview {
        val duration = durationSeconds?.takeIf { it > 0 }
        val audioBytes = bestAudioBytes(formats, duration)

        val variants = formats
            .filter { it.isVideo }
            .groupBy { it.height }
            .map { (height, atHeight) ->
                // Format terbesar pada tinggi itu = kualitas terbaiknya.
                val best = atHeight.maxByOrNull { estimate(it, duration) ?: 0L } ?: atHeight.first()
                val videoBytes = estimate(best, duration)
                val total = when {
                    videoBytes == null -> null
                    // Video-only harus digabung audio; kalau ukuran audio tidak
                    // diketahui, totalnya juga tidak diketahui.
                    !best.hasAudio -> audioBytes?.let { videoBytes + it }
                    else -> videoBytes
                }
                PreviewVariant(height, total)
            }
            .sortedByDescending { it.height }

        return MediaPreview(
            url = url,
            title = title?.takeIf { it.isNotBlank() },
            uploader = uploader?.takeIf { it.isNotBlank() },
            durationSeconds = duration,
            thumbnailUrl = thumbnailUrl?.takeIf { it.isNotBlank() },
            extractor = extractor?.takeIf { it.isNotBlank() },
            variants = variants,
            audioBytes = audioBytes,
        )
    }

    /**
     * Ukuran format: pakai angka server bila ada, selain itu hitung dari
     * bitrate × durasi. Tanpa durasi, bitrate tidak ada gunanya.
     */
    private fun estimate(format: RawFormat, durationSeconds: Int?): Long? {
        if (format.bytes > 0) return format.bytes
        val kbps = format.bitrateKbps
        if (kbps <= 0 || durationSeconds == null) return null
        return kbps.toLong() * 1000L / 8L * durationSeconds
    }

    /** Audio terbaik = perkiraan terbesar di antara format audio saja. */
    private fun bestAudioBytes(formats: List<RawFormat>, durationSeconds: Int?): Long? =
        formats
            .filter { it.height <= 0 && it.hasAudio }
            .mapNotNull { estimate(it, durationSeconds) }
            .maxOrNull()
}
