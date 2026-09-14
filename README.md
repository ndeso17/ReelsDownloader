# ReelsDownloader - Telegram Reels Downloader (Instagram / Facebook / TikTok)

Bot Telegram penggunaan pribadi: kirim URL video publik dari Instagram, Facebook,
atau TikTok, bot memvalidasi domain, mengunduh dengan `yt-dlp` (FFmpeg merge
lewat yt-dlp), mengirim video/audio balik dengan caption, lalu menghapus file
sementara. Tanpa database, tanpa Redis, tanpa worker eksternal, tanpa login
platform.

Stack: Python 3.11+ (dev/image: 3.12), `python-telegram-bot` 22.8,
`yt-dlp` 2026.8.19, `pydantic-settings` 2.15.0.

## Fitur

Kontrol dasar:

- `/start` dan `/help` dengan instruksi singkat + contoh URL yang benar-benar
  berfungsi; teks welcome dan menu dikirim sebagai dua pesan terpisah.
- Deteksi URL otomatis di tengah teks biasa (regex `https?://\S+`), tanpa command
  khusus; teks tanpa URL dibalas panduan `/start`.
- Download publik Instagram Reels/Post, Facebook Video/Reels, dan TikTok (termasuk
  shortlink `vm.tiktok`/`vt.tiktok`) via `yt-dlp` + FFmpeg; mode default berperilaku
  identik dengan v1.0 untuk IG/FB.
- Kirim hasil sebagai video (mp4, merge lewat FFmpeg) atau audio saja (mp3),
  dengan caption `🎬 {judul}` / `🎵 {judul}` + `Source: Instagram`/`Facebook`/`TikTok`.
- Fallback `send_document` saat `send_video`/`send_audio` ditolak Telegram
  (mis. file > 50 MB atau codec tidak didukung) supaya user tetap menerima hasil.
- Batas ukuran file `MAX_FILE_SIZE_MB` (dicek dari metadata sebelum unduh dan saat
  upload), concurrency terbatas, rate limit per chat, timeout keras 60 detik.
- 9 kondisi error dipetakan ke pesan ramah; traceback lengkap hanya ke log.
- Cleanup file sementara di blok `finally` - sukses maupun gagal.

Kontrol akses (FR-012..FR-014):

- `/getID` membalas user ID pengirim (publik, untuk semua user).
- `/menu` menampilkan command yang tersedia + status akses user.
- Mode `public` (default) vs `private` dengan whitelist via `BOT_MODE`,
  `OWNER_USER_ID`, `AUTHORIZED_USER_IDS`, dan `USERS_FILE`.
- `/setUser add|remove|list` khusus owner; perubahan persisten dan tetap ada
  setelah restart.

Mode advance (FR-015..FR-019):

- `/advance` → dialog dua langkah dengan inline keyboard: pilih tipe
  `🎬 Video`/`🎵 Audio`, lalu pilih kualitas (video: Best/1080p/720p/480p/360p;
  audio: 320kbps/192kbps/128kbps).
- Kirim link → bot unduh sesuai pilihan, hasil = kualitas TEKENA (bukan yang
  diminta) bila sumber tidak menyediakan. Caption hasil menampilkan kualitas
  actual + requested (mis. `(1080p→720p)`).
- TTL dialog 120 detik (`⌛ Sesi pilihan berakhir. Kirim link lagi (dengan /advance
  bila mau mode advance).`).
- `/cancel` membatalkan dialog aktif dan mengirim menu; tanpa dialog aktif →
  pesan info.

Statistik & notifikasi admin (FR-021):

- `/stats` owner/admin: total user unik, total request diproses, total ditolak
  (rate limit / akses / antrean penuh), kedalaman antrean saat ini.
- Notifikasi realtime ke `ADMIN_NOTIFY_CHAT_ID` (fallback `OWNER_USER_ID`) saat
  user baru `/start` pertama kali; satu kali per user seumur hidup (dijaga
  counter `first_seen`).
