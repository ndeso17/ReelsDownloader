# Product Requirements Document

## Telegram Reels Downloader (Instagram · Facebook · TikTok)

**Version:** 2.2
**Platform:** Telegram Bot
**Backend:** Python
**Downloader Engine:** yt-dlp
**Media Processing:** FFmpeg
**Penyimpanan User:** file JSON lokal (`users.json`), tanpa database server

---

## 1. Tujuan

Membangun Telegram Bot **penggunaan pribadi** yang memungkinkan user terdaftar mengirim URL video publik dari Instagram, Facebook, atau TikTok, kemudian bot:

1. menerima URL,
2. memvalidasi URL,
3. mendeteksi platform,
4. mengunduh media menggunakan yt-dlp,
5. mengirim video kembali ke Telegram,
6. menghapus file sementara setelah selesai.

Bot memiliki **mode akses** yang diatur via `.env` (FR-013): **public** (default, semua user bisa download) atau **private** (hanya user dalam whitelist Telegram ID). Pada mode private, `/getID`, `/start`, `/menu` tetap publik; fitur download dan `/setUser` dikunci untuk user terdaftar.

### Alur Bisnis

| # | Alur | Rujukan |
|---|---|---|
| 1 | User terdaftar mengirimkan link saja → diproses dengan aturan default (kualitas terbaik, video) - sama seperti v1.0 | FR-003, FR-005 |
| 2 | User mengirimkan `/advance`, lalu mengirimkan link → dialog step-by-step: (a) pilih **Video atau Audio**, (b) pilih **kualitas** sesuai pilihan langkah (a), lalu proses | FR-015..FR-018 |
| 3 | User mengirimkan `/start` → welcome message + daftar menu yang tersedia | FR-001 |
| 4 | User mengirimkan `/getID` → bot merespons Telegram user ID pengirim | FR-012 |
| 5 | Admin mendaftarkan satu atau lebih Telegram ID untuk mengakses download (default & advance) lewat `/setUser` | FR-014 |
| 6 | Download video/reels **TikTok** didukung | FR-004, FR-020 |
| 7 | `/start` pertama dari seseorang dicatat sebagai user baru; admin dapat notifikasi realtime dengan total count (1++) | FR-021 |
| 8 | Saat bot dihujani request, permintaan masuk **antrean terbatas**; saat penuh ditolak cepat tanpa menguras RAM (anti-OOM) | FR-022 |

Contoh alur default:

```text
User:

https://www.instagram.com/reel/ABC123/

Bot:

⏳ Sedang memproses...

Bot:

✅ Selesai

[Video]
```

Contoh alur advance:

```text
User: /advance

Bot: ⚙️ Mode Advance aktif. Kirim link-nya.

User: https://vt.tiktok.com/ZSxY12/

Bot: Pilih hasil:  [ 🎬 Video ]  [ 🎵 Audio ]        ← dialog 1 (FR-016)

User: (tap 🎬 Video)

Bot: Pilih kualitas: [ Best ] [ 1080p ] [ 720p ] [ 480p ] [ 360p ]   ← dialog 2 (FR-017)

User: (tap 720p)

Bot: ⏳ Sedang memproses...

Bot: ✅ Selesai  🎬 {title}  Source: TikTok  (720p)

[Video]
```

---

## 2. Target Platform

### Instagram

MVP mendukung URL seperti:

```text
https://www.instagram.com/reel/...
https://www.instagram.com/reels/...
https://www.instagram.com/p/...
```

Fokus utama adalah:

```text
/reel/
/reels/
```

### Facebook

MVP mendukung URL video publik yang dapat diekstrak oleh yt-dlp.

Contoh:

```text
https://www.facebook.com/reel/...
https://www.facebook.com/watch/...
https://www.facebook.com/...
```

### TikTok

MVP mendukung URL publik yang dapat diekstrak oleh yt-dlp, termasuk shortlink:

```text
https://www.tiktok.com/@user/video/...
https://vm.tiktok.com/...
https://vt.tiktok.com/...
```

Bila extractor menyediakan varian dengan dan tanpa watermark, varian **tanpa watermark** diprioritaskan (FR-020).

Dukungan aktual bergantung pada extractor yt-dlp dan perubahan platform.

