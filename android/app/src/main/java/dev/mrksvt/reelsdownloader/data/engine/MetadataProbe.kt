package dev.mrksvt.reelsdownloader.data.engine

import android.util.Log
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.mapper.VideoFormat
import com.yausername.youtubedl_android.mapper.VideoInfo
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.MediaPreview
import dev.mrksvt.reelsdownloader.domain.PreviewAssembler
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Mengambil metadata untuk pratinjau (A18).
 *
 * Dipisah dari [DownloadEngine] karena tujuannya berbeda: kelas ini tidak
 * pernah menyentuh berkas, hanya bertanya "ini media apa" ke yt-dlp. Pemisahan
 * ini juga membuat jalur unduhan tidak ikut berubah saat pratinjau diubah.
 *
 * Biaya satu panggilan setara satu `yt-dlp --dump-json` (beberapa detik di HP),
 * jadi pemanggil wajib men-debounce dan menyimpan hasilnya.
 */
class MetadataProbe(
    private val engine: DownloadEngine,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) {

    /**
     * Serialisasi: setiap probe menjalankan proses python, dan dua proses
     * sekaligus hanya memperlambat keduanya tanpa manfaat.
     */
    private val mutex = Mutex()

    /**
     * Ambil ringkasan media untuk [url].
     *
     * @throws EngineException bila yt-dlp tidak bisa membaca halaman; pemanggil
     *   yang memutuskan apakah kegagalan itu layak ditampilkan.
     */
    suspend fun probe(url: String): MediaPreview = withContext(ioDispatcher) {
        // Runtime python harus siap; idempoten dan cepat bila sudah siap.
        engine.prepare()

        mutex.withLock {
            ensureActive()
            val info = try {
                // PENTING: getInfo() menambahkan `--dump-json` ke request yang
                // diberikan, jadi request ini tidak boleh dipakai ulang untuk
                // mengunduh.
                YoutubeDL.getInstance().getInfo(
                    YoutubeDLRequest(url).apply {
                        addOption("--no-playlist")
                        addOption("--no-warnings")
                    }
                )
            } catch (canceled: YoutubeDL.CanceledException) {
                throw EngineException(DownloadError.Cancelled, "probe dibatalkan", canceled)
            } catch (error: Exception) {
                Log.w(TAG, "probe gagal: $url", error)
                throw EngineException(
                    DownloadError.fromEngineMessage(error.message),
                    error.message,
                    error,
                )
            } ?: throw EngineException(DownloadError.NotFound, "metadata kosong")

            toPreview(url, info)
        }
    }

    private fun toPreview(url: String, info: VideoInfo): MediaPreview {
        val formats = info.formats.orEmpty().map { it.toRawFormat() }
        return PreviewAssembler.assemble(
            url = url,
            title = info.title?.takeIf { it.isNotBlank() } ?: info.fulltitle,
            uploader = info.uploader,
            durationSeconds = info.duration.takeIf { it > 0 },
            thumbnailUrl = bestThumbnail(info),
            extractor = info.extractor ?: info.extractorKey,
            // Sebagian ekstraktor (mis. Instagram) tidak memberi daftar
            // `formats`, hanya satu format terpilih di level atas. Tanpa
            // fallback ini kartu pratinjau kehilangan perkiraan ukuran.
            formats = formats.ifEmpty { listOf(topLevelFormat(info)) },
        )
    }

    private fun topLevelFormat(info: VideoInfo) = PreviewAssembler.RawFormat(
        height = info.height,
        videoCodec = "unknown",
        // Format level atas adalah berkas yang sudah lengkap (video+audio),
        // jadi ukurannya bisa dipakai apa adanya tanpa menambah audio lagi.
        audioCodec = "unknown",
        bytes = info.fileSize.takeIf { it > 0 } ?: info.fileSizeApproximate,
        // `VideoInfo` tidak membawa `tbr`, jadi ukuran hanya bisa dipakai bila
        // server benar-benar melaporkannya.
        bitrateKbps = 0,
    )

    /**
     * Thumbnail terbaik yang dilaporkan.
     *
     * `VideoThumbnail` tidak membawa ukuran, jadi urutan dari yt-dlp dipakai
     * apa adanya: entri terakhir biasanya yang terbesar.
     */
    private fun bestThumbnail(info: VideoInfo): String? =
        info.thumbnail?.takeIf { it.isNotBlank() }
            ?: info.thumbnails.orEmpty().lastOrNull()?.url?.takeIf { it.isNotBlank() }

    private fun VideoFormat.toRawFormat() = PreviewAssembler.RawFormat(
        height = height,
        videoCodec = vcodec,
        audioCodec = acodec,
        // `fileSize` = 0 saat server tidak mengirim Content-Length; angka
        // perkiraan yt-dlp masih lebih baik daripada tidak ada sama sekali.
        bytes = fileSize.takeIf { it > 0 } ?: fileSizeApproximate,
        // Video-only memakai `tbr`; audio-only sering hanya mengisi `abr`.
        bitrateKbps = tbr.takeIf { it > 0 } ?: abr,
    )

    private companion object {
        const val TAG = "MetadataProbe"
    }
}