- Persisten di `STATS_FILE` (JSON), atomik tmp+rename; counter `processed`/`rejected`
  = sejak restart (lihat Log WP-20).

Antrean anti-OOM (FR-022):

- Satu `asyncio.Queue(maxsize=QUEUE_MAX_SIZE)` in-process, dikonsumsi
  `MAX_CONCURRENT_DOWNLOADS` worker.
- Queue penuh → tolak cepat `🚦 Server sedang penuh, coba lagi sebentar.`
- Job menunggu > `MAX_QUEUE_WAIT_SECONDS` → dibatalkan +
  `⌛ Permintaanmu kedaluwarsa di antrean. Kirim ulang, ya.`
- Rate limiter per chat (FR-011) tetap lapis pertama; antrean = lapis kedua untuk
  kontrol beban global.
- Ack `⏳ Sedang memproses...` terkirim **sebelum** work masuk antrean, jadi
  response awal tetap cepat (< 2 dtk, NFR Performance).
- Shutdown worker rapi: task dibatalkan, tidak ada task yatim.

## Environment variables

Persis 14 var (`TELEGRAM_BOT_TOKEN` sampai `MAX_QUEUE_WAIT_SECONDS`), tidak ada var lain
yang dibaca (`extra="forbid"`). Nilai di luar rentang sah → `ValidationError` saat boot.

| Variabel | Default | Contoh | Arti |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(wajib)* | `123456:AAExampleTokenPlaceholder` | Token bot dari @BotFather; tersimpan sebagai `SecretStr`, tidak pernah tercetak di log/dump |
| `DOWNLOAD_DIR` | `downloads` | `downloads` | Direktori file sementara + volume download |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | `2` | Jumlah job (download+upload+cleanup) serentak (`asyncio.Semaphore`); `>= 1` |
| `MAX_FILE_SIZE_MB` | `50` | `50` | Batas ukuran file (MB); `>= 1` |
| `RATE_LIMIT_SECONDS` | `10` | `10` | Jeda minimum antar request per chat; `>= 0` |
| `LOG_LEVEL` | `INFO` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `BOT_MODE` | `public` | `private` | `public` \| `private`; private mengaktifkan whitelist dan `/setUser` |
| `OWNER_USER_ID` | *(kosong)* | `123456789` | Telegram user ID owner; WAJIB diisi bila `BOT_MODE=private` |
| `AUTHORIZED_USER_IDS` | *(kosong)* | `11111111,22222222` | Seed whitelist tambahan, koma-tanpa-spasi; opsional |
| `USERS_FILE` | `users.json` | `data/users.json` | Path file JSON persisten daftar user terdaftar; sensitif |
| `ADMIN_NOTIFY_CHAT_ID` | *(kosong)* | `123456789` | Chat target notifikasi user baru; kosong = fallback `OWNER_USER_ID` |
| `STATS_FILE` | `stats.json` | `data/stats.json` | Path file JSON persisten statistik; sensitif |
| `QUEUE_MAX_SIZE` | `20` | `20` | Kapasitas antrean in-process (`>= 1`); saat penuh → tolak cepat `🚦` |
| `MAX_QUEUE_WAIT_SECONDS` | `60` | `60` | Batas waktu tunggu sebelum job dibatalkan (`>= 1`) → `⌛` |

Catatan mode: `BOT_MODE=private` WAJIB `OWNER_USER_ID` diisi (fail-closed bila kosong =
semua download ditolak). `AUTHORIZED_USER_IDS` koma-tanpa-spasi. Daftar efektif =
union(`OWNER_USER_ID`, `AUTHORIZED_USER_IDS`, isi `USERS_FILE`). `QUEUE_MAX_SIZE` dan
`MAX_QUEUE_WAIT_SECONDS` mengendalikan perilaku penolakan `🚦`/`⌛`.

