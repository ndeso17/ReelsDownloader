# RENCANA — Engine Downloader Cadangan (A17)

Status: **rencana**, belum dieksekusi.
Prasyarat: A9 (riwayat), A17-0 (migrasi Room non-destruktif).

---

## 1. Masalah yang diselesaikan

Engine utama (`yt-dlp` lewat `youtubedl-android`) kuat, tapi bergantung pada
ekstraktor yang harus terus mengikuti perubahan platform. Saat ekstraktor
ketinggalan (mis. Facebook/Instagram mengubah struktur halaman), unduhan gagal
total walaupun file aslinya sebenarnya bisa diambil.

1DM/XDM di desktop menyiasatinya dengan cara berbeda: mereka **mengintip lalu
lintas jaringan browser** (ekstensi/add-on), menangkap tautan media langsung
(`.mp4`, `.m4a`, `.webm`, manifest HLS/DASH), lalu mengunduhnya sendiri.
Pendekatan itu tahan terhadap perubahan ekstraktor karena tidak perlu
memahami API platform — cukup mengenali URL media.

WP ini menambahkan jalur kedua di Android dengan semangat yang sama, dan
memastikan **hasilnya tetap tercatat di riwayat** persis seperti unduhan biasa.

---

## 2. Kendala Android vs desktop (dasar pemilihan desain)

| Desktop (1DM/XDM) | Android | Konsekuensi |
|---|---|---|
| Ekstensi browser bisa membaca semua request | Tidak ada API publik untuk membaca request aplikasi lain | Tidak bisa "mengintip" lalu lintas browser apa adanya |
| Add-on menangkap URL media | Bisa: **WebView** milik sendiri + `shouldInterceptRequest` | Penangkapan harus terjadi di WebView kita |
| Bebas menulis file ke folder mana pun | Scoped storage + MediaStore | Wajib lewat `MediaStoreWriter` yang sudah ada |

Jadi bentuk realistisnya di Android: **browser mini berbasis WebView** di dalam
aplikasi, yang memantau request dan menawarkan unduhan saat menemukan media.
Native messaging (pola 1DM ↔ ekstensi) **tidak** bisa dipakai karena butuh
ekstensi yang tidak ada di browser Android.

---

## 3. Arsitektur yang diusulkan

```
HomeScreen ──(URL)──┐
                    ├─► EngineRouter ──► YtDlpEngine        (utama, sudah ada)
                    │        │
                    │        └────────► DirectHttpEngine    (cadangan, baru)
                    │                          ▲
BrowserActivity (WebView) ──(URL media)────────┘
        │
        └─► MediaSniffer (shouldInterceptRequest) ─► daftar kandidat ─► UI pilih
```

### 3.1 `DirectHttpEngine` — mesin cadangan sesungguhnya

Mengunduh langsung dari URL media tanpa yt-dlp.

| Bagian | Detail |
|---|---|
| HTTP | `HttpURLConnection` bawaan → **tidak menambah ukuran APK** (OkHttp akan +1 MB; tidak sepadan) |
| Progres | Baca `InputStream` per blok 64 KB, hitung `percent` dari `Content-Length` |
| Resume | `Range: bytes=N-` + `.part` → penting untuk file besar di jaringan buruk |
| HLS/DASH | `.m3u8` → gabungkan segmen lewat **FFmpeg yang sudah ada** di APK (`libffmpeg.zip.so`), jadi tidak perlu komponen baru; `.mpd` ditunda (butuh dash.js/ExoPlayer — lihat §8) |
| Nama file | `Content-Disposition` → fallback ke segmen terakhir URL, saniter |
| Batas ukuran | `AppSettings.maxSizeBytes` (sudah ada) |

### 3.2 `EngineRouter`

Satu pintu masuk untuk UI/worker, memilih engine dan menangani kegagalan.

- `DownloadSpec` memperoleh `engine: EngineKind` (`AUTO`, `YT_DLP`, `DIRECT`).
- `AUTO` = coba yt-dlp → bila gagal dengan `DownloadError` yang menandakan
  ekstraktor ketinggalan (`DownloadFailed`, `UnsupportedUrl`, `NotFound`),
  ulangi lewat engine cadangan **untuk URL yang sama**.
- Status tiap percobaan **wajib** terlihat di riwayat (lihat §5).

### 3.3 `MediaSniffer` + `BrowserActivity`

- `WebView` + `WebViewClient.shouldInterceptRequest`.
- Kandidat diambil dari: `Content-Type` (`video/*`, `audio/*`,
  `application/vnd.apple.mpegurl`, `application/dash+xml`) atau ekstensi path
  (`.mp4 .m4a .webm .m3u8 .mpd .ts`).
- Filter penting agar tidak banjir: minimal 1 kandidat per URL, buang iklan/
  gambar, urutkan berdasarkan ukuran bila `Content-Length` ada.
