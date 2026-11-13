package dev.mrksvt.reelsdownloader.data.engine

import android.content.Context
import android.util.Log
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.MediaSniffer
import dev.mrksvt.reelsdownloader.util.CrashReporter
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap
import kotlin.coroutines.coroutineContext

/**
 * Engine cadangan (A17-2): unduh langsung dari URL media tanpa yt-dlp.
 *
 * Dipakai saat ekstraktor yt-dlp ketinggalan (mis. platform mengubah struktur
 * halaman) padahal berkas medianya bisa diambil. Semangatnya sama dengan
 * 1DM/XDM: kenali tautan media, lalu unduh sendiri.
 *
 * Sengaja memakai [HttpURLConnection] bawaan, bukan OkHttp, supaya ukuran APK
 * tidak bertambah.
 *
 * Mendukung:
 * - progres dari `Content-Length`
 * - lanjut unduh (`Range`) bila koneksi terputus
 * - batas ukuran dari pengaturan
 *
 * Tidak mendukung (lihat docs/PLAN-BACKUP-ENGINE.md §8): DRM, login, DASH penuh.
 */
class DirectHttpEngine(
    private val appContext: Context,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : DownloadEngine {

    /** Handle koneksi aktif per job, supaya [cancel] bisa memutus segera. */
    private val connections = ConcurrentHashMap<String, HttpURLConnection>()

    override suspend fun prepare() = Unit

    override suspend fun engineVersion(): String? = "http/1.1"

    override suspend fun updateEngine(): String? = null

    override fun cancel(processId: String) {
        runCatching { connections.remove(processId)?.disconnect() }
        Remux.cancel(processId)
    }

    override suspend fun download(
        request: EngineRequest,
        onEvent: (DownloadEvent) -> Unit,
    ): EngineResult = withContext(ioDispatcher) {
        // Media URL diutamakan; kalau kosong berarti URL halaman → tidak bisa.
        val mediaUrl = request.mediaUrl ?: request.url
        val workDir = File(request.workDir, request.jobId).apply { mkdirs() }
        val partFile = File(workDir, "download.part")

        stage("direct:start ${request.jobId}")

        // URL media dari browser mini sudah pasti berkas media, jadi tidak perlu
        // probe. Probe hanya dipakai saat yang kita punya cuma URL halaman.
        val resolvedUrl = if (request.mediaUrl == null) {
            resolveMediaUrl(mediaUrl, request.jobId)
        } else {
            mediaUrl
        }

        onEvent(DownloadEvent.Metadata(title = null, actualQuality = null))

        // Manifest HLS tidak bisa disimpan sebagai berkas media; harus diunduh
        // lalu di-remux dulu. FFmpeg sudah ada di APK (dipakai yt-dlp), jadi
        // tidak ada komponen baru yang perlu ditambahkan.
        val result = if (isHls(mediaUrl, resolvedUrl)) {
            Remux.hlsToMp4(
                context = appContext,
                url = resolvedUrl,
                outFile = File(workDir, "${baseNameOf(resolvedUrl)}.mp4"),
                jobId = request.jobId,
                onPercent = { percent ->
                    onEvent(DownloadEvent.Progress(percent, null, null))
                },
            ).let { FetchResult(it.name, it) }
        } else {
            fetch(
                url = resolvedUrl,
                partFile = partFile,
                jobId = request.jobId,
                maxSizeBytes = request.maxSizeBytes,
                onProgress = { percent, _, _ ->
                    onEvent(DownloadEvent.Progress(percent, null, null))
                },
            )
        }

        val finalFile = result.file ?: File(workDir, result.fileName).also { target ->
            if (partFile.exists()) {
                if (target.exists()) target.delete()
                if (!partFile.renameTo(target)) {
                    partFile.copyTo(target, overwrite = true)
                    partFile.delete()
                }
            }
        }

        onEvent(DownloadEvent.Progress(percent = 100, speed = null, etaSeconds = null))
        stage("direct:done ${finalFile.name} ${finalFile.length()}")
        EngineResult(
            file = finalFile,
            title = null,
            actualQuality = null,
        )
    }

    /** [file] terisi bila berkas sudah jadi (jalur HLS); selain itu [fileName]. */
    private class FetchResult(val fileName: String, val file: File? = null)

    /** HLS/M3U8 perlu digabung FFmpeg, bukan disimpan apa adanya. */
    private fun isHls(original: String, resolved: String): Boolean =
        listOf(original, resolved).any { MediaSniffer.extensionOf(it) == "m3u8" }

    /** Nama berkas tanpa ekstensi, untuk dasar nama hasil remux. */
    private fun baseNameOf(url: String): String {
        val last = url.substringBefore('#').substringBefore('?').substringAfterLast('/')
        val base = last.substringBeforeLast('.', last)
        return base.replace(Regex("""[\\/:*?"<>|\n\r\t]"""), "_")
            .ifBlank { "media" }
            .take(60)
    }

    /**
     * Unduh [url] ke [partFile] dengan dukungan lanjut-unduh.
     *
     * Bila koneksi terputus, coba lagi dari posisi terakhir (maks 3 percobaan).
     */
    private suspend fun fetch(
        url: String,
        partFile: File,
        jobId: String,
        maxSizeBytes: Long,
        onProgress: (percent: Int, done: Long, total: Long) -> Unit,
    ): FetchResult {
        var attempt = 0
        var lastError: Exception? = null

        while (attempt < MAX_RETRIES) {
            attempt++
            coroutineContext.ensureActive()
            var connection: HttpURLConnection? = null
            try {
                val already = if (partFile.exists()) partFile.length() else 0L
                connection = (URL(url).openConnection() as HttpURLConnection).apply {
                    connectTimeout = CONNECT_TIMEOUT_MS
                    readTimeout = READ_TIMEOUT_MS
                    instanceFollowRedirects = true
                    requestMethod = "GET"
                    setRequestProperty("User-Agent", USER_AGENT)
                    setRequestProperty("Accept", "*/*")
                    if (already > 0) setRequestProperty("Range", "bytes=$already-")
                }
                connections[jobId] = connection

                val code = connection.responseCode
                if (code !in 200..299) {
                    throw EngineException(
                        mapHttpError(code),
                        "HTTP $code untuk $url",
                    )
                }

                val contentLength = connection.contentLengthLong
                val resuming = code == HttpURLConnection.HTTP_PARTIAL && already > 0
                val total = when {
                    resuming && contentLength > 0 -> already + contentLength
                    contentLength > 0 -> contentLength
                    else -> -1L
                }

                if (total > 0 && total > maxSizeBytes) {
                    throw EngineException(DownloadError.TooLarge, "ukuran $total melebihi batas")
                }

                val fileName = buildFileName(connection, url)

                RandomAccessFile(partFile, "rw").use { raf ->
                    if (resuming) raf.seek(already) else raf.setLength(0)

                    connection.inputStream.use { input ->
                        val buffer = ByteArray(BUFFER_SIZE)
                        var written = if (resuming) already else 0L
                        var lastReport = 0L

                        while (true) {
                            coroutineContext.ensureActive()
                            val read = input.read(buffer)
                            if (read <= 0) break
                            raf.write(buffer, 0, read)
                            written += read

                            if (written > maxSizeBytes) {
                                throw EngineException(
                                    DownloadError.TooLarge,
                                    "ukuran melebihi batas",
                                )
                            }

                            // Jangan spam UI: laporkan tiap ~200 ms atau tiap 1%.
                            if (total > 0) {
                                val percent = ((written * 100) / total).toInt().coerceIn(0, 100)
                                if (percent > lastReport) {
                                    lastReport = percent.toLong()
                                    onProgress(percent, written, total)
                                }
                            }
                        }

                        if (total > 0 && written < total) {
                            // Putus di tengah jalan: ulangi, lanjut dari posisi ini.
                            throw IOException("terputus di $written dari $total")
                        }
                    }
                }

                return FetchResult(fileName)
            } catch (canceled: kotlinx.coroutines.CancellationException) {
                throw EngineException(DownloadError.Cancelled, "dibatalkan", canceled)
            } catch (error: EngineException) {
                throw error
            } catch (error: Exception) {
                lastError = error
                Log.w(TAG, "Percobaan $attempt gagal untuk $url", error)
                stage("direct:retry-$attempt ${error::class.java.simpleName}")
                if (attempt >= MAX_RETRIES) break
            } finally {
                connections.remove(jobId)
                runCatching { connection?.disconnect() }
            }
        }

        throw EngineException(
            DownloadError.DownloadFailed,
            lastError?.message ?: "unduhan langsung gagal",
            lastError,
        )
    }

    /**
     * Ikuti redirect untuk menemukan tautan media asli.
     *
     * @throws EngineException bila halaman ternyata bukan berkas media (mis.
     *   HTML biasa) — lebih jelas daripada mengunduh halaman sebagai `.mp4`.
     */
    private fun resolveMediaUrl(pageUrl: String, jobId: String): String {
        var current = pageUrl
        repeat(MAX_REDIRECTS) {
            var connection: HttpURLConnection? = null
            try {
                connection = (URL(current).openConnection() as HttpURLConnection).apply {
                    connectTimeout = CONNECT_TIMEOUT_MS
                    readTimeout = READ_TIMEOUT_MS
                    instanceFollowRedirects = false
                    requestMethod = "HEAD"
                    setRequestProperty("User-Agent", USER_AGENT)
                }
                connections[jobId] = connection
                val code = connection.responseCode
                if (code in 300..399) {
                    val location = connection.getHeaderField("Location") ?: return current
                    current = URL(URL(current), location).toString()
                    return@repeat
                }
                if (code !in 200..299) {
                    throw EngineException(mapHttpError(code), "HTTP $code untuk $current")
                }

                val contentType = connection.contentType?.substringBefore(';')?.trim()
                // Media jelas (video/audio/HLS): inilah berkasnya.
                if (MediaSniffer.inspect(current, contentType) != null) return current

                // Bukan media: ini halaman. Tanpa `mediaUrl` dari browser mini
                // engine cadangan tidak bisa menebak berkas di dalamnya.
                throw EngineException(
                    DownloadError.NotFound,
                    "bukan berkas media (${contentType ?: "tanpa Content-Type"})",
                )
            } catch (error: EngineException) {
                throw error
            } catch (error: Exception) {
                Log.w(TAG, "resolve gagal", error)
                return current
            } finally {
                connections.remove(jobId)
                runCatching { connection?.disconnect() }
            }
        }
        return current
    }

    /** Nama berkas dari `Content-Disposition`, atau dari URL. */
    private fun buildFileName(connection: HttpURLConnection, url: String): String {
        val disposition = connection.getHeaderField("Content-Disposition")
        val fromHeader = disposition
            ?.substringAfter("filename=", "")
            ?.trim()
            ?.trim('"')
            ?.takeIf { it.isNotEmpty() }
        val raw = fromHeader ?: url.substringBefore('#').substringBefore('?')
            .substringAfterLast('/')
            .ifEmpty { "media" }
        val safe = raw.replace(Regex("""[\\/:*?"<>|\n\r\t]"""), "_").take(80)
        // Pastikan ada ekstensi supaya MediaStore bisa menebak tipe.
        return if (MediaSniffer.extensionOf(safe) == null) "$safe.mp4" else safe
    }

    private fun mapHttpError(code: Int): DownloadError = when (code) {
        401, 403 -> DownloadError.Private
        404, 410 -> DownloadError.NotFound
        413 -> DownloadError.TooLarge
        408, 504 -> DownloadError.Timeout
        else -> DownloadError.DownloadFailed
    }

    private fun stage(name: String) {
        CrashReporter.stage(appContext, name)
    }

    private companion object {
        const val TAG = "DirectHttpEngine"
        const val CONNECT_TIMEOUT_MS = 20_000
        const val READ_TIMEOUT_MS = 30_000
        const val BUFFER_SIZE = 64 * 1024
        const val MAX_RETRIES = 3
        const val MAX_REDIRECTS = 5
        const val USER_AGENT =
            "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 " +
                "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
    }
}