`USERS_FILE` dan `STATS_FILE` memuat identifier Telegram = PII sensitif: jangan
di-commit, jangan dibagikan via kanal publik (PRD §4 Security + AGENTS §5a), gunakan
`chmod 600` di host, dan pastikan tercakup di `.gitignore`/`.dockerignore`.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Isi `TELEGRAM_BOT_TOKEN` di `.env` dengan token dari **@BotFather** (`/newbot`).
`.env` sudah ada di `.gitignore` dan repo ini publik: jangan pernah menaruh token asli
di file yang bisa di-diff.

Bila ingin private mode (whitelist), tambahkan:

```bash
BOT_MODE=private
OWNER_USER_ID=<your_telegram_id>   # cek via /getID setelah bot berjalan
AUTHORIZED_USER_IDS=               # opsional, kosongkan bila tidak ada
```

Bila bot jalan sebagai container non-root (`appuser`), arahkan file persisten ke direktori
yang bisa ditulis + mount volume:

```bash
mkdir -p data && chmod 700 data
USERS_FILE=data/users.json
STATS_FILE=data/stats.json
chmod 600 data/users.json data/stats.json  # setelah file dibuat oleh bot
```

## Run

```bash
python -m app.main
```

Bot polling (`getUpdates`), tidak butuh webhook/domain. Log INFO `application built`
lalu `polling started` menandakan boot sukses. Token salah → `telegram.error.InvalidToken`
dan proses exit (rc=1). `ValidationError` boot → nama var di luar 14, nilai enum salah,
atau numeric < 1.

## Docker

Build image (basis `python:3.12-slim` + `ffmpeg` + `procps`, user non-root `appuser`
uid 10001, `HEALTHCHECK` `pgrep -f "python -m app.main"` tiap 30s):

```bash
docker build -t reelsdownloader .
```

Jalankan, semua var dari `--env-file`, `DOWNLOAD_DIR=/app/downloads` sudah di-set di
image dan di-mount sebagai volume. Bila `BOT_MODE=private` atau ingin statistik
persisten, sediakan direktori `data/` yang bisa ditulis `appuser` (uid 10001 di
container):

```bash
mkdir -p "$PWD/data" && chmod 777 "$PWD/data"   # owner appuser di container
docker run --rm --env-file .env \
  -v "$PWD/downloads:/app/downloads" \
  -v "$PWD/data:/app/data" \
  -e USERS_FILE=/app/data/users.json \
  -e STATS_FILE=/app/data/stats.json \
  reelsdownloader
```

Setelah bot menulis pertama kalinya, ketatkan permission di host:
`chmod 600 data/users.json data/stats.json`. Var bisa juga lewat `-e` satu per satu:

```bash
docker run -d --name reelsdownloader --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
  -e DOWNLOAD_DIR=/app/downloads \
  -e MAX_CONCURRENT_DOWNLOADS=2 \
  -e MAX_FILE_SIZE_MB=50 \
  -e RATE_LIMIT_SECONDS=10 \
  -e LOG_LEVEL=INFO \
  -e BOT_MODE=private \
  -e OWNER_USER_ID=<your_telegram_id> \
  -e AUTHORIZED_USER_IDS=11111111,22222222 \
  -e USERS_FILE=/app/data/users.json \
  -e ADMIN_NOTIFY_CHAT_ID= \
  -e STATS_FILE=/app/data/stats.json \
  -e QUEUE_MAX_SIZE=20 \
  -e MAX_QUEUE_WAIT_SECONDS=60 \
  -v "$PWD/downloads:/app/downloads" \
  -v "$PWD/data:/app/data" \
  reelsdownloader
```

Catatan operasional:
- Satu container = satu proses (`CMD` exec form, `python -m app.main`), supaya
  `Semaphore` dan rate limiter in-memory valid. Banyak replika = banyak limit independen.
- `.dockerignore` mengecualikan `tests/`, `docs/`, `.env`, `.env.*`, `.venv`,
  `AGENTS.md`, `users.json*`, `stats.json*` dari build context.
