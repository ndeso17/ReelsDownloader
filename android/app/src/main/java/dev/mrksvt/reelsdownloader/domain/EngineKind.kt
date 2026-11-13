package dev.mrksvt.reelsdownloader.domain

/**
 * Engine yang bisa dipakai untuk satu unduhan (A17).
 *
 * [AUTO] dipakai UI sebagai default: coba yt-dlp dulu, lalu jatuh ke engine
 * cadangan bila ekstraktornya ketinggalan. Nilai yang tersimpan di riwayat
 * hanya [YT_DLP], [DIRECT], atau [WEB] — engine yang benar-benar dipakai.
 */
enum class EngineKind {
    /** UI: pilih otomatis (yt-dlp, lalu cadangan). */
    AUTO,

    /** yt-dlp on-device (engine utama). */
    YT_DLP,

    /** Unduh langsung dari URL media yang ditemukan (engine cadangan). */
    DIRECT,

    /** Ditemukan lewat browser mini (WebView) lalu diunduh engine cadangan. */
    WEB;

    companion object {
        /** Baris riwayat lama tidak punya nilai engine → dianggap yt-dlp. */
        fun fromName(value: String?): EngineKind =
            entries.firstOrNull { it.name == value && it != AUTO } ?: YT_DLP
    }
}
