package dev.mrksvt.reelsdownloader.data.engine

import android.util.Log
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.EngineKind

/**
 * Hasil unduhan beserta engine yang benar-benar dipakai.
 *
 * Engine dikembalikan per panggilan (bukan field bersama pada router) supaya
 * dua job yang berjalan bersamaan tidak saling menimpa catatan asalnya —
 * riwayat harus jujur soal engine mana yang berhasil.
 */
data class RoutedResult(
    val result: EngineResult,
    val engine: EngineKind,
)

/**
 * Pemilih engine (A17-4).
 *
 * Mode [EngineKind.AUTO] mencoba yt-dlp lebih dulu; bila gagal dengan error
 * yang menandakan ekstraktor ketinggalan, unduhan diulang lewat engine
 * cadangan memakai [EngineRequest.mediaUrl] bila tersedia.
 *
 * Kalau engine cadangan juga tidak punya URL media, kegagalan asli yt-dlp yang
 * dilaporkan — pesannya lebih informatif bagi pengguna.
 */
class EngineRouter(
    private val ytDlp: DownloadEngine,
    private val direct: DownloadEngine,
) {

    suspend fun prepare(kind: EngineKind = EngineKind.AUTO) {
        when (kind) {
            EngineKind.DIRECT, EngineKind.WEB -> direct.prepare()
            EngineKind.YT_DLP -> ytDlp.prepare()
            EngineKind.AUTO -> ytDlp.prepare()
        }
    }

    /**
     * Jalankan unduhan sesuai [kind].
     *
     * @throws EngineException kegagalan yang sudah dipetakan ke domain.
     */
    suspend fun download(
        kind: EngineKind,
        request: EngineRequest,
        onEvent: (DownloadEvent) -> Unit,
    ): RoutedResult {
        when (kind) {
            EngineKind.DIRECT -> return RoutedResult(
                direct.download(request, onEvent),
                EngineKind.DIRECT,
            )

            EngineKind.WEB -> return RoutedResult(
                direct.download(request, onEvent),
                EngineKind.WEB,
            )

            EngineKind.YT_DLP -> return RoutedResult(
                ytDlp.download(request, onEvent),
                EngineKind.YT_DLP,
            )

            EngineKind.AUTO -> Unit // ditangani di bawah
        }

        // --- AUTO ---------------------------------------------------------
        val primaryFailure = try {
            return RoutedResult(ytDlp.download(request, onEvent), EngineKind.YT_DLP)
        } catch (error: EngineException) {
            if (error.error == DownloadError.Cancelled) throw error
            if (!shouldFallback(error.error)) throw error
            Log.i(TAG, "yt-dlp gagal (${error.error}), pertimbangkan engine cadangan")
            error
        }

        // Tanpa URL media, engine cadangan tidak punya bahan: laporkan kegagalan
        // utama karena pesannya lebih menjelaskan (mis. "video tidak tersedia").
        if (request.mediaUrl.isNullOrBlank()) throw primaryFailure

        return try {
            RoutedResult(direct.download(request, onEvent), EngineKind.DIRECT)
        } catch (error: EngineException) {
            if (error.error == DownloadError.Cancelled) throw error
            Log.w(TAG, "engine cadangan juga gagal: ${error.error}")
            // Laporkan kegagalan utama: biasanya lebih menjelaskan sebabnya.
            throw primaryFailure
        }
    }

    fun cancel(kind: EngineKind, processId: String) {
        runCatching { ytDlp.cancel(processId) }
        runCatching { direct.cancel(processId) }
    }

    suspend fun engineVersion(): String? = ytDlp.engineVersion()

    suspend fun updateEngine(): String? = ytDlp.updateEngine()

    /** Error yang berarti "coba jalur lain masih masuk akal". */
    private fun shouldFallback(error: DownloadError): Boolean = when (error) {
        DownloadError.DownloadFailed,
        DownloadError.UnsupportedUrl,
        DownloadError.NotFound,
        DownloadError.FfmpegFailed,
        DownloadError.InvalidUrl,
        -> true

        else -> false
    }

    private companion object {
        const val TAG = "EngineRouter"
    }
}
