package dev.mrksvt.reelsdownloader.data

import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.ResultType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.coroutines.resume

/** Hasil penyimpanan ke galeri. */
data class SavedMedia(val uri: Uri, val path: String)

/**
 * Menyimpan hasil unduhan ke galeri (FR-109).
 *
 * API 29+ memakai MediaStore + `RELATIVE_PATH` (scoped storage, tanpa izin).
 * API 26-28 menulis langsung ke direktori publik lalu memicu MediaScanner;
 * jalur legacy ini butuh `WRITE_EXTERNAL_STORAGE`.
 */
class MediaStoreWriter(private val appContext: Context) {

    suspend fun save(
        source: File,
        type: ResultType,
        displayName: String,
    ): SavedMedia = withContext(Dispatchers.IO) {
        if (!source.exists() || source.length() == 0L) {
            throw MediaSaveException(DownloadError.SaveFailed, "file sumber kosong")
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            saveScoped(source, type, displayName)
        } else {
            saveLegacy(source, type, displayName)
        }
    }

    private fun saveScoped(source: File, type: ResultType, displayName: String): SavedMedia {
        val resolver = appContext.contentResolver
        val isVideo = type == ResultType.VIDEO
        val collection = if (isVideo) {
            MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        } else {
            MediaStore.Audio.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        }
        val relativePath = if (isVideo) {
            "${Environment.DIRECTORY_MOVIES}/$FOLDER_NAME"
        } else {
            "${Environment.DIRECTORY_MUSIC}/$FOLDER_NAME"
        }
        val mimeType = if (isVideo) "video/mp4" else "audio/mpeg"

        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, displayName)
            put(MediaStore.MediaColumns.MIME_TYPE, mimeType)
            put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }

        val uri = resolver.insert(collection, values)
            ?: throw MediaSaveException(DownloadError.SaveFailed, "insert MediaStore gagal")

        try {
            resolver.openOutputStream(uri)?.use { output ->
                source.inputStream().use { input -> input.copyTo(output, DEFAULT_BUFFER) }
            } ?: throw MediaSaveException(DownloadError.SaveFailed, "stream output null")

            val done = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
            resolver.update(uri, done, null, null)
        } catch (error: Exception) {
            runCatching { resolver.delete(uri, null, null) }
            if (error is MediaSaveException) throw error
            throw MediaSaveException(DownloadError.SaveFailed, error.message, error)
        }

        return SavedMedia(uri = uri, path = "$relativePath/$displayName")
    }

    @Suppress("DEPRECATION")
    private suspend fun saveLegacy(
        source: File,
        type: ResultType,
        displayName: String,
    ): SavedMedia {
        val baseDir = Environment.getExternalStoragePublicDirectory(
            if (type == ResultType.VIDEO) Environment.DIRECTORY_MOVIES else Environment.DIRECTORY_MUSIC
        )
        val targetDir = File(baseDir, FOLDER_NAME).apply { mkdirs() }
        val target = File(targetDir, displayName)

        try {
            source.inputStream().use { input ->
                target.outputStream().use { output -> input.copyTo(output, DEFAULT_BUFFER) }
            }
        } catch (error: Exception) {
            runCatching { target.delete() }
            throw MediaSaveException(DownloadError.SaveFailed, error.message, error)
        }

        val uri = scanFile(target)
            ?: throw MediaSaveException(DownloadError.SaveFailed, "MediaScanner gagal")
        return SavedMedia(uri = uri, path = target.absolutePath)
    }

    private suspend fun scanFile(file: File): Uri? = suspendCancellableCoroutine { cont ->
        MediaScannerConnection.scanFile(
            appContext,
            arrayOf(file.absolutePath),
            null,
        ) { _, uri -> cont.resume(uri) }
    }

    /** Hapus file lewat MediaStore (API 29+) atau langsung (legacy). */
    suspend fun delete(uri: Uri?, path: String?): Boolean = withContext(Dispatchers.IO) {
        if (uri != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val rows = runCatching { appContext.contentResolver.delete(uri, null, null) }
                .getOrDefault(0)
            // 0 baris bisa berarti file sudah tidak ada (mis. dihapus dari
            // aplikasi Galeri). Anggap berhasil bila URI sudah tidak valid.
            rows > 0 || !exists(uri)
        } else {
            path?.let { runCatching { !File(it).exists() || File(it).delete() }.getOrDefault(false) }
                ?: false
        }
    }

    /** Apakah [uri] masih menunjuk ke file yang ada. */
    private fun exists(uri: Uri): Boolean = runCatching {
        appContext.contentResolver.openFileDescriptor(uri, "r")?.use { true } ?: false
    }.getOrDefault(false)

    private companion object {
        const val FOLDER_NAME = "ReelsDownloader"
        const val DEFAULT_BUFFER = 64 * 1024
    }
}

class MediaSaveException(
    val error: DownloadError,
    message: String? = null,
    cause: Throwable? = null,
) : Exception(message, cause)
