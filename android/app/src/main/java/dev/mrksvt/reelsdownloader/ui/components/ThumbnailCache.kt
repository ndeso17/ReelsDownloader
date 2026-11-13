package dev.mrksvt.reelsdownloader.ui.components

import android.content.ContentUris
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.util.LruCache
import android.util.Size
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Cache thumbnail video untuk tampilan galeri.
 *
 * API 29+ memakai `ContentResolver.loadThumbnail` (scoped storage, tanpa izin);
 * API 26-28 memakai `MediaStore.Video.Thumbnails`. Semua kegagalan menghasilkan
 * `null` supaya UI jatuh ke placeholder, bukan crash.
 */
object ThumbnailCache {

    /** Batas memori cache: 1/8 heap, minimal 8 MB. */
    private val maxBytes: Int = run {
        val heap = Runtime.getRuntime().maxMemory()
        (heap / 8).coerceIn(8L * 1024 * 1024, 48L * 1024 * 1024).toInt()
    }

    private val cache = object : LruCache<String, Bitmap>(maxBytes) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount
    }

    suspend fun load(context: Context, uri: Uri, sizePx: Int = 512): Bitmap? =
        withContext(Dispatchers.IO) {
            val key = "$uri@$sizePx"
            cache.get(key)?.let { return@withContext it }

            val bitmap = runCatching { decode(context, uri, sizePx) }.getOrNull()
            if (bitmap != null) cache.put(key, bitmap)
            bitmap
        }

    private fun decode(context: Context, uri: Uri, sizePx: Int): Bitmap? {
        val resolver = context.contentResolver
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            resolver.loadThumbnail(uri, Size(sizePx, sizePx), null)
        } else {
            @Suppress("DEPRECATION")
            MediaStore.Video.Thumbnails.getThumbnail(
                resolver,
                ContentUris.parseId(uri),
                MediaStore.Video.Thumbnails.MINI_KIND,
                null,
            )
        }
    }

    /** Panggil setelah file dihapus agar thumbnail lama tidak muncul lagi. */
    fun evict(uri: Uri?) {
        if (uri == null) return
        val prefix = uri.toString()
        cache.snapshot().keys
            .filter { it.startsWith(prefix) }
            .forEach { cache.remove(it) }
    }

    fun clear() = cache.evictAll()
}
