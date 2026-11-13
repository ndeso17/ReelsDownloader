package dev.mrksvt.reelsdownloader.ui.vm

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.mrksvt.reelsdownloader.ReelsDownloaderApp
import dev.mrksvt.reelsdownloader.data.HistoryViewMode
import dev.mrksvt.reelsdownloader.data.db.DownloadJobEntity
import dev.mrksvt.reelsdownloader.ui.components.ThumbnailCache
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

data class HistoryUiState(
    val jobs: List<DownloadJobEntity> = emptyList(),
    val selected: DownloadJobEntity? = null,
    val busy: Boolean = false,
    val confirmDeleteAll: Boolean = false,
    val confirmDeleteWithFile: DownloadJobEntity? = null,
    /** Mode pilihan berganda aktif (= jumlah item yang dicentang > 0). */
    val selecting: Boolean = false,
    val checkedIds: Set<String> = emptySet(),
    val viewMode: HistoryViewMode = HistoryViewMode.GRID,
    /** Dialog konfirmasi untuk hapus massal, null = tersembunyi. */
    val confirmBulk: BulkDeleteRequest? = null,
) {
    val checkedJobs: List<DownloadJobEntity>
        get() = jobs.filter { it.id in checkedIds }

    val allChecked: Boolean
        get() = jobs.isNotEmpty() && jobs.all { it.id in checkedIds }
}

/** Permintaan hapus massal: [withFile] menentukan berkas galeri ikut dihapus. */
data class BulkDeleteRequest(val jobs: List<DownloadJobEntity>, val withFile: Boolean)

/** Pesan sekali-tampil untuk Snackbar. */
sealed interface HistoryEvent {
    data object RemovedFromHistory : HistoryEvent
    data object DeletedWithFile : HistoryEvent
    data object FileDeleted : HistoryEvent
    data object DeleteFailed : HistoryEvent
    data class RemovedFailedEntries(val count: Int) : HistoryEvent
    data class RemovedAll(val count: Int) : HistoryEvent
    data object Retried : HistoryEvent

    /** Hapus massal selesai; [count] entri, [files] berkas ikut terhapus. */
    data class BulkRemoved(val count: Int, val files: Int) : HistoryEvent
}

class HistoryViewModel(application: Application) : AndroidViewModel(application) {

    private val container = (application as ReelsDownloaderApp).container
    private val repository = container.downloadRepository
    private val settingsRepository = container.settingsRepository

    private val _state = MutableStateFlow(HistoryUiState())
    val state: StateFlow<HistoryUiState> = _state.asStateFlow()

    private val _events = Channel<HistoryEvent>(Channel.BUFFERED)
    val events = _events.receiveAsFlow()

    init {
        viewModelScope.launch {
            repository.history.collect { jobs ->
                val known = jobs.mapTo(HashSet()) { it.id }
                _state.value = _state.value.copy(
                    jobs = jobs,
                    // Segarkan objek terpilih agar sheet ikut ter-update.
                    selected = _state.value.selected?.let { current ->
                        jobs.firstOrNull { it.id == current.id }
                    },
                    // Buang centang untuk entri yang sudah tidak ada.
                    checkedIds = _state.value.checkedIds.intersect(known),
                )
            }
        }
        viewModelScope.launch {
            settingsRepository.settings.collect { settings ->
                _state.value = _state.value.copy(viewMode = settings.historyView)
            }
        }
    }

    fun select(job: DownloadJobEntity?) {
        _state.value = _state.value.copy(selected = job)
    }

    fun askDeleteAll(show: Boolean) {
        _state.value = _state.value.copy(confirmDeleteAll = show)
    }

    /** Minta konfirmasi sebelum menghapus file permanen. */
    fun askDeleteWithFile(job: DownloadJobEntity) {
        _state.value = _state.value.copy(selected = null, confirmDeleteWithFile = job)
    }

    fun cancelDeleteWithFile() {
        _state.value = _state.value.copy(confirmDeleteWithFile = null)
    }

    fun confirmDeleteWithFile() {
        val job = _state.value.confirmDeleteWithFile ?: return
        _state.value = _state.value.copy(confirmDeleteWithFile = null)
        deleteWithFile(job)
    }

    // --- Mode pilihan berganda ---------------------------------------------

    fun setViewMode(mode: HistoryViewMode) {
        viewModelScope.launch { settingsRepository.setHistoryView(mode) }
    }

    fun toggleViewMode() {
        val next = if (_state.value.viewMode == HistoryViewMode.GRID) {
            HistoryViewMode.LIST
        } else {
            HistoryViewMode.GRID
        }
        setViewMode(next)
    }

