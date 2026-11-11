# PLAN - Reels Downloader Android

Rencana eksekusi untuk `android/docs/PRD-ANDROID.md`. Terpisah dari `bot/docs/agents/PLAN.md`
(bot Python) karena stack, toolchain, dan "definition of done" berbeda.

**Status:** rencana, belum ada kode. Tidak ada file di `app/`, `tests/`, atau
`pyproject.toml` yang boleh diubah untuk pekerjaan ini (AGENTS.md §1 peringkat 1-5).

---

## 0. Prasyarat toolchain

**Status 2026-10-29 (sudah terpenuhi untuk WP-A1):** SDK ada di
`/home/mrksvt/Expo` (platforms 34/35/36, build-tools 36.0.0, ndk 28.2.13676358).
Build dijalankan dengan `JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`
(JDK 25 tidak dipakai Gradle 8.14.5). `./gradlew :app:assembleDebug` dan
`:app:assembleRelease` sudah lulus. Versi acuan diambil dari proyek WhatsVault:

| Komponen | Versi |
|---|---|
| Gradle wrapper | 8.14.5 |
| AGP | 8.13.2 |
| Kotlin | 2.2.21 |
| KSP | 2.2.21-2.0.4 |
| compileSdk / targetSdk | 36 / 36 |
| minSdk | 26 |
| JVM target | 17 |
| NDK | 28.2.13676358 |

Langkah yang sudah dikerjakan (jangan diulang):

1. SDK dipakai dari `/home/mrksvt/Expo` (bukan install baru).
2. `android/local.properties` berisi `sdk.dir=/home/mrksvt/Expo` (gitignored).
3. Gradle wrapper 8.14.5 disalin dari WhatsVault (`gradlew`, `gradlew.bat`, `gradle/wrapper/*`).
4. Entri `.gitignore` sudah ditambahkan (lihat `android/.gitignore` di root `.gitignore`).

Tanpa langkah ini WP-A1 tidak bisa diverifikasi. Ini **bukan** blocker untuk
menulis dokumen rencana.

---

## 1. Work packages

| WP | Judul | Deliverable | Test / Verifikasi | Dep |
|---|---|---|---|---|
| A0 | Keputusan engine (spike) | Dokumen hasil: apakah `youtubedl-android` arm64 berjalan di HP target, 1 unduhan IG + 1 YT sukses, APK size terukur | Log + screenshot hp | - |
| A1 | Scaffold Gradle + Compose | `android/` buildable (`dev.mrksvt.reelsdownloader`), `minSdk 26`/`target 36`/`abiFilters arm64-v8a`, helloscreen, `.gitignore` | `./gradlew assembleDebug` | A0 |
| A2 | Icon & branding | `res/mipmap-anydpi-v26/ic_launcher.xml`, foreground WebP dari `ReelsDownloader.png`, monochrome, splash, `colors.xml` | Screenshot API 26/30/33/35 | A1 |
| A3 | Domain pure-Kotlin | `UrlValidator`, `PlatformDetector`, `ErrorMapper` (port dari `validator.py` + `errors.py`) | JUnit, port kasus `tests/test_validator.py` + `tests/test_errors.py` | A1 |
| A4 | Engine wrapper | `YtDlpEngine` → `Flow<DownloadEvent>`, parsing progress, format selection video/audio + resolusi | Test dengan fake engine, manual test real | A0, A3 |
| A5 | Worker + scheduler | `DownloadWorker`, foreground service, notifikasi, batas concurrency 2, cancel | Instrumented test / manual | A4 |
| A6 | Persistensi | Room: `download_job`, `download_history`; DAO + Flow | Room test | A1 |
| A7 | Simpan galeri | `MediaStoreWriter` (Movies/Music), daftarkan ke MediaStore, akses scoped storage | Manual di API 29/33/35 | A5 |
| A8 | UI Home + DownloadSheet | Tempel URL, deteksi platform, pilih tipe/kualitas, tombol Unduh | Compose UI test | A3, A5 |
| A9 | UI Riwayat + Detail Job | List, progres, cancel, retry, share, play, delete | Compose UI test | A6, A7 |
| A10 | Settings | Kualitas default, tipe default, batas ukuran, "Update Engine", tema | Compose UI test | A4 |
| A11 | Share sheet + deep link | `ACTION_SEND` intent-filter, clipboard auto-read (Android 13+ prompt) | Manual | A8 |
| A12 | i18n | Semua string masuk `values/strings.xml` (en), `values-id/strings.xml`, `generateLocaleConfig`, `crowdin.yml`, audit tanpa string hard-code. Sumber siap: `android/docs/i18n/strings-en.xml` + `android/docs/i18n/strings-id.xml` | Lint `MissingTranslation`/`HardcodedText` = 0, screenshot locale id | A8-A11 |
| A13 | Hardening | Cleanup file parsial, error UI, aksesibilitas (contentDescription, kontras) | Audit + manual | A7-A12 |
| A14 | Build rilis + GitHub Release | `assembleRelease` signed (arm64-v8a, R8), APK ≤ 60 MB, tag `android-vX.Y.Z`, upload artefak + `RELEASE-NOTES.md` via `gh` | Install dari halaman Releases | A13 |
| A15 | CI | GitHub Actions: `./gradlew test`, cache Gradle, build debug APK pada PR | Workflow hijau | A1 |
| A16 | Dokumentasi | `android/README.md` (instalasi APK, izin, troubleshooting, cara rilis), update `README.md` root | Review manusia | A14 |

