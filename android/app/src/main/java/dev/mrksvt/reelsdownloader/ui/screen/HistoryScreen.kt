package dev.mrksvt.reelsdownloader.ui.screen

import android.content.Intent
import android.net.Uri
import android.text.format.Formatter
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.mrksvt.reelsdownloader.R
import dev.mrksvt.reelsdownloader.data.HistoryViewMode
import dev.mrksvt.reelsdownloader.data.db.DownloadJobEntity
import dev.mrksvt.reelsdownloader.domain.JobStatus
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.ui.components.ThumbnailCache
import dev.mrksvt.reelsdownloader.ui.icons.AppIcons
import dev.mrksvt.reelsdownloader.ui.vm.HistoryEvent
import dev.mrksvt.reelsdownloader.ui.vm.HistoryViewModel

/**
 * Riwayat berbentuk galeri dengan dua mode tampilan (kisi/daftar) dan CRUD.
 *
 * Pilihan berganda: tekan lama satu item untuk masuk mode pilih, lalu ketuk
 * item lain untuk menambah/mengurangi. Selama mode pilih, bilah atas berganti
 * menjadi bilah aksi massal (pilih semua, hapus riwayat, hapus riwayat+berkas).
 */
@Composable
fun HistoryScreen(
    viewModel: HistoryViewModel,
    onEvent: (HistoryEvent) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    LaunchedEffect(Unit) {
        viewModel.events.collect { onEvent(it) }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        if (state.selecting) {
            SelectionBar(
                checkedCount = state.checkedIds.size,
                allChecked = state.allChecked,
                onClose = viewModel::clearSelection,
                onToggleAll = viewModel::toggleSelectAll,
                onDeleteHistory = { viewModel.askBulkDelete(withFile = false) },
                onDeleteWithFile = { viewModel.askBulkDelete(withFile = true) },
            )
        } else {
            HeaderBar(
                state = state,
                onChangeView = viewModel::toggleViewMode,
                onDeleteFailed = viewModel::deleteFailed,
                onDeleteAll = { viewModel.askDeleteAll(true) },
            )
        }

        if (state.jobs.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    text = stringResource(R.string.history_empty),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            when (state.viewMode) {
                HistoryViewMode.GRID -> GalleryGrid(state = state, viewModel = viewModel)
                HistoryViewMode.LIST -> GalleryList(state = state, viewModel = viewModel)
            }
        }
    }

    state.selected?.let { job ->
        JobActionsSheet(
            job = job,
            onDismiss = { viewModel.select(null) },
            onOpen = { openJob(context, job) },
            onShare = { shareJob(context, job) },
            onForget = { viewModel.forget(job) },
            onDeleteWithFile = { viewModel.askDeleteWithFile(job) },
            onDeleteFileOnly = { viewModel.deleteFileOnly(job) },
            onRetry = { viewModel.retry(job) },
        )
    }

    state.confirmBulk?.let { request ->
        val withFile = request.withFile
        AlertDialog(
            onDismissRequest = viewModel::cancelBulkDelete,
            title = {
                Text(
                    stringResource(
                        if (withFile) {
                            R.string.history_bulk_delete_with_file
                        } else {
                            R.string.history_bulk_delete_history
                        },
                        request.jobs.size,
                    )
                )
            },
            text = {
                Text(
                    stringResource(
                        if (withFile) {
                            R.string.history_bulk_delete_with_file_confirm
                        } else {
                            R.string.history_bulk_delete_history_confirm
                        },
                        request.jobs.size,
                    )
                )
            },
            confirmButton = {
                TextButton(onClick = viewModel::confirmBulkDelete) {
                    Text(stringResource(R.string.history_delete))
                }
            },
            dismissButton = {
                TextButton(onClick = viewModel::cancelBulkDelete) {
                    Text(stringResource(android.R.string.cancel))
                }
            },
        )
    }

    state.confirmDeleteWithFile?.let {
        AlertDialog(
            onDismissRequest = viewModel::cancelDeleteWithFile,
            title = { Text(stringResource(R.string.history_delete_with_file)) },
            text = { Text(stringResource(R.string.history_delete_with_file_confirm)) },
            confirmButton = {
                TextButton(onClick = viewModel::confirmDeleteWithFile) {
                    Text(stringResource(R.string.history_delete))
                }
            },
            dismissButton = {
                TextButton(onClick = viewModel::cancelDeleteWithFile) {
                    Text(stringResource(android.R.string.cancel))
                }
            },
        )
    }

    if (state.confirmDeleteAll) {
        AlertDialog(
            onDismissRequest = { viewModel.askDeleteAll(false) },
            title = { Text(stringResource(R.string.history_clear_all)) },
            text = { Text(stringResource(R.string.history_clear_all_confirm)) },
            confirmButton = {
                TextButton(onClick = viewModel::deleteAll) {
                    Text(stringResource(R.string.history_delete))
                }
            },
            dismissButton = {
                TextButton(onClick = { viewModel.askDeleteAll(false) }) {
                    Text(stringResource(android.R.string.cancel))
                }
            },
        )
    }
}

