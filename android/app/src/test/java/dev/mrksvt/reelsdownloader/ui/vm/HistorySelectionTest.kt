package dev.mrksvt.reelsdownloader.ui.vm

import dev.mrksvt.reelsdownloader.data.db.DownloadJobEntity
import dev.mrksvt.reelsdownloader.domain.JobStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Logika pilihan berganda di [HistoryUiState].
 *
 * State ini murni (tanpa Android), jadi perilaku centang, "pilih semua", dan
 * pembersihan otomatis saat data berubah bisa diuji langsung.
 */
class HistorySelectionTest {

    private fun job(id: String, status: JobStatus = JobStatus.DONE) = DownloadJobEntity(
        id = id,
        url = "https://example.com/$id",
        platform = "OTHER",
        type = "VIDEO",
        requestedQuality = "BEST",
        requestedBitrate = "K320",
        status = status.name,
    )

    private fun state(vararg ids: String, checked: Set<String> = emptySet()) =
        HistoryUiState(jobs = ids.map { job(it) }, checkedIds = checked)

    @Test
    fun `checkedJobs hanya mengembalikan entri yang dicentang`() {
        val s = state("a", "b", "c", checked = setOf("a", "c"))
        assertEquals(listOf("a", "c"), s.checkedJobs.map { it.id })
    }

    @Test
    fun `allChecked benar hanya bila semua entri dicentang`() {
        assertFalse(state("a", "b", checked = setOf("a")).allChecked)
        assertTrue(state("a", "b", checked = setOf("a", "b")).allChecked)
    }

    @Test
    fun `allChecked salah saat daftar kosong`() {
        assertFalse(state().allChecked)
        assertFalse(HistoryUiState(jobs = emptyList(), checkedIds = setOf("x")).allChecked)
    }

    @Test
    fun `checkedJobs mengabaikan id yang tidak ada di daftar`() {
        val s = state("a", checked = setOf("a", "hilang"))
        assertEquals(1, s.checkedJobs.size)
        assertEquals("a", s.checkedJobs.single().id)
    }

    @Test
    fun `urutan checkedJobs mengikuti urutan tampilan`() {
        // Daftar tampil c, a, b; hanya a dan b dicentang.
        val s = state("c", "a", "b", checked = setOf("b", "a"))
        assertEquals(listOf("a", "b"), s.checkedJobs.map { it.id })
    }

    @Test
    fun `bulk delete request menyimpan mode withFile`() {
        val jobs = listOf(job("a"), job("b"))
        assertTrue(BulkDeleteRequest(jobs, withFile = true).withFile)
        assertFalse(BulkDeleteRequest(jobs, withFile = false).withFile)
        assertNull(HistoryUiState().confirmBulk)
    }

    @Test
    fun `entri gagal tetap terhitung sebagai riwayat`() {
        val s = HistoryUiState(
            jobs = listOf(job("ok"), job("bad", JobStatus.FAILED)),
            checkedIds = setOf("ok", "bad"),
        )
        assertEquals(2, s.checkedJobs.size)
    }
}
