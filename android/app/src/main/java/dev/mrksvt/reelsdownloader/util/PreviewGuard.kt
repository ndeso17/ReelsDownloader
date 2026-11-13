package dev.mrksvt.reelsdownloader.util

import android.content.Context

/**
 * Penjaga agar pratinjau tidak bisa membuat aplikasi berhenti berulang kali.
 *
 * Pratinjau menjalankan proses python (yt-dlp). Kegagalan di sisi Java sudah
 * ditangkap menjadi pesan "pratinjau tidak tersedia", tetapi **crash native**
 * dan **proses yang dimatikan sistem karena kehabisan memori** tidak bisa
 * ditangkap kode apa pun. Karena itu jejak "probe sedang berjalan" disimpan
 * sebelum probe dimulai: bila aplikasi dibuka lagi dan jejak itu masih ada
 * sementara sistem mencatat proses keluar yang bermasalah, pratinjau otomatis
 * dimatikan dan pengguna bisa menyalakannya lagi dengan satu ketukan.
 *
 * Unduhan tidak pernah terpengaruh.
 */
object PreviewGuard {

    private const val PREFS = "preview_guard"
    private const val KEY_IN_FLIGHT = "probe_in_flight"
    private const val KEY_DISABLED = "auto_preview_disabled"

    /** Tandai probe dimulai. */
    fun beginProbe(context: Context) {
        prefs(context).edit().putBoolean(KEY_IN_FLIGHT, true).apply()
    }

    /** Tandai probe selesai (berhasil maupun gagal dengan rapi). */
    fun endProbe(context: Context) {
        prefs(context).edit().putBoolean(KEY_IN_FLIGHT, false).apply()
    }

    /**
     * Dipanggil sekali saat aplikasi dibuka.
     *
     * @return `true` bila sesi sebelumnya berakhir saat probe berjalan **dan**
     *   sistem mencatat proses keluar yang bermasalah — yaitu pola crash yang
     *   disebabkan pratinjau.
     */
    fun checkAfterRestart(context: Context): Boolean {
        val inFlight = prefs(context).getBoolean(KEY_IN_FLIGHT, false)
        if (!inFlight) return false
        // Jejak lama dibersihkan; kalau prosesnya hanya ditutup pengguna,
        // pratinjau tetap boleh berjalan seperti biasa.
        endProbe(context)
        if (!CrashReporter.hasRecentProblemExit(context)) return false
        prefs(context).edit().putBoolean(KEY_DISABLED, true).apply()
        CrashReporter.stage(context, "preview:disabled-after-crash")
        return true
    }

    /** Apakah pratinjau boleh berjalan otomatis. */
    fun isAutoPreviewEnabled(context: Context): Boolean =
        !prefs(context).getBoolean(KEY_DISABLED, false)

    /** Nyalakan lagi setelah pengguna memintanya. */
    fun enableAutoPreview(context: Context) {
        prefs(context).edit().putBoolean(KEY_DISABLED, false).apply()
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
