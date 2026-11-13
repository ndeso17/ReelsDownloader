# Aturan R8 tambahan.

# youtubedl-android memakai Jackson untuk mem-parse JSON dari yt-dlp dan
# merefleksikan model datanya, jadi paket ini tidak boleh disusutkan.
-keep class com.yausername.** { *; }
-keep class com.fasterxml.jackson.** { *; }
-keepattributes *Annotation*, Signature, InnerClasses, EnclosingMethod

# Room menghasilkan implementasi DAO secara reflektif.
-keep class * extends androidx.room.RoomDatabase { *; }
-dontwarn androidx.room.paging.**

# WorkManager meng-instansiasi Worker dan Receiver lewat nama kelas.
-keep class * extends androidx.work.ListenableWorker { *; }
-keep class * extends androidx.work.WorkerFactory { *; }

-dontwarn org.apache.commons.**
-dontwarn com.fasterxml.jackson.**
