package dev.mrksvt.reelsdownloader.ui.screen

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.mrksvt.reelsdownloader.R
import dev.mrksvt.reelsdownloader.data.db.DownloadJobEntity
import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.domain.UrlValidator
import dev.mrksvt.reelsdownloader.ui.components.JobCard
import dev.mrksvt.reelsdownloader.ui.vm.HomeUiState
import dev.mrksvt.reelsdownloader.ui.vm.HomeViewModel
import dev.mrksvt.reelsdownloader.ui.icons.AppIcons

@Composable
fun HomeScreen(
    viewModel: HomeViewModel,
    onRequestNotificationPermission: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val activeJobs by viewModel.activeJobs.collectAsStateWithLifecycle(
        initialValue = emptyList(),
    )
    val context = LocalContext.current

    LaunchedEffect(Unit) { onRequestNotificationPermission() }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(
            start = 16.dp,
            end = 16.dp,
            top = 16.dp,
            bottom = 96.dp,
        ),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { UrlInputCard(state, viewModel, context) }
        item { TypeAndQualityCard(state, viewModel) }

        if (activeJobs.isNotEmpty()) {
            item {
                Text(
                    text = stringResource(R.string.section_active),
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
            items(activeJobs, key = { it.id }) { job ->
                ActiveJobCard(job = job, viewModel = viewModel)
            }
        }

        item {
            Text(
                text = stringResource(R.string.disclaimer_short),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 12.dp),
            )
        }
    }
}

@Composable
private fun UrlInputCard(
    state: HomeUiState,
    viewModel: HomeViewModel,
    context: Context,
) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = stringResource(R.string.home_url_label),
                style = MaterialTheme.typography.labelLarge,
            )
            Spacer(Modifier.height(8.dp))

            OutlinedTextField(
                value = state.url,
                onValueChange = viewModel::onUrlChanged,
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text(stringResource(R.string.home_url_placeholder)) },
                singleLine = false,
                minLines = 2,
                maxLines = 4,
                isError = state.error != null,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Done,
                ),
                trailingIcon = {
                    TextButton(onClick = {
                        val clipboard = context.getSystemService(ClipboardManager::class.java)
                        viewModel.onPaste(clipboard?.primaryClip?.getItemAt(0)?.text?.toString())
                    }) {
                        Icon(AppIcons.ContentPaste, contentDescription = null, Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text(stringResource(R.string.home_paste))
                    }
                },
            )

            state.error?.let { error ->
                Spacer(Modifier.height(6.dp))
                Text(
                    text = stringResource(error.messageRes),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            state.platform?.let { platform ->
                Spacer(Modifier.height(6.dp))
                Text(
                    text = stringResource(R.string.home_detected_platform, stringResource(platform.labelRes)),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            }

            state.hint?.let { hint ->
                Spacer(Modifier.height(6.dp))
                Text(
                    text = stringResource(
                        when (hint) {
                            dev.mrksvt.reelsdownloader.ui.vm.HomeHint.CLIPBOARD_EMPTY ->
                                R.string.home_paste_empty

                            dev.mrksvt.reelsdownloader.ui.vm.HomeHint.SHARE_RECEIVED ->
                                R.string.share_received
                        }
                    ),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            Spacer(Modifier.height(12.dp))
            Button(
                onClick = viewModel::submit,
                enabled = !state.submitting && state.url.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.submitting) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                } else {
                    Icon(AppIcons.Download, contentDescription = null, Modifier.size(18.dp))
                }
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.home_download))
            }

            // Jalur cadangan (A17): buka halaman di WebView, lalu unduh berkas
            // media yang tertangkap. Hanya muncul saat URL sudah valid.
            if (state.platform != null) {
                Spacer(Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = stringResource(R.string.browser_hint),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = {
                        val target = UrlValidator.validate(state.url)
                        if (target is UrlValidator.ValidationResult.Valid) {
                            context.startActivity(
                                android.content.Intent(
                                    context,
                                    dev.mrksvt.reelsdownloader.BrowserActivity::class.java,
                                ).putExtra(
                                    dev.mrksvt.reelsdownloader.BrowserActivity.EXTRA_URL,
                                    target.url,
                                )
                            )
                        }
                    }) {
                        Text(stringResource(R.string.browser_open_from_app))
                    }
                }
            }
        }
    }
}

@Composable
private fun TypeAndQualityCard(state: HomeUiState, viewModel: HomeViewModel) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = stringResource(R.string.home_type_label),
                style = MaterialTheme.typography.labelLarge,
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = state.type == ResultType.VIDEO,
                    onClick = { viewModel.setType(ResultType.VIDEO) },
                    label = { Text(stringResource(R.string.home_type_video)) },
                )
                FilterChip(
                    selected = state.type == ResultType.AUDIO,
                    onClick = { viewModel.setType(ResultType.AUDIO) },
                    label = { Text(stringResource(R.string.home_type_audio)) },
                )
            }

            Spacer(Modifier.height(16.dp))
            Text(
                text = stringResource(
                    if (state.type == ResultType.VIDEO) {
                        R.string.home_quality_label
                    } else {
                        R.string.home_bitrate_label
                    }
                ),
                style = MaterialTheme.typography.labelLarge,
            )
            Spacer(Modifier.height(8.dp))

            if (state.type == ResultType.VIDEO) {
                ChipFlow(
                    options = Quality.entries,
                    selected = state.quality,
                    label = { stringResource(it.labelRes) },
                    onSelect = viewModel::setQuality,
                )
            } else {
                ChipFlow(
                    options = AudioBitrate.entries,
                    selected = state.bitrate,
                    label = { stringResource(it.labelRes) },
                    onSelect = viewModel::setBitrate,
                )
            }
        }
    }
}

/** Baris chip sederhana; cukup untuk 5 opsi maksimum. */
@Composable
private fun <T> ChipFlow(
    options: List<T>,
    selected: T,
    label: @Composable (T) -> String,
    onSelect: (T) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        options.chunked(3).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { option ->
                    FilterChip(
                        selected = option == selected,
                        onClick = { onSelect(option) },
                        label = { Text(label(option)) },
                    )
                }
            }
        }
    }
}

@Composable
private fun ActiveJobCard(job: DownloadJobEntity, viewModel: HomeViewModel) {
    JobCard(
        job = job,
        onCancel = { viewModel.cancel(job.id) },
    )
}