Urutan eksekusi: **A0 → A1 → A2 ∥ A3 → A4 → A5 ∥ A6 → A7 → A8 ∥ A10 → A9 → A11 → A12 → A13 → A15 → A14 → A16.**

(CI A15 didahulukan dari rilis A14 supaya release build punya gerbang otomatis.)

### 1.1 Status eksekusi (2026-10-29)

| WP | Status | Bukti |
|---|---|---|
| A0 | **Sebagian** | Library `io.github.junkfood02.youtubedl-android:0.18.1` (Maven Central) + `ffmpeg` terpasang dan build sukses. Sisa: unduhan nyata di HP arm64 (tidak bisa diotomasi dari mesin build) |
| A1 | **Selesai** | `assembleDebug` 77 MB, `assembleRelease` 53 MB signed `CN=mrksvt`; `apksigner verify` OK |
| A2 | **Sebagian** | Adaptive icon (v26 + v33 monochrome), legacy mipmap 5 densitas, splash, `colors.xml` sudah dibuat. Sisa: verifikasi visual di emulator API 26/30/33/35 |
| A12 | **Sebagian** | `values/strings.xml` (80) + `values-id/strings.xml` (79) + `crowdin.yml` + `locales_config.xml` sudah ada. Sisa: audit `lint` setelah UI jadi |
| A3-A11, A13-A16 | Belum | - |

---

## 2. Traceability FR → WP → test

| FR | WP | Test |
|---|---|---|
| FR-101 | A8, A11 | Compose UI + manual share |
| FR-102 | A3 | Unit `UrlValidatorTest` (10 host valid, 6 host ditolak) |
| FR-103 | A3 | Unit `PlatformDetectorTest` |
| FR-104 | A4, A7 | Manual + engine fake |
| FR-105 | A4 | Format selector test |
| FR-106 | A4, A8 | Format selector: fallback ≥ terdekat + label `(x→y)` |
| FR-107 | A5 | Manual 5 job simultan |
| FR-108 | A5, A9 | UI test progres & cancel |
| FR-109 | A7 | Manual MediaStore |
| FR-110 | A6 | Room test |
| FR-111 | A5 | Manual notifikasi |
| FR-112 | A9 | UI test |
| FR-113 | A13 | Manual gagal/batal |
| FR-114 | A4, A10 | Unit + manual |
| FR-115 | A3 | Unit `ErrorMapperTest` (teks sama persis dengan bot) |
| FR-116 | A9 | UI test |
| FR-117 | A10 | UI test |
| FR-118 | A2 (tema), A12 (i18n) | Lint + screenshot en/id |
| NFR-101/103 | A1, A14 | `apkanalyzer` + cek `abiFilters` di APK |
| NFR-108/110 | A12 | `lint --check MissingTranslation,HardcodedText` |
| SC-108 | A14 | Cek halaman GitHub Releases |