- UI: tombol mengambang berisi jumlah kandidat → daftar → pilih → unduh.
- **Jangan** otomatis mengunduh apa pun tanpa persetujuan pengguna.

---

## 4. Yang harus dimatangkan lebih dulu: migrasi Room (A17-0)

Ini **blocker**, dan bukan soal engine.

`AppDatabase` memakai:

```kotlin
Room.databaseBuilder(...).fallbackToDestructiveMigration(dropAllTables = true)
```

Begitu ada kolom baru (`engine`, `mimeType`, `source`) dan `version` dinaikkan,
**seluruh riwayat pengguna terhapus**. Untuk aplikasi yang justru sedang
memperbaiki riwayat, itu tidak bisa diterima.

Langkah wajib sebelum WP ini:

1. `version = 2`, `exportSchema = true`, simpan skema ke `app/schemas/`.
2. `Migration(1, 2)` yang hanya `ALTER TABLE ... ADD COLUMN` (semua kolom baru
   `nullable` atau punya `DEFAULT`).
3. Hapus `fallbackToDestructiveMigration`; ganti `addMigrations(MIGRATION_1_2)`.
4. Test migrasi: `MigrationTestHelper` dengan skema v1 → v2, pastikan baris lama
   tetap ada (bukan hanya "tidak crash").

Kolom baru yang dibutuhkan WP ini:

| Kolom | Tipe | Alasan |
|---|---|---|
| `engine` | `TEXT?` | `YT_DLP` / `DIRECT` / `WEBVIEW` — supaya jelas asal unduhan |
| `mediaUrl` | `TEXT?` | URL media langsung, untuk unduh ulang tanpa yt-dlp |
| `mimeType` | `TEXT?` | Menentukan tipe simpan ke MediaStore (video vs audio) |
| `attempts` | `INTEGER NOT NULL DEFAULT 0` | Berapa kali dicoba (utama + cadangan) |

---

## 5. Riwayat wajib tercatat dari engine cadangan (inti permintaan)

Aturannya sama untuk semua engine — tidak ada jalur "unduhan diam-diam".

1. **Baris dibuat sebelum unduhan mulai.** `DownloadRepository.start()` sudah
   melakukan ini; engine cadangan harus lewat jalur yang sama, bukan menulis
   sendiri ke MediaStore.
2. `engine` + `mediaUrl` diisi saat job dibuat, sehingga entri riwayat bisa
   dijelaskan ("via browser") dan diunduh ulang.
3. `DownloadWorker` tetap satu-satunya tempat yang memanggil `MediaStoreWriter`
   dan status akhir (`DONE`/`FAILED`/`CANCELLED`). `BrowserActivity` **tidak**
   menyimpan file sendiri; ia hanya memanggil `DownloadRepository.start()`.
4. Unduhan yang dimulai dari WebView harus **bertahan** saat `BrowserActivity`
   ditutup → pekerjaan tetap di `DownloadWorker` (WorkManager), bukan di
   coroutine milik Activity.
5. Kegagalan engine cadangan memakai `DownloadError` yang sama supaya pesan di
   UI konsisten; tambahkan `DownloadError.DirectFailed` bila perlu membedakan.

Dengan pola ini, tidak ada perubahan apa pun pada layar Riwayat: entri dari
engine cadangan otomatis muncul, bisa dibuka/dibagikan/dihapus seperti biasa.

---

## 6. Rencana eksekusi

| WP | Isi | Deliverable | Verifikasi |
|---|---|---|---|
| A17-0 | Migrasi Room non-destruktif | `version=2`, migration, skema v1/v2 | `MigrationTestHelper`; riwayat lama utuh |
| A17-1 | Domain: `EngineKind`, `MediaCandidate`, `DownloadSpec.engine` | Kelas + test murni | Unit test |
| A17-2 | `DirectHttpEngine` (progres, resume, Content-Length, batas ukuran) | Implementasi `DownloadEngine` | Test dengan `MockWebServer`/server lokal |
| A17-3 | Integrasi HLS ke FFmpeg bawaan | Gabung segmen `.m3u8` → mp4 | Manual, file hasil bisa diputar |
| A17-4 | `EngineRouter` + `AUTO` fallback | Pemilihan engine + retry | Unit test router, manual |
| A17-5 | `MediaSniffer` (pure) | Deteksi kandidat dari header/URL | Unit test (matriks MIME + ekstensi) |
| A17-6 | `BrowserActivity` (WebView + tombol jumlah kandidat) | UI browser mini | Manual di HP |
| A17-7 | Kolom `engine`/`mediaUrl`/`mimeType` di UI riwayat | Label kecil "via browser" | Screenshot |
| A17-8 | Dokumentasi + release | Bagian di `README.md`, APK rilis | Review |

Urutan: **A17-0 → A17-1 → A17-2 ∥ A17-5 → A17-3 → A17-4 → A17-6 → A17-7 → A17-8.**

