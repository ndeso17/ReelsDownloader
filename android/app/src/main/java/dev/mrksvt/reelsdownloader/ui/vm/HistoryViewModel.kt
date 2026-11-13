package dev.mrksvt.reelsdownloader.ui.vm

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.mrksvt.reelsdownloader.ReelsDownloaderApp
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
)

/** Pesan sekali-tampil untuk Snackbar. */
sealed interface HistoryEvent {
    data object RemovedFromHistory : HistoryEvent
    data object DeletedWithFile : HistoryEvent
    data object FileDeleted : HistoryEvent
    data object DeleteFailed : HistoryEvent
    data class RemovedFailedEntries(val count: Int) : HistoryEvent
    data class RemovedAll(val count: Int) : HistoryEvent
    data object Retried : HistoryEvent
}

class HistoryViewModel(application: Application) : AndroidViewModel(application) {

    private val repository = (application as ReelsDownloaderApp).container.downloadRepository

    private val _state = MutableStateFlow(HistoryUiState())
    val state: StateFlow<HistoryUiState> = _state.asStateFlow()

    private val _events = Channel<HistoryEvent>(Channel.BUFFERED)
    val events = _events.receiveAsFlow()

    init {
        viewModelScope.launch {
            repository.history.collect { jobs ->
                _state.value = _state.value.copy(
                    jobs = jobs,
                    // Segarkan objek terpilih agar sheet ikut ter-update.
                    selected = _state.value.selected?.let { current ->
                        jobs.firstOrNull { it.id == current.id }
                    },
                )
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