---

## 3. Functional Requirements

### FR-001: Start

Bot harus merespons:

```text
/start
```

(perintah **publik**) dengan welcome message **lalu menampilkan menu yang tersedia** (inline keyboard):

```text
👋 Selamat datang di Reels Downloader

Kirim link Instagram / Facebook / TikTok dan saya unduh videonya,
atau pakai /advance untuk memilih tipe & kualitas dulu.

[📥 Download Default] [⚙️ Advance] [🆔 Get ID] [ℹ️ Menu]
```

Tombol hanya bisa dipakai sesuai hak akses user (FR-013); user tak terdaftar mendapat pesan akses ditolak.

---

### FR-002: Menu

Command:

```text
/menu
```

(perintah **publik**) menampilkan daftar perintah yang tersedia beserta status akses pengirim:

```text
📋 Menu
/getID  , lihat Telegram ID kamu (publik)
/start  , selamat datang + menu (publik)
/menu   , daftar ini (publik)
/advance, download dengan dialog pilihan (user terdaftar)
/setUser, kelola user (admin)
/cancel , batalkan dialog aktif (user terdaftar)
/stats  , statistik pemakaian (admin)
```

Menggantikan `/help` versi 1.0.

---

### FR-003: URL Detection

Bot harus mendeteksi URL yang dikirim sebagai plain text.

Tidak perlu command khusus.

```text
https://www.instagram.com/reel/xxxxx/
```

- Bila pengirim adalah user terdaftar dan mode default aktif → langsung diproses (FR-005).
- Bila mode `/advance` aktif untuk chat itu → masuk dialog FR-016/FR-017.
- Bila pengirim tidak terdaftar → ditolak sesuai FR-013 (private mode only; public mode bebas).

---

### FR-004: Platform Validation

Bot hanya menerima domain:

```text
instagram.com
www.instagram.com

facebook.com
www.facebook.com
m.facebook.com
fb.watch

tiktok.com
www.tiktok.com
vm.tiktok.com
vt.tiktok.com
```

URL dari domain lain ditolak.

---

### FR-005: Download

Downloader menggunakan yt-dlp.

Mode default (tanpa `/advance`), target format:

```text
bestvideo+bestaudio/best
```

Jika video dan audio terpisah, FFmpeg digunakan untuk menggabungkannya.

Pada mode advance, format mengikuti pilihan user di dialog (FR-016/FR-017), bukan default ini.

---

### FR-006: Metadata

Downloader mengambil metadata:

```text
title
duration
uploader
webpage_url
ext
filesize
```

Metadata digunakan untuk caption/logging.

---

### FR-007: Telegram Upload

Setelah download selesai, bot mengirim:

```text
🎬 {title}

Source: Instagram/Facebook/TikTok
```

beserta video. Output audio memakai caption `🎵 {title}` (FR-018).

---

### FR-008: Temporary Files

Semua file download disimpan pada:

```text
downloads/
```

Setelah upload berhasil atau gagal:

```text
file harus dihapus
```

---

### FR-009: Error Handling

Bot harus menangani:

```text
URL tidak valid
URL tidak didukung
Video private
Video tidak ditemukan
Download gagal
FFmpeg gagal
File terlalu besar
Telegram upload gagal
Timeout
Akses ditolak (user tidak terdaftar / bukan admin)      ← baru v2.0
Sesi dialog kedaluwarsa / dibatalkan                     ← baru v2.0
Antrean penuh / server sibuk (permintaan ditolak)        ← baru v2.2
```

User mendapatkan pesan yang mudah dipahami.

---

### FR-010: Concurrent Download

MVP membatasi jumlah download aktif agar VPS tidak kehabisan RAM/CPU.

Default:

```text
MAX_CONCURRENT_DOWNLOADS=2
```

---

### FR-011: User Rate Limit

MVP menggunakan rate limit sederhana.

Default:

```text
1 download / user / 10 detik
```

---

### FR-012: /getID (baru, v2.0)

Command:

```text
/getID
```

Perintah **publik**, siapa pun yang bisa mengakses bot boleh memakai ini.

Bot merespons dengan Telegram user ID numerik pengirim:

