package dev.mrksvt.reelsdownloader.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface DownloadJobDao {

    @Query("SELECT * FROM download_jobs ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<DownloadJobEntity>>

    @Query(
        "SELECT * FROM download_jobs WHERE status IN ('QUEUED','RUNNING','SAVING') " +
            "ORDER BY createdAt ASC"
    )
    fun observeActive(): Flow<List<DownloadJobEntity>>

    @Query(
        "SELECT * FROM download_jobs WHERE status NOT IN ('QUEUED','RUNNING','SAVING') " +
            "ORDER BY createdAt DESC"
    )
    fun observeHistory(): Flow<List<DownloadJobEntity>>

    @Query("SELECT * FROM download_jobs WHERE id = :id")
    fun observeById(id: String): Flow<DownloadJobEntity?>

    @Query("SELECT * FROM download_jobs WHERE id = :id")
    suspend fun getById(id: String): DownloadJobEntity?

    @Query("SELECT * FROM download_jobs WHERE status IN ('FAILED','CANCELLED')")
    suspend fun getFailed(): List<DownloadJobEntity>

    @Query("SELECT * FROM download_jobs WHERE status NOT IN ('QUEUED','RUNNING','SAVING')")
    suspend fun getHistory(): List<DownloadJobEntity>

    @Query("DELETE FROM download_jobs WHERE status IN ('FAILED','CANCELLED')")
    suspend fun deleteFailed(): Int

    @Query("DELETE FROM download_jobs WHERE status NOT IN ('QUEUED','RUNNING','SAVING')")
    suspend fun deleteAllHistory(): Int

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(job: DownloadJobEntity)

    @Query("DELETE FROM download_jobs WHERE id = :id")
    suspend fun deleteById(id: String)

    @Query("UPDATE download_jobs SET status = :status, updatedAt = :now WHERE id = :id")
    suspend fun updateStatus(id: String, status: String, now: Long)

    @Query(
        "UPDATE download_jobs SET progress = :progress, speed = :speed, etaSeconds = :eta, " +
            "status = :status, updatedAt = :now WHERE id = :id"
    )
    suspend fun updateProgress(
        id: String,
        progress: Int,
        speed: String?,
        eta: Long?,
        status: String,
        now: Long,
    )
}