- Cek health: `docker inspect --format '{{json .State.Health}}' <container>`.
- Log: `docker logs -f <container>`. Hentikan: `docker stop <container>` (SIGTERM).

## Deploy 24/7 di VPS

Docker (rekomendasi, FFmpeg sudah termasuk):

```bash
git clone git@github.com:ndeso17/ReelsDownloader.git && cd ReelsDownloader
docker build -t reelsdownloader .
cp .env.example .env && chmod 600 .env && $EDITOR .env   # isi token + mode
mkdir -p /srv/reelsdownloader/{downloads,data}
chmod 777 /srv/reelsdownloader/data   # appuser uid 10001 perlu tulis
docker run -d --name reelsdownloader --restart unless-stopped \
  --env-file .env \
  -v /srv/reelsdownloader/downloads:/app/downloads \
  -v /srv/reelsdownloader/data:/app/data \
  -e USERS_FILE=/app/data/users.json \
  -e STATS_FILE=/app/data/stats.json \
  reelsdownloader
docker logs -f reelsdownloader        # tunggu "polling started"
```

Tanpa Docker (systemd; butuh FFmpeg terpasang di host):

```ini
# /etc/systemd/system/reelsdownloader.service
[Unit]
Description=ReelsDownloader Telegram bot
After=network-online.target

[Service]
WorkingDirectory=/srv/reelsdownloader/ReelsDownloader
EnvironmentFile=/srv/reelsdownloader/ReelsDownloader/.env
ExecStart=/srv/reelsdownloader/ReelsDownloader/.venv/bin/python -m app.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now reelsdownloader
journalctl -u reelsdownloader -f
```

`--restart unless-stopped` / `Restart=always` menjaga bot hidup; satu URL gagal tidak
menghentikan proses (exception tertangkap per job, NFR Reliability). `USERS_FILE` dan
`STATS_FILE` di bawah `/srv/...` perlu permission `600` dan owned service user. Status
24/7 nyata di VPS masih perlu diverifikasi manusia (PRD §8 butir 10 = MANUAL-VERIFY).

## Test & lint

```bash
ruff check .
ruff format --check .
.venv/bin/python -m pytest -q --tb=short
```

Semua test jalan tanpa akses Instagram/Facebook/TikTok nyata (yt-dlp dan bot di-mock).
`tests/test_wp13.py` otomatis *skip* bila daemon/image Docker tidak ada.

## Ops

### Tuning antrean (FR-022)

| Situasi | Rekomendasi |
|---|---|
| Server sering penuh di jam ramai | Naikkan `QUEUE_MAX_SIZE` (default 20) |
| User komplain request kedaluwarsa | Naikkan `MAX_QUEUE_WAIT_SECONDS` (default 60) |
| RAM terbatas, worker antri lama | Turunkan `MAX_CONCURRENT_DOWNLOADS` (default 2) |
| Ingin tolak lebih agresif | Perkecil `QUEUE_MAX_SIZE`; pastikan `>= 1` |

Antrean in-memory: reset saat restart, tidak dibagi antar replika (NFR Reliability).
Rate limiter per-user (FR-011) tetap lapis PERTAMA; antrean = kontrol beban global
lapis kedua.

### Monitoring statistik (FR-021)

Command admin `/stats` menampilkan:
- Total user unik (persisten di `STATS_FILE`, bertahan antar restart)
- Total permintaan diproses (counter sejak restart)
- Total ditolak - rate limit / akses / antrean penuh (counter sejak restart)
- Kedalaman antrean saat ini (`queue.qsize()` / `QUEUE_MAX_SIZE`)

Notifikasi realtime dikirim ke `ADMIN_NOTIFY_CHAT_ID`; kosong = fallback
`OWNER_USER_ID`. Bila keduanya kosong, notifikasi dilewati (log saja).

### Privasi file sensitif (USERS_FILE + STATS_FILE)

