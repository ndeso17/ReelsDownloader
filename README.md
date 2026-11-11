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

## Aset

- `ReelsDownloader.png`: ikon sumber (500×500, RGBA, latar transparan).
- `ReelsDownloader.jpg`: ikon lama, tidak dipakai.
