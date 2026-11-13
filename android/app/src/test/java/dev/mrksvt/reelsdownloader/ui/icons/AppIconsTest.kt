package dev.mrksvt.reelsdownloader.ui.icons

import androidx.compose.ui.graphics.vector.ImageVector
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Ikon sekarang didefinisikan sebagai data path SVG yang di-parse saat runtime
 * oleh `PathParser`. Salah satu karakter saja membuat parser melempar exception
 * dan aplikasi crash saat ikon pertama digambar. Test ini memastikan seluruh
 * ikon bisa dibangun dan tidak kosong.
 */
class AppIconsTest {

    private val all: Map<String, ImageVector> = mapOf(
        "Cancel" to AppIcons.Cancel,
        "CheckCircle" to AppIcons.CheckCircle,
        "ContentPaste" to AppIcons.ContentPaste,
        "Delete" to AppIcons.Delete,
        "DeleteSweep" to AppIcons.DeleteSweep,
        "Download" to AppIcons.Download,
        "Error" to AppIcons.Error,
        "History" to AppIcons.History,
        "MoreVert" to AppIcons.MoreVert,
        "Movie" to AppIcons.Movie,
        "MusicNote" to AppIcons.MusicNote,
        "PlayArrow" to AppIcons.PlayArrow,
        "Refresh" to AppIcons.Refresh,
        "Settings" to AppIcons.Settings,
        "Share" to AppIcons.Share,
    )

    @Test
    fun `semua ikon terbangun dari path yang valid`() {
        all.forEach { (name, vector) ->
            assertEquals("nama ikon $name", name, vector.name)
            assertTrue(
                "ikon $name tidak punya path",
                vector.defaultWidth.value > 0f && vector.viewportWidth > 0f,
            )
        }
    }

    @Test
    fun `setiap ikon punya minimal satu path dengan perintah gambar`() {
        all.forEach { (name, vector) ->
            assertTrue(
                "ikon $name tidak punya path",
                vector.root.size > 0,
            )
        }
    }

    @Test
    fun `viewport mengikuti kanvas material 24dp`() {
        all.values.forEach { vector ->
            assertEquals(24f, vector.viewportWidth, 0.001f)
            assertEquals(24f, vector.viewportHeight, 0.001f)
            assertEquals(24f, vector.defaultWidth.value, 0.001f)
            assertEquals(24f, vector.defaultHeight.value, 0.001f)
        }
    }
}
