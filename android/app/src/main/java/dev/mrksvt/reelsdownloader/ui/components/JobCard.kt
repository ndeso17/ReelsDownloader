package dev.mrksvt.reelsdownloader.ui.components

import android.text.format.Formatter
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.mrksvt.reelsdownloader.R
import dev.mrksvt.reelsdownloader.data.db.DownloadJobEntity
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.JobStatus
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.ui.icons.AppIcons

/** Satu kartu job: dipakai di daftar aktif maupun riwayat. */
@Composable
fun JobCard(
    job: DownloadJobEntity,
    onCancel: (() -> Unit)? = null,
    onRetry: (() -> Unit)? = null,
    onClick: (() -> Unit)? = null,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
        ),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = if (job.typeEnum == ResultType.AUDIO) {
                        AppIcons.MusicNote
                    } else {
                        AppIcons.Movie
                    },
                    contentDescription = null,
                    modifier = Modifier.size(20.dp),
                    tint = MaterialTheme.colorScheme.primary,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = job.title ?: job.url,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
            }

            Spacer(Modifier.padding(top = 6.dp))

            Text(
                text = statusLabel(job),
                style = MaterialTheme.typography.bodySmall,
                color = statusColor(job.statusEnum),
            )

            if (job.statusEnum.isActive) {
                Spacer(Modifier.padding(top = 6.dp))
                LinearProgressIndicator(
                    progress = { job.progress / 100f },
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = subtitle(job),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                when {
                    onCancel != null && job.statusEnum.isActive -> TextButton(onClick = onCancel) {
                        Text(stringResource(R.string.job_cancel))
                    }

                    onRetry != null && (job.statusEnum == JobStatus.FAILED ||
                        job.statusEnum == JobStatus.CANCELLED) -> TextButton(onClick = onRetry) {
                        Text(stringResource(R.string.job_retry))
                    }
                }
            }
        }
    }
}

@Composable
private fun statusLabel(job: DownloadJobEntity): String = when (job.statusEnum) {
    JobStatus.QUEUED -> stringResource(R.string.job_queued)
    JobStatus.RUNNING -> stringResource(R.string.job_downloading, job.progress)
    JobStatus.SAVING -> stringResource(R.string.job_saving)
    JobStatus.DONE -> stringResource(R.string.job_done)
    JobStatus.FAILED -> job.errorName
        ?.let { runCatching { DownloadError.valueOf(it) }.getOrNull() }
        ?.let { stringResource(it.messageRes) }
        ?: stringResource(R.string.job_failed)

    JobStatus.CANCELLED -> stringResource(R.string.job_cancelled)
}

@Composable
private fun statusColor(status: JobStatus) = when (status) {
    JobStatus.DONE -> MaterialTheme.colorScheme.primary
    JobStatus.FAILED -> MaterialTheme.colorScheme.error
    JobStatus.CANCELLED -> MaterialTheme.colorScheme.onSurfaceVariant
    else -> MaterialTheme.colorScheme.onSurface
}

@Composable
private fun subtitle(job: DownloadJobEntity): String {
    val context = LocalContext.current
    val platform = job.platformEnum?.let { stringResource(it.labelRes) } ?: job.platform
    val quality = when {
        job.actualQuality != null && job.actualQuality != requestedLabel(job) ->
            stringResource(R.string.job_quality_actual, requestedLabel(job), job.actualQuality)

        else -> job.actualQuality ?: requestedLabel(job)
    }
    val size = if (job.sizeBytes > 0) {
        " · " + Formatter.formatShortFileSize(context, job.sizeBytes)
    } else {
        ""
    }
    val speed = job.speed?.let { " · $it" } ?: ""
    return "$platform · $quality$size$speed"
}

@Composable
private fun requestedLabel(job: DownloadJobEntity): String = when (job.typeEnum) {
    ResultType.VIDEO -> stringResource(job.qualityEnum.labelRes)
    ResultType.AUDIO -> stringResource(job.bitrateEnum.labelRes)
}

/** Ikon status kecil untuk header kartu. */
@Composable
fun StatusIcon(status: JobStatus, modifier: Modifier = Modifier) {
    val icon = when (status) {
        JobStatus.DONE -> AppIcons.CheckCircle
        JobStatus.FAILED -> AppIcons.Error
        JobStatus.CANCELLED -> AppIcons.Cancel
        else -> AppIcons.Movie
    }
    Icon(
        imageVector = icon,
        contentDescription = null,
        modifier = modifier.size(18.dp),
        tint = statusColor(status),
    )
}
