# PRD - Reels Downloader Android (On-Device)

| Item | Nilai |
|---|---|
| Versi | 0.1 (draf rencana, belum dieksekusi) |
| Tanggal | 2026-10-28 |
| Platform | Android (Kotlin + Jetpack Compose, Material 3) |
| Engine unduh | yt-dlp **on-device** (tanpa VPS/backend) |
| Proyek induk | Repositori ini (`ReelsDownloader/`, bot Telegram Python) |
| Status | Rencana; menunggu jawaban §14 (signing, repo, bahasa tambahan, engine update) |

---

## 1. Latar belakang & posisi

Repositori ini berisi **bot Telegram** (Python + `python-telegram-bot` + `yt-dlp`)
yang berjalan di VPS. Aplikasi Android ini adalah **jalur akses kedua** ke
kemampuan yang sama, tetapi **berjalan penuh di HP** (offline-first, tanpa server).

Repo bot dan aplikasi Android **berbagi domain sama, engine berbeda tempat**:

```
                  ┌───────────────────────────┐
                  │   VPS (yang sudah ada)    │
                  │  Telegram Bot (Python)    │  ← repo ini, TIDAK diubah
                  │  yt-dlp + FFmpeg di VPS   │
                  └───────────────────────────┘
                              ▲
                              │ keduanya mengunduh media publik IG / FB / YT
                              ▼
                  ┌───────────────────────────┐
                  │  Android App (BARU)       │
                  │  Compose UI + yt-dlp/lib  │  ← semua unduhan di HP
                  └───────────────────────────┘
```

**Tidak ada backend baru, tidak ada VPS, tidak ada VPS loopback ke HP.**
Kalau suatu saat ingin server lokal di HP (mis. Termux + FastAPI), itu fase
terpisah dan **bukan** syarat MVP (lihat §7 Out of scope + §10 Risk R3).

---

## 2. Tujuan & non-tujuan

### 2.1 Tujuan (MVP)

1. User tempel URL publik Instagram / Facebook / YouTube → app mengunduh video/audio.
2. Proses unduh berjalan **di HP**, tanpa koneksi ke server mana pun selain
   platform sumber.
3. Hasil tersimpan di galeri / folder unduhan HP dan muncul di daftar riwayat app.
4. Pilih video (mp4) atau audio (m4a/mp3), pilih kualitas.
5. Antrean unduhan dengan progres per-job, bisa batalkan.
6. Notifikasi progres & selesai (Android 13+ notification permission).
7. Icon launcher **identik** dengan aset `ReelsDownloader.png` di akar repo.

### 2.2 Non-tujuan MVP

- Login/akun platform, video private, atau konten berbayar (PRD bot §6 juga menolak ini).
- Upload balik ke Telegram dari app.
- Sinkronisasi riwayat antara bot dan app.
- iOS / Desktop.
- Monetisasi, IAP, iklan.

---

## 3. Karakteristik pengguna & alur utama

### Alur 1 - tempel & unduh (happy path)

```text
Buka app → tab "Unduh"
  → tempel https://www.instagram.com/reel/ABC123/
  → app deteksi platform: Instagram ✓
  → pilih 🎬 Video / 🎵 Audio, pilih kualitas (Best / 1080p / 720p / 480p / 360p)
  → [Unduh]
  → job masuk antrean, progres bar 0-100%
  → notifikasi "Selesai" → tap → putar dari galeri
```

### Alur 2 - share sheet

```text
User di Instagram/TikTok app → Share → "Reels Downloader"
  → app terbuka dengan URL sudah terisi → lanjut Alur 1 langkah 3
```

### Alur 3 - riwayat

```text
Tab "Riwayat" → daftar judul + thumbnail + platform + ukuran
  → tap: putar, bagikan file, buka folder, hapus
```

### Alur 4 - URL ditolak

```text
Host tidak didukung → Snackbar "❌ Link tidak didukung (hanya Instagram/Facebook/YouTube)."
```

---

## 4. Kebutuhan fungsional (FR)