---

## 3. Definition of done per WP

1. Kode ter-compile, `./gradlew test` hijau.
2. String baru ada di `strings.xml`, tidak ada teks hard-code.
3. Tidak ada permission yang tidak dipakai di manifest.
4. Tidak ada file besar (`.aab`, `.apk`, `.jar` hasil build) di-commit.
5. Commit kecil per WP dengan prefix `feat(android-wp-Ax): ...`.
6. Untuk WP yang menyentuh engine: bukti satu unduhan nyata (log/screenshot).

---

## 4. Risk register (ringkas, detail di PRD §10)

| ID | Risk | Checkpoint |
|---|---|---|
| R1 | `youtubedl-android` tidak layak | **Gerbang A0**: jika gagal, ganti ke ProcessBuilder + binary resmi sebelum A1 |
| R2 | Platform ubah API | Checkpoint tiap rilis: uji 3 link per platform |
| R3 | ~~Ekspektasi Termux~~ | **Ditutup**: keputusan = Kotlin native tanpa server |
| R4 | APK terlalu besar | Gerbang A14 (`apkanalyzer`) |
| R5 | Worker terbunuh | Uji di HP dengan battery saver aktif (A13) |
| R6 | Distribusi | **Diputuskan**: GitHub Releases, bukan Play Store |

---

## 5. Keputusan yang sudah diambil manusia (2026-10-28)

| Pertanyaan | Jawaban |
|---|---|
| Server di HP / Termux | Tidak. Kotlin + Compose native, tanpa server |
| Aset icon | `ReelsDownloader.png` (500×500 RGBA, latar transparan) di akar repo |
| Distribusi | GitHub Releases |
| ABI | arm64-v8a saja |
| Nama paket | `dev.mrksvt.reelsdownloader` |
| Bahasa | Multi-bahasa `values-*`, pola WhatsVault (en default + `values-id`) |

## 6. Item yang masih butuh jawaban manusia sebelum A14

1. **Signing key**: keystore khusus app ini sudah ada, atau saya generate
   `release.jks` (gitignored) yang Anda simpan sendiri?
2. **Repo GitHub untuk Releases**: repo `ReelsDownloader` ini, atau repo terpisah?
3. **Bahasa tambahan**: langsung ar, de, es, fr, it, pt, ru, tr, zh seperti
   WhatsVault, atau en + id dulu? (Rekomendasi: en + id dulu.)
4. **Engine update di MVP?** Fitur "Update Engine" (unduh yt-dlp terbaru dari
   rilis resmi ke `filesDir`) masuk A10 atau fase 2?

---

## 7. Blocker terdeteksi saat menyusun rencana

| # | Temuan | Bukti | Dampak | Butuh keputusan |
|---|---|---|---|---|
| B1 | `.gitignore` mengabaikan `.github/` | baris `.github/` di `.gitignore` repo ini | **WP-A15 (GitHub Actions) tidak bisa di-commit** tanpa mengubah `.gitignore` | Izinkan hapus/`unignore` `.github/` untuk workflow Android, atau pakai CI di luar repo? |
| B2 | `PRD.md`, `Struktur.md`, `Arsitektur.md`, `ArsitekturRules.md` gitignored (internal) | blok terakhir `.gitignore` | Dokumen baru `android/docs/PRD-ANDROID.md` + `android/docs/PLAN-ANDROID.md` **tidak** ter-ignore, jadi akan ikut publik bila di-commit | Ikutkan ke publik (aman, tanpa secret) atau tambahkan ke `.gitignore` seperti PRD bot? |
| B3 | `ReelsDownloader.png` belum di-track git | `git status` → `??` | WP-A2 butuh aset ini di repo agar build reproducible | Setuju commit aset PNG (372 KB)? |
| B4 | `ReelsDownloader.jpg` (640×640) masih ada dan tidak dipakai | `ls` akar repo | Bingung aset mana yang sumber resmi | Hapus JPG, atau simpan sebagai alternatif? |

Semua B1-B4 hanya butuh jawaban singkat; tidak ada yang memblokir penulisan
dokumen.
