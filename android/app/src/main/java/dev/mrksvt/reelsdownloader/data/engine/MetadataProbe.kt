package dev.mrksvt.reelsdownloader.data.engine

import android.content.Context
import android.util.Log
import com.fasterxml.jackson.databind.DeserializationFeature
import com.fasterxml.jackson.databind.ObjectMapper
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.mapper.VideoFormat
import com.yausername.youtubedl_android.mapper.VideoInfo
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.MediaPreview
import dev.mrksvt.reelsdownloader.domain.PreviewAssembler
import dev.mrksvt.reelsdownloader.util.CrashReporter
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicInteger

/**
 * Mengambil metadata untuk pratinjau (A18).
 *
 * Dipisah dari [DownloadEngine] karena tujuannya berbeda: kelas ini tidak
 * pernah menyentuh berkas, hanya bertanya "ini media apa" ke yt-dlp. Pemisahan
 * ini juga membuat jalur unduhan tidak ikut berubah saat pratinjau diubah.
 *
 * Biaya satu panggilan setara satu `yt-dlp --dump-json` (beberapa detik di HP),
 * jadi pemanggil wajib men-debounce dan menyimpan hasilnya.
 *
 * **Pratinjau tidak boleh mematikan aplikasi.** Karena itu seluruh badan
 * [probe] dibungkus `Throwable`: kegagalan pemetaan JSON, `NoSuchMethodError`
 * dari pustaka native, sampai `OutOfMemoryError` saat mem-parse JSON besar
 * semuanya berubah menjadi [EngineException] yang bisa ditampilkan sebagai
 * "pratinjau tidak tersedia".
 *
 * Catatan penting soal proses python: `YoutubeDL.getInfo()` memanggil
 * `execute(request, null, null)` dengan process id **null**, sehingga prosesnya
 * tidak terdaftar di `idProcessMap` dan `destroyProcessById` tidak bisa
 * menghentikannya. Saat probe macet, proses itu hidup terus dan menumpuk —
 * riwayat perangkat menunjukkan `REASON_LOW_MEMORY` berulang. Karena itu kelas
 * ini memanggil `execute()` dengan process id miliknya sendiri
 * ([processId]) dan menyediakan [cancelCurrent] untuk menghentikannya.
 */