| ID | Kebutuhan | Prioritas |
|---|---|---|
| FR-101 | Terima URL dari clipboard, share sheet, atau input manual | Must |
| FR-102 | Validasi host dengan daftar yang sama dengan `app/services/validator.py` (10 host: `instagram.com`, `www.instagram.com`, `facebook.com`, `www.facebook.com`, `m.facebook.com`, `fb.watch`, `youtube.com`, `www.youtube.com`, `m.youtube.com`, `youtu.be`); shortlink lain (`vt.tiktok.com`, `tiktok.com`, dll) ditolak | Must |
| FR-103 | Deteksi platform → label `Instagram` / `Facebook` / `YouTube` | Must |
| FR-104 | Unduh video ke format mp4 (merge via FFmpeg on-device) | Must |
| FR-105 | Unduh audio-only ke m4a (default) atau mp3 (FFmpeg) | Must |
| FR-106 | Pilihan kualitas: Best / 1080p / 720p / 480p / 360p; bila sumber tidak punya, pakai kualitas terdekat dan tampilkan `(1080p→720p)` di detail job - **sama seperti perilaku `/advance` di bot** | Must |
| FR-107 | Antrean maksimal N job bersamaan (default 2); job berlebih menunggu di status `Queued` | Must |
| FR-108 | Progress per-job (persen, kecepatan, ETA) dan tombol Cancel | Must |
| FR-109 | Simpan hasil ke folder `Movies/ReelsDownloader/` (video) dan `Music/ReelsDownloader/` (audio) via MediaStore; daftarkan ke galeri | Must |
| FR-110 | Riwayat persisten (Room DB): URL, judul, platform, tipe, kualitas aktual, path, timestamp, ukuran | Must |
| FR-111 | Notifikasi progres + notifikasi selesai/gagal (deep link ke detail job) | Must |
| FR-112 | Share/Play/Open-with dari riwayat | Should |
| FR-113 | Bersihkan file parsial setelah gagal/batal (setara `safe_remove` di bot) | Must |
| FR-114 | Batas ukuran file (default 2 GB, konfigurabel) dengan pesan `📏 File terlalu besar.` | Must |
| FR-115 | Pemetaan error ramah yang **identik teksnya** dengan `app/services/errors.py` (🔒, 🔍, ⚠️, 📏, ⏱️, ❌) | Should |
| FR-116 | Retry job gagal (1 tap) | Should |
| FR-117 | Pilih kualitas/tipe default di Settings, supaya Alur 1 bisa one-tap | Should |
| FR-118 | Tema terang/gelap mengikuti sistem; UI multi-bahasa: Inggris (`values/`) + Indonesia (`values-id/`), string dari `strings.xml`, bukan hard-code | Should |

---

## 5. Kebutuhan non-fungsional (NFR)

| ID | Kebutuhan |
|---|---|
| NFR-101 | `minSdk 26` (Android 8.0), `targetSdk 36`, `compileSdk 36`, **ABI arm64-v8a saja** (armeabi-v7a & x86 tidak dibuild di release) |
| NFR-102 | Unduhan lewat **WorkManager** (survive proses mati / app di-kill), foreground service dengan notifikasi progres |
| NFR-103 | APK release ≤ 60 MB (single ABI arm64-v8a). Terukur 2026-10-29: 53 MB dengan FFmpeg (36 MB native), 77 MB debug. Batas 45 MB tidak realistis bila FFmpeg dibundel |
| NFR-104 | Cold start ke layar siap-tempel ≤ 1.5 s di HP mid-range |
| NFR-105 | Tidak ada koneksi ke jaringan selain host sumber; tidak ada analytics/tracker |
| NFR-106 | Tidak menyimpan cookie/kredensial platform; log tidak memuat token/URL bertanda tangan |
| NFR-107 | RAM puncak pemrosesan ≤ 256 MB; pemrosesan file streaming, bukan buffer penuh |
| NFR-108 | Semua string user-facing di `strings.xml` (tidak hard-code); bahasa Inggris sebagai `values/`, Indonesia di `values-id/` (tanpa `values-in`) |
| NFR-109 | Aksesibilitas: content description pada semua ikon aksi, kontras WCAG AA |
| NFR-110 | `app_name` bertanda `translatable="false"`; struktur folder locale mengikuti proyek WhatsVault (`crowdin.yml`, `values-%two_letters_code%`) |

---

## 6. Engine unduh di HP - keputusan teknis kunci

Ini bagian paling berisiko. Tiga opsi yang dipertimbangkan:

| Opsi | Cara kerja | Kelebihan | Kekurangan | Lolos? |
|---|---|---|---|---|
| **A. `youtubedl-android`** (Maven Central `io.github.junkfood02.youtubedl-android`) | Membundel binary yt-dlp + FFmpeg untuk arm64/armv7/x86_64, dipanggil dari Kotlin | Paling dekat dengan perilaku bot; update engine tanpa update app (unduh yt-dlp versi baru ke `filesDir`) | APK besar (terukur 53 MB release); butuh native libs | **Pilihan utama** |
| B. Reimplement extractor di Kotlin | Ambil halaman → regex JSON → URL media | APK kecil | Rapuh, rusak tiap platform ubah API, duplikasi kerja | Tolak |
| C. Server lokal di HP (Termux/FastAPI/Python) | Jalankan service Python yang sama dengan bot | Reuse kode 100% | Butuh Termux, bukan app obah-install, boros baterai, fragile vendor | Tolak untuk MVP |

