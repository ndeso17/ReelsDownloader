package dev.mrksvt.reelsdownloader.ui.components

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import dev.mrksvt.reelsdownloader.ui.icons.AppIcons
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Pemuat thumbnail dari jaringan untuk pratinjau (A18).
 *
 * Sengaja ditulis sendiri, bukan menambah pustaka pemuat gambar: kebutuhannya
 * hanya satu — gambar kecil di kartu pratinjau — dan APK sudah cukup besar
 * karena membawa yt-dlp + FFmpeg.
 */
object RemoteImageLoader {

    private const val MAX_BYTES = 4 * 1024 * 1024
    private const val TIMEOUT_MS = 8_000
    private const val USER_AGENT =
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"

    private val maxCacheBytes: Int = run {
        val heap = Runtime.getRuntime().maxMemory()
        (heap / 16).coerceIn(4L * 1024 * 1024, 24L * 1024 * 1024).toInt()
    }

    private val cache = object : LruCache<String, Bitmap>(maxCacheBytes) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount
    }

    /** Nilai cache, dipakai sebagai isi awal supaya tidak berkedip. */
    fun peek(url: String?): Bitmap? = url?.let { cache.get(keyOf(it)) }

    suspend fun load(url: String, maxPx: Int = 640): Bitmap? = withContext(Dispatchers.IO) {
        val key = keyOf(url)
        cache.get(key)?.let { return@withContext it }

        val bytes = runCatching { download(normalize(url)) }.getOrNull()
            ?: return@withContext null

        val bitmap = runCatching { decode(bytes, maxPx) }.getOrNull()
        if (bitmap != null) cache.put(key, bitmap)
        bitmap
    }

    /**
     * Beberapa ekstraktor masih memberi URL `http://`, sedangkan aplikasi
     * menolak cleartext. Hampir semua CDN thumbnail punya TLS, jadi naikkan
     * skemanya; bila ternyata tidak, pemuatan gagal dan placeholder dipakai.
     */
    private fun normalize(url: String): String =
        if (url.startsWith("http://", ignoreCase = true)) "https://" + url.substring(7) else url

    private fun keyOf(url: String): String = normalize(url)

    private fun download(url: String): ByteArray {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", USER_AGENT)
            setRequestProperty("Accept", "image/*")
        }
        try {
            if (connection.responseCode !in 200..299) {
                throw IllegalStateException("HTTP ${connection.responseCode}")
            }
            connection.inputStream.use { stream ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(16 * 1024)
                while (true) {
                    val read = stream.read(buffer)
                    if (read < 0) break
                    output.write(buffer, 0, read)
                    // Batas keras: ini hanya thumbnail, bukan media.
                    if (output.size() > MAX_BYTES) break
                }
                return output.toByteArray()
            }
        } finally {
            runCatching { connection.disconnect() }
        }
    }

    private fun decode(bytes: ByteArray, maxPx: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

        var sample = 1
        while (bounds.outWidth / (sample * 2) >= maxPx || bounds.outHeight / (sample * 2) >= maxPx) {
            sample *= 2
        }

        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
    }
}

/**
 * Thumbnail pratinjau dengan placeholder yang tenang.
 *
 * Tidak ada indikator memuat: gambar ini pelengkap, bukan hal yang ditunggu
 * pengguna. Placeholder abu-abu lebih baik daripada spinner yang berkedip.
 */
@Composable
fun RemoteThumbnail(
    url: String?,
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
) {
    val bitmap by produceState<Bitmap?>(initialValue = null, key1 = url) {
        // Nilai awal diambil di dalam producer, bukan lewat `initialValue`,
        // supaya thumbnail lama tidak tertinggal sesaat saat URL berganti.
        value = RemoteImageLoader.peek(url)
        if (url != null && value == null) value = RemoteImageLoader.load(url)
    }

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant),
        contentAlignment = Alignment.Center,
    ) {
        val image = bitmap
        if (image != null) {
            Image(
                bitmap = image.asImageBitmap(),
                contentDescription = contentDescription,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
            )
        } else {
            Icon(
                imageVector = AppIcons.Movie,
                contentDescription = null,
                modifier = Modifier.size(32.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
