package dev.mrksvt.reelsdownloader.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.mrksvt.reelsdownloader.ReelsDownloaderApp
import dev.mrksvt.reelsdownloader.domain.EngineKind
import dev.mrksvt.reelsdownloader.domain.MediaCandidate
import dev.mrksvt.reelsdownloader.domain.MediaSniffer
import dev.mrksvt.reelsdownloader.domain.Platform
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.domain.UrlValidator
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Satu kandidat media yang siap ditampilkan ke pengguna. */
data class BrowserCandidate(
    val url: String,
    val type: ResultType,
    val mimeType: String?,
    val contentLength: Long?,
    val isStream: Boolean,
    /** Asal halaman, dipakai untuk mendeteksi platform/kualitas. */
    val pageUrl: String,
) {
    /** Label unik untuk LazyColumn. */
    val key: String get() = "$pageUrl|$url"
}

data class BrowserUiState(
    val pageUrl: String = "",
    val candidates: List<BrowserCandidate> = emptyList(),
    /** Halaman sedang memuat. */
    val loading: Boolean = false,
    /** Snackbar sekali-tampil. */
    val message: BrowserMessage? = null,
)

sealed interface BrowserMessage {
    data object Queued : BrowserMessage
    data object Untrusted : BrowserMessage
    data object Failed : BrowserMessage

    /** URL ternyata bukan media (mis. halaman HTML). */
    data object NotMedia : BrowserMessage
}

/**
 * ViewModel untuk browser mini (A17-6).
 *
 * Tugasnya sempit: mengumpulkan kandidat media yang ditemukan WebView, lalu
 * meneruskannya ke [dev.mrksvt.reelsdownloader.data.DownloadRepository.start].
 * Penyimpanan berkas tetap di worker — layar ini tidak pernah menyentuh file.
 */
class BrowserViewModel(application: Application) : AndroidViewModel(application) {

    private val container = (application as ReelsDownloaderApp).container
    private val repository = container.downloadRepository

    private val _state = MutableStateFlow(BrowserUiState())
    val state: StateFlow<BrowserUiState> = _state.asStateFlow()

    /**
     * Periksa satu request yang lewat di WebView.
     *
     * Dipanggil dari thread IO WebView, jadi tidak boleh melakukan pekerjaan
     * berat. [MediaSniffer] murni dan murah.
     */
    fun onRequest(url: String, contentType: String?, contentLength: Long?, pageUrl: String) {
        // `range`/`?bytestart=` menandakan potongan berkas yang sama; menawarkan
        // semuanya hanya membuat daftar penuh duplikat.
        val candidate = MediaSniffer.inspect(url, contentType, contentLength) ?: return
        if (isRangeRequest(url, contentType)) return

        val entry = BrowserCandidate(
            url = candidate.url,
            type = candidate.type,
            mimeType = candidate.mimeType,
            contentLength = candidate.contentLength,
            isStream = candidate.isStream,
            pageUrl = pageUrl,
        )
        _state.update { current ->
            // Dedupe berdasarkan URL; segarkan metadata bila kali ini lebih lengkap.
            val existing = current.candidates.firstOrNull { it.url == entry.url }
            when {
                existing == null -> current.copy(candidates = current.candidates + entry)
                existing.contentLength == null && entry.contentLength != null ->
                    current.copy(
                        candidates = current.candidates.map {
                            if (it.url == entry.url) entry else it
                        }
                    )

                else -> current
            }
        }
    }

    fun onPageStarted(url: String) {
        _state.update { it.copy(pageUrl = url, loading = true) }
    }

    fun onPageFinished(url: String) {
        _state.update { it.copy(pageUrl = url, loading = false) }
    }

    /** Buang kandidat lama saat pindah halaman, supaya daftar tidak tercampur. */
    fun onPageChanged(url: String) {
        _state.update { it.copy(pageUrl = url, candidates = emptyList()) }
    }

    fun clearMessage() {
        _state.update { it.copy(message = null) }
    }

