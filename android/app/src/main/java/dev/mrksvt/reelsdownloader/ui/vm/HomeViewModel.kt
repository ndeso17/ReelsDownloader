package dev.mrksvt.reelsdownloader.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.mrksvt.reelsdownloader.ReelsDownloaderApp
import dev.mrksvt.reelsdownloader.BuildConfig
import dev.mrksvt.reelsdownloader.data.AppSettings
import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.Platform
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.domain.UrlValidator
import dev.mrksvt.reelsdownloader.util.CrashReporter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
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
)

enum class HomeHint { CLIPBOARD_EMPTY, SHARE_RECEIVED }

class HomeViewModel(application: Application) : AndroidViewModel(application) {

    private val container = (application as ReelsDownloaderApp).container
    private val repository = container.downloadRepository

    private val _state = MutableStateFlow(HomeUiState())
    val state: StateFlow<HomeUiState> = _state.asStateFlow()

    val activeJobs = repository.activeJobs

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
                        )
                    }.onSuccess {
                        _state.update {
                            it.copy(url = "", platform = null, submitting = false, hint = null)
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

    companion object {
        fun newJobId() = UUID.randomUUID().toString()
        val defaultSettings = AppSettings()
    }
}
