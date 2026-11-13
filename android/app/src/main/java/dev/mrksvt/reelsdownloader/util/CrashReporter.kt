package dev.mrksvt.reelsdownloader.util

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Perekam crash untuk build yang dipasang manual.
 *
 * Tiga sumber data:
 * 1. `Thread.setDefaultUncaughtExceptionHandler` - exception Java yang tidak
 *    tertangkap (proses masih hidup sesaat, jadi bisa langsung ditulis).
 * 2. `ActivityManager.getHistoricalProcessExitReasons` (API 30+) - alasan
 *    proses mati sebelumnya, termasuk **native crash** yang tidak bisa
 *    ditangkap handler Java.
 * 3. Breadcrumb [stage] - jejak langkah terakhir di `filesDir`, sehingga kita
 *    tahu di mana proses berhenti bila mati mendadak.
 *
 * Laporan ditulis ke `Download/reels-crashlog.txt` lewat MediaStore agar bisa
 * dibaca tanpa adb. Dipasang di **semua** build: APK release adalah satu-satunya
 * yang terpasang di HP pengguna, dan tanpa laporan dari build itu setiap crash
 * hanya terlihat sebagai "aplikasi berhenti" tanpa petunjuk. Isi laporan hanya
 * diagnostik (tahap terakhir, stack trace, info perangkat) — tidak ada isi
 * unduhan, URL, atau data pribadi.
 */
object CrashReporter {

    private const val TAG = "CrashReporter"
    private const val TRACE_FILE = "stage-trace.txt"
    private const val REPORT_NAME = "reels-crashlog.txt"
    private const val MAX_TRACE_LINES = 400

    /** Batas umur catatan crash agar tidak mematikan pratinjau selamanya. */
    private const val RECENT_EXIT_MS = 10 * 60 * 1000L

