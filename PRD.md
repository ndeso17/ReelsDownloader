# Product Requirements Document

## Telegram Instagram & Facebook Reels Downloader

**Version:** 1.0 MVP
**Platform:** Telegram Bot
**Backend:** Python
**Downloader Engine:** yt-dlp
**Media Processing:** FFmpeg
**Database:** Tidak diperlukan untuk MVP

---

## 1. Tujuan

Membangun Telegram Bot yang memungkinkan pengguna mengirim URL video publik dari Instagram atau Facebook, kemudian bot:

1. menerima URL,
2. memvalidasi URL,
3. mendeteksi platform,
4. mengunduh media menggunakan yt-dlp,
5. mengirim video kembali ke Telegram,
6. menghapus file sementara setelah selesai.

Contoh:

```text
User:

https://www.instagram.com/reel/ABC123/

Bot:

⏳ Sedang memproses...

Bot:

✅ Selesai

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

Dukungan aktual bergantung pada extractor yt-dlp dan perubahan platform.

---

## 3. Functional Requirements

### FR-001 — Start

Bot harus merespons:

```text
/start
```

dengan informasi:

```text
👋 Instagram/Facebook Downloader

Kirim link Instagram atau Facebook Reels
dan saya akan mencoba mengunduh videonya.

Contoh:
https://www.instagram.com/reel/xxxxx/
```

---

### FR-002 — Help

Command:

```text
/help
```

menampilkan cara penggunaan.

---

### FR-003 — URL Detection

Bot harus mendeteksi URL yang dikirim sebagai plain text.

Tidak perlu command khusus.

Contoh:

```text
https://www.instagram.com/reel/xxxxx/
```

langsung diproses.

---

### FR-004 — Platform Validation

Bot hanya menerima domain:

```text
instagram.com
www.instagram.com

facebook.com
www.facebook.com
m.facebook.com
fb.watch
```

URL dari domain lain ditolak.

---

### FR-005 — Download

Downloader menggunakan yt-dlp.

Target format:

```text
bestvideo+bestaudio/best
```

Jika video dan audio terpisah, FFmpeg digunakan untuk menggabungkannya.

---

### FR-006 — Metadata

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

### FR-007 — Telegram Upload

Setelah download selesai, bot mengirim:

```text
🎬 {title}

Source: Instagram/Facebook
```

beserta video.

---

### FR-008 — Temporary Files

Semua file download disimpan pada:

```text
downloads/
```

Setelah upload berhasil atau gagal:

```text
file harus dihapus
```

---

### FR-009 — Error Handling

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
```

User mendapatkan pesan yang mudah dipahami.

---

### FR-010 — Concurrent Download

MVP membatasi jumlah download aktif agar VPS tidak kehabisan RAM/CPU.

Default:

```text
MAX_CONCURRENT_DOWNLOADS=2
```

---

### FR-011 — User Rate Limit

MVP menggunakan rate limit sederhana.

Default:

```text
1 download / user / 10 detik
```

---

## 4. Non-Functional Requirements

### Performance

Target:

```text
Bot response < 2 detik
```

untuk menerima request.

Download bergantung pada:

* ukuran video,
* bandwidth source,
* bandwidth VPS,
* server platform.

---

### Reliability

Bot tidak boleh crash hanya karena satu URL gagal.

Setiap pekerjaan download harus dibungkus exception handling.

---

### Security

Bot harus:

* tidak mengeksekusi shell command dari input user,
* tidak mempercayai filename dari URL,
* menggunakan temporary directory,
* membatasi ukuran download,
* membatasi concurrency,
* tidak menyimpan token Telegram di source code.

---

## 5. Environment Variables

```env
TELEGRAM_BOT_TOKEN=

DOWNLOAD_DIR=downloads

MAX_CONCURRENT_DOWNLOADS=2

MAX_FILE_SIZE_MB=50

RATE_LIMIT_SECONDS=10

LOG_LEVEL=INFO
```

---

## 6. MVP Scope

### Included

* Telegram Bot
* Instagram
* Facebook
* URL validation
* yt-dlp
* FFmpeg
* download
* upload video
* cleanup
* error handling
* concurrency limit
* basic rate limit
* logging

### Not Included

* database
* user account system
* premium subscription
* payment
* admin dashboard
* Redis
* persistent download history
* authentication Instagram
* authentication Facebook
* scraping private accounts

---

## 7. Future Version

### V2

* Redis queue
* PostgreSQL
* download history
* admin commands
* user statistics
* configurable quality
* thumbnail
* progress percentage

### V3

* TikTok
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

MVP dianggap berhasil jika:

1. Bot dapat menerima URL Instagram.
2. Bot dapat menerima URL Facebook.
3. URL publik yang didukung yt-dlp dapat di-download.
4. Video dapat dikirim kembali ke Telegram.
5. File sementara otomatis dihapus.
6. Error tidak menyebabkan bot berhenti.
7. Dua download dapat berjalan bersamaan.
8. Token Telegram tidak disimpan dalam source code.
9. Bot dapat berjalan 24/7 pada VPS.

---

## 9. Legal / Usage

Downloader ditujukan untuk konten yang pengguna berhak mengunduh atau gunakan.

Bot tidak dirancang untuk:

* melewati kontrol akses akun private,
* mengambil konten yang membutuhkan autentikasi tanpa izin,
* menghindari DRM,
* mengambil konten dengan cara mengakali pembatasan akses.

Dukungan terhadap URL juga bergantung pada kemampuan extractor yt-dlp dan perubahan platform.
