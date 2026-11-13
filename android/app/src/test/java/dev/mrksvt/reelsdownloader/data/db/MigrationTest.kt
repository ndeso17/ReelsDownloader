package dev.mrksvt.reelsdownloader.data.db

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.sql.Connection
import java.sql.DriverManager

/**
 * Test migrasi v1 → v2 (A17-0).
 *
 * Migrasi Room biasanya diuji dengan `MigrationTestHelper` di perangkat/emulator.
 * Di lingkungan build ini tidak ada emulator, jadi test memakai **SQLite asli**
 * lewat `sqlite-jdbc`: skema v1 dibuat dari DDL yang tersimpan di
 * `src/test/resources/migration/v1_download_jobs.sql`, lalu pernyataan migrasi
 * yang sama dengan produksi dijalankan.
 *
 * Yang diuji bukan cuma "tidak melempar error", tetapi juga **baris lama tetap
 * utuh** — inilah yang sebenarnya penting bagi pengguna.
 */
class MigrationTest {

    private fun openV1(): Connection {
        val connection = DriverManager.getConnection("jdbc:sqlite::memory:")
        val ddl = javaClass.classLoader!!
            .getResourceAsStream("migration/v1_download_jobs.sql")!!
            .bufferedReader()
            .readText()
        connection.createStatement().use { it.executeUpdate(ddl) }
        return connection
    }

    /** Jalankan migrasi yang sama persis dengan produksi. */
    private fun migrate(connection: Connection) {
        MigrationSql.V1_TO_V2.forEach { sql ->
            connection.createStatement().use { it.executeUpdate(sql) }
        }
    }

    private fun insertV1Row(connection: Connection, id: String) {
        connection.createStatement().use { statement ->
            statement.executeUpdate(
                """
                INSERT INTO download_jobs
                    (id, url, platform, type, requestedQuality, requestedBitrate,
                     actualQuality, title, status, progress, speed, etaSeconds,
                     errorName, uri, filePath, sizeBytes, createdAt, updatedAt)
                VALUES
                    ('$id', 'https://www.instagram.com/reel/abc', 'instagram', 'VIDEO',
                     'BEST', 'K320', '1080p', 'Video lama', 'DONE', 100, NULL, NULL,
                     NULL, 'content://media/1', '/storage/emulated/0/Movies/a.mp4',
                     1048576, 1700000000000, 1700000001000)
                """
            )
        }
    }

    @Test
    fun `migrasi mempertahankan baris lama`() {        openV1().use { connection ->
            insertV1Row(connection, "job-1")
            migrate(connection)

            connection.createStatement().use { statement ->
                statement.executeQuery("SELECT COUNT(*) FROM download_jobs").use { rs ->
                    assertTrue(rs.next())
                    assertEquals(1, rs.getInt(1))
                }
            }
        }
    }

    @Test
    fun `kolom lama tidak berubah nilainya setelah migrasi`() {
        openV1().use { connection ->
            insertV1Row(connection, "job-1")
            migrate(connection)

            connection.createStatement().use { statement ->
                statement.executeQuery(
                    "SELECT url, title, status, sizeBytes, uri FROM download_jobs WHERE id = 'job-1'"
                ).use { rs ->
                    assertTrue(rs.next())
                    assertEquals("https://www.instagram.com/reel/abc", rs.getString("url"))
                    assertEquals("Video lama", rs.getString("title"))
                    assertEquals("DONE", rs.getString("status"))
                    assertEquals(1048576L, rs.getLong("sizeBytes"))
                    assertEquals("content://media/1", rs.getString("uri"))
                }
            }
        }
    }