```text
🆔 Telegram ID kamu: 123456789
```

Sumber nilai: `update.effective_user.id`.

ID ini dipakai untuk pendaftaran whitelist oleh admin (FR-014). Bot tidak pernah menampilkan ID user lain.

---

### FR-013: Bot Mode & Access Whitelist (baru, v2.0)

Mode bot diatur lewat `.env`, var `BOT_MODE`:

```text
public   (default) → semua user boleh memakai semua fitur download,
                     identik perilaku v1.0; whitelist tidak berlaku
private            → download & konfigurasi khusus user ID terdaftar
```

Perubahan `BOT_MODE` diterapkan saat restart bot.

**Public mode**, tanpa gate:

* siapa pun boleh mengirim URL (default & advance), memakai dialog kualitas;
* `/setUser` tidak aktif; bila dipanggil bot membalas:

```text
ℹ️ /setUser tidak aktif.
Bot berjalan dalam public mode (BOT_MODE=public).
Ubah BOT_MODE=private di .env bila ingin mengunci akses.
```

**Private mode**, yang di-gate whitelist:

```text
kiriman URL (mode default maupun advance)
/advance
/setUser
/cancel
```

Yang tetap publik di **kedua** mode:

```text
/start
/menu
/getID
```

Status whitelist sebuah ID (private mode):

```text
admin       → OWNER_USER_ID dan/atau role admin di USERS_FILE; boleh /setUser
terdaftar   → boleh download default & advance
tidak ada   → akses ditolak
```

Daftar efektif = union(`OWNER_USER_ID`, `AUTHORIZED_USER_IDS`, isi `USERS_FILE`).

Bila `BOT_MODE=private` dan daftar efektif kosong (OWNER tidak diset, tidak ada seed), bot **fail-closed**, semua permintaan download ditolak dengan pesan:

```text
🔒 Bot dikunci (private mode).
Konfigurasi OWNER_USER_ID di .env untuk mengaktifkan akses.
```

Pesan penolakan standar (private mode, user tidak terdaftar):

```text
⛔ Akses ditolak. ID kamu belum didaftarkan.
Lihat ID kamu dengan /getID, lalu minta admin mendaftarkan via /setUser.
```

Perbandingan memakai `int` (Telegram user ID), bukan username.

---

### FR-014: /setUser (baru, v2.0)

Command khusus **admin**, **hanya aktif pada private mode** (`BOT_MODE=private`):

```text
/setUser add <telegram_id>
/setUser remove <telegram_id>
/setUser list
```

Bila bot berjalan di public mode, pengguna yang mencoba `/setUser` menerima:

```text
ℹ️ /setUser tidak aktif.
Bot berjalan dalam public mode (BOT_MODE=public).
Ubah BOT_MODE=private di .env bila ingin mengunci akses ke user terdaftar.
```

Perilaku (private mode):

- Menambah / menghapus user ID yang boleh mengakses download default & advance.
- Lebih dari satu ID boleh didaftarkan.
- `list` menampilkan ID + role (admin/terdaftar).
- Persisten di `USERS_FILE` (JSON), tetap ada setelah restart bot.
- Pemanggil bukan admin → pesan akses ditolak (FR-013); percobaan berulang di-log.
- Admin tidak bisa menghapus `OWNER_USER_ID` dari daftar efektif.
- Format ID harus angka; input lain ditolak dengan pesan jelas.

Contoh:

```text
Admin: /setUser add 987654321

Bot: ✅ User 987654321 ditambahkan.

Admin: /setUser list

Bot:
👥 Terdaftar:
987654321, terdaftar
123456789, admin
```

---

### FR-015: Advance Mode (baru, v2.0)

Command (user terdaftar):

```text
/advance
```

Mengaktifkan **mode advance** untuk chat tersebut (state in-memory per chat). Setelah aktif, bot meminta user mengirim link. Link berikutnya yang valid masuk dialog FR-016 → FR-017 → proses.

Ketentuan:

