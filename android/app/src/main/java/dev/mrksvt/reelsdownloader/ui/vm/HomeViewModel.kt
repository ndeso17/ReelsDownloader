package dev.mrksvt.reelsdownloader.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.mrksvt.reelsdownloader.ReelsDownloaderApp
import dev.mrksvt.reelsdownloader.BuildConfig
import dev.mrksvt.reelsdownloader.data.AppSettings
import dev.mrksvt.reelsdownloader.data.engine.EngineException
import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.MediaPreview
import dev.mrksvt.reelsdownloader.domain.Platform
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.domain.UrlValidator
import dev.mrksvt.reelsdownloader.util.CrashReporter
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID

data class HomeUiState(
    val url: String = "",
    val platform: Platform? = null,
    val type: ResultType = ResultType.VIDEO,
    val quality: Quality = Quality.BEST,
    val bitrate: AudioBitrate = AudioBitrate.K320,
    val error: DownloadError? = null,
    val hint: HomeHint? = null,
    val submitting: Boolean = false,
    /** Ringkasan media untuk URL saat ini; `null` bila belum/tidak tersedia. */
    val preview: MediaPreview? = null,
    val previewLoading: Boolean = false,
    /** Kegagalan pratinjau; tidak menghalangi unduhan. */
    val previewError: DownloadError? = null,
)

enum class HomeHint { CLIPBOARD_EMPTY, SHARE_RECEIVED }

class HomeViewModel(application: Application) : AndroidViewModel(application) {

    private val container = (application as ReelsDownloaderApp).container
    private val repository = container.downloadRepository
    private val probe = container.metadataProbe

    private val _state = MutableStateFlow(HomeUiState())
    val state: StateFlow<HomeUiState> = _state.asStateFlow()

    val activeJobs = repository.activeJobs

    /** Pekerjaan pratinjau yang sedang berjalan; dibatalkan saat URL berubah. */
    private var previewJob: Job? = null

    /** URL yang pratinjaunya sudah tampil, supaya tidak diprobe ulang. */
    private var previewedUrl: String? = null

