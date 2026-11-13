package dev.mrksvt.reelsdownloader.data.engine

import android.content.Context
import android.util.Log
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.util.CrashReporter
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale

/**
 * Engine yt-dlp on-device lewat `io.github.junkfood02.youtubedl-android` (WP-A4).
 *
 * Semua pemanggilan native dijalankan di [ioDispatcher] karena `execute`
 * memblokir thread sampai proses python selesai.
 */
class YtDlpEngine(
    private val appContext: Context,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : DownloadEngine {

    private val initMutex = Mutex()

    @Volatile
    private var prepared = false

    override suspend fun prepare() = withContext(ioDispatcher) {
        if (prepared) return@withContext
        initMutex.withLock {
            if (prepared) return@withLock
            try {
                stage("engine:init-ytdl-start")
                YoutubeDL.getInstance().init(appContext)
                stage("engine:init-ytdl-ok")
                FFmpeg.getInstance().init(appContext)
                stage("engine:init-ffmpeg-ok")
                prepared = true
            } catch (error: Exception) {
                Log.e(TAG, "Gagal menyiapkan engine", error)
                stage("engine:init-fail ${describe(error)}")
                throw EngineException(DownloadError.EngineMissing, error.message, error)
            }
        }
    }

    private fun stage(name: String) {
        CrashReporter.stage(appContext, name)
    }

    /**
     * Cari file hasil unduhan.
     *
     * Utamakan path yang dicetak `--print after_move:filepath`; bila tidak ada,
     * pindai direktori kerja secara rekursif (yt-dlp bisa membuat subfolder).
     */
    private fun locateResultFile(
        outDir: File,
        response: com.yausername.youtubedl_android.YoutubeDLResponse?,
    ): File? {
        response?.out
            ?.lineSequence()
            ?.map { it.trim() }
            ?.filter { it.startsWith("/") }
            ?.lastOrNull { File(it).isFile && File(it).length() > 0 }
            ?.let { return File(it) }

        return outDir.walkTopDown()
            .filter { it.isFile && it.length() > 0 }
            .filterNot { it.name.endsWith(".part") || it.name.endsWith(".ytdl") }
            .maxByOrNull { it.length() }
    }

    /** Detail untuk laporan: perintah, exit code, stderr, isi direktori. */
    private fun buildFailureDetail(
        response: com.yausername.youtubedl_android.YoutubeDLResponse?,
        outDir: File,
    ): String = buildString {
        append("hasil unduhan tidak ditemukan")
        if (response == null) return@buildString
        append("\nexit=").append(response.exitCode)
        append("\ncmd=").append(response.command.joinToString(" "))
        append("\nstdout=").append(response.out.takeLast(1500))
        append("\nstderr=").append(response.err.takeLast(3000))
        append("\nfiles=")
        append(
            outDir.walkTopDown().filter { it.isFile }
                .joinToString(", ") { "${it.name}(${it.length()})" }
                .ifBlank { "-" }
        )
    }

    /** Rangkum rantai cause agar akar masalah native terlihat di laporan. */
    private fun describe(error: Throwable): String = buildString {
        var current: Throwable? = error
        var depth = 0
        while (current != null && depth < 4) {
            if (depth > 0) append(" <- ")
            append(current::class.java.simpleName)
            append(": ")
            append(current.message?.take(160))
            current = current.cause
            depth++
        }
    }

    override suspend fun engineVersion(): String? = withContext(ioDispatcher) {
        if (!prepared) return@withContext null
        runCatching {
            YoutubeDL.getInstance()
                .execute(YoutubeDLRequest("").addOption("--version"), "engine-version")
                .out
                ?.trim()
                ?.lineSequence()
                ?.lastOrNull { it.isNotBlank() }
        }.getOrNull()
    }

    override fun cancel(processId: String) {
        runCatching { YoutubeDL.getInstance().destroyProcessById(processId) }
            .onFailure { Log.w(TAG, "Gagal membatalkan $processId", it) }
    }

    override suspend fun updateEngine(): String? = withContext(ioDispatcher) {
        prepare()
        try {
            YoutubeDL.getInstance().updateYoutubeDL(appContext, YoutubeDL.UpdateChannel.STABLE)
        } catch (error: Exception) {
            Log.e(TAG, "Gagal memperbarui engine", error)
            throw EngineException(DownloadError.EngineMissing, error.message, error)
        }
        engineVersion()
    }

    override suspend fun download(
        request: EngineRequest,
        onEvent: (DownloadEvent) -> Unit,
    ): EngineResult = withContext(ioDispatcher) {
        prepare()

        val outDir = File(request.workDir, request.jobId).apply { mkdirs() }

        // PENTING: getInfo() menambahkan `--dump-json` ke objek request yang
        // diberikan. Bila request yang sama dipakai untuk execute(), yt-dlp
        // hanya mencetak JSON, tidak mengunduh, dan tetap exit 0. Karena itu
        // probe metadata memakai request TERPISAH.
        stage("engine:getInfo-start")
        val title = runCatching {
            val probe = YoutubeDLRequest(request.url).apply {
                addOption("--no-playlist")
                addOption("--no-warnings")
            }
            YoutubeDL.getInstance().getInfo(probe)?.title
        }.getOrNull()?.takeIf { it.isNotBlank() }
        stage("engine:getInfo-done title=$title")
        onEvent(DownloadEvent.Metadata(title = title, actualQuality = null))

        val ytDlpRequest = buildRequest(request, outDir, singleFile = false, type = request.type)

        var response: com.yausername.youtubedl_android.YoutubeDLResponse? = null
        try {
            stage("engine:execute-start")
            response = YoutubeDL.getInstance()
                .execute(ytDlpRequest, request.jobId) { percent, etaSeconds, line ->
                    onEvent(
                        DownloadEvent.Progress(
                            percent = percent.coerceIn(0f, 100f).toInt(),
                            speed = parseSpeed(line),
                            etaSeconds = etaSeconds.takeIf { it > 0 },
                        )
                    )
                }
            stage("engine:execute-done exit=${response.exitCode}")
        } catch (canceled: YoutubeDL.CanceledException) {
            throw EngineException(DownloadError.Cancelled, "cancelled", canceled)
        } catch (error: Exception) {
            Log.w(TAG, "Unduhan gagal: ${request.url}", error)
            throw EngineException(
                DownloadError.fromEngineMessage(error.message),
                error.message,
                error,
            )
        }

        var file = locateResultFile(outDir, response)

        // Fallback: bila merge video+audio gagal (mis. ffmpeg tidak tersedia),
        // ulangi dengan format tunggal terbaik agar hasil tetap terkirim.
        if (file == null && request.type == ResultType.VIDEO) {
            stage("engine:retry-single-format")
            outDir.listFiles()?.forEach { it.delete() }
            runCatching {
                response = YoutubeDL.getInstance()
                    .execute(buildRequest(request, outDir, singleFile = true, type = request.type), request.jobId) { p, eta, line ->
                        onEvent(
                            DownloadEvent.Progress(
                                percent = p.coerceIn(0f, 100f).toInt(),
                                speed = parseSpeed(line),
                                etaSeconds = eta.takeIf { it > 0 },
                            )
                        )
                    }
                stage("engine:retry-done exit=${response?.exitCode}")
            }.onFailure { stage("engine:retry-fail ${describe(it)}") }
            file = locateResultFile(outDir, response)
        }

        val resolved = file
            ?: throw EngineException(
                DownloadError.fromEngineMessage(response?.err),
                buildFailureDetail(response, outDir),
            )

        if (resolved.length() > request.maxSizeBytes) {
            resolved.delete()
            throw EngineException(DownloadError.TooLarge, "ukuran melebihi batas")
        }

        onEvent(DownloadEvent.Progress(percent = 100, speed = null, etaSeconds = null))
        EngineResult(
            file = resolved,
            title = title,
            actualQuality = if (request.type == ResultType.VIDEO) {
                request.quality.height?.let { "${it}p" } ?: "Best"
            } else {
                "${request.bitrate.kbps} kbps"
            },
        )
    }

    /** Bangun request unduhan; [singleFile] true = format tunggal (fallback). */
    private fun buildRequest(
        request: EngineRequest,
        outDir: File,
        singleFile: Boolean,
        type: ResultType,
    ): YoutubeDLRequest = YoutubeDLRequest(request.url).apply {
        addOption("--no-playlist")
        addOption("--no-mtime")
        addOption("--newline")
        addOption("--no-warnings")
        addOption("--max-filesize", request.maxSizeBytes.toString())
        addOption("-P", outDir.absolutePath)
        addOption("-o", "%(id)s.%(ext)s")
        // Cetak path final setelah merge/postprocess, supaya kita tidak menebak
        // lokasi file hasil. `--print` menyiratkan --quiet dan --simulate,
        // jadi keduanya harus dinetralkan lagi.
        addOption("--print", "after_move:filepath")
        addOption("--no-simulate")
        addOption("--progress")
        when (type) {
            ResultType.VIDEO -> {
                addOption("-f", if (singleFile) "b" else videoFormat(request.quality.height))
                addOption("--merge-output-format", "mp4")
            }

            ResultType.AUDIO -> {
                addOption("-f", "ba/b")
                addOption("-x")
                addOption("--audio-format", "mp3")
                addOption("--audio-quality", "${request.bitrate.kbps}K")
            }
        }
    }

    private fun videoFormat(maxHeight: Int?): String {
        if (maxHeight == null) return "bv*+ba/b"
        return "bv*[height<=$maxHeight]+ba/b[height<=$maxHeight]/b"
    }

    /** Ambil kecepatan dari baris progres yt-dlp, mis. `... 2.35MiB/s ...`. */
    private fun parseSpeed(line: String?): String? {
        if (line.isNullOrBlank()) return null
        val match = SPEED_REGEX.find(line) ?: return null
        val value = match.groupValues[1].replace(',', '.')
        val unit = match.groupValues[2]
        val number = value.toDoubleOrNull() ?: return null
        return String.format(Locale.US, "%.1f %s/s", number, unit)
    }

    private companion object {
        const val TAG = "YtDlpEngine"
        val SPEED_REGEX = Regex("""([\d.,]+)\s*([KMG]i?B)/s""")
    }
}
