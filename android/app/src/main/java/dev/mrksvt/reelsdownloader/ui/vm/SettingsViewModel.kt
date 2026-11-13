package dev.mrksvt.reelsdownloader.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.mrksvt.reelsdownloader.ReelsDownloaderApp
import dev.mrksvt.reelsdownloader.data.AppSettings
import dev.mrksvt.reelsdownloader.data.ThemeMode
import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class SettingsUiState(
    val settings: AppSettings = AppSettings(),
    val engineVersion: String? = null,
    val updating: Boolean = false,
    val updateResult: EngineUpdateResult? = null,
)

enum class EngineUpdateResult { SUCCESS, FAILED }

class SettingsViewModel(application: Application) : AndroidViewModel(application) {

    private val container = (application as ReelsDownloaderApp).container
    private val settingsRepository = container.settingsRepository

    private val _state = MutableStateFlow(SettingsUiState())
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            settingsRepository.settings.collect { settings ->
                _state.value = _state.value.copy(settings = settings)
            }
        }
        refreshEngineVersion()
    }

    fun setDefaultType(type: ResultType) = viewModelScope.launch {
        settingsRepository.setDefaultType(type)
    }

    fun setDefaultQuality(quality: Quality) = viewModelScope.launch {
        settingsRepository.setDefaultQuality(quality)
    }

    fun setDefaultBitrate(bitrate: AudioBitrate) = viewModelScope.launch {
        settingsRepository.setDefaultBitrate(bitrate)
    }

    fun setMaxSizeMb(value: Int) = viewModelScope.launch {
        settingsRepository.setMaxSizeMb(value)
    }

    fun setTheme(mode: ThemeMode) = viewModelScope.launch {
        settingsRepository.setTheme(mode)
    }

    fun refreshEngineVersion() {
        viewModelScope.launch(Dispatchers.IO) {
            val version = runCatching { container.engine.engineVersion() }.getOrNull()
            _state.value = _state.value.copy(engineVersion = version)
        }
    }

    fun updateEngine() {
        if (_state.value.updating) return
        _state.value = _state.value.copy(updating = true, updateResult = null)
        viewModelScope.launch(Dispatchers.IO) {
            val version = runCatching { container.engine.updateEngine() }.getOrNull()
            _state.value = _state.value.copy(
                updating = false,
                engineVersion = version ?: _state.value.engineVersion,
                updateResult = if (version != null) {
                    EngineUpdateResult.SUCCESS
                } else {
                    EngineUpdateResult.FAILED
                },
            )
        }
    }

    fun clearUpdateResult() {
        _state.value = _state.value.copy(updateResult = null)
    }
}
