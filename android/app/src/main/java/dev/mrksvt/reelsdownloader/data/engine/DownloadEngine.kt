package dev.mrksvt.reelsdownloader.data.engine

import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType
import java.io.File

/** Permintaan satu unduhan ke engine. */
data class EngineRequest(
    val jobId: String,
    val url: String,
    val type: ResultType,
    val quality: Quality,
    val bitrate: AudioBitrate,
    val maxSizeBytes: Long,
    val workDir: File,
)

/** Event streaming dari engine ke worker. */
sealed interface DownloadEvent {
    data class Progress(
        val percent: Int,
        val speed: String?,
        val etaSeconds: Long?,
    ) : DownloadEvent

    data class Metadata(
        val title: String?,
        val actualQuality: String?,
    ) : DownloadEvent
}

/** Hasil akhir satu unduhan (file masih di [workDir]). */
data class EngineResult(
    val file: File,
    val title: String?,
    val actualQuality: String?,
)

/** Error engine yang sudah dipetakan ke domain. */
class EngineException(
    val error: DownloadError,
    message: String? = null,
    cause: Throwable? = null,
) : Exception(message, cause)

/**
 * Antarmuka engine unduhan (WP-A4).
 *
 * Dipisah dari implementasi supaya bisa dites dengan fake engine tanpa
 * menyentuh yt-dlp/FFmpeg native.
 */
interface DownloadEngine {
    /** Siapkan runtime yt-dlp + FFmpeg (idempoten, aman dipanggil berulang). */
    suspend fun prepare()

    /** Jalankan unduhan; event progres dikirim lewat [onEvent]. */
    suspend fun download(
        request: EngineRequest,
        onEvent: (DownloadEvent) -> Unit,
    ): EngineResult

    /** Hentikan proses yt-dlp milik [processId] (job id). */
    fun cancel(processId: String)

    /** Versi yt-dlp yang terpasang, atau `null` bila belum siap. */
    suspend fun engineVersion(): String?

    /** Perbarui yt-dlp ke rilis stabil terbaru; kembalikan versi baru. */
    suspend fun updateEngine(): String?
}
