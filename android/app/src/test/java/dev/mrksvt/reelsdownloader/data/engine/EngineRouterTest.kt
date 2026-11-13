package dev.mrksvt.reelsdownloader.data.engine

import dev.mrksvt.reelsdownloader.domain.AudioBitrate
import dev.mrksvt.reelsdownloader.domain.DownloadError
import dev.mrksvt.reelsdownloader.domain.EngineKind
import dev.mrksvt.reelsdownloader.domain.Quality
import dev.mrksvt.reelsdownloader.domain.ResultType
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

/**
 * Perilaku pemilihan engine (A17-4).
 *
 * Fokusnya bukan unduhan sungguhan, tetapi keputusan yang mudah salah:
 * kapan jatuh ke engine cadangan, kapan tidak, dan error mana yang dilaporkan.
 */
class EngineRouterTest {

    /** Engine palsu: bisa diatur untuk gagal atau sukses. */
    private class FakeEngine(
        private val name: String,
        var failWith: DownloadError? = null,
        var file: File? = null,
    ) : DownloadEngine {

        var downloadCalls = 0
        var prepared = 0
        var canceled = mutableListOf<String>()

        override suspend fun prepare() {
            prepared++
        }

        override suspend fun download(
            request: EngineRequest,
            onEvent: (DownloadEvent) -> Unit,
        ): EngineResult {
            downloadCalls++
            onEvent(DownloadEvent.Progress(percent = 50, speed = null, etaSeconds = null))
            failWith?.let { throw EngineException(it, "$name gagal") }
            val out = file ?: File.createTempFile("engine", ".mp4").apply {
                writeText("x")
                deleteOnExit()
            }
            return EngineResult(file = out, title = name, actualQuality = name)
        }

        override fun cancel(processId: String) {
            canceled += processId
        }

        override suspend fun engineVersion(): String? = name

        override suspend fun updateEngine(): String? = name
    }

    private fun request(mediaUrl: String?) = EngineRequest(
        jobId = "job-1",
        url = "https://www.instagram.com/reel/abc",
        type = ResultType.VIDEO,
        quality = Quality.BEST,
        bitrate = AudioBitrate.K320,
        maxSizeBytes = 100L * 1024 * 1024,
        workDir = File(System.getProperty("java.io.tmpdir")),
        mediaUrl = mediaUrl,
    )

    @Test
    fun `YtDlp dipakai apa adanya tanpa mencoba cadangan`() = runTest {
        val yt = FakeEngine("yt")
        val direct = FakeEngine("direct")
        val router = EngineRouter(yt, direct)

        val routed = router.download(EngineKind.YT_DLP, request(mediaUrl = "https://cdn/v.mp4")) {}

        assertEquals(1, yt.downloadCalls)
        assertEquals(0, direct.downloadCalls)
        assertEquals(EngineKind.YT_DLP, routed.engine)
    }

    @Test
    fun `DIRECT langsung memakai engine cadangan`() = runTest {
        val yt = FakeEngine("yt")
        val direct = FakeEngine("direct")
        val router = EngineRouter(yt, direct)

        val routed = router.download(EngineKind.DIRECT, request(mediaUrl = "https://cdn/v.mp4")) {}

        assertEquals(0, yt.downloadCalls)
        assertEquals(1, direct.downloadCalls)
        assertEquals(EngineKind.DIRECT, routed.engine)
    }

    @Test
    fun `WEB ditandai sebagai WEB di riwayat`() = runTest {
        val router = EngineRouter(FakeEngine("yt"), FakeEngine("direct"))

        val routed = router.download(EngineKind.WEB, request(mediaUrl = "https://cdn/v.mp4")) {}

        assertEquals(EngineKind.WEB, routed.engine)
    }

    @Test
    fun `AUTO sukses di yt-dlp tidak menyentuh cadangan`() = runTest {
        val yt = FakeEngine("yt")
        val direct = FakeEngine("direct")
        val router = EngineRouter(yt, direct)

        val routed = router.download(EngineKind.AUTO, request(mediaUrl = "https://cdn/v.mp4")) {}

        assertEquals(1, yt.downloadCalls)
        assertEquals(0, direct.downloadCalls)
        assertEquals(EngineKind.YT_DLP, routed.engine)
    }