**Keputusan: Opsi A**, dengan catatan mitigasi:
- Pin versi yt-dlp & FFmpeg saat build; sediakan *in-app engine update* lewat Settings (HTTP GET ke rilis resmi yt-dlp, verifikasi SHA-256, simpan di `filesDir`) supaya ekstraktor platform bisa diperbaiki tanpa menunggu rilis APK baru.
- Bila `youtubedl-android` tidak lagi dirawat saat implementasi dimulai, fallback ke binary yt-dlp resmi + pemanggilan `ProcessBuilder` manual (masih Opsi A secara prinsip).

**Status verifikasi 2026-10-29 (WP-A1):**

| Fakta | Bukti |
|---|---|
| Library tersedia di Maven Central, bukan JitPack | `io.github.junkfood02.youtubedl-android:{library,common,ffmpeg}` versi `0.18.1` |
| `library-0.18.1.aar` berisi native per ABI | `jni/arm64-v8a/{libpython.so,libpython.zip.so,libqjs.so}` |
| FFmpeg terpisah, harus ditambahkan eksplisit | `ffmpeg-0.18.1.aar` = 139 MB, `libffmpeg.zip.so` 35 MB untuk arm64 |
| APK debug (library + ffmpeg, arm64 only) | 77 MB |
| APK release (R8 + shrink, signed) | 53 MB |
| Sisa pekerjaan A0 | uji unduhan nyata (1 IG + 1 YT) di HP arm64; belum bisa diotomasi dari mesin build |

---

## 7. Arsitektur aplikasi

### 7.1 Layer

```text
┌──────────────────────────────────────────────────┐
│ UI (Compose, Material 3)                         │
│  HomeScreen · DownloadSheet · HistoryScreen      │
│  JobDetailScreen · SettingsScreen                │
└───────────────┬──────────────────────────────────┘
                │ ViewModel (StateFlow<UiState>)
┌───────────────▼──────────────────────────────────┐
│ Domain                                           │
│  UrlValidator · PlatformDetector                 │
│  StartDownloadUseCase · CancelDownloadUseCase    │
│  ErrorMapper (identik errors.py bot)             │
└───────────────┬──────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────┐
│ Data                                             │
│  YtDlpEngine        (repository eksekusi)        │
│  DownloadRepository (Room + WorkManager)         │
│  MediaStoreWriter   (simpan ke galeri)           │
│  SettingsRepository (DataStore)                  │
└──────────────────────────────────────────────────┘
```

### 7.2 Komponen kunci

- `DownloadWorker : CoroutineWorker` - satu job per unduhan, `inputData` berisi
  jobId; melaporkan progres via `setForeground` + `setProgress`, menulis status ke Room.
- `YtDlpEngine` - antarmuka `download(request): Flow<DownloadEvent>`; implementasi
  membungkus `YoutubedlAndroid.getYoutubeDL(context).execute(...)`.
- `DownloadScheduler` - `WorkManager` unique-work per jobId + queue constraint untuk
  FR-107 (batas concurrency).
- `Container` - DI manual (tanpa Hilt) agar build sederhana dan ringan.

### 7.3 Struktur modul (subproject terpisah di repo ini)

```text
ReelsDownloader/                 ← root monorepo
├── bot/                         ← bot Python (dipindah 2026-10-29)
│   ├── app/
│   ├── tests/
│   └── ...
├── android/                     ← Gradle project mandiri
│   ├── settings.gradle.kts
│   ├── build.gradle.kts
│   ├── gradle/libs.versions.toml
│   ├── keystore/                (release.jks + keystore.properties: lokal, gitignored)
│   ├── app/
│   │   ├── build.gradle.kts
│   │   ├── src/main/AndroidManifest.xml
│   │   ├── src/main/res/          (icon, strings, theme)
│   │   └── src/main/java/dev/mrksvt/reelsdownloader/
│   │       ├── MainActivity.kt
│   │       ├── ui/                 (screen, component, theme)
│   │       ├── domain/             (validator, platform, mapper)
│   │       ├── data/               (engine, repository, mediastore)
│   │       └── worker/             (DownloadWorker, scheduler)
│   ├── app/src/test + androidTest
│   ├── docs/PRD-ANDROID.md        ← dokumen ini
│   ├── docs/PLAN-ANDROID.md       ← work packages
│   ├── docs/brand/
│   └── docs/i18n/
├── ReelsDownloader.png           ← aset sumber ikon
└── ReelsDownloader.jpg           ← aset sumber lama (disimpan, tidak dipakai)
```

