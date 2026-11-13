package dev.mrksvt.reelsdownloader.data.db

/**
 * Pernyataan SQL migrasi, dipisah dari [AppDatabase] (A17-0).
 *
 * Dipisah supaya migrasi produksi dan test memakai **daftar yang sama**.
 * Kalau SQL-nya disalin ke test, test bisa lulus sementara migrasi asli
 * berbeda — kegagalan yang justru paling berbahaya karena baru terlihat di
 * perangkat pengguna, saat riwayat sudah terlanjur hilang.
 *
 * Kelas ini sengaja tidak menyentuh API Android supaya bisa diuji di JVM.
 */
internal object MigrationSql {

    /**
     * v1 → v2: kolom untuk engine cadangan.
     *
     * Semua kolom baru `NULL`-able atau punya `DEFAULT`, jadi `ALTER TABLE`
     * aman untuk baris lama.
     */
    val V1_TO_V2: List<String> = listOf(
        "ALTER TABLE download_jobs ADD COLUMN engine TEXT",
        "ALTER TABLE download_jobs ADD COLUMN mediaUrl TEXT",
        "ALTER TABLE download_jobs ADD COLUMN mimeType TEXT",
        "ALTER TABLE download_jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
    )
}
