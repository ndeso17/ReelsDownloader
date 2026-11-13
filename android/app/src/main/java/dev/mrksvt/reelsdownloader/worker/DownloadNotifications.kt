package dev.mrksvt.reelsdownloader.worker

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.ForegroundInfo
import dev.mrksvt.reelsdownloader.MainActivity
import dev.mrksvt.reelsdownloader.R

/** Notifikasi progres + hasil unduhan (FR-111). */
object DownloadNotifications {

    const val CHANNEL_ID = "downloads"
    private const val NOTIFICATION_ID_BASE = 1000

    /** Harus sama dengan `android:foregroundServiceType` di manifest. */
    private val FOREGROUND_SERVICE_TYPE =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }

    fun ensureChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            context.getString(R.string.channel_download_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = context.getString(R.string.channel_download_desc)
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    fun foregroundInfo(
        context: Context,
        jobId: String,
        title: String,
        percent: Int,
        indeterminate: Boolean = false,
    ): ForegroundInfo = ForegroundInfo(
        notificationId(jobId),
        progressNotification(context, jobId, title, percent, indeterminate),
        // Android 14+ (target 35+) mewajibkan tipe FGS eksplisit di
        // startForeground(); tanpa ini muncul InvalidForegroundServiceTypeException.
        FOREGROUND_SERVICE_TYPE,
    )

    fun progressNotification(
        context: Context,
        jobId: String,
        title: String,
        percent: Int,
        indeterminate: Boolean = false,
    ): Notification = NotificationCompat.Builder(context, CHANNEL_ID)
        .setSmallIcon(R.drawable.ic_stat_download)
        .setContentTitle(context.getString(R.string.notif_downloading, title))
        .setContentText(
            if (indeterminate) {
                context.getString(R.string.job_processing)
            } else {
                context.getString(R.string.job_downloading, percent)
            }
        )
        .setProgress(100, percent, indeterminate)
        .setOngoing(true)
        .setOnlyAlertOnce(true)
        .setSilent(true)
        .setCategory(NotificationCompat.CATEGORY_PROGRESS)
        .setContentIntent(openAppIntent(context, jobId))
        .addAction(
            0,
            context.getString(R.string.notif_cancel),
            cancelIntent(context, jobId),
        )
        .build()

    fun finishedNotification(context: Context, jobId: String, title: String, success: Boolean) {
        val text = if (success) {
            context.getString(R.string.notif_done)
        } else {
            context.getString(R.string.notif_failed)
        }
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentTitle(title)
            .setContentText(text)
            .setAutoCancel(true)
            .setContentIntent(openAppIntent(context, jobId))
            .build()
        NotificationManagerCompat.from(context).notify(notificationId(jobId), notification)
    }

    fun cancel(context: Context, jobId: String) {
        NotificationManagerCompat.from(context).cancel(notificationId(jobId))
    }

    private fun notificationId(jobId: String): Int =
        NOTIFICATION_ID_BASE + (jobId.hashCode() and 0x0FFF)

    private fun openAppIntent(context: Context, jobId: String): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(MainActivity.EXTRA_JOB_ID, jobId)
        }
        return PendingIntent.getActivity(
            context,
            notificationId(jobId),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun cancelIntent(context: Context, jobId: String): PendingIntent {
        val intent = Intent(context, CancelDownloadReceiver::class.java).apply {
            action = CancelDownloadReceiver.ACTION_CANCEL
            putExtra(CancelDownloadReceiver.EXTRA_JOB_ID, jobId)
        }
        return PendingIntent.getBroadcast(
            context,
            notificationId(jobId),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }
}