    /**
     * Cache kecil hasil probe. Satu probe = satu proses yt-dlp (beberapa detik),
     * jadi menempelkan URL yang sama dua kali tidak boleh membayarnya lagi.
     */
    private val previewCache = object : LinkedHashMap<String, MediaPreview>(8, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, MediaPreview>) =
            size > MAX_CACHED_PREVIEWS
    }

    init {
        viewModelScope.launch {
            container.settingsRepository.settings.collect { settings ->
                _state.update { current ->
                    current.copy(
                        type = settings.defaultType,
                        quality = settings.defaultQuality,
                        bitrate = settings.defaultBitrate,
                    )
                }
            }
        }
    }

    fun onUrlChanged(value: String) {
        val validation = UrlValidator.validate(value)
        _state.update {
            it.copy(
                url = value,
                platform = (validation as? UrlValidator.ValidationResult.Valid)?.platform,
                error = null,
                hint = null,
            )
        }
        if (validation is UrlValidator.ValidationResult.Valid) {
            requestPreview(validation.url, debounce = true)
        } else {
            cancelPreview()
        }
    }
    fun onPaste(text: String?) {
        val extracted = UrlValidator.extractUrl(text)
        if (extracted == null) {
            _state.update { it.copy(hint = HomeHint.CLIPBOARD_EMPTY) }
            return
        }
        acceptSharedUrl(extracted)
    }

    /** Dipakai share sheet (FR-101) dan Clipboard. */
    fun acceptSharedUrl(rawUrl: String) {
        val validation = UrlValidator.validate(rawUrl)
        _state.update { current ->
            when (validation) {
                is UrlValidator.ValidationResult.Valid -> current.copy(
                    url = validation.url,
                    platform = validation.platform,
                    error = null,
                    hint = HomeHint.SHARE_RECEIVED,
                )

                is UrlValidator.ValidationResult.Unsupported -> current.copy(
                    url = rawUrl,
                    platform = null,
                    error = DownloadError.UnsupportedUrl,
                )

                is UrlValidator.ValidationResult.Invalid -> current.copy(
                    url = rawUrl,
                    platform = null,
                    error = validation.error,
                )
            }
        }
        // Tempel/bagikan = URL sudah final, tidak perlu menunggu jeda ketik.
        if (validation is UrlValidator.ValidationResult.Valid) {
            requestPreview(validation.url, debounce = false)
        }
    }

    fun setType(type: ResultType) {
        _state.update { it.copy(type = type) }
        viewModelScope.launch { container.settingsRepository.setDefaultType(type) }
    }

    fun setQuality(quality: Quality) {
        _state.update { it.copy(quality = quality) }
        viewModelScope.launch { container.settingsRepository.setDefaultQuality(quality) }
    }

    fun setBitrate(bitrate: AudioBitrate) {
        _state.update { it.copy(bitrate = bitrate) }
        viewModelScope.launch { container.settingsRepository.setDefaultBitrate(bitrate) }
    }

    fun clearHint() {
        _state.update { it.copy(hint = null) }
    }

    /** Coba ambil pratinjau lagi, melewati cache (mis. setelah jaringan pulih). */
    fun refreshPreview() {
        val url = (_state.value.url)
        val validation = UrlValidator.validate(url)
        if (validation is UrlValidator.ValidationResult.Valid) {
            previewCache.remove(validation.url)
            previewedUrl = null
            requestPreview(validation.url, debounce = false)
        }
    }

    fun submit() {
        val current = _state.value
        if (BuildConfig.DEBUG) CrashReporter.stage(getApplication(), "ui:submit-tapped")
        val validation = UrlValidator.validate(current.url)
        when (validation) {
            is UrlValidator.ValidationResult.Valid -> {
                _state.update { it.copy(error = null, submitting = true) }
                viewModelScope.launch(Dispatchers.IO) {
                    runCatching {
                        repository.start(
                            url = validation.url,
                            platform = validation.platform,
                            type = current.type,
                            quality = current.quality,
                            bitrate = current.bitrate,
                            // Judul dari pratinjau dipakai sejak awal supaya
                            // riwayat langsung terbaca, bukan menampilkan URL.
                            title = current.preview?.title,
                        )
                    }.onSuccess {
                        cancelPreview()
                        _state.update {
                            it.copy(
                                url = "",
                                platform = null,
                                submitting = false,
                                hint = null,
                                preview = null,
                                previewError = null,
                            )
                        }
                    }.onFailure {
                        _state.update {
                            it.copy(error = DownloadError.DownloadFailed, submitting = false)
                        }
                    }
                }
            }

            is UrlValidator.ValidationResult.Unsupported -> _state.update {
                it.copy(error = DownloadError.UnsupportedUrl)
            }

            is UrlValidator.ValidationResult.Invalid -> _state.update {
                it.copy(error = validation.error)
            }
        }
    }

    fun cancel(jobId: String) = repository.cancel(jobId)

    /**
     * Ambil pratinjau untuk [url].
     *
     * Debounce dipakai saat pengguna mengetik: tanpa itu setiap karakter yang
     * membentuk URL valid akan memulai proses yt-dlp baru.
     */
    private fun requestPreview(url: String, debounce: Boolean) {
        // Beranda platform bukan media: jangan buang satu proses yt-dlp.
        if (!UrlValidator.pointsToContent(url)) {
            cancelPreview()
            return
        }
        if (url == previewedUrl && _state.value.preview != null) return

        previewJob?.cancel()
        // URL berbeda → pratinjau lama tidak relevan lagi; jangan biarkan
        // kartu menampilkan video yang salah selama probe berjalan.
        if (previewedUrl != url) {
            previewedUrl = null
            _state.update { it.copy(preview = null, previewError = null, previewLoading = false) }
        }

        previewJob = viewModelScope.launch {
            if (debounce) delay(PREVIEW_DEBOUNCE_MS)

            previewCache[url]?.let { cached ->
                previewedUrl = url
                _state.update {
                    it.copy(preview = cached, previewLoading = false, previewError = null)
                }
                return@launch
            }

            _state.update { it.copy(previewLoading = true, previewError = null) }
            val result = try {
                withTimeoutOrNull(PREVIEW_TIMEOUT_MS) { probe.probe(url) }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: EngineException) {
                // Probe yang dibatalkan bukan kegagalan yang perlu ditampilkan.
                if (error.error == DownloadError.Cancelled) {
                    _state.update { it.copy(previewLoading = false) }
                    return@launch
                }
                _state.update { it.copy(previewLoading = false, previewError = error.error) }
                return@launch
            }

            if (result == null) {
                // Lewat batas waktu: proses native tidak bisa dihentikan paksa,
                // jadi cukup berhenti menunggu dan beri tahu pengguna.
                _state.update {
                    it.copy(previewLoading = false, previewError = DownloadError.DownloadFailed)
                }
                return@launch
            }

            previewCache[url] = result
            previewedUrl = url
            _state.update {
                it.copy(preview = result, previewLoading = false, previewError = null)
            }
        }
    }

    private fun cancelPreview() {
        previewJob?.cancel()
        previewJob = null
        previewedUrl = null
        _state.update {
            it.copy(preview = null, previewLoading = false, previewError = null)
        }
    }

    companion object {
        /** Jeda setelah ketikan terakhir sebelum probe dijalankan. */
        private const val PREVIEW_DEBOUNCE_MS = 700L

        /** Batas tunggu probe; yt-dlp bisa menggantung pada jaringan buruk. */
        private const val PREVIEW_TIMEOUT_MS = 40_000L

        private const val MAX_CACHED_PREVIEWS = 8

        fun newJobId() = UUID.randomUUID().toString()
        val defaultSettings = AppSettings()
    }
}
