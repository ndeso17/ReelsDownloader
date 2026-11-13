package dev.mrksvt.reelsdownloader.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Pilihan tema (FR-118). */
enum class ThemeMode {
    SYSTEM, LIGHT, DARK;

    companion object {
        fun fromName(value: String?): ThemeMode =
            entries.firstOrNull { it.name == value } ?: SYSTEM
    }
}

/** Cara menampilkan riwayat: kisi galeri atau daftar ringkas. */
enum class HistoryViewMode {
    GRID, LIST;

    companion object {
        fun fromName(value: String?): HistoryViewMode =
            entries.firstOrNull { it.name == value } ?: GRID
    }
}

/** Preferensi yang dipakai Home + Settings (FR-117). */
data class AppSettings(
    val defaultType: ResultType = ResultType.VIDEO,
    val defaultQuality: Quality = Quality.BEST,
    val defaultBitrate: AudioBitrate = AudioBitrate.K320,
    val maxSizeMb: Int = DEFAULT_MAX_SIZE_MB,
    val theme: ThemeMode = ThemeMode.SYSTEM,
    val historyView: HistoryViewMode = HistoryViewMode.GRID,
) {
    val maxSizeBytes: Long get() = maxSizeMb.toLong() * 1024L * 1024L

    companion object {
        const val DEFAULT_MAX_SIZE_MB = 2048
        const val MIN_MAX_SIZE_MB = 8
        const val MAX_MAX_SIZE_MB = 8192
    }
}

private val Context.settingsDataStore: DataStore<Preferences> by preferencesDataStore("settings")

class SettingsRepository(private val appContext: Context) {

    val settings: Flow<AppSettings> = appContext.settingsDataStore.data.map { prefs ->
        AppSettings(
            defaultType = ResultType.fromName(prefs[KEY_TYPE]),
            defaultQuality = Quality.fromName(prefs[KEY_QUALITY]),
            defaultBitrate = AudioBitrate.fromName(prefs[KEY_BITRATE]),
            maxSizeMb = prefs[KEY_MAX_SIZE] ?: AppSettings.DEFAULT_MAX_SIZE_MB,
            theme = ThemeMode.fromName(prefs[KEY_THEME]),
            historyView = HistoryViewMode.fromName(prefs[KEY_HISTORY_VIEW]),
        )
    }

    suspend fun setDefaultType(type: ResultType) {
        appContext.settingsDataStore.edit { it[KEY_TYPE] = type.name }
    }

    suspend fun setDefaultQuality(quality: Quality) {
        appContext.settingsDataStore.edit { it[KEY_QUALITY] = quality.name }
    }

    suspend fun setDefaultBitrate(bitrate: AudioBitrate) {
        appContext.settingsDataStore.edit { it[KEY_BITRATE] = bitrate.name }
    }

    suspend fun setMaxSizeMb(value: Int) {
        val clamped = value.coerceIn(AppSettings.MIN_MAX_SIZE_MB, AppSettings.MAX_MAX_SIZE_MB)
        appContext.settingsDataStore.edit { it[KEY_MAX_SIZE] = clamped }
    }

    suspend fun setTheme(mode: ThemeMode) {
        appContext.settingsDataStore.edit { it[KEY_THEME] = mode.name }
    }

    suspend fun setHistoryView(mode: HistoryViewMode) {
        appContext.settingsDataStore.edit { it[KEY_HISTORY_VIEW] = mode.name }
    }

    private companion object {
        val KEY_TYPE = stringPreferencesKey("default_type")
        val KEY_QUALITY = stringPreferencesKey("default_quality")
        val KEY_BITRATE = stringPreferencesKey("default_bitrate")
        val KEY_MAX_SIZE = intPreferencesKey("max_size_mb")
        val KEY_THEME = stringPreferencesKey("theme")
        val KEY_HISTORY_VIEW = stringPreferencesKey("history_view")
    }
}