    @Test
    fun `AUTO jatuh ke cadangan saat ekstraktor ketinggalan`() = runTest {
        // DownloadFailed = ekstraktor gagal memahami halaman; kasus utama A17.
        val yt = FakeEngine("yt", failWith = DownloadError.DownloadFailed)
        val direct = FakeEngine("direct")
        val router = EngineRouter(yt, direct)

        val routed = router.download(EngineKind.AUTO, request(mediaUrl = "https://cdn/v.mp4")) {}

        assertEquals(1, yt.downloadCalls)
        assertEquals(1, direct.downloadCalls)
        assertEquals(EngineKind.DIRECT, routed.engine)
        assertNotNull(routed.result.file)
    }

    @Test
    fun `AUTO tanpa mediaUrl tidak mencoba cadangan`() = runTest {
        val yt = FakeEngine("yt", failWith = DownloadError.DownloadFailed)
        val direct = FakeEngine("direct")
        val router = EngineRouter(yt, direct)

        try {
            router.download(EngineKind.AUTO, request(mediaUrl = null)) {}
            fail("seharusnya melempar")
        } catch (error: EngineException) {
            assertEquals(DownloadError.DownloadFailed, error.error)
        }
        assertEquals(0, direct.downloadCalls)
    }

    @Test
    fun `kegagalan utama dilaporkan bila cadangan juga gagal`() = runTest {
        val yt = FakeEngine("yt", failWith = DownloadError.DownloadFailed)
        val direct = FakeEngine("direct", failWith = DownloadError.NotFound)
        val router = EngineRouter(yt, direct)

        try {
            router.download(EngineKind.AUTO, request(mediaUrl = "https://cdn/v.mp4")) {}
            fail("seharusnya melempar")
        } catch (error: EngineException) {
            // Pesan yt-dlp lebih menjelaskan sebab masalah bagi pengguna.
            assertEquals(DownloadError.DownloadFailed, error.error)
            assertTrue(error.message!!.contains("yt"))
        }
    }

    @Test
    fun `error private tidak memicu fallback`() = runTest {
        val yt = FakeEngine("yt", failWith = DownloadError.Private)
        val direct = FakeEngine("direct")
        val router = EngineRouter(yt, direct)

        try {
            router.download(EngineKind.AUTO, request(mediaUrl = "https://cdn/v.mp4")) {}
            fail("seharusnya melempar")
        } catch (error: EngineException) {
            assertEquals(DownloadError.Private, error.error)
        }
        assertEquals(0, direct.downloadCalls)
    }

    @Test
    fun `pembatalan tidak pernah jatuh ke cadangan`() = runTest {
        val yt = FakeEngine("yt", failWith = DownloadError.Cancelled)
        val direct = FakeEngine("direct")
        val router = EngineRouter(yt, direct)

        try {
            router.download(EngineKind.AUTO, request(mediaUrl = "https://cdn/v.mp4")) {}
            fail("seharusnya melempar")
        } catch (error: EngineException) {
            assertEquals(DownloadError.Cancelled, error.error)
        }
        assertEquals(0, direct.downloadCalls)
    }

    @Test
    fun `cancel memanggil kedua engine`() {
        val yt = FakeEngine("yt")
        val direct = FakeEngine("direct")
        EngineRouter(yt, direct).cancel(EngineKind.AUTO, "job-1")

        assertEquals(listOf("job-1"), yt.canceled)
        assertEquals(listOf("job-1"), direct.canceled)
    }

    @Test
    fun `engineVersion dan updateEngine diteruskan ke yt-dlp`() = runTest {
        val router = EngineRouter(FakeEngine("yt"), FakeEngine("direct"))
        assertEquals("yt", router.engineVersion())
        assertEquals("yt", router.updateEngine())
    }

    @Test
    fun `prepare memilih runtime yang sesuai`() = runTest {
        val yt = FakeEngine("yt")
        val direct = FakeEngine("direct")
        val router = EngineRouter(yt, direct)

        router.prepare(EngineKind.DIRECT)
        assertEquals(1, direct.prepared)
        assertEquals(0, yt.prepared)

        router.prepare(EngineKind.AUTO)
        assertEquals(1, yt.prepared)
    }

    @Test
    fun `EngineKind dari nama tidak pernah mengembalikan AUTO`() {
        assertEquals(EngineKind.YT_DLP, EngineKind.fromName(null))
        assertEquals(EngineKind.YT_DLP, EngineKind.fromName("AUTO"))
        assertEquals(EngineKind.WEB, EngineKind.fromName("WEB"))
        assertEquals(EngineKind.DIRECT, EngineKind.fromName("DIRECT"))
    }
}