/** Bilah atas normal: jumlah item, tombol hapus gagal, menu, dan switch mode. */
@Composable
private fun HeaderBar(
    state: dev.mrksvt.reelsdownloader.ui.vm.HistoryUiState,
    onChangeView: () -> Unit,
    onDeleteFailed: () -> Unit,
    onDeleteAll: () -> Unit,
) {
    if (state.jobs.isEmpty()) return
    val failedCount = state.jobs.count {
        it.statusEnum == JobStatus.FAILED || it.statusEnum == JobStatus.CANCELLED
    }
    var menuOpen by remember { mutableStateOf(false) }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 16.dp, end = 4.dp, top = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.history_count, state.jobs.size),
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            modifier = Modifier.weight(1f),
        )
        if (failedCount > 0) {
            TextButton(
                onClick = onDeleteFailed,
                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
            ) {
                Text(
                    text = stringResource(R.string.history_clear_failed, failedCount),
                    maxLines = 1,
                )
            }
        }
        IconButton(onClick = onChangeView) {
            Icon(
                imageVector = if (state.viewMode == HistoryViewMode.GRID) {
                    AppIcons.ViewList
                } else {
                    AppIcons.GridView
                },
                contentDescription = stringResource(
                    if (state.viewMode == HistoryViewMode.GRID) {
                        R.string.history_switch_to_list
                    } else {
                        R.string.history_switch_to_grid
                    }
                ),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Box {
            IconButton(onClick = { menuOpen = true }) {
                Icon(
                    imageVector = AppIcons.MoreVert,
                    contentDescription = stringResource(R.string.history_more),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.history_clear_all)) },
                    onClick = {
                        menuOpen = false
                        onDeleteAll()
                    },
                )
            }
        }
    }
}

/** Bilah aksi saat mode pilihan berganda aktif. */
@Composable
private fun SelectionBar(
    checkedCount: Int,
    allChecked: Boolean,
    onClose: () -> Unit,
    onToggleAll: () -> Unit,
    onDeleteHistory: () -> Unit,
    onDeleteWithFile: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onClose) {
                Icon(
                    imageVector = AppIcons.Close,
                    contentDescription = stringResource(R.string.history_exit_selection),
                )
            }
            Text(
                text = stringResource(R.string.history_selected_count, checkedCount),
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onToggleAll) {
                Icon(
                    imageVector = if (allChecked) {
                        AppIcons.CheckCircleOutline
                    } else {
                        AppIcons.SelectAll
                    },
                    contentDescription = stringResource(
                        if (allChecked) {
                            R.string.history_deselect_all
                        } else {
                            R.string.history_select_all
                        }
                    ),
                )
            }
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 8.dp, end = 8.dp, bottom = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            TextButton(
                onClick = onDeleteHistory,
                enabled = checkedCount > 0,
                modifier = Modifier.weight(1f),
            ) {
                Icon(
                    imageVector = AppIcons.DeleteSweep,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    text = stringResource(R.string.history_bulk_delete_history),
                    maxLines = 1,
                )
            }
            TextButton(
                onClick = onDeleteWithFile,
                enabled = checkedCount > 0,
                modifier = Modifier.weight(1f),
            ) {
                Icon(
                    imageVector = AppIcons.Delete,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.error,
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    text = stringResource(R.string.history_bulk_delete_with_file),
                    maxLines = 1,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
        HorizontalDivider()
    }
}

@Composable
private fun GalleryGrid(
    state: dev.mrksvt.reelsdownloader.ui.vm.HistoryUiState,
    viewModel: HistoryViewModel,
) {
    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 150.dp),
        contentPadding = PaddingValues(8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(state.jobs, key = { it.id }) { job ->
            GalleryTile(
                job = job,
                selecting = state.selecting,
                checked = job.id in state.checkedIds,
                onClick = {
                    if (state.selecting) viewModel.toggleChecked(job) else viewModel.select(job)
                },
                onLongClick = { viewModel.startSelecting(job) },
            )
        }
    }
}