---

## 7. Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Migrasi Room salah → riwayat hilang | Tinggi | A17-0 wajib lebih dulu + test migrasi |
| `shouldInterceptRequest` tidak melihat body media yang diputar via Blob/MSE | Tinggi | Batasi klaim: tangkap URL langsung & HLS; beri pesan jelas bila tidak ada kandidat |
| Situs butuh login/DRM | Sedang | Tidak didukung sejak awal; laporkan sebagai `DownloadError.Private` |
| Ukuran APK bertambah | Rendah | Pakai `HttpURLConnection` + WebView bawaan; tanpa dependency baru |
| Kebocoran memori WebView | Sedang | `BrowserActivity` sendiri, `destroy()` di `onDestroy`, tanpa banyak tab |
| Unduhan dari WebView mati saat Activity ditutup | Sedang | Wajib lewat WorkManager (lihat §5.4) |

---

## 8. Di luar cakupan (disengaja)

- Membaca request aplikasi lain (butuh akses root/VPN service; bukan tujuan).
- DASH `.mpd` penuh (butuh ExoPlayer/dash.js — pertimbangkan WP terpisah).
- DRM (Widevine).
- Login otomatis ke platform.
- Integrasi ekstensi browser (tidak ada mekanisme native messaging di Android).

---

## 9. Hasil implementasi (2026-11-13)

Semua WP A17-0 … A17-7 selesai dan terpasang di 0.1.7 (versionCode 8).
49 test unit hijau; APK debug 66 MB, release 54 MB.

### 9.1 Cara pakai

1. Tempel URL di Home (Instagram/Facebook/YouTube) seperti biasa.
2. Bila unduhan normal gagal, tekan **"Buka di browser bawaan"** di bawah tombol
   Unduh — atau langsung tekan itu bila ingin memilih berkas sendiri.
3. Putar videonya di browser mini. Setiap request media yang lewat ditangkap
   (URL request + pemindaian DOM/`performance`), lalu muncul di panel bawah
   beserta perkiraan ukuran.
4. Tekan **Unduh** pada kandidat. Job masuk antrean WorkManager seperti unduhan
   biasa, jadi tetap berjalan walau layar browser ditutup.
5. Entri riwayat muncul dengan label **`via browser`** (atau `direct` untuk
   engine cadangan non-WebView).

### 9.2 Yang berubah dari rencana

| Rencana | Kenyataan | Alasan |
|---|---|---|
| `MigrationTestHelper` | `sqlite-jdbc` di JVM | Tidak ada emulator di mesin build; DDL v1 disimpan di `src/test/resources/migration/` |
| SQL migrasi ditulis di `AppDatabase` | `MigrationSql.V1_TO_V2` dipakai bersama prod + test | Test tidak bisa "lulus sendiri" bila SQL produksi berbeda |
| `EngineRouter.lastUsed` | `RoutedResult(result, engine)` | Dua job berjalan bersamaan (semaphore 2) akan saling menimpa field bersama |
| `engine` disimpan di DB saat enqueue | Engine yang diminta lewat WorkManager `KEY_ENGINE`; DB hanya diisi engine yang **benar-benar** dipakai | `AUTO` bukan engine nyata; menyimpannya membuat riwayat berbohong |
| `DownloadSpec.engine` | `DownloadJobEntity.engine` + `DownloadRepository.start(engine=…)` | Menyesuaikan struktur yang sudah ada |

### 9.3 Batasan yang tetap berlaku

- **DASH `.mpd`** tidak didukung; hanya HLS `.m3u8` (di-remux FFmpeg bawaan).
- **DRM (Widevine)** dan **login** tidak didukung.
- Video yang diputar lewat **MSE/Blob** tidak menghasilkan URL yang bisa diunduh;
  panel akan tetap kosong dan pengguna diberi pesan.
- Halaman di luar 10 host yang didukung `UrlValidator` tidak bisa dibuka di
  browser mini — aplikasi ini bukan browser umum.

### 9.4 Verifikasi

| Uji | Hasil |
|---|---|
| `MigrationTest` (6) | Baris lama utuh, kolom baru `NULL`/`DEFAULT 0`, bentuk kolom sesuai Room |
| `EngineRouterTest` (13) | Fallback hanya untuk `DownloadFailed`/`UnsupportedUrl`/`NotFound`/`FfmpegFailed`/`InvalidUrl`; tidak untuk `Cancelled`/`Private` |
| `MediaSnifferTest` (14) | `image/*` ditolak walau URL `.mp4`; HLS ditandai stream; `best()` memilih berkas utuh lebih dulu |
| Mutasi | Menghapus `mimeType` dari `MigrationSql` → 3 test migrasi gagal |
| Rilis | `MediaScanBridge.push` bertahan setelah R8 (diverifikasi lewat `dexdump`) |