`namespace` / `applicationId` = `dev.mrksvt.reelsdownloader`, `minSdk 26`,
`targetSdk 36`, `compileSdk 36`, `abiFilters += "arm64-v8a"`.

Gradle project Android **terpisah** dari `bot/pyproject.toml`; tidak ada interaksi
build antara keduanya. `.gitignore` sudah memuat entri `android/.gradle/`,
`android/**/build/`, `android/local.properties`, `android/.idea/`, `*.jks`,
`*.keystore`, `android/keystore/keystore.properties`.

---

## 8. Icon & aset visual

### 8.1 Aset sumber

- File: `ReelsDownloader.png` (500×500 px, PNG **RGBA, latar transparan** - sudut
  alpha 0, artwork opaque mulai ~1% dari tepi).
- Karena sudah transparan, anchor yang benar adalah **full-bleed `@drawable/…`**
  untuk ikon legacy dan **inset kecil untuk layer `monochrome`**; tidak perlu
  membuat background putih tambahan.
- Lihat `android/docs/brand/ICON-SPEC.md` untuk langkah konversi ke WebP/XML, splash,
  serta aturan i18n dan release notes GitHub.

### 8.2 Ikon UI

- **Material Symbols (Google Fonts)**: `download`, `movie`, `music_note`,
  `history`, `settings`, `link`, `check_circle`, `error`, `cancel`, `share`,
  `play_arrow`, `delete`, `open_in_new`.
- Sumber: `https://fonts.google.com/icons` - diunduh sebagai XML vector
  (`Android Studio → New → Vector Asset → Clip Art`) atau SVG → XML converter.
- **Emoji tetap dipakai di teks pesan** (🎬 🎵 ⏳ ✅ ⚠️ 📏 ⏱️ 🔒 🔍 ❌) agar
  konsisten dengan pesan bot.

### 8.3 Lokalisasi

Mengikuti konvensi proyek WhatsVault (`/home/mrksvt/Documents/Coding/Android/WhatsVault`):

| Aturan | Detail |
|---|---|
| Sumber | `app/src/main/res/values/strings.xml` berbahasa Inggris |
| Indonesia | `app/src/main/res/values-id/strings.xml` (bukan `values-in`) |
| Nama app | `<string name="app_name" translatable="false">Reels Downloader</string>` |
| Locale config | `androidResources.generateLocaleConfig = true` (AGP) |
| Crowdin | `crowdin.yml` di root `android/`, pola `**/values/strings.xml` → `values-%two_letters_code%`, mapping `he → iw` |
| Larangan | String user-facing hard-code di Compose; format string wajib `%1$s` bernomor agar urutan argumen aman saat diterjemahkan |
| Placeholder khusus | Emoji tidak diterjemahkan; nama platform (`Instagram`, `Facebook`, `YouTube`) tidak diterjemahkan |

Sumber string siap-pakai: `android/docs/i18n/strings-en.xml`, `android/docs/i18n/strings-id.xml`
(80 entri, mencakup Home, status job, riwayat, notifikasi, error, settings, izin,
share sheet). Catatan konvensi lengkap: `android/docs/i18n/README.md`.

---

## 9. Kriteria keberhasilan MVP

| # | Kriteria | Cara ukur |
|---|---|---|
| SC-101 | 10 URL valid (IG reel, FB video, YT shorts, shortlink `youtu.be`) berhasil diunduh ke galeri | Manual test 10 link di HP arm64 |
| SC-102 | URL tidak didukung ditolak sebelum ada trafik jaringan | Unit test validator (port dari `tests/test_validator.py`) |
| SC-103 | Unduhan selesai saat layar mati / app di background | Manual test |
| SC-104 | Batal & gagal tidak meninggalkan file parsial | Manual test + unit test cleanup |
| SC-105 | APK release ≤ 60 MB | `apkanalyzer` (terukur 53 MB di WP-A1) |
| SC-106 | Semua test unit hijau di CI (`./gradlew test`) | GitHub Actions |
| SC-107 | Icon launcher tampil benar di API 26, 30, 33, 35 (adaptive + monochrome themed icon) | Emulator screenshot |
| SC-108 | GitHub Release per tag berisi APK arm64-v8a signed + release notes | Cek halaman Releases |