    @Test
    fun `kolom baru punya nilai default yang aman`() {
        openV1().use { connection ->
            insertV1Row(connection, "job-1")
            migrate(connection)

            connection.createStatement().use { statement ->
                statement.executeQuery(
                    "SELECT engine, mediaUrl, mimeType, attempts FROM download_jobs WHERE id = 'job-1'"
                ).use { rs ->
                    assertTrue(rs.next())
                    // Baris lama dianggap yt-dlp oleh EngineKind.fromName(null).
                    assertNull(rs.getString("engine"))
                    assertNull(rs.getString("mediaUrl"))
                    assertNull(rs.getString("mimeType"))
                    assertEquals(0, rs.getInt("attempts"))
                }
            }
        }
    }

    @Test
    fun `baris baru bisa memakai kolom engine`() {
        openV1().use { connection ->
            migrate(connection)
            connection.createStatement().use { statement ->
                statement.executeUpdate(
                    """
                    INSERT INTO download_jobs
                        (id, url, platform, type, requestedQuality, requestedBitrate,
                         status, progress, sizeBytes, createdAt, updatedAt,
                         engine, mediaUrl, mimeType, attempts)
                    VALUES
                        ('job-2', 'https://www.facebook.com/watch/?v=1', 'facebook', 'VIDEO',
                         'BEST', 'K320', 'DONE', 100, 2048, 1, 2,
                         'WEB', 'https://cdn.example.com/v.mp4', 'video/mp4', 1)
                    """
                )
            }
            connection.createStatement().use { statement ->
                statement.executeQuery(
                    "SELECT engine, mediaUrl, mimeType, attempts FROM download_jobs WHERE id = 'job-2'"
                ).use { rs ->
                    assertTrue(rs.next())
                    assertEquals("WEB", rs.getString("engine"))
                    assertEquals("https://cdn.example.com/v.mp4", rs.getString("mediaUrl"))
                    assertEquals("video/mp4", rs.getString("mimeType"))
                    assertEquals(1, rs.getInt("attempts"))
                }
            }
        }
    }

    @Test
    fun `migrasi bisa dijalankan pada tabel kosong`() {
        openV1().use { connection ->
            migrate(connection)
            connection.createStatement().use { statement ->
                statement.executeQuery("SELECT COUNT(*) FROM download_jobs").use { rs ->
                    assertTrue(rs.next())
                    assertEquals(0, rs.getInt(1))
                }
            }
        }
    }

    @Test
    fun `hasil migrasi punya bentuk kolom yang benar`() {
        // Membandingkan hasil migrasi dengan bentuk yang diharapkan Room:
        // nama, jenis, nullability, dan default. Ini menangkap kasus "migrasi
        // lupa satu kolom" yang tidak terlihat dari test baris-lama di atas.
        openV1().use { connection ->
            migrate(connection)
            connection.createStatement().use { statement ->
                statement.executeQuery("PRAGMA table_info(download_jobs)").use { rs ->
                    val columns = mutableMapOf<String, Triple<String, Boolean, String?>>()
                    while (rs.next()) {
                        columns[rs.getString("name")] = Triple(
                            rs.getString("type"),
                            rs.getInt("notnull") == 1,
                            rs.getString("dflt_value"),
                        )
                    }

                    assertEquals(
                        listOf(
                            "id", "url", "platform", "type", "requestedQuality",
                            "requestedBitrate", "actualQuality", "title", "status",
                            "progress", "speed", "etaSeconds", "errorName", "uri",
                            "filePath", "sizeBytes", "createdAt", "updatedAt",
                            "engine", "mediaUrl", "mimeType", "attempts",
                        ),
                        columns.keys.toList(),
                    )

                    // Kolom baru: teks nullable, dan `attempts` NOT NULL default 0
                    // (sama dengan @ColumnInfo(defaultValue = "0")).
                    assertEquals(Triple("TEXT", false, null), columns["engine"])
                    assertEquals(Triple("TEXT", false, null), columns["mediaUrl"])
                    assertEquals(Triple("TEXT", false, null), columns["mimeType"])
                    assertEquals(Triple("INTEGER", true, "0"), columns["attempts"])
                }
            }
        }
    }
}
