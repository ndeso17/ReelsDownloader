# ReelsDownloader

Monorepo dua aplikasi:

| Folder | Isi | Dokumentasi |
|---|---|---|
| [`bot/`](bot/) | Bot Telegram (Python, yt-dlp, FFmpeg) | [`bot/README.md`](bot/README.md) |
| [`android/`](android/) | Aplikasi Android (Kotlin, Jetpack Compose, yt-dlp on-device) | [`android/docs/PRD-ANDROID.md`](android/docs/PRD-ANDROID.md), [`android/docs/PLAN-ANDROID.md`](android/docs/PLAN-ANDROID.md) |

Kedua aplikasi terpisah: tidak ada kode yang dipakai bersama, build dan
dependensi masing-masing.

## Menjalankan

- Bot: lihat `bot/README.md` (semua perintah dari dalam `bot/`).
- Android: `cd android && ./gradlew :app:assembleDebug` (butuh JDK 17 dan Android SDK).
  Build release butuh `android/keystore/keystore.properties` (lihat
  `keystore.properties.example`; file ini tidak masuk git).

## Aplikasi Android

Unduhan dijalankan sepenuhnya di HP (yt-dlp + FFmpeg dikemas di APK), tanpa server.
Kualitas, tipe (video/audio), dan batas ukuran diatur di Settings; riwayat
tersimpan sebagai galeri dengan hapus-per-entri (riwayat saja atau riwayat +
berkas) dan pilihan berganda.

Sebelum tombol Unduh ditekan, aplikasi menampilkan pratinjau: judul, pengunggah,
durasi, resolusi yang benar-benar tersedia, perkiraan ukuran untuk pilihan
kualitas saat itu, thumbnail, dan tombol untuk menonton dulu di aplikasi lain.
Pratinjau hanya membaca metadata; kegagalannya tidak pernah menghalangi unduhan.

Dua jalur unduhan:

| Jalur | Kapan dipakai | Catatan |
|---|---|---|
| yt-dlp (utama) | default untuk semua URL yang didukung | Menangani halaman platform, pemilihan format, gabung audio+video |
| Engine cadangan | otomatis bila yt-dlp gagal karena ekstraktor ketinggalan, atau dipilih sendiri lewat browser mini | HTTP langsung dengan resume/retry; HLS `.m3u8` di-remux FFmpeg bawaan |

Engine cadangan **tidak** menangani DASH `.mpd`, DRM (Widevine), atau konten
yang butuh login. Rincian desain dan batasannya: [`android/docs/PLAN-BACKUP-ENGINE.md`](android/docs/PLAN-BACKUP-ENGINE.md).

Semua entri riwayat mencatat engine yang benar-benar dipakai (`via browser` /
`direct`), termasuk unduhan yang berasal dari browser mini.

## Aset

- `ReelsDownloader.png`: ikon sumber (500×500, RGBA, latar transparan).
- `ReelsDownloader.jpg`: ikon lama, tidak dipakai.