Keduanya memuat identifier Telegram = PII:
- Jangan di-commit ke repo (default `users.json` / `stats.json` + varian `data/`).
- Gunakan `chmod 600` pada host; di container gunakan volume terpisah + ketatkan
  setelah bot menulis pertama kalinya.
- Tercakup di `.gitignore` dan `.dockerignore`; jangan pernah tempel isinya di issue/PR.

### Command reference

| Command | Akses | Keterangan |
|---|---|---|
| `/start` | Publik | Welcome message + daftar command singkat |
| `/help` | Publik | Panduan penggunaan bot |
| `/getID` | Publik | Balas user ID numerik pengirim |
| `/menu` | Publik | Menu lengkap + status akses user |
| `/advance` | Whitelist di `BOT_MODE=private` | Dialog pilih tipe + kualitas/resolusi |
| `/cancel` | Whitelist di `BOT_MODE=private` | Batalkan dialog advance aktif |
| `/setUser add|remove|list` | Owner saja (`OWNER_USER_ID`) | Kelola whitelist user; hanya aktif di `BOT_MODE=private` |
| `/stats` | Owner saja (`OWNER_USER_ID`) | Statistik pemakaian bot |

## Troubleshooting

9 kondisi error FR-009 + pesan tambahan v2.2. String persis seperti di kode:

| Kondisi | Pesan bot | Penyebab / langkah |
|---|---|---|
| URL tidak valid | `❌ URL tidak valid` | URL tidak bisa diparse; minta link lengkap `https://...` |
| URL tidak didukung | `❌ URL tidak didukung. Kirim link Instagram/Facebook/TikTok.` | Domain di luar whitelist 10 host (jalur validasi membalas `Host tidak didukung: '<host>'`) |
| Video private | `🔒 Video private/terbatas.` | Akun privat / butuh login / age-restricted. Bot **tidak** mengakali login (PRD §6/§9) |
| Video tidak ditemukan | `🔍 Video tidak ditemukan.` | Post dihapus / URL salah / extractor tidak mendukung format itu |
| Download gagal | `⚠️ Gagal mengunduh.` | Jaringan/sumber bermasalah; cek `docker logs` untuk traceback |
| FFmpeg gagal | `⚠️ Gagal memproses video.` | Mapping tersedia untuk `FFmpegFailedError`; pastikan `ffmpeg` tersedia di host/image |
| File terlalu besar | `📏 File terlalu besar.` | Melebihi `MAX_FILE_SIZE_MB` (default 50). Naikkan bila perlu |
| Upload Telegram gagal | `⚠️ Gagal mengirim ke Telegram.` | API Telegram menolak (token, jaringan, atau batas ukuran/format) |
| Timeout | `⏱️ Timeout.` | Job melebihi 60 dtk (`DOWNLOAD_TIMEOUT_SECONDS`) atau socket/http 30 dtk |

Pesan tambahan di luar 9 kondisi FR-009 (kontrol alur v2.2):

| Kondisi | Pesan bot | Sumber |
|---|---|---|
| Rate limit (FR-011) | `Terlalu sering; coba lagi dalam N.N detik` | Handler mengirim langsung (`str(exc)`), tanpa emoji |
| Akses ditolak (FR-013) | `🚫 Akses ditolak. Bot hanya untuk pengguna terdaftar.` | `BOT_MODE=private` dan user tidak ada di whitelist; minta `/setUser add` |
| Queue penuh (FR-022) | `🚦 Server sedang penuh, coba lagi sebentar.` | Antrean mencapai `QUEUE_MAX_SIZE`; naikkan `QUEUE_MAX_SIZE` atau kurangi beban |
| Job kedaluwarsa (FR-022) | `⌛ Permintaanmu kedaluwarsa di antrean. Kirim ulang, ya.` | Job menunggu > `MAX_QUEUE_WAIT_SECONDS`; kemungkinan antrean sangat padat |
| Dialog advance kedaluwarsa (FR-018) | `⌛ Sesi pilihan berakhir. Kirim link lagi (dengan /advance bila mau mode advance).` | TTL 120 detik dialog terlampaui; kirim `/advance` ulang |

