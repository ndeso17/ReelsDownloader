package dev.mrksvt.reelsdownloader.data

import android.content.Context
import android.net.Uri
import dev.mrksvt.reelsdownloader.data.db.DownloadJobDao
import dev.mrksvt.reelsdownloader.data.db.DownloadJobEntity
import dev.mrksvt.reelsdownloader.domain.JobStatus
import dev.mrksvt.reelsdownloader.domain.Platform
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.worker.DownloadScheduler
import kotlinx.coroutines.flow.Flow
import java.util.UUID

/** Titik masuk tunggal untuk membuat/membatalkan/menghapus job (FR-107, FR-116). */
class DownloadRepository(
    private val appContext: Context,
    private val dao: DownloadJobDao,
    private val mediaStoreWriter: MediaStoreWriter,
) {

    val activeJobs: Flow<List<DownloadJobEntity>> = dao.observeActive()
    val history: Flow<List<DownloadJobEntity>> = dao.observeHistory()
    val allJobs: Flow<List<DownloadJobEntity>> = dao.observeAll()

    suspend fun start(
        url: String,
        platform: Platform,
        type: ResultType,
        quality: Quality,
        bitrate: AudioBitrate,
    ): String {
        val jobId = UUID.randomUUID().toString()
        val job = DownloadJobEntity(
            id = jobId,
            url = url,
            platform = platform.id,
            type = type.name,
            requestedQuality = quality.name,
            requestedBitrate = bitrate.name,
            status = JobStatus.QUEUED.name,
            createdAt = System.currentTimeMillis(),
            updatedAt = System.currentTimeMillis(),
        )
        dao.upsert(job)
        DownloadScheduler.enqueue(appContext, job)
        return jobId
    }

    fun cancel(jobId: String) {
        DownloadScheduler.cancel(appContext, jobId)
    }

    /** Ulangi job yang gagal/dibatalkan (FR-116). */
    suspend fun retry(job: DownloadJobEntity) {
        val fresh = job.copy(
            status = JobStatus.QUEUED.name,
            progress = 0,
            speed = null,
            etaSeconds = null,
            errorName = null,
            uri = null,
            filePath = null,
            sizeBytes = 0,
            updatedAt = System.currentTimeMillis(),
        )
        dao.upsert(fresh)
        DownloadScheduler.enqueue(appContext, fresh)
    }

    /** Hapus entri riwayat sekaligus file di galeri (FR-112). */
    suspend fun delete(job: DownloadJobEntity): Boolean {
        val uri = job.uri?.let { runCatching { Uri.parse(it) }.getOrNull() }
        val removed = mediaStoreWriter.delete(uri, job.filePath)
        dao.deleteById(job.id)
        // Entri tanpa file (mis. gagal) tidak punya apa pun untuk dihapus,
        // jadi tetap dianggap berhasil.
        return removed || (job.uri == null && job.filePath == null)
    }

    /** Hapus riwayat saja; file di galeri dibiarkan (FR-112b). */
    suspend fun forget(job: DownloadJobEntity) {
        dao.deleteById(job.id)
    }

    /** Hapus semua entri berstatus FAILED/CANCELLED beserta file sisa (jika ada). */
    suspend fun deleteFailed(): Int {
        val jobs = dao.getFailed()
        jobs.forEach { job ->
            val uri = job.uri?.let { runCatching { Uri.parse(it) }.getOrNull() }
            runCatching { mediaStoreWriter.delete(uri, job.filePath) }
        }
        return dao.deleteFailed()
    }

    /** Hapus seluruh riwayat (entri selesai) beserta filenya. */
    suspend fun deleteAllHistory(): Int {
        val jobs = dao.getHistory()
        jobs.forEach { job ->
            val uri = job.uri?.let { runCatching { Uri.parse(it) }.getOrNull() }
            runCatching { mediaStoreWriter.delete(uri, job.filePath) }
        }
        return dao.deleteAllHistory()
    }

    /** Hapus file galeri saja; entri riwayat tetap ada. */
    suspend fun deleteFile(job: DownloadJobEntity): Boolean {
        val uri = job.uri?.let { runCatching { Uri.parse(it) }.getOrNull() }
        val removed = mediaStoreWriter.delete(uri, job.filePath)
        // Jangan kosongkan referensi bila file benar-benar gagal dihapus,
        // supaya pengguna masih bisa mencoba lagi.
        if (!removed) return false
        dao.upsert(
            job.copy(
                uri = null,
                filePath = null,
                sizeBytes = 0,
                updatedAt = System.currentTimeMillis(),
            )
        )
        return true
    }

    /**
     * Hapus banyak entri sekaligus.
     *
     * @param withFile `true` menghapus berkas di galeri juga, `false` hanya
     *   menghapus entri riwayat dan membiarkan berkas tetap ada.
     * @return jumlah berkas yang benar-benar terhapus (0 bila [withFile] false).
     */
    suspend fun deleteMany(jobs: List<DownloadJobEntity>, withFile: Boolean): Int {
        var filesRemoved = 0
        jobs.forEach { job ->
            if (withFile) {
                val uri = job.uri?.let { runCatching { Uri.parse(it) }.getOrNull() }
                if (mediaStoreWriter.delete(uri, job.filePath)) filesRemoved++
            }
            dao.deleteById(job.id)
        }
        return filesRemoved
    }
}