---

## 10. Risiko & mitigasi

| ID | Risiko | Dampak | Mitigasi |
|---|---|---|---|
| R1 | Library `youtubedl-android` tidak dirawat / API breaking | Tinggi | Spike **WP-A0** di awal sebelum arsitektur dikunci; fallback `ProcessBuilder` + binary yt-dlp resmi |
| R2 | Platform (IG/YT) ubah API → ekstraktor rusak | Tinggi | In-app engine update (unduh yt-dlp terbaru) + tombol "Update Engine" |
| R3 | ~~Ekspektasi "server di HP" (Termux)~~ | - | **Ditutup**: keputusan manusia = Kotlin native tanpa server apa pun |
| R4 | Ukuran APK membengkak karena FFmpeg | Sedang | Hanya bundel ABI **arm64-v8a** (keputusan: tidak ada armeabi-v7a/x86 di release) |
| R5 | Doze/battery optimization mematikan worker | Sedang | Foreground service + minta whitelist battery via Settings link |
| R6 | Distribusi | Rendah | **Keputusan: GitHub Releases** (APK langsung). Tidak ada Play Store, jadi tidak ada review policy downloader dan tidak perlu AAB/512 ikon store |
| R7 | Legalitas / ToS platform | Tinggi | Hanya URL publik, tanpa login; disclaimer in-app; tidak ada monetisasi |

---

## 11. Milestone

| Milestone | Isi | Estimasi |
|---|---|---|
| M0 - Spike | Buktikan yt-dlp on-device bisa unduh 1 link IG & YT di HP nyata | 2-3 hari |
| M1 - Skeleton | Gradle project, Compose theme, icon, navigasi, validator + test | 3 hari |
| M2 - Download core | Engine, WorkManager, progress, simpan galeri | 5-7 hari |
| M3 - UX lengkap | Riwayat Room, detail job, cancel/retry, settings, share sheet | 5 hari |
| M4 - Hardening | Error mapping, cleanup, notifikasi, aksesibilitas, lokalisasi id/en, release build | 3-4 hari |
| M5 - Rilis | Signed APK arm64, workflow GitHub Release, dokumentasi instalasi | 2 hari |

Total ± 4 minggu kerja fokus.

---

## 12. Distribusi & pembaruan

| Aspek | Keputusan |
|---|---|
| Kanal | **GitHub Releases** di repo ini, satu release per tag `android-vX.Y.Z` |
| Artefak | `ReelsDownloader-X.Y.Z-arm64-v8a-release.apk` + `RELEASE-NOTES.md` |
| Signing | keystore lokal (tidak di-commit), password dari Gradle property / env CI |
| Update check | Tidak ada auto-updater; versi baru diumumkan di halaman Releases |
| versionCode | naik +1 tiap release, `versionName` semver |

Release notes mengikuti gaya `changelog.txt` WhatsVault: bagian `[ADDED]`,
`[IMPROVED]`, `[FIXED]`, `[NOTE]`.

---

## 13. Out of scope eksplisit

- Menjalankan server HTTP/FastAPI **di dalam HP** lewat Termux. (Ditutup; keputusan
  manusia: Kotlin native tanpa server.)
- Memakai VPS/menghubungi bot Telegram untuk mengunduh.
- Play Store / App Bundle / ikon store 512 px.
- ABI `armeabi-v7a` dan `x86_64` (device target adalah HP arm64 modern).
- Akun, login, cookie platform.
- Platform selain Instagram, Facebook, YouTube.

---

## 14. Keputusan terkunci (2026-10-28)

| # | Pertanyaan | Keputusan |
|---|---|---|
| 1 | Server di HP / Termux | **Tidak.** Kotlin + Compose native, tanpa server |
| 2 | Aset icon | **`ReelsDownloader.png`** (500×500, RGBA, latar transparan) di akar repo |
| 3 | Distribusi | **GitHub Releases** (APK langsung) |
| 4 | ABI | **arm64-v8a saja** |
| 5 | Nama paket | **`dev.mrksvt.reelsdownloader`** |
| 6 | Bahasa | **Multi-bahasa** `values-*` pola WhatsVault (Inggris default + `values-id`) |

Sisa yang menunggu jawaban: signing key, repo target GitHub Releases, bahasa
tambahan (ar/de/es/fr/it/pt/ru/tr/zh), dan apakah "Update Engine" masuk MVP.
