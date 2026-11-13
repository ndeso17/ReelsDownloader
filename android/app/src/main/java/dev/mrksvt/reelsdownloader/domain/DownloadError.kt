package dev.mrksvt.reelsdownloader.domain

import androidx.annotation.StringRes
import dev.mrksvt.reelsdownloader.R

/**
 * Pemetaan error ramah, port dari `bot/app/services/errors.py` (FR-115).
 *
 * Teksnya identik dengan bot; hanya `UnsupportedUrl` yang sedikit berbeda karena
 * di app pesannya juga menyebut daftar platform (lihat `values/strings.xml`).
 * Detail teknis (pesan yt-dlp, path, stack trace) TIDAK pernah sampai ke UI.
 */
enum class DownloadError(@param:StringRes val messageRes: Int) {
    InvalidUrl(R.string.err_invalid_url),
    UnsupportedUrl(R.string.err_unsupported_url),
    Private(R.string.err_private),
    NotFound(R.string.err_not_found),
    DownloadFailed(R.string.err_download_failed),
    FfmpegFailed(R.string.err_ffmpeg),
    TooLarge(R.string.err_too_large),
    SaveFailed(R.string.err_save_failed),
    Timeout(R.string.err_timeout),
    NoNetwork(R.string.err_no_network),
    EngineMissing(R.string.err_engine_missing),
    Cancelled(R.string.job_cancelled);

    companion object {
        /**
         * Tebak error dari pesan mentah engine.
         *
         * yt-dlp tidak punya kode error terstruktur, jadi pencocokan dilakukan
         * pada potongan pesan yang stabil. Urutan penting: pola paling spesifik
         * lebih dulu.
         */
        fun fromEngineMessage(message: String?): DownloadError {
            val text = message?.lowercase().orEmpty()
            return when {
                text.isBlank() -> DownloadFailed
                "cancelled" in text || "canceled" in text -> Cancelled
                "private" in text || "login" in text || "sign in" in text ||
                    "age" in text && "restrict" in text || "members-only" in text -> Private
                // Cek FFmpeg lebih dulu: pesan "ffmpeg not found" juga memuat
                // "not found" dan tidak boleh jatuh ke NotFound.
                "ffmpeg" in text || "merging" in text || "postprocessing" in text -> FfmpegFailed
                "not available" in text || "not found" in text || "404" in text ||
                    "unavailable" in text || "does not exist" in text -> NotFound
                "timed out" in text || "timeout" in text -> Timeout
                "unable to download" in text || "connection" in text ||
                    "network" in text || "resolve host" in text -> NoNetwork
                "unsupported url" in text -> UnsupportedUrl
                else -> DownloadFailed
            }
        }
    }
}