    fun install(context: Context) {
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            runCatching {
                val trace = readTrace(context)
                val report = buildString {
                    appendLine("=== UNCAUGHT ${timestamp()} ===")
                    appendLine(deviceInfo())
                    appendLine("thread=${thread.name}")
                    appendLine(error.stackTraceToString().take(20_000))
                    appendLine("--- stage trace ---")
                    append(trace)
                }
                writeReport(context, report)
            }
            previous?.uncaughtException(thread, error)
        }
    }

    /** Catat satu langkah; dipanggil di titik-titik penting alur unduhan. */
    fun stage(context: Context, name: String) {
        runCatching {
            val file = File(context.filesDir, TRACE_FILE)
            file.appendText("${timestamp()}  $name\n")
            if (file.length() > 64 * 1024) {
                val lines = file.readLines().takeLast(MAX_TRACE_LINES)
                file.writeText(lines.joinToString("\n", postfix = "\n"))
            }
        }
    }

    /**
     * Dipanggil saat app dibuka. Menulis laporan bila ada jejak crash/exit
     * bermasalah dari proses sebelumnya.
     */
    fun dumpOnStart(context: Context) {
        val trace = readTrace(context)
        val exits = exitInfo(context)
        if (exits.isBlank()) {
            // Tidak ada yang perlu dilaporkan. Bersihkan jejak supaya laporan
            // berikutnya hanya memuat sesi yang benar-benar bermasalah.
            runCatching { File(context.filesDir, TRACE_FILE).writeText("") }
            return
        }

        val report = buildString {
            appendLine("=== STARTUP REPORT ${timestamp()} ===")
            appendLine(deviceInfo())
            if (exits.isNotBlank()) {
                appendLine("--- previous process exits ---")
                appendLine(exits)
            }
            appendLine("--- stage trace ---")
            append(trace)
        }
        writeReport(context, report)
        runCatching { File(context.filesDir, TRACE_FILE).writeText("") }
    }

    /**
     * Tulis laporan kegagalan job SEJATARNYA saat terjadi, tanpa menunggu
     * restart aplikasi. Dipakai worker saat unduhan gagal.
     */
    fun recordFailure(context: Context, tag: String, error: Throwable?) {
        runCatching {
            val report = buildString {
                appendLine("=== FAILURE $tag ${timestamp()} ===")
                appendLine(deviceInfo())
                appendLine("--- engine environment ---")
                appendLine(engineSnapshot(context))
                if (error != null) {
                    appendLine("--- error chain ---")
                    appendLine(describeChain(error))
                    appendLine("--- stacktrace ---")
                    appendLine(error.stackTraceToString().take(20_000))
                }
                appendLine("--- stage trace ---")
                append(readTrace(context))
            }
            writeReport(context, report)
        }
    }

    /** Apakah runtime python/ffmpeg benar-benar ter-ekstrak ke disk. */
    private fun engineSnapshot(context: Context): String = buildString {
        val nativeDir = context.applicationInfo.nativeLibraryDir
        appendLine("nativeLibraryDir=$nativeDir")
        listOf("libpython.so", "libpython.zip.so", "libffmpeg.so", "libffmpeg.zip.so", "libqjs.so")
            .forEach { name ->
                val file = File(nativeDir, name)
                appendLine("  $name exists=${file.exists()} size=${file.length()}")
            }
        val packages = File(File(context.noBackupFilesDir, "youtubedl-android"), "packages")
        appendLine("packagesDir=$packages exists=${packages.exists()}")
        runCatching {
            packages.listFiles()?.take(20)?.forEach { appendLine("  pkg ${it.name}") }
        }
        val pythonBin = File(packages, "python")
        appendLine("pythonDir exists=${pythonBin.exists()}")
        runCatching {
            File(pythonBin, "bin").listFiles()?.take(10)?.forEach { appendLine("  bin ${it.name}") }
        }
    }

    private fun describeChain(error: Throwable): String = buildString {
        var current: Throwable? = error
        var depth = 0
        while (current != null && depth < 6) {
            if (depth > 0) appendLine()
            append("[").append(depth).append("] ")
            append(current::class.java.name).append(": ")
            append(current.message)
            current = current.cause
            depth++
        }
    }

    private fun readTrace(context: Context): String = runCatching {
        File(context.filesDir, TRACE_FILE).readText().takeLast(32_000)
    }.getOrDefault("")

    /** Apakah ada catatan proses keluar bermasalah yang masih relevan. */
    fun hasRecentProblemExit(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return false
        val manager = context.getSystemService(ActivityManager::class.java) ?: return false
        val problemReasons = setOf(
            ApplicationExitInfo.REASON_CRASH,
            ApplicationExitInfo.REASON_CRASH_NATIVE,
            ApplicationExitInfo.REASON_ANR,
            ApplicationExitInfo.REASON_LOW_MEMORY,
            ApplicationExitInfo.REASON_SIGNALED,
            ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE,
        )
        return runCatching {
            manager.getHistoricalProcessExitReasons(context.packageName, 0, 5)
                .any {
                    it.reason in problemReasons &&
                        // Hanya kejadian baru; catatan lama tidak boleh
                        // mematikan pratinjau selamanya.
                        System.currentTimeMillis() - it.timestamp < RECENT_EXIT_MS
                }
        }.onFailure { Log.w(TAG, "exit info gagal dibaca", it) }
            .getOrDefault(false)
    }

    /**
     * Riwayat proses mati yang **bermasalah** saja.
     *
     * `getHistoricalProcessExitReasons` selalu berisi entri (setiap kali
     * aplikasi ditutup pengguna pun tercatat), jadi tanpa penyaringan laporan
     * akan ditulis setiap kali aplikasi dibuka.
     */
    private fun exitInfo(context: Context): String {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return ""
        val manager = context.getSystemService(ActivityManager::class.java) ?: return ""
        // Konstanta REASON_* baru ada di API 30, jadi disusun setelah guard di
        // atas; menyimpannya sebagai properti objek akan crash di Android 8-10.
        val problemReasons = setOf(
            ApplicationExitInfo.REASON_CRASH,
            ApplicationExitInfo.REASON_CRASH_NATIVE,
            ApplicationExitInfo.REASON_ANR,
            ApplicationExitInfo.REASON_SIGNALED,
            ApplicationExitInfo.REASON_LOW_MEMORY,
            ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE,
            ApplicationExitInfo.REASON_INITIALIZATION_FAILURE,
        )
        return runCatching {
            manager.getHistoricalProcessExitReasons(context.packageName, 0, 10)
                .filter { it.reason in problemReasons }
                .take(5)
                .joinToString("\n\n") { describe(it) }
        }.onFailure { Log.w(TAG, "exit info gagal dibaca", it) }
            .getOrDefault("")
    }

    private fun describe(info: ApplicationExitInfo): String = buildString {
        append("reason=").append(reasonName(info.reason))
        append(" ts=").append(timestamp(info.timestamp))
        append(" importance=").append(info.importance)
        append(" desc=").append(info.description ?: "-")
        info.status?.let { append(" status=").append(it) }
        runCatching {
            info.traceInputStream?.bufferedReader()?.use { reader ->
                val text = reader.readText().take(20_000)
                if (text.isNotBlank()) {
                    append("\ntrace:\n").append(text)
                }
            }
        }
    }

    private fun reasonName(reason: Int): String = when (reason) {
        ApplicationExitInfo.REASON_CRASH -> "CRASH"
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "CRASH_NATIVE"
        ApplicationExitInfo.REASON_ANR -> "ANR"
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE -> "INIT_FAILURE"
        ApplicationExitInfo.REASON_LOW_MEMORY -> "LOW_MEMORY"
        ApplicationExitInfo.REASON_SIGNALED -> "SIGNALED"
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE -> "RESOURCE_USAGE"
        ApplicationExitInfo.REASON_USER_REQUESTED -> "USER_REQUESTED"
        ApplicationExitInfo.REASON_EXIT_SELF -> "EXIT_SELF"
        ApplicationExitInfo.REASON_OTHER -> "OTHER"
        else -> reason.toString()
    }

    private fun deviceInfo(): String = buildString {
        append("device=").append(Build.MANUFACTURER).append(' ').append(Build.MODEL)
        append(" android=").append(Build.VERSION.RELEASE)
        append(" sdk=").append(Build.VERSION.SDK_INT)
        append(" abis=").append(Build.SUPPORTED_ABIS.joinToString(","))
        append(" pageSize=").append(runCatching { android.system.Os.sysconf(android.system.OsConstants._SC_PAGESIZE) }.getOrDefault(0))
    }

    private fun writeReport(context: Context, report: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            writeViaMediaStore(context, report)
        } else {
            runCatching {
                File(context.getExternalFilesDir(null), REPORT_NAME).writeText(report)
            }
        }
    }

    private fun writeViaMediaStore(context: Context, report: String) {
        val resolver = context.contentResolver
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)

        // Hapus laporan lama agar hanya ada satu berkas terbaru.
        runCatching {
            resolver.delete(
                collection,
                "${MediaStore.MediaColumns.DISPLAY_NAME}=?",
                arrayOf(REPORT_NAME),
            )
        }

        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, REPORT_NAME)
            put(MediaStore.MediaColumns.MIME_TYPE, "text/plain")
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = resolver.insert(collection, values) ?: return
        runCatching {
            resolver.openOutputStream(uri)?.use { it.write(report.toByteArray()) }
            val done = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
            resolver.update(uri, done, null, null)
        }.onFailure { Log.e(TAG, "gagal menulis laporan", it) }
    }

    private fun timestamp(): String =
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US).format(Date())

    private fun timestamp(millis: Long): String =
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US).format(Date(millis))
}
