package dev.mrksvt.reelsdownloader.worker

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.work.WorkManager

/** Aksi tombol "Batalkan" pada notifikasi (FR-108). */
class CancelDownloadReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_CANCEL) return
        val jobId = intent.getStringExtra(EXTRA_JOB_ID) ?: return
        WorkManager.getInstance(context).cancelUniqueWork(jobId)
        DownloadNotifications.cancel(context, jobId)
    }

    companion object {
        const val ACTION_CANCEL = "dev.mrksvt.reelsdownloader.action.CANCEL_DOWNLOAD"
        const val EXTRA_JOB_ID = "job_id"
    }
}
