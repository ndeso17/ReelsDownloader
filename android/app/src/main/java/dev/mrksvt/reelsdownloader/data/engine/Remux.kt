package dev.mrksvt.reelsdownloader.data.engine

import android.content.Context
import android.util.Log
import com.yausername.ffmpeg.FFmpeg
import dev.mrksvt.reelsdownloader.domain.DownloadError
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.io.File
import java.util.concurrent.ConcurrentHashMap

/**
 * Penggabung HLS memakai FFmpeg yang sudah dibundel `youtubedl-android` (A17-3).
 *
 * Stream `.m3u8` bukan berkas media: isinya daftar segmen. Untuk mendapat satu
 * berkas yang bisa diputar, segmen harus diunduh lalu di-remux. FFmpeg sudah
 * ada di APK untuk kebutuhan yt-dlp, jadi tidak ada komponen baru — hanya
 * memanggilnya langsung.
 *
 * Lokasi yang dipakai sama dengan yang dipakai `youtubedl-android`:
 * - biner: `ApplicationInfo.nativeLibraryDir/libffmpeg.so`
 * - pustaka: hasil unzip `libffmpeg.zip.so` ke `noBackupFilesDir/.../packages/ffmpeg`
 */
object Remux {

    private const val TAG = "Remux"

    /** Proses aktif per job, supaya pembatalan bisa mematikan ffmpeg. */
    private val processes = ConcurrentHashMap<String, Process>()

    /**
     * Unduh + gabungkan [url] (HLS) menjadi berkas mp4 di [outFile].
     *
     * @param onPercent progres 0..100 bila durasi stream diketahui.
     * @throws EngineException bila ffmpeg tidak tersedia atau gagal.
     */
    suspend fun hlsToMp4(
        context: Context,
        url: String,
        outFile: File,
        jobId: String,
        onPercent: (Int) -> Unit,
    ): File {
        // Inisialisasi idempoten: menyiapkan pustaka bersama + memastikan
        // `libffmpeg.so` ada di nativeLibraryDir.
        runCatching { FFmpeg.getInstance().init(context) }
            .onFailure { Log.w(TAG, "FFmpeg.init gagal", it) }

        val binary = File(context.applicationInfo.nativeLibraryDir, FFMPEG_BIN)
        // Pustaka bersama ffmpeg di-unzip `FFmpeg.init()` ke
        // noBackupFilesDir/youtubedl-android/packages/ffmpeg/usr/lib.
        val libDir = File(
            File(context.noBackupFilesDir, "youtubedl-android"),
            "packages/ffmpeg/usr/lib",
        )

        if (!binary.exists()) {
            throw EngineException(DownloadError.EngineMissing, "ffmpeg tidak ditemukan")
        }
        outFile.parentFile?.mkdirs()
        if (outFile.exists()) outFile.delete()

        val command = listOf(
            binary.absolutePath,
            "-hide_banner",
            "-nostdin",
            "-y",
            // Jaringan lambat + banyak segmen: beri kelonggaran.
            "-rw_timeout", "30000000",
            "-i", url,
            // Tanpa transcode: segmen HLS sudah berupa H.264/AAC.
            // `aac_adtstoasc` sengaja tidak dipaksa: muxer mp4 menambahkannya
            // sendiri untuk AAC, sedangkan memaksakannya gagal bila audio
            // stream ternyata bukan AAC (mis. mp3).
            "-c", "copy",
            "-movflags", "+faststart",
            outFile.absolutePath,
        )

        val builder = ProcessBuilder(command).redirectErrorStream(true)
        if (libDir.exists()) {
            val env = builder.environment()
            val current = env["LD_LIBRARY_PATH"].orEmpty()
            env["LD_LIBRARY_PATH"] = listOf(libDir.absolutePath, current)
                .filter { it.isNotBlank() }
                .joinToString(":")
        }

        val process = try {
            builder.start()
        } catch (error: Exception) {
            throw EngineException(
                DownloadError.FfmpegFailed,
                "gagal menjalankan ffmpeg: ${error.message}",
                error,
            )
        }

        processes[jobId] = process
        val tail = StringBuilder()
        var durationMs = -1L
        var lastPercent = -1

        try {
            process.inputStream.bufferedReader().useLines { lines ->
                for (line in lines) {
                    // Pembatalan dicek per baris progres: ffmpeg menulis cukup
                    // sering, dan prosesnya dimatikan di blok finally.
                    currentCoroutineContext().ensureActive()
                    if (tail.length < 4000) tail.appendLine(line.trim())
                    if (durationMs <= 0) durationMs = parseDurationMs(line)
                    val timeMs = parseTimeMs(line)
                    if (durationMs > 0 && timeMs >= 0) {
                        val percent = ((timeMs * 100) / durationMs).toInt().coerceIn(0, 99)
                        if (percent > lastPercent) {
                            lastPercent = percent
                            onPercent(percent)
                        }
                    }
                }
            }
            val exit = process.waitFor()
            if (exit != 0) {
                throw EngineException(
                    DownloadError.FfmpegFailed,
                    "ffmpeg keluar dengan kode $exit: ${tail.takeLast(400)}",
                )
            }
        } catch (canceled: InterruptedException) {
            throw EngineException(DownloadError.Cancelled, "dibatalkan", canceled)
        } finally {
            processes.remove(jobId)
            // Jangan tinggalkan proses yatim saat job dibatalkan.
            if (process.isAlive) process.destroy()
        }

        if (!outFile.exists() || outFile.length() <= 0L) {
            throw EngineException(
                DownloadError.FfmpegFailed,
                "hasil gabungan kosong: ${tail.takeLast(300)}",
            )
        }
        onPercent(100)
        return outFile
    }

    /** Hentikan ffmpeg milik [jobId] bila sedang berjalan. */
    fun cancel(jobId: String) {
        runCatching { processes.remove(jobId)?.destroy() }
    }

    private const val FFMPEG_BIN = "libffmpeg.so"

    /** Ambil `Duration: 00:01:23.45` dari keluaran ffmpeg. */
    private fun parseDurationMs(line: String): Long {
        val match = DURATION.find(line) ?: return -1L
        val (h, m, s) = match.destructured
        return toMillis(h, m, s)
    }

    /** Ambil `time=00:00:12.34` dari baris progres ffmpeg. */
    private fun parseTimeMs(line: String): Long {
        val match = TIME.find(line) ?: return -1L
        val (h, m, s) = match.destructured
        return toMillis(h, m, s)
    }

    private fun toMillis(h: String, m: String, s: String): Long {
        val seconds = s.toDoubleOrNull() ?: return -1L
        return ((h.toLongOrNull() ?: 0L) * 3600L + (m.toLongOrNull() ?: 0L) * 60L) * 1000L +
            (seconds * 1000).toLong()
    }

    private val DURATION = Regex("""Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)""")
    private val TIME = Regex("""time=(\d+):(\d+):(\d+(?:\.\d+)?)""")
}