    /** Pindai ulang: buang kandidat lama, halaman tetap seperti sekarang. */
    fun clearCandidates() {
        _state.update { it.copy(candidates = emptyList(), message = null) }
    }

    /**
     * Antrekan unduhan dari kandidat terpilih.
     *
     * Selalu lewat repository supaya entri riwayat tercatat dan unduhan dikerjakan
     * worker (bertahan walau layar ini ditutup).
     */
    fun download(candidate: BrowserCandidate) {
        viewModelScope.launch {
            val pageUrl = candidate.pageUrl.ifBlank { candidate.url }
            val platform = platformOf(pageUrl) ?: platformOf(candidate.url)
            if (platform == null) {
                _state.update { it.copy(message = BrowserMessage.Untrusted) }
                return@launch
            }

            // `shouldInterceptRequest` hanya memberi URL (tanpa header respons),
            // jadi MIME dipastikan sekali di sini lewat HEAD. Ini menentukan
            // folder MediaStore (video vs audio) dan menolak URL yang ternyata
            // bukan media.
            val probe = probeMedia(candidate.url)
            if (probe != null && probe.mimeType != null &&
                MediaSniffer.inspect(candidate.url, probe.mimeType) == null
            ) {
                _state.update { it.copy(message = BrowserMessage.NotMedia) }
                return@launch
            }
            val type = probe?.type ?: candidate.type
            val settings = container.settingsRepository.settings.first()

            runCatching {
                repository.start(
                    url = pageUrl,
                    platform = platform,
                    type = type,
                    quality = settings.defaultQuality,
                    bitrate = settings.defaultBitrate,
                    engine = EngineKind.WEB,
                    mediaUrl = candidate.url,
                    mimeType = probe?.mimeType ?: candidate.mimeType,
                )
            }.onSuccess {
                _state.update { it.copy(message = BrowserMessage.Queued) }
            }.onFailure {
                _state.update { it.copy(message = BrowserMessage.Failed) }
            }
        }
    }

    /** Hasil pemeriksaan HEAD: jenis media + MIME yang sebenarnya. */
    private data class Probe(val type: ResultType, val mimeType: String?)

    /**
     * Tanyakan jenis media ke server tanpa mengunduh isinya.
     *
     * Gagal atau `null` bukan alasan membatalkan: engine cadangan masih akan
     * membaca `Content-Type` saat mengunduh sungguhan.
     */
    private suspend fun probeMedia(url: String): Probe? = withContext(Dispatchers.IO) {
        var connection: java.net.HttpURLConnection? = null
        try {
            connection = (java.net.URL(url).openConnection() as java.net.HttpURLConnection).apply {
                connectTimeout = PROBE_TIMEOUT_MS
                readTimeout = PROBE_TIMEOUT_MS
                instanceFollowRedirects = true
                requestMethod = "HEAD"
            }
            if (connection.responseCode !in 200..299) return@withContext null
            val mime = connection.contentType?.substringBefore(';')?.trim()?.lowercase()
                ?.takeIf { it.isNotEmpty() }
            val detected = MediaSniffer.inspect(url, mime) ?: return@withContext null
            Probe(detected.type, mime)
        } catch (_: Exception) {
            null
        } finally {
            runCatching { connection?.disconnect() }
        }
    }

    /** Platform dari URL; `null` bila host tidak didukung. */
    private fun platformOf(url: String): Platform? {
        val host = runCatching { java.net.URI(url).host }.getOrNull() ?: return null
        return UrlValidator.detectPlatform(host)
    }

    private fun isRangeRequest(url: String, contentType: String?): Boolean {
        // Segmen HLS/DASH memang tidak punya Content-Length dan sering
        // diminta dalam rentang; jangan dianggap kandidat berkas.
        if (contentType?.startsWith("video/", ignoreCase = true) == true &&
            URL_RANGE_HINTS.any { url.contains(it, ignoreCase = true) }
        ) {
            return true
        }
        return false
    }

    private companion object {
        const val PROBE_TIMEOUT_MS = 10_000
        val URL_RANGE_HINTS = listOf("bytestart=", "byteend=", "range=")
    }
}