Boot failure cepat (v2.2):

- `ValidationError: BOT_MODE` → nilai bukan `public`/`private` (case-sensitive).
- `ValidationError: OWNER_USER_ID` di private mode → kosong atau bukan integer positip.
- `ValidationError: QUEUE_MAX_SIZE` / `MAX_QUEUE_WAIT_SECONDS` → < 1 (harus positip).
- `InvalidToken` → `TELEGRAM_BOT_TOKEN` salah; cek @BotFather, jangan tempel di issue.

Masalah umum lain:

- **Bot tidak merespons** → token salah (`InvalidToken` di log), bot di-block,
  atau `polling started` belum muncul.
- **`/setUser` tidak aktif** → normal di `BOT_MODE=public`. Ubah `BOT_MODE=private`
  di `.env` + restart bot.
- **Notifikasi user baru tidak sampai** → cek `ADMIN_NOTIFY_CHAT_ID`/`OWNER_USER_ID`;
  keduanya kosong = dilewati (log saja). Bot harus bisa kirim message ke chat itu.
- **`users.json`/`stats.json` hilang setelah restart container** → path belum di-mount
  sebagai volume; cek `-v "$PWD/data:/app/data"` + `USERS_FILE=/app/data/users.json`.
- **`File hasil download tidak ditemukan` / merge error di Docker** → FFmpeg tidak ada
  atau volume `/app/downloads` tidak bisa ditulis (`appuser` uid 10001).
- **Instagram/Facebook/TikTok berhenti mendukung** → biasanya perubahan extractor
  `yt-dlp`; `pip install -U yt-dlp` lalu rebuild image.
- **Dialog advance tidak bisa dilanjutkan setelah restart** → state `DialogState`
  in-memory; restart = reset. Kirim `/advance` ulang.

## Batasan

Sesuai PRD §6 (Not Included) bukan bug, memang di luar MVP:

- Tanpa database, tanpa akun user permanen, tanpa riwayat download persisten, tanpa
  quota/statistik untuk user umum (statistik hanya admin, PRD §7), tanpa admin
  dashboard, tanpa pembayaran.
- Tanpa Redis dan tanpa worker terpisah (ARSITEKTUR.md menggambarkan itu untuk V2
  lanjut, bukan target v2.2 ini).
- Tanpa autentikasi Instagram/Facebook/TikTok dan tanpa scraping akun privat.
- Kualitas video/audio bisa dipilih lewat `/advance` (FR-015..FR-018), tetapi tanpa
  progres persen, tanpa thumbnail kustom, dan hasil = kualitas TEKENA bila sumber
  tidak menyediakan kualitas diminta (ada di caption).
- Domain didukung terbatas pada 10 host whitelist (`instagram.com`,
  `www.instagram.com`, `facebook.com`, `www.facebook.com`, `m.facebook.com`,
  `fb.watch`, `tiktok.com`, `www.tiktok.com`, `vm.tiktok.com`, `vt.tiktok.com`);
  dukungan aktual bergantung pada kemampuan extractor `yt-dlp` dan perubahan
  platform (PRD §2, §9).
- Limit concurrency/rate/queue bersifat in-memory: reset saat restart dan tidak
  dibagi antar replika.
- State dialog advance (FR-015..FR-018) in-memory: reset saat restart.
- File sementara hidup hanya selama job; tidak ada cache/arsip download.

## Legal

Bot ini ditujukan untuk konten publik atau konten yang pengguna berhak
mengunduh/menggunakannya. Bot **tidak** dirancang untuk:

- melewati kontrol akses akun privat,
- mengambil konten yang membutuhkan autentikasi tanpa izin,
- menghindari DRM,
- mengakali pembatasan akses platform.

Bot secara eksplisit menolak konten privat/login-required (`🔒 Video
private/terbatas.`). Kepatuhan terhadap hak cipta konten tetap tanggung jawab
pengguna.
