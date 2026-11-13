package dev.mrksvt.reelsdownloader

import android.app.Application
import dev.mrksvt.reelsdownloader.data.DownloadRepository
import dev.mrksvt.reelsdownloader.data.MediaStoreWriter
import dev.mrksvt.reelsdownloader.data.SettingsRepository
import dev.mrksvt.reelsdownloader.data.db.AppDatabase
import dev.mrksvt.reelsdownloader.data.engine.DownloadEngine
import dev.mrksvt.reelsdownloader.data.engine.YtDlpEngine
import dev.mrksvt.reelsdownloader.util.CrashReporter
import dev.mrksvt.reelsdownloader.worker.DownloadNotifications
import kotlinx.coroutines.sync.Semaphore

/**
 * Dependency container sederhana (tanpa DI framework).
 *
 * Semua dependensi dibuat lazy supaya app start tetap ringan; engine baru
 * menyentuh native library saat unduhan pertama dipicu.
 */
class AppContainer(private val app: Application) {

    val database: AppDatabase by lazy { AppDatabase.build(app) }

    val settingsRepository: SettingsRepository by lazy { SettingsRepository(app) }

    val engine: DownloadEngine by lazy { YtDlpEngine(app) }

    val mediaStoreWriter: MediaStoreWriter by lazy { MediaStoreWriter(app) }

    val downloadRepository: DownloadRepository by lazy {
        DownloadRepository(app, database.downloadJobDao(), mediaStoreWriter)
    }

    /** Batas unduhan paralel (FR-107). */
    val downloadSlots: Semaphore by lazy { Semaphore(MAX_PARALLEL_DOWNLOADS) }

    fun warmUp() {
        DownloadNotifications.ensureChannel(app)
        if (BuildConfig.DEBUG) CrashReporter.stage(app, "app:onCreate")
        // Aplikasi di background → engine boleh menyiapkan runtime python.
        Thread {
            runCatching {
                if (BuildConfig.DEBUG) CrashReporter.stage(app, "engine:warmup-start")
                kotlinx.coroutines.runBlocking { engine.prepare() }
                if (BuildConfig.DEBUG) CrashReporter.stage(app, "engine:warmup-ok")
            }.onFailure {
                if (BuildConfig.DEBUG) {
                    CrashReporter.stage(app, "engine:warmup-fail ${it::class.java.simpleName}: ${it.message}")
                }
            }
        }.apply { isDaemon = true }.start()
    }

    private companion object {
        const val MAX_PARALLEL_DOWNLOADS = 2
    }
}

class ReelsDownloaderApp : Application() {

    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        if (BuildConfig.DEBUG) {
            CrashReporter.install(this)
            CrashReporter.dumpOnStart(this)
        }
        container.warmUp()
    }
}
