package dev.mrksvt.reelsdownloader.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [DownloadJobEntity::class],
    version = 2,
    exportSchema = true,
)
abstract class AppDatabase : RoomDatabase() {

    abstract fun downloadJobDao(): DownloadJobDao

    companion object {

        const val DATABASE_NAME = "reelsdownloader.db"

        /**
         * v1 → v2 (A17): kolom untuk engine cadangan.
         *
         * Semua kolom baru `NULL`-able atau punya `DEFAULT`, jadi aman untuk
         * `ALTER TABLE` tanpa menyentuh baris lama. Migrasi ini sengaja TIDAK
         * memakai `fallbackToDestructiveMigration`: riwayat pengguna tidak
         * boleh hilang hanya karena skema berubah.
         */
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                MigrationSql.V1_TO_V2.forEach(db::execSQL)
            }
        }

        fun build(context: Context): AppDatabase =
            Room.databaseBuilder(context, AppDatabase::class.java, DATABASE_NAME)
                .addMigrations(MIGRATION_1_2)
                .build()
    }
}
