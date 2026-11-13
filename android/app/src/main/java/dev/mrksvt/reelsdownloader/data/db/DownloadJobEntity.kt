package dev.mrksvt.reelsdownloader.data.db

import androidx.room.Entity
import androidx.room.PrimaryKey
import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.JobStatus
import dev.mrksvt.reelsdownloader.domain.Platform
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType

/**
 * Satu baris = satu job unduhan, sekaligus riwayat (FR-110).
 *
 * Job aktif dan riwayat disatukan supaya progres dan riwayat memakai sumber
 * data yang sama; UI memfilter berdasarkan [status].
 */
@Entity(tableName = "download_jobs")
data class DownloadJobEntity(
    @PrimaryKey val id: String,
    val url: String,
    val platform: String,
    val type: String,
    val requestedQuality: String,
    val requestedBitrate: String,
    val actualQuality: String? = null,
    val title: String? = null,
    val status: String = JobStatus.QUEUED.name,
    val progress: Int = 0,
    val speed: String? = null,
    val etaSeconds: Long? = null,
    val errorName: String? = null,
    val uri: String? = null,
    val filePath: String? = null,
    val sizeBytes: Long = 0L,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis(),
) {
    val platformEnum: Platform? get() = Platform.fromId(platform)
    val typeEnum: ResultType get() = ResultType.fromName(type)
    val statusEnum: JobStatus get() = JobStatus.fromName(status)
    val qualityEnum: Quality get() = Quality.fromName(requestedQuality)
    val bitrateEnum: AudioBitrate get() = AudioBitrate.fromName(requestedBitrate)
}