@Composable
private fun GalleryList(
    state: dev.mrksvt.reelsdownloader.ui.vm.HistoryUiState,
    viewModel: HistoryViewModel,
) {
    LazyColumn(contentPadding = PaddingValues(vertical = 4.dp)) {
        items(state.jobs, key = { it.id }) { job ->
            ListRow(
                job = job,
                selecting = state.selecting,
                checked = job.id in state.checkedIds,
                onClick = {
                    if (state.selecting) viewModel.toggleChecked(job) else viewModel.select(job)
                },
                onLongClick = { viewModel.startSelecting(job) },
            )
        }
    }
}

/** Thumbnail video, atau ikon jenis media bila thumbnail tidak tersedia. */
@Composable
private fun JobThumbnail(job: DownloadJobEntity, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val isVideo = job.typeEnum == ResultType.VIDEO
    val hasFile = job.uri != null && job.statusEnum == JobStatus.DONE

    val thumbnail by produceState<android.graphics.Bitmap?>(initialValue = null, job.uri) {
        value = if (isVideo && hasFile) {
            ThumbnailCache.load(context, Uri.parse(job.uri))
        } else {
            null
        }
    }

    Box(
        modifier = modifier.background(MaterialTheme.colorScheme.surfaceVariant),
        contentAlignment = Alignment.Center,
    ) {
        val bitmap = thumbnail
        if (bitmap != null) {
            Image(
                bitmap = bitmap.asImageBitmap(),
                contentDescription = job.title,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Icon(
                imageVector = if (isVideo) AppIcons.PlayArrow else AppIcons.MusicNote,
                contentDescription = null,
                modifier = Modifier.size(40.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun GalleryTile(
    job: DownloadJobEntity,
    selecting: Boolean,
    checked: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
) {
    val context = LocalContext.current
    val isVideo = job.typeEnum == ResultType.VIDEO
    val hasFile = job.uri != null && job.statusEnum == JobStatus.DONE

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onClick, onLongClick = onLongClick),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column {
            Box {
                JobThumbnail(
                    job = job,
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(1f),
                )

                if (isVideo && hasFile) {
                    Box(
                        modifier = Modifier
                            .align(Alignment.BottomEnd)
                            .padding(6.dp)
                            .size(24.dp)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.6f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = AppIcons.PlayArrow,
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                            tint = MaterialTheme.colorScheme.inverseOnSurface,
                        )
                    }
                }

                if (selecting) {
                    SelectionCheck(
                        checked = checked,
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .padding(6.dp),
                    )
                } else {
                    StatusBadge(job, Modifier.align(Alignment.TopStart))
                }
            }

            Column(modifier = Modifier.padding(8.dp)) {
                Text(
                    text = job.title ?: job.url,
                    style = MaterialTheme.typography.labelMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    text = subtitle(context, job),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ListRow(
    job: DownloadJobEntity,
    selecting: Boolean,
    checked: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
) {
    val context = LocalContext.current

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onClick, onLongClick = onLongClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (selecting) {
            SelectionCheck(checked = checked)
            Spacer(Modifier.width(10.dp))
        }
        JobThumbnail(
            job = job,
            modifier = Modifier
                .size(56.dp)
                .clip(RoundedCornerShape(8.dp)),
        )
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = job.title ?: job.url,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                text = subtitle(context, job),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (!selecting) {
            JobStatusLabel(job)
        }
    }
}

/** Label status ringkas untuk mode daftar. */
@Composable
private fun JobStatusLabel(job: DownloadJobEntity) {
    val text = when (job.statusEnum) {
        JobStatus.DONE -> return
        JobStatus.FAILED -> stringResource(R.string.job_failed)
        JobStatus.CANCELLED -> stringResource(R.string.job_cancelled)
        else -> stringResource(R.string.job_downloading, job.progress)
    }
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        color = when (job.statusEnum) {
            JobStatus.FAILED -> MaterialTheme.colorScheme.error
            JobStatus.CANCELLED -> MaterialTheme.colorScheme.outline
            else -> MaterialTheme.colorScheme.tertiary
        },
    )
}

/** Kotak centang sederhana untuk mode pilihan. */
@Composable
private fun SelectionCheck(checked: Boolean, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .size(24.dp)
            .clip(CircleShape)
            .background(
                if (checked) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.surface.copy(alpha = 0.85f)
                }
            ),
        contentAlignment = Alignment.Center,
    ) {
        if (checked) {
            Icon(
                imageVector = AppIcons.Check,
                contentDescription = null,
                modifier = Modifier.size(16.dp),
                tint = MaterialTheme.colorScheme.onPrimary,
            )
        }
    }
}

@Composable
private fun subtitle(context: android.content.Context, job: DownloadJobEntity): String =
    buildString {
        append(job.platformEnum?.let { stringResource(it.labelRes) } ?: job.platform)
        if (job.sizeBytes > 0) {
            append(" · ")
            append(Formatter.formatShortFileSize(context, job.sizeBytes))
        }
    }

@Composable
private fun StatusBadge(job: DownloadJobEntity, modifier: Modifier = Modifier) {
    val (label, color) = when (job.statusEnum) {
        JobStatus.DONE -> null to MaterialTheme.colorScheme.primary
        JobStatus.FAILED -> stringResource(R.string.job_failed) to MaterialTheme.colorScheme.error
        JobStatus.CANCELLED ->
            stringResource(R.string.job_cancelled) to MaterialTheme.colorScheme.outline

        else -> stringResource(R.string.job_downloading, job.progress) to
            MaterialTheme.colorScheme.tertiary
    }
    if (label == null) return
    Box(
        modifier = modifier
            .padding(6.dp)
            .clip(RoundedCornerShape(6.dp))
            .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.9f))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(text = label, style = MaterialTheme.typography.labelSmall, color = color)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun JobActionsSheet(
    job: DownloadJobEntity,
    onDismiss: () -> Unit,
    onOpen: () -> Unit,
    onShare: () -> Unit,
    onForget: () -> Unit,
    onDeleteWithFile: () -> Unit,
    onDeleteFileOnly: () -> Unit,
    onRetry: () -> Unit,
) {
    val context = LocalContext.current
    val hasFile = job.uri != null
    val retryable = job.statusEnum == JobStatus.FAILED || job.statusEnum == JobStatus.CANCELLED

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) {
            Text(
                text = job.title ?: job.url,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = stringResource(
                    R.string.history_meta,
                    job.platformEnum?.let { stringResource(it.labelRes) } ?: job.platform,
                    job.actualQuality ?: "-",
                    Formatter.formatShortFileSize(context, job.sizeBytes),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))

            if (hasFile) {
                SheetAction(AppIcons.PlayArrow, stringResource(R.string.history_play), onOpen)
                SheetAction(AppIcons.Share, stringResource(R.string.history_share), onShare)
            }
            if (retryable) {
                SheetAction(AppIcons.Refresh, stringResource(R.string.job_retry), onRetry)
            }

            SheetAction(
                AppIcons.DeleteSweep,
                stringResource(R.string.history_forget),
                onForget,
            )
            if (hasFile) {
                SheetAction(
                    AppIcons.Delete,
                    stringResource(R.string.history_delete_file_only),
                    onDeleteFileOnly,
                )
                SheetAction(
                    AppIcons.Delete,
                    stringResource(R.string.history_delete_with_file),
                    onDeleteWithFile,
                    destructive = true,
                )
            } else {
                // Tidak ada file: hapus entri saja (tanpa dialog konfirmasi).
                SheetAction(
                    AppIcons.Delete,
                    stringResource(R.string.history_delete),
                    onForget,
                    destructive = true,
                )
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun SheetAction(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    onClick: () -> Unit,
    destructive: Boolean = false,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onClick)
            .padding(vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            modifier = Modifier.size(20.dp),
            tint = if (destructive) {
                MaterialTheme.colorScheme.error
            } else {
                MaterialTheme.colorScheme.onSurface
            },
        )
        Spacer(Modifier.width(14.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = if (destructive) {
                MaterialTheme.colorScheme.error
            } else {
                MaterialTheme.colorScheme.onSurface
            },
        )
    }
}

private fun openJob(context: android.content.Context, job: DownloadJobEntity) {
    val uri = job.uri?.let(Uri::parse) ?: return
    val intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(
            uri,
            if (job.typeEnum == ResultType.VIDEO) "video/*" else "audio/*",
        )
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    runCatching { context.startActivity(intent) }
}

private fun shareJob(context: android.content.Context, job: DownloadJobEntity) {
    val uri = job.uri?.let(Uri::parse) ?: return
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = if (job.typeEnum == ResultType.VIDEO) "video/*" else "audio/*"
        putExtra(Intent.EXTRA_STREAM, uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    runCatching { context.startActivity(Intent.createChooser(intent, null)) }
}
