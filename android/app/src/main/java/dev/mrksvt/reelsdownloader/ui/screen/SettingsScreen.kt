package dev.mrksvt.reelsdownloader.ui.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.mrksvt.reelsdownloader.BuildConfig
import dev.mrksvt.reelsdownloader.R
import dev.mrksvt.reelsdownloader.data.AppSettings
import dev.mrksvt.reelsdownloader.data.ThemeMode
import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.ui.vm.EngineUpdateResult
import dev.mrksvt.reelsdownloader.ui.vm.SettingsViewModel
import kotlin.math.roundToInt

@Composable
fun SettingsScreen(viewModel: SettingsViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val settings = state.settings

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            SettingsCard(title = stringResource(R.string.settings_defaults)) {
                Text(stringResource(R.string.home_type_label), style = MaterialTheme.typography.labelLarge)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(
                        selected = settings.defaultType == ResultType.VIDEO,
                        onClick = { viewModel.setDefaultType(ResultType.VIDEO) },
                        label = { Text(stringResource(R.string.home_type_video)) },
                    )
                    FilterChip(
                        selected = settings.defaultType == ResultType.AUDIO,
                        onClick = { viewModel.setDefaultType(ResultType.AUDIO) },
                        label = { Text(stringResource(R.string.home_type_audio)) },
                    )
                }

                Spacer(Modifier.height(12.dp))
                Text(stringResource(R.string.home_quality_label), style = MaterialTheme.typography.labelLarge)
                QualityOptions(settings, viewModel)

                Spacer(Modifier.height(12.dp))
                Text(stringResource(R.string.home_bitrate_label), style = MaterialTheme.typography.labelLarge)
                BitrateOptions(settings, viewModel)
            }
        }

        item {
            SettingsCard(title = stringResource(R.string.settings_max_size)) {
                Text(
                    text = "${settings.maxSizeMb} MB",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Slider(
                    value = settings.maxSizeMb.toFloat(),
                    onValueChange = { viewModel.setMaxSizeMb(it.roundToInt()) },
                    valueRange = AppSettings.MIN_MAX_SIZE_MB.toFloat()..AppSettings.MAX_MAX_SIZE_MB.toFloat(),
                    steps = 0,
                )
            }
        }

        item {
            SettingsCard(title = stringResource(R.string.settings_theme)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ThemeMode.entries.forEach { mode ->
                        FilterChip(
                            selected = settings.theme == mode,
                            onClick = { viewModel.setTheme(mode) },
                            label = {
                                Text(
                                    stringResource(
                                        when (mode) {
                                            ThemeMode.SYSTEM -> R.string.settings_theme_system
                                            ThemeMode.LIGHT -> R.string.settings_theme_light
                                            ThemeMode.DARK -> R.string.settings_theme_dark
                                        }
                                    )
                                )
                            },
                        )
                    }
                }
            }
        }

        item {
            SettingsCard(title = stringResource(R.string.settings_engine)) {
                Text(
                    text = state.engineVersion?.let {
                        stringResource(R.string.settings_engine_version_value, it)
                    } ?: stringResource(R.string.settings_engine_unknown),
                    style = MaterialTheme.typography.bodySmall,
                )
                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = viewModel::updateEngine,
                    enabled = !state.updating,
                ) {
                    if (state.updating) {
                        CircularProgressIndicator(
                            modifier = Modifier.height(16.dp),
                            strokeWidth = 2.dp,
                        )
                    } else {
                        Text(stringResource(R.string.settings_engine_update))
                    }
                }
                state.updateResult?.let { result ->
                    Spacer(Modifier.height(6.dp))
                    Text(
                        text = if (result == EngineUpdateResult.SUCCESS) {
                            stringResource(
                                R.string.settings_engine_updated,
                                state.engineVersion ?: "",
                            )
                        } else {
                            stringResource(R.string.settings_engine_failed)
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = if (result == EngineUpdateResult.SUCCESS) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.error
                        },
                    )
                }
            }
        }

        item {
            SettingsCard(title = stringResource(R.string.settings_about)) {
                Text(
                    text = stringResource(R.string.settings_version, BuildConfig.VERSION_NAME),
                    style = MaterialTheme.typography.bodySmall,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    text = stringResource(R.string.settings_disclaimer),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun QualityOptions(settings: AppSettings, viewModel: SettingsViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Quality.entries.chunked(3).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { quality ->
                    FilterChip(
                        selected = settings.defaultQuality == quality,
                        onClick = { viewModel.setDefaultQuality(quality) },
                        label = { Text(stringResource(quality.labelRes)) },
                    )
                }
            }
        }
    }
}

@Composable
private fun BitrateOptions(settings: AppSettings, viewModel: SettingsViewModel) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        AudioBitrate.entries.forEach { bitrate ->
            FilterChip(
                selected = settings.defaultBitrate == bitrate,
                onClick = { viewModel.setDefaultBitrate(bitrate) },
                label = { Text(stringResource(bitrate.labelRes)) },
            )
        }
    }
}

@Composable
private fun SettingsCard(title: String, content: @Composable () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(text = title, style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.height(10.dp))
            content()
        }
    }
}