    /** Tekan lama / ketuk saat mode pilihan: centang atau lepas centang. */
    fun toggleChecked(job: DownloadJobEntity) {
        val current = _state.value.checkedIds
        val next = if (job.id in current) current - job.id else current + job.id
        _state.value = _state.value.copy(
            checkedIds = next,
            selecting = next.isNotEmpty() && _state.value.selecting,
            selected = null,
        )
    }

    fun startSelecting(job: DownloadJobEntity) {
        _state.value = _state.value.copy(
            selecting = true,
            checkedIds = _state.value.checkedIds + job.id,
            selected = null,
        )
    }

    fun clearSelection() {
        _state.value = _state.value.copy(selecting = false, checkedIds = emptySet())
    }

    fun toggleSelectAll() {
        val all = _state.value.jobs.mapTo(HashSet()) { it.id }
        _state.value = _state.value.copy(
            checkedIds = if (_state.value.allChecked) emptySet() else all,
        )
    }

    /** Buka dialog konfirmasi hapus massal untuk entri yang dicentang. */
    fun askBulkDelete(withFile: Boolean) {
        val jobs = _state.value.checkedJobs
        if (jobs.isEmpty()) return
        _state.value = _state.value.copy(confirmBulk = BulkDeleteRequest(jobs, withFile))
    }

    fun cancelBulkDelete() {
        _state.value = _state.value.copy(confirmBulk = null)
    }

    fun confirmBulkDelete() {
        val request = _state.value.confirmBulk ?: return
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true, confirmBulk = null)
            request.jobs.forEach { job ->
                ThumbnailCache.evict(job.uri?.let { runCatching { Uri.parse(it) }.getOrNull() })
            }
            val files = runCatching {
                repository.deleteMany(request.jobs, request.withFile)
            }.getOrDefault(0)
            _state.value = _state.value.copy(
                busy = false,
                selecting = false,
                checkedIds = emptySet(),
            )
            _events.send(HistoryEvent.BulkRemoved(request.jobs.size, files))
        }
    }

    // --- Delete: riwayat saja ------------------------------------------------

    fun forget(job: DownloadJobEntity) {
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true, selected = null)
            runCatching { repository.forget(job) }
            _state.value = _state.value.copy(busy = false)
            _events.send(HistoryEvent.RemovedFromHistory)
        }
    }

    // --- Delete: riwayat + file ---------------------------------------------

    fun deleteWithFile(job: DownloadJobEntity) {
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true, selected = null)
            val removed = runCatching { repository.delete(job) }.getOrDefault(false)
            ThumbnailCache.evict(job.uri?.let { runCatching { Uri.parse(it) }.getOrNull() })
            _state.value = _state.value.copy(busy = false)
            _events.send(
                if (removed) HistoryEvent.DeletedWithFile else HistoryEvent.DeleteFailed
            )
        }
    }

    // --- Delete: file saja (entri riwayat tetap) ----------------------------

    fun deleteFileOnly(job: DownloadJobEntity) {
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true, selected = null)
            val removed = runCatching { repository.deleteFile(job) }.getOrDefault(false)
            ThumbnailCache.evict(job.uri?.let { runCatching { Uri.parse(it) }.getOrNull() })
            _state.value = _state.value.copy(busy = false)
            _events.send(
                if (removed) HistoryEvent.FileDeleted else HistoryEvent.DeleteFailed
            )
        }
    }

    // --- Delete massal: entri gagal -----------------------------------------

    fun deleteFailed() {
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true)
            val count = runCatching { repository.deleteFailed() }.getOrDefault(0)
            _state.value = _state.value.copy(busy = false)
            _events.send(HistoryEvent.RemovedFailedEntries(count))
        }
    }

    // --- Delete massal: seluruh riwayat + file ------------------------------

    fun deleteAll() {
        viewModelScope.launch {
            _state.value = _state.value.copy(busy = true, confirmDeleteAll = false)
            val jobs = _state.value.jobs
            jobs.forEach { job ->
                ThumbnailCache.evict(job.uri?.let { runCatching { Uri.parse(it) }.getOrNull() })
            }
            val count = runCatching { repository.deleteAllHistory() }.getOrDefault(0)
            _state.value = _state.value.copy(busy = false)
            _events.send(HistoryEvent.RemovedAll(count))
        }
    }

    fun retry(job: DownloadJobEntity) {
        viewModelScope.launch {
            _state.value = _state.value.copy(selected = null)
            runCatching { repository.retry(job) }
            _events.send(HistoryEvent.Retried)
        }
    }
}