- Mode berlaku sampai pemrosesan selesai, `/advance` kedua (toggle off), `/cancel`, atau sesi kedaluwarsa (FR-019).
- Setelah satu pemrosesan selesai, mode kembali non-default (matikan sendiri; user bisa kirim link lagi untuk mode default, konsisten aturan alur #1).
- `/advance` dari user tidak terdaftar → ditolak (FR-013).

---

### FR-016: Dialog 1: Tipe Hasil (baru, v2.0)

Setelah link valid diterima dalam mode advance, bot menampilkan inline keyboard:

```text
Mau diambil yang mana?
[ 🎬 Video ]  [ 🎵 Audio ]
```

- Memilih **Video** → lanjut FR-017 daftar kualitas video.
- Memilih **Audio** → lanjut FR-017 daftar kualitas audio.
- Tidak ada tombol lain yang sah; pesan/editan lama dari dialog sebelumnya tidak lagi diterima (satu sesi dialog = satu link).

---

### FR-017: Dialog 2: Kualitas (baru, v2.0)

**Cabang Video**, inline keyboard:

```text
[ Best ] [ 1080p ] [ 720p ] [ 480p ] [ 360p ]
```

Mapping yt-dlp:

```text
Best  → bestvideo+bestaudio/best          (identik mode default)
1080p → bestvideo[height<=1080]+bestaudio/best[height<=1080]
720p  → bestvideo[height<=720]+bestaudio/best[height<=720]
480p  → bestvideo[height<=480]+bestaudio/best[height<=480]
360p  → bestvideo[height<=360]+bestaudio/best[height<=360]
```

Bila kualitas terpilih tidak tersedia di sumber, bot memakai kualitas **tertinggi yang <= pilihan** dan memberitahu di caption (mis. `(720p→480p)`).

**Cabang Audio**, inline keyboard:

```text
[ 320 kbps ] [ 192 kbps ] [ 128 kbps ]
```

Mapping: yt-dlp format audio terbaik + FFmpeg postprocessor `FFmpegExtractAudio` ke `mp3` dengan bitrate terpilih.

Setelah pilihan diterima → status `⏳ Sedang memproses...` (FR-003/Performance) → unduh → upload → cleanup.

---

### FR-018: Audio-Only Download (baru, v2.0)

Hasil audio-only adalah file `.mp3` (FFmpeg extraction), dikirim via `send_audio` dengan caption `🎵 {title}`, fallback `send_document` mengikuti aturan `MAX_FILE_SIZE_MB` (FR-007). Cleanup mengikuti FR-008.

---

### FR-019: Dialog Session Lifecycle (baru, v2.0)

- State dialog per chat: `(chat_id → {url, step, tipe, kualitas})`, in-memory.
- TTL dialog **120 detik**; kedaluwarsa → pesan:

```text
⌛ Sesi pilihan berakhir. Kirim link lagi (dengan /advance bila mau mode advance).
```

- `/cancel` membatalkan mode advance / dialog aktif dan menghapus state.
- Pesan callback dari dialog yang sudah selesai/kedaluwarsa diabaikan dengan jawaban `Sesi sudah berakhir`.

---

### FR-020: Dukungan TikTok (baru, v2.0)

URL TikTok diproses melalui jalur yang sama (validasi FR-004, download FR-005/FR-017, upload FR-007, cleanup FR-008), dengan ketentuan:

- Shortlink `vm.tiktok.com` / `vt.tiktok.com` diterima apa adanya (yt-dlp resolving sendiri, tanpa fetch redirect manual oleh bot).
- Prioritas varian tanpa watermark bila tersedia di metadata format.
- Caption `Source: TikTok`.
- Batas `MAX_FILE_SIZE_MB`, rate limit, dan whitelist berlaku identik dengan platform lain.

---

### FR-021: User Counter & Notifikasi Admin Realtime (baru, v2.2)

Bot mencatat setiap Telegram user ID yang pernah mengakses bot (sumber:
`update.effective_user.id`) ke himpunan user unik yang persisten.

Pemicu pencatatan: perintah `/start` (publik).

Perilaku:

- ID **pertama kali** terlihat → tambah ke daftar, naikkan hitungan user unik
  sebesar 1, lalu **kirim notifikasi realtime ke admin** (count 1++).
- ID yang sudah pernah tercatat → `/start` dijawab normal, **tanpa** notifikasi
  ulang (satu notifikasi per user seumur hidup; anti-spam, karena `/start`
  sering ditekan berulang).
- Yang dilaporkan = jumlah user **unik** yang pernah mengakses, bukan jumlah
  pesan.

Chat tujuan notifikasi: `ADMIN_NOTIFY_CHAT_ID`; bila kosong, fallback ke
`OWNER_USER_ID`. Bila keduanya kosong → notifikasi dilewati (hanya di-log);
bot tetap menjawab user.

Format notifikasi admin:

```text
🆕 User baru memakai bot

Telegram ID: 987654321
Nama:        Budi
Username:    @budi
Total user:  7
```

Ketentuan:

- Persistensi di `STATS_FILE` (JSON): himpunan ID unik + counter. Tetap ada
  setelah restart. Tulis atomik (file tmp + `os.replace`) agar tidak korup.
- Pengiriman notifikasi **fire-and-forget** sebagai task terpisah: kegagalan
  atau kelambatan API Telegram tidak menunda balasan `/start` (NFR Performance
  < 2 detik tetap terpenuhi).
- Kegagalan kirim (admin memblokir bot, `RetryAfter`, jaringan) di-log WARNING
 , tidak boleh meng-crash-kan bot (NFR Reliability). Counter TETAP bertambah
  meski notifikasi gagal dikirim.
- `/stats` (hanya admin, `OWNER_USER_ID`/role admin; di public mode tetap
  dibatasi ke admin): tampilkan total user unik, total permintaan diproses,
  total ditolak (rate limit / akses / antrean penuh), dan kedalaman antrean
  saat ini (`queue.qsize()`).
- Privasi: `STATS_FILE` dan `USERS_FILE` memuat identifier pribadi → file
  sensitif: jangan di-commit, `chmod 600`, dikecualikan dari image via
  `.dockerignore`. Daftar user tidak pernah ditampilkan ke non-admin.

---

### FR-022: Antrean Terbatas & Admission Control (baru, v2.2)

Tujuan: bot tidak kehabisan RAM saat dihujani request (anti-OOM).

Model lama membuat satu task background per request yang lolos rate limiter
dan membatasinya hanya dengan `asyncio.Semaphore`, saat diserbu, backlog task
tumbuh tanpa batas, ack membanjiri API Telegram, dan pekerjaan basi menumpuk.

Model baru:

- Satu `asyncio.Queue(maxsize=QUEUE_MAX_SIZE)` in-process, dikonsumsi worker
  berjumlah `MAX_CONCURRENT_DOWNLOADS` (pool worker tetap, started saat
  post_init, stopped saat shutdown).
- Handler TIDAK lagi `create_task` per request; handler hanya
  `queue.put_nowait(job)`.
- Jalur cepat handler memutuskan diterima/ditolak:
  - `QueueFull` → tolak cepat TANPA download:

```text
🚦 Server sedang penuh, coba lagi sebentar.
```

  - diterima → ack `⏳ Sedang memproses...` (boleh sertakan posisi antrean).
- Job yang sudah menunggu > `MAX_QUEUE_WAIT_SECONDS` (timestamp di objek job,
  dicek worker saat mengambil) dilewati: user diberi tahu

```text
⌛ Permintaanmu kedaluwarsa di antrean. Kirim ulang, ya.
```

  dan slot langsung dipakai job berikutnya (anti pekerjaan basi).
- `QUEUE_MAX_SIZE >= 1` dan `MAX_QUEUE_WAIT_SECONDS >= 1`; di luar rentang →
  `ValidationError` saat boot (`extra="forbid"` seperti var lain).
- Antrean in-memory: tanpa Redis/worker eksternal (tetap scope V2); konsekuensi
  yang diterima = reset saat restart, tidak dibagi antar replika.
- Satu job = satu slot utuh (download → upload → cleanup) sebagaimana WP-11;
  worker mengambil FIFO.
- Shutdown: worker dihentikan rapi, task aktif dibatalkan, tanpa task yatim.
- Rate limiter per-user (FR-011) tetap lapis PERTAMA (sebelum antrean);
  antrean = kontrol beban global lapis kedua.

---

## 4. Non-Functional Requirements

### Performance

Target:

```text
Bot response < 2 detik
```

untuk menerima request (termasuk respons dialog inline keyboard).

Download bergantung pada:

* ukuran video,
* bandwidth source,
* bandwidth VPS,
* server platform.

---

### Reliability

Bot tidak boleh crash hanya karena satu URL gagal.

Setiap pekerjaan download harus dibungkus exception handling.

Bot tidak boleh kehabisan memori saat diserbu: semua download lewat antrean
terbatas dengan penolakan cepat (FR-022); pekerjaan berat serentak tetap
dibatasi `MAX_CONCURRENT_DOWNLOADS`.

---

### Security

Bot harus:

* tidak mengeksekusi shell command dari input user,
* tidak mempercayai filename dari URL,
* menggunakan temporary directory,
* membatasi ukuran download,
* membatasi concurrency,
* tidak menyimpan token Telegram di source code,
* **menerapkan gate whitelist saat `BOT_MODE=private`: tolak akses non-whitelist ke semua fitur download dan `/setUser` (FR-013, FR-014)**,
* **tidak pernah menampilkan ID user lain kepada user selain ID-nya sendiri via `/getID` (FR-012)**,
* **memperlakukan `USERS_FILE` dan `STATS_FILE` sebagai file sensitif: jangan di-commit, chmod 600, dikecualikan dari image** (berisi identifier pribadi),
* **otorisasi `/setUser` berdasarkan user ID numerik, bukan username/nama tampilan yang bisa dipalsukan.**

---

## 5. Environment Variables

```env
TELEGRAM_BOT_TOKEN=

DOWNLOAD_DIR=downloads

MAX_CONCURRENT_DOWNLOADS=2

MAX_FILE_SIZE_MB=50

RATE_LIMIT_SECONDS=10

LOG_LEVEL=INFO

# Bot access mode (FR-013):
#   public : semua user boleh download; whitelist tidak aktif
#   private: hanya user ID terdaftar (OWNER_USER_ID + AUTHORIZED_USER_IDS) yang bisa download
BOT_MODE=public

# Private-mode seeds (hanya dipakai saat BOT_MODE=private):
OWNER_USER_ID=
AUTHORIZED_USER_IDS=
USERS_FILE=users.json

# User counter & notifikasi admin (FR-021)
ADMIN_NOTIFY_CHAT_ID=              # chat target notifikasi user baru; kosong = fallback OWNER_USER_ID
STATS_FILE=stats.json              # persistensi hitungan user unik + counter

# Antrean anti-OOM (FR-022)
QUEUE_MAX_SIZE=20                  # kapasitas antrean (>=1); penuh -> tolak cepat
MAX_QUEUE_WAIT_SECONDS=60          # job menunggu lebih dari ini dibatalkan
```

Catatan: `BOT_MODE=public` (default) = semua user bebas download seperti v1.0; tiga var whitelist hanya berlaku saat `BOT_MODE=private`. Untuk pemakaian pribadi, set `BOT_MODE=private` + `OWNER_USER_ID` di `.env`. `TELEGRAM_BOT_TOKEN` dsb. tetap wajib sah.

---

## 6. MVP Scope

### Included

* Telegram Bot
* Instagram
* Facebook
* TikTok
* URL validation
* yt-dlp
* FFmpeg
* download
* upload video
* upload audio (mp3)
* cleanup
* error handling
* concurrency limit
* basic rate limit
* logging
* mode publik/private via `.env` (`BOT_MODE`); whitelist user ID private (`/getID`, `/setUser`, gate FR-013/FR-014)
* user counter realtime + notifikasi admin (`/stats`) (FR-021)
* antrean kerja in-memory terbatas + penolakan cepat (FR-022)
* menu publik (`/start` + menu, `/menu`)
* mode advance + dialog tipe & kualitas (FR-015..FR-019)

### Not Included

* database server (whitelist cukup file JSON lokal)
* sistem akun/login penuh (hanya whitelist Telegram ID)
* premium subscription
* payment
* admin dashboard web
* Redis
* persistent download history
* authentication Instagram
* authentication Facebook
* scraping private accounts
* bypass privasi/watermark TikTok secara ilegal

---

## 7. Future Version

### V2

* Redis queue
* PostgreSQL (migrasi whitelist + history)
* download history
* admin commands lanjutan (suspend, quota per user)
* user statistics
* thumbnail
* progress percentage

### V3

* YouTube Shorts
* X/Twitter
* Pinterest
* Reddit

### V4

* Web dashboard
* authentication
* premium user
* quota
* payment
* analytics

---

## 8. Success Criteria

Bot dianggap berhasil (v2.0) jika:

1. Bot dapat menerima URL Instagram.
2. Bot dapat menerima URL Facebook.
3. Bot dapat menerima URL TikTok (termasuk shortlink). ← baru
4. URL publik yang didukung yt-dlp dapat di-download.
5. Video dapat dikirim kembali ke Telegram.
6. File sementara otomatis dihapus.
7. Error tidak menyebabkan bot berhenti.
8. Dua download dapat berjalan bersamaan.
9. Token Telegram tidak disimpan dalam source code.
10. Bot dapat berjalan 24/7 pada VPS.
11. `/getID` selalu membalas ID numerik pengirim yang benar, dari user mana pun. ← baru
12. Saat `BOT_MODE=private`, hanya user dalam whitelist yang dapat mengunduh; user lain ditolak dengan pesan jelas. ← baru
13. `/setUser add/remove/list` bekerja, dan hasil tetap ada setelah bot restart. ← baru
14. Alur advance menghasilkan file sesuai pilihan: tipe (video/audio) dan kualitas (mis. 720p atau 192k) terbukti pada output. ← baru
15. Audio-only menghasilkan `.mp3` dengan bitrate terpilih. ← baru
16. Mode default (kirim link saja) berperilaku identik dengan v1.0. ← baru
17. `/start` dari orang baru memicu tepat satu notifikasi admin dengan count naik 1; `/start` berulang dari ID sama tidak memicu notifikasi lagi. ← baru v2.2
18. `/stats` admin menampilkan total user unik, jumlah diproses/ditolak, dan kedalaman antrean yang benar. ← baru v2.2
19. Saat antrean penuh, permintaan baru ditolak cepat dengan pesan jelas dan penggunaan memori tetap datar. ← baru v2.2

Butir 3, 4, 14, 15 butuh uji nyata dengan konten publik → tandai `MANUAL-VERIFY` pada verifikasi.

---

## 9. Legal / Usage

Downloader ditujukan untuk konten yang pengguna berhak mengunduh atau gunakan, dan bot ini dikonfigurasi untuk **pemakaian pribadi** oleh pemilik akun Telegram yang terdaftar di whitelist.

Bot tidak dirancang untuk:

* melewati kontrol akses akun private,
* mengambil konten yang membutuhkan autentikasi tanpa izin,
* menghindari DRM,
* mengambil konten dengan cara mengakali pembatasan akses.

Dukungan terhadap URL juga bergantung pada kemampuan extractor yt-dlp dan perubahan platform.

---

## 10. Riwayat Versi

| Versi | Tanggal | Perubahan |
|---|---|---|
| 1.0 | 2026-09-12 | MVP awal: Instagram + Facebook, alur download default |
| 2.0 | 2026-09-13 | Whitelist user ID (`/getID`, `/setUser`, gate akses), `/menu`, mode `/advance` + dialog tipe Video/Audio dan pilihan kualitas, audio-only mp3, dukungan TikTok, env var `OWNER_USER_ID` / `AUTHORIZED_USER_IDS` / `USERS_FILE` |
| 2.1 | 2026-09-13 | Gate akses menjadi opsional via `BOT_MODE` (`public` default = terbuka seperti v1.0; `private` = whitelist aktif dan `/setUser` berfungsi); public mode menolak `/setUser` dengan pesan informatif |
| 2.2 | 2026-09-13 | FR-021 user counter + notifikasi admin realtime saat `/start` pertama (count 1++, persist di `STATS_FILE`, `/stats` untuk admin); FR-022 antrean `asyncio.Queue` terbatas + admission control (tolak cepat saat penuh, batal job kedaluwarsa) untuk cegah OOM saat diserbu; env var `ADMIN_NOTIFY_CHAT_ID`, `STATS_FILE`, `QUEUE_MAX_SIZE`, `MAX_QUEUE_WAIT_SECONDS` |
