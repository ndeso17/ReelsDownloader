package dev.mrksvt.reelsdownloader.worker

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import dev.mrksvt.reelsdownloader.ReelsDownloaderApp
import dev.mrksvt.reelsdownloader.data.MediaSaveException
import dev.mrksvt.reelsdownloader.data.db.DownloadJobDao
import dev.mrksvt.reelsdownloader.data.db.DownloadJobEntity
import dev.mrksvt.reelsdownloader.data.engine.DownloadEvent
import dev.mrksvt.reelsdownloader.data.engine.EngineException
import dev.mrksvt.reelsdownloader.data.engine.EngineRequest
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.EngineKind
import dev.mrksvt.reelsdownloader.domain.JobStatus
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.util.CrashReporter
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Satu job unduhan = satu unique work (WP-A5).
 *
 * Worker memegang siklus hidup job: status di Room, progres notifikasi,
 * penyimpanan ke galeri, dan cleanup file sementara di blok `finally`
 * (FR-111, FR-113).
 */
class DownloadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    private val container = (appContext as ReelsDownloaderApp).container

    override suspend fun doWork(): Result = coroutineScope {
        val jobId = inputData.getString(KEY_JOB_ID) ?: return@coroutineScope Result.failure()
        val dao = container.database.downloadJobDao()
        val router = container.engineRouter
        val writer = container.mediaStoreWriter

        stage("worker:start $jobId")
        DownloadNotifications.ensureChannel(applicationContext)

        val job = dao.getById(jobId) ?: return@coroutineScope Result.failure()
        if (job.statusEnum.isActive.not() && job.statusEnum != JobStatus.QUEUED) {
            return@coroutineScope Result.success()
        }

        val displayTitle = job.title ?: job.url
        // Engine yang diminta lewat WorkManager; AUTO bisa berubah saat
        // berjalan (router memutuskan cadangan atau tidak).
        val kind = inputData.getString(KEY_ENGINE)
            ?.let { name -> EngineKind.entries.firstOrNull { it.name == name } }
            ?: job.engineEnum
        // Notifikasi progres bersifat best-effort: bila OEM menolak foreground
        // service, unduhan tetap harus jalan (FR-111 tidak boleh memblokir job).
        runCatching {
            setForeground(
                DownloadNotifications.foregroundInfo(
                    applicationContext,
                    jobId,
                    displayTitle,
                    0,
                    indeterminate = true,
                )
            )
        }.onFailure { stage("worker:setForeground-fail ${it::class.java.simpleName}: ${it.message}") }
        stage("worker:foreground-ok")
        dao.updateProgress(
            jobId,
            0,
            null,
            null,
            JobStatus.RUNNING.name,
            System.currentTimeMillis(),
        )

        val workDir = File(applicationContext.cacheDir, "downloads")
        val settings = container.settingsRepository.settings.first()
        stage("worker:settings-loaded")
        val events = Channel<DownloadEvent>(Channel.CONFLATED)

        // Engine memanggil callback dari thread IO dan tidak boleh suspend,
        // jadi event dialirkan lewat channel ke coroutine terpisah.
        val eventProcessor = launch {
            var lastPercent = -1
            for (event in events) {
                when (event) {
                    is DownloadEvent.Metadata -> dao.upsert(
                        (dao.getById(jobId) ?: job).copy(
                            title = event.title ?: job.title,
                            actualQuality = event.actualQuality,
                            updatedAt = System.currentTimeMillis(),
                        )
                    )

                    is DownloadEvent.Progress -> {
                        if (event.percent == lastPercent) continue
                        lastPercent = event.percent
                        dao.updateProgress(
                            jobId,
                            event.percent,
                            event.speed,
                            event.etaSeconds,
                            JobStatus.RUNNING.name,
                            System.currentTimeMillis(),
                        )
                        runCatching {
                            setForeground(
                                DownloadNotifications.foregroundInfo(
                                    applicationContext,
                                    jobId,
                                    dao.getById(jobId)?.title ?: displayTitle,
                                    event.percent,
                                )
                            )
                        }
                    }
                }
            }
        }

        var acquired = false
        try {
            // Batas concurrency 2 (FR-107); job berlebih tetap QUEUED.
            container.downloadSlots.acquire()
            acquired = true
            stage("worker:engine-download-start")

            // Catat percobaan ke-n sebelum mulai, supaya riwayat bisa
            // menjelaskan berapa kali job ini dicoba.
            dao.bumpAttempts(jobId, System.currentTimeMillis())

            val routed = router.download(
                kind = kind,
                request = EngineRequest(
                    jobId = jobId,
                    url = job.url,
                    type = job.typeEnum,
                    quality = job.qualityEnum,
                    bitrate = job.bitrateEnum,
                    maxSizeBytes = settings.maxSizeBytes,
                    workDir = workDir,
                    mediaUrl = job.mediaUrl,
                ),
            ) { event -> events.trySend(event) }
            val result = routed.result

            // Simpan engine yang benar-benar dipakai (AUTO bisa jatuh ke
            // cadangan), sehingga entri riwayat jujur soal asalnya.
            dao.updateSource(
                id = jobId,
                engine = routed.engine.name,
                mediaUrl = job.mediaUrl,
                mimeType = job.mimeType,
                now = System.currentTimeMillis(),
            )

            events.close()
            eventProcessor.join()
            stage("worker:engine-download-ok")

            dao.updateProgress(
                jobId,
                100,
                null,
                null,
                JobStatus.SAVING.name,
                System.currentTimeMillis(),
            )
            val savingTitle = dao.getById(jobId)?.title ?: result.title ?: displayTitle
            runCatching {
                setForeground(
                    DownloadNotifications.foregroundInfo(
                        applicationContext,
                        jobId,
                        savingTitle,
                        100,
                        indeterminate = true,
                    )
                )
            }

            val displayName = buildDisplayName(result.file, job.typeEnum)
            stage("worker:save-start $displayName")
            val saved = writer.save(result.file, job.typeEnum, displayName)
            stage("worker:save-ok")
            val sizeBytes = result.file.length()

            val finished = dao.getById(jobId) ?: job
            dao.upsert(
                finished.copy(
                    status = JobStatus.DONE.name,
                    progress = 100,
                    title = result.title ?: finished.title,
                    actualQuality = result.actualQuality ?: finished.actualQuality,
                    uri = saved.uri.toString(),
                    filePath = saved.path,
                    sizeBytes = sizeBytes,
                    speed = null,
                    etaSeconds = null,
                    errorName = null,
                    updatedAt = System.currentTimeMillis(),
                )
            )
            DownloadNotifications.finishedNotification(
                applicationContext,
                jobId,
                result.title ?: displayTitle,
                success = true,
            )
            Result.success()
        } catch (cancelled: CancellationException) {
            events.close()
            withContext(NonCancellable) {
                // Hentikan proses yt-dlp native; cancellable coroutine saja tidak
                // cukup karena execute() memblokir thread IO.
                runCatching { router.cancel(kind, jobId) }
                markFinished(dao, jobId, JobStatus.CANCELLED, DownloadError.Cancelled)
                DownloadNotifications.cancel(applicationContext, jobId)
            }
            throw cancelled
        } catch (engineError: EngineException) {
            events.close()
            val status = if (engineError.error == DownloadError.Cancelled) {
                JobStatus.CANCELLED
            } else {
                JobStatus.FAILED
            }
            stage("worker:engine-fail ${engineError.error}")
            CrashReporter.recordFailure(applicationContext, "ENGINE", engineError)
            markFinished(dao, jobId, status, engineError.error)
            DownloadNotifications.finishedNotification(
                applicationContext,
                jobId,
                displayTitle,
                success = false,
            )
            Result.failure(workDataOf(KEY_ERROR to engineError.error.name))
        } catch (saveError: MediaSaveException) {
            events.close()
            stage("worker:save-fail ${saveError.error}")
            CrashReporter.recordFailure(applicationContext, "SAVE", saveError)
            markFinished(dao, jobId, JobStatus.FAILED, saveError.error)
            DownloadNotifications.finishedNotification(
                applicationContext,
                jobId,
                displayTitle,
                success = false,
            )
            Result.failure(workDataOf(KEY_ERROR to saveError.error.name))
        } catch (error: Exception) {
            events.close()
            stage("worker:unexpected ${error::class.java.simpleName}: ${error.message}")
            CrashReporter.recordFailure(applicationContext, "UNEXPECTED", error)
            markFinished(dao, jobId, JobStatus.FAILED, DownloadError.DownloadFailed)
            DownloadNotifications.finishedNotification(
                applicationContext,
                jobId,
                displayTitle,
                success = false,
            )
            Result.failure(workDataOf(KEY_ERROR to DownloadError.DownloadFailed.name))
        } finally {
            if (acquired) container.downloadSlots.release()
            eventProcessor.cancel()
            // Cleanup file sementara: sukses maupun gagal (FR-113).
            runCatching { File(workDir, jobId).deleteRecursively() }
        }
    }

    private fun stage(name: String) {
        CrashReporter.stage(applicationContext, name)
    }

    private suspend fun markFinished(
        dao: DownloadJobDao,
        jobId: String,
        status: JobStatus,
        error: DownloadError,
    ) {
        val current = dao.getById(jobId) ?: return
        dao.upsert(
            current.copy(
                status = status.name,
                errorName = error.name,
                speed = null,
                etaSeconds = null,
                updatedAt = System.currentTimeMillis(),
            )
        )
    }

    private fun buildDisplayName(source: File, type: ResultType): String {
        val extension = source.extension.takeIf { it.isNotBlank() }
            ?: if (type == ResultType.VIDEO) "mp4" else "mp3"
        val base = source.nameWithoutExtension.ifBlank { "reels_${System.currentTimeMillis()}" }
        val safe = base.replace(UNSAFE_CHARS, "_").trim().take(MAX_NAME_LENGTH)
        return "$safe.$extension"
    }

    companion object {
        const val KEY_JOB_ID = "job_id"

        /** Engine yang diminta (A17). Tidak disimpan di DB sebelum job berjalan. */
        const val KEY_ENGINE = "engine"
        const val KEY_ERROR = "error"
        private const val MAX_NAME_LENGTH = 80
        private val UNSAFE_CHARS = Regex("""[\\/:*?"<>|\n\r\t]""")

        fun uniqueWorkName(jobId: String) = "download_$jobId"
    }
}

/** Helper enqueue/cancel supaya UI tidak menyentuh WorkManager langsung. */
object DownloadScheduler {

    fun enqueue(context: Context, job: DownloadJobEntity, kind: EngineKind = EngineKind.AUTO) {
        val request = OneTimeWorkRequestBuilder<DownloadWorker>()
            .setInputData(
                workDataOf(
                    DownloadWorker.KEY_JOB_ID to job.id,
                    DownloadWorker.KEY_ENGINE to kind.name,
                )
            )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .addTag(job.id)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            DownloadWorker.uniqueWorkName(job.id),
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    fun cancel(context: Context, jobId: String) {
        WorkManager.getInstance(context)
            .cancelUniqueWork(DownloadWorker.uniqueWorkName(jobId))
    }
}