class MetadataProbe(
    private val appContext: Context,
    private val engine: DownloadEngine,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) {

    /**
     * Serialisasi: setiap probe menjalankan proses python, dan dua proses
     * sekaligus hanya memperlambat keduanya tanpa manfaat.
     */
    private val mutex = Mutex()

    /**
     * Proses python yang sedang berjalan; `null` bila tidak ada.
     *
     * Disimpan supaya [cancelCurrent] bisa menghentikannya tanpa menunggu
     * timeout selesai.
     */
    @Volatile
    private var processId: String? = null

    /**
     * Ambil ringkasan media untuk [url].
     *
     * @throws EngineException bila yt-dlp tidak bisa membaca halaman; pemanggil
     *   yang memutuskan apakah kegagalan itu layak ditampilkan.
     */
    suspend fun probe(url: String): MediaPreview = withContext(ioDispatcher) {
        stage("preview:probe-start")
        val id = "preview-${COUNTER.incrementAndGet()}"
        try {
            // Runtime python harus siap; idempoten dan cepat bila sudah siap.
            engine.prepare()

            mutex.withLock {
                ensureActive()
                processId = id
                val info = fetchInfo(url, id)
                toPreview(url, info)
            }.also { stage("preview:probe-ok") }
        } catch (cancelled: CancellationException) {
            // Coroutine dibatalkan (URL berganti / ViewModel hilang). Proses
            // python-nya tidak ikut mati karena `execute` memblokir thread,
            // jadi harus dimatikan di sini.
            kill(id)
            stage("preview:probe-cancelled")
            throw cancelled
        } catch (engineError: EngineException) {
            stage("preview:probe-fail ${engineError.error}")
            // Bila coroutine sudah dibatalkan (URL berganti atau batas waktu
            // ViewModel), lempar CancellationException — bukan exception biasa
            // dari coroutine yang sudah mati.
            currentCoroutineContext().ensureActive()
            throw engineError
        } catch (error: Throwable) {
            // Jaring pengaman terakhir. Jangan pernah melempar apa pun selain
            // EngineException dari sini: pemanggilnya adalah coroutine UI, dan
            // exception yang lolos berarti aplikasi tertutup.
            stage("preview:probe-crash ${error::class.java.simpleName}")
            Log.e(TAG, "probe tidak terduga: $url", error)
            val wrapped = EngineException(
                DownloadError.fromEngineMessage(error.message),
                error.message,
                error,
            )
            currentCoroutineContext().ensureActive()
            throw wrapped
        } finally {
            if (processId == id) processId = null
        }
    }

    /**
     * Hentikan probe yang sedang berjalan.
     *
     * Dipakai saat menunggu terlalu lama atau saat URL berganti sebelum probe
     * selesai: tanpa ini thread IO tetap terblokir dan proses python tetap
     * memakan memori sampai sistem membunuh aplikasi.
     */
    fun cancelCurrent() {
        val id = processId ?: return
        stage("preview:probe-kill")
        kill(id)
    }

    private fun kill(id: String) {
        runCatching { engine.cancel(id) }
            .onFailure { Log.w(TAG, "Gagal menghentikan $id", it) }
    }

    /**
     * Jalankan `yt-dlp --dump-json` lalu petakan JSON-nya ke [VideoInfo].
     *
     * Sengaja tidak memakai `getInfo()`: fungsi itu memilih process id `null`
     * yang tidak bisa dihentikan (lihat dokumentasi kelas).
     */
    private fun fetchInfo(url: String, id: String): VideoInfo {
        val request = YoutubeDLRequest(url).apply {
            addOption("--dump-json")
            addOption("--no-playlist")
            addOption("--no-warnings")
            // Batas waktu jaringan di sisi yt-dlp. Tanpa ini, probe yang macet
            // bisa menggantung bermenit-menit.
            addOption("--socket-timeout", 15)
        }
        try {
            val response = YoutubeDL.getInstance().execute(request, id, null)
            val json = response.out
                ?.lineSequence()
                ?.map { it.trim() }
                ?.lastOrNull { it.startsWith("{") }
                ?: throw EngineException(DownloadError.NotFound, "metadata kosong")
            return MAPPER.readValue(json, VideoInfo::class.java)
        } catch (canceled: YoutubeDL.CanceledException) {
            throw EngineException(DownloadError.Cancelled, "probe dibatalkan", canceled)
        } catch (error: EngineException) {
            throw error
        } catch (error: Exception) {
            Log.w(TAG, "probe gagal: $url", error)
            throw EngineException(
                DownloadError.fromEngineMessage(error.message),
                error.message,
                error,
            )
        }
    }

    private fun toPreview(url: String, info: VideoInfo): MediaPreview {
        // `formats` bisa berisi entri null bila JSON-nya tidak rapi; satu entri
        // rusak tidak boleh menjatuhkan seluruh pratinjau.
        val formats = info.formats.orEmpty().mapNotNull { format ->
            runCatching { format.toRawFormat() }.getOrNull()
        }
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

    /**
     * Jejak langkah pratinjau. Ditulis di semua build karena build release
     * adalah satu-satunya yang terpasang di HP pengguna — tanpa ini kita tidak
     * punya cara mengetahui di mana proses berhenti.
     */
    private fun stage(name: String) = CrashReporter.stage(appContext, name)

    private companion object {
        const val TAG = "MetadataProbe"

        /** Penomoran proses agar id tidak bertabrakan dengan unduhan. */
        val COUNTER = AtomicInteger(0)

        /**
         * Pemeta JSON. `VideoInfo`/`VideoFormat` adalah model pustaka, jadi
         * properti yang tidak dikenal tidak boleh menggagalkan pembacaan.
         */
        val MAPPER = ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false)
    }
}
