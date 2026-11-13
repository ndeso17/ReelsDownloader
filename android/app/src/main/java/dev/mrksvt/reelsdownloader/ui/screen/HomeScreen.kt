package dev.mrksvt.reelsdownloader.ui.screen

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.text.format.Formatter
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.mrksvt.reelsdownloader.R
import dev.mrksvt.reelsdownloader.data.db.DownloadJobEntity
import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.domain.UrlValidator
import dev.mrksvt.reelsdownloader.domain.formatDuration
import dev.mrksvt.reelsdownloader.ui.components.JobCard
import dev.mrksvt.reelsdownloader.ui.components.RemoteThumbnail
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
        item { PreviewCard(state, viewModel) }
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
                        // `getItemAt(0)` melempar IndexOutOfBounds bila clip
                        // kosong/merah (mis. isi dari pengelola sandi), jadi
                        // jumlah item diperiksa lebih dulu.
                        val text = runCatching {
                            val clipboard = context.getSystemService(ClipboardManager::class.java)
                            val clip = clipboard?.primaryClip
                            if (clip == null || clip.itemCount == 0) null
                            else clip.getItemAt(0)?.text?.toString()
                        }.getOrNull()
                        viewModel.onPaste(text)
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
private fun PreviewCard(state: HomeUiState, viewModel: HomeViewModel) {
    val preview = state.preview
    // Tidak ada apa pun untuk ditampilkan dan tidak ada yang dimuat: kartu
    // pratinjau tidak boleh menjadi ruang kosong di layar. Pengecualian:
    // pratinjau yang dimatikan penjaga crash harus terlihat agar pengguna tahu
    // cara menyalakannya lagi.
    if (preview == null && !state.previewLoading && state.previewError == null &&
        !state.previewDisabled
    ) {
        return
    }

    val context = LocalContext.current

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
        ),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            when {
                state.previewLoading && preview == null -> Row(
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                    )
                    Spacer(Modifier.width(10.dp))
                    Text(
                        text = stringResource(R.string.preview_loading),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                preview == null -> Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        // Sebagian kegagalan memang layak diketahui lebih awal
                        // (video privat, tautan mati); sisanya cukup pesan umum.
                        text = stringResource(
                            if (state.previewDisabled) {
                                R.string.preview_disabled
                            } else {
                                when (state.previewError) {
                                    DownloadError.Private,
                                    DownloadError.NotFound,
                                    DownloadError.UnsupportedUrl,
                                    DownloadError.InvalidUrl,
                                    -> state.previewError.messageRes

                                    else -> R.string.preview_unavailable
                                }
                            }
                        ),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(
                        onClick = {
                            if (state.previewDisabled) viewModel.enablePreview()
                            else viewModel.refreshPreview()
                        },
                    ) {
                        Text(
                            stringResource(
                                if (state.previewDisabled) R.string.preview_enable
                                else R.string.preview_refresh
                            )
                        )
                    }
                }

                else -> PreviewContent(state = state, preview = preview, context = context)
            }
        }
    }
}

@Composable
private fun PreviewContent(
    state: HomeUiState,
    preview: dev.mrksvt.reelsdownloader.domain.MediaPreview,
    context: Context,
) {
    Row {
        Box {
            RemoteThumbnail(
                url = preview.thumbnailUrl,
                modifier = Modifier.size(width = 96.dp, height = 72.dp),
                contentDescription = preview.title,
            )
            // Menonton dulu sebelum mengunduh: pratinjau yang sebenarnya.
            // Dibuka lewat aplikasi lain supaya tidak perlu memutar video di
            // dalam aplikasi ini (tidak ada player tambahan di APK).
            Box(
                modifier = Modifier
                    .matchParentSize()
                    .clickable { openExternally(context, preview.url) },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = AppIcons.PlayArrow,
                    contentDescription = stringResource(R.string.preview_play),
                    tint = Color.White,
                    modifier = Modifier
                        .size(30.dp)
                        .background(
                            color = Color.Black.copy(alpha = 0.45f),
                            shape = CircleShape,
                        )
                        .padding(5.dp),
                )
            }
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = preview.title ?: preview.url,
                style = MaterialTheme.typography.titleSmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            preview.uploader?.let { uploader ->
                Text(
                    text = uploader,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                text = buildString {
                    preview.durationSeconds?.let {
                        append(context.getString(R.string.preview_duration, formatDuration(it)))
                    }
                    val estimate = preview.estimateBytes(state.type, state.quality)
                    if (isNotEmpty()) append(" · ")
                    append(
                        if (estimate != null) {
                            context.getString(
                                R.string.preview_size_estimate,
                                Formatter.formatShortFileSize(context, estimate),
                            )
                        } else {
                            context.getString(R.string.preview_size_unknown)
                        }
                    )
                },
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }

    // Resolusi yang benar-benar tersedia — inilah yang membedakan "pilih 720p"
    // dari "720p memang ada di video ini".
    if (preview.heights.isNotEmpty()) {
        Spacer(Modifier.height(8.dp))
        Text(
            text = stringResource(
                R.string.preview_available,
                preview.heights.joinToString(" · ") { "${it}p" },
            ),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }

    if (state.previewLoading) {
        Spacer(Modifier.height(6.dp))
        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun TypeAndQualityCard(state: HomeUiState, viewModel: HomeViewModel) {    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh)) {
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

/**
 * Buka [url] di aplikasi lain (browser/aplikasi platform).
 *
 * Dipakai tombol putar pada pratinjau: menonton dulu sebelum mengunduh.
 * Kegagalan (tidak ada aplikasi yang bisa menangani) diabaikan — ini hanya
 * aksi tambahan, bukan jalan utama.
 */
private fun openExternally(context: Context, url: String) {
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
    runCatching { context.startActivity(Intent.createChooser(intent, null)) }
}
