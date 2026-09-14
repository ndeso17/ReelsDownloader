# ReelsDownloader Telegram Reels Downloader (Instagram / Facebook / TikTok)

Bot Telegram penggunaan pribadi: kirim URL video publik dari Instagram, Facebook,
atau TikTok, bot memvalidasi domain, mengunduh dengan `yt-dlp` (FFmpeg merge
lewat yt-dlp), mengirim video/audio balik dengan caption, lalu menghapus file
sementara. Tanpa database, tanpa Redis, tanpa worker eksternal, tanpa login
platform.

Stack: Python 3.11+ (dev/image: 3.12), `python-telegram-bot` 22.8,
`yt-dlp` 2026.8.19, `pydantic-settings` 2.15.0.

## Fitur

| FR | Perilaku user (persis seperti diimplementasi) |
|---|---|
| FR-001 | `/start` → welcome message "👋 Instagram/Facebook/TikTok Downloader" + instruksi + contoh URL; kemudian kirim `_MENU_SHORT_TEXT` berisi daftar command singkat. Teks welcome dan menu dikirim sebagai dua pesan terpisah agar UI tetap bersih |
| FR-002 | `/help` → teks bantuan ("Cara penggunaan:") yang merangkum cara pakai bot, perintah yang tersedia, dan contoh URL. Pesan ini dikirim langsung oleh handler |
| FR-003 | URL di tengah teks biasa diambil otomatis (regex `https?://\S+`), tanpa command khusus. Teks tanpa URL → bot membalas panduan `/start`. URL diproses via modal default (langsung unduh) atau modal advance (`/advance`) sesuai pilihan user |
| FR-004 | Domain didukung 10 host (6 Instagram/Facebook + 4 TikTok): `instagram.com`, `www.instagram.com`, `facebook.com`, `www.facebook.com`, `m.facebook.com`, `fb.watch`, `tiktok.com`, `www.tiktok.com`, `vm.tiktok.com`, `vt.tiktok.com`. Host lain → balasan `Host tidak didukung: '<host>'`; scheme bukan http/https → `Scheme tidak didukung: '<scheme>'` |
| FR-005 | yt-dlp via Python API. Video: format `bestvideo+bestaudio/best` (merge mp4). Audio: format `bestaudio` + FFmpeg postprocessor `FFmpegExtractAudio` ke mp3. `noplaylist`, timeout socket/http 30 dtk, hard-cap job 60 dtk |
| FR-006 | Metadata dibaca: `title`, `duration`, `uploader`, `webpage_url`, `ext`, `filesize` |
| FR-007 | Caption video: `🎬 {title}` baris kosong `Source: Instagram`/`Source: Facebook`/`Source: TikTok`. Caption audio: `🎵 {title}` baris kosong `Source: ...`. Kirim via `send_video`/`send_audio`; bila ukuran > `MAX_FILE_SIZE_MB` → fallback `send_document` |
| FR-008 | `downloads/` dibersihkan di blok `finally` - sukses maupun gagal |
| FR-009 | 9 kondisi error dipetakan ke pesan ramah (lihat Troubleshooting); traceback lengkap hanya ke log |
| FR-010 | Maks `MAX_CONCURRENT_DOWNLOADS` job (download+upload+cleanup) serentak; sisanya mengantri lewat antrean terbatas |
| FR-011 | Per chat: request kedua dalam `RATE_LIMIT_SECONDS` ditolak dengan pesan dari `str(exc)` (`Terlalu sering; coba lagi dalam N.N detik`), tanpa emoji. Pesan dikirim langsung dari handler |
| FR-012 | `/getID` (publik): balas user ID numerik pengirim. Tidak ada parameter `<telegram_id>` — semua user melihat ID mereka sendiri |
| FR-013 | Bot mode: `public` (default, semua user bebas download, identik MVP v1.0) atau `private` (whitelist aktif, download & `/setUser` dikunci ke user terdaftar). Perubahan efektif setelah restart |
| FR-014 | `/setUser add/remove/list` khusus **owner** (`OWNER_USER_ID`), hanya aktif di `BOT_MODE=private`; persisten di `USERS_FILE` (JSON). Owner tidak bisa menghapus dirinya sendiri. User terdaftar (non-owner) tidak bisa mengelola daftar |
| FR-015 | `/advance` memicu dialog step-by-step dengan inline keyboard: pilih tipe (Video/Audio), lalu pilih kualitas (resolusi untuk video: Best/720p/480p/360p; kualitas untuk audio: 320k/192k/128k). Setelah dipilih, proses unduh dimulai. Tombol Cancel membatalkan dialog |
| FR-016 | Dialog advance menyimpan state per-user (`DialogState` dengan TTL 120 detik). Saat queue penuh, pengguna yang sedang dialog tetap mendapat callback keyboard (stale check via TTL), tapi link tidak diproses sampai queue longgar |
| FR-017 | State advance TIDAK dipulihkan setelah restart bot (tidak ada file persistensi). Jika bot restart saat user menunggu callback, state hilang. User perlu memulai `/advance` ulang |
| FR-018 | `/cancel` membatalkan dialog advance aktif: jika ada dialog aktif, hapus state dan kirim menu; jika tidak ada dialog aktif → kirim pesan info bahwa tidak ada dialog yang aktif. Callback kedaluwarsa → toast `Sesi sudah berakhir` (PRD MD:546) + pesan baru ke chat (PRD MD:542) |
| FR-020 | Download video/reels TikTok didukung; shortlink `vm.tiktok.com`/`vt.tiktok.com` diterima apa adanya (resolving oleh yt-dlp). Caption `Source: TikTok`. Batas ukuran, rate limit, dan whitelist berlaku identik dengan platform lain |
| FR-021 | `/start` pertama dari seseorang dicatat sebagai user baru; admin mendapat notifikasi realtime format: `🆕 User baru memakai bot\n\nID: <user_id>\nNama: <first_name>\nUsername: @<username>\nTotal user: <N>` (format sesuai kode). Persistensi di `STATS_FILE` (atomik write via tmp+rename). Counter unik (satu notifikasi per seumur hidup per user). `/stats` admin menampilkan total user unik, total request diproses, total ditolak (rate limit/akses/antrean penuh), kedalaman antrean saat ini |
| FR-022 | Antrean terbatas: satu `asyncio.Queue(maxsize=QUEUE_MAX_SIZE)` in-process, dikonsumsi `MAX_CONCURRENT_DOWNLOADS` worker; saat penuh ditolak cepat `🚦 Server sedang penuh, coba lagi sebentar.`; job menunggu > `MAX_QUEUE_WAIT_SECONDS` dibatalkan → `⌛ Permintaanmu kedaluwarsa di antrean. Kirim ulang, ya.`; shutdown worker rapi (task dibatalkan, tidak ada task yatim) |

Ack `⏳ Sedang memproses...` terkirim **sebelum** work masuk antrean, jadi
response awal tetap cepat (< 2 dtk, NFR Performance) walau semua slot busy.

## Environment variables

Persis 14 var (`TELEGRAM_BOT_TOKEN` sampai `MAX_QUEUE_WAIT_SECONDS`), tidak ada var lain yang dibaca (`extra="forbid"`).
Nilai di luar rentang sah → `ValidationError` saat boot.

### Variabel inti

| Variabel | Default | Arti | Batas valid |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(wajib)* | Token bot dari @BotFather. Disimpan sebagai `SecretStr`, tidak pernah tercetak di log/dump | - |
| `DOWNLOAD_DIR` | `downloads` | Direktori file sementara + volume download | - |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | Jumlah unduhan aktif serentak (`asyncio.Semaphore`) | `>= 1` |
| `MAX_FILE_SIZE_MB` | `50` | Batas ukuran file; dicek sebelum download (metadata) dan saat upload (fallback document) | `>= 1` |
| `RATE_LIMIT_SECONDS` | `10` | Jeda minimum antar request per chat | `>= 0` |
| `LOG_LEVEL` | `INFO` | Level logging stdlib | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |

### Variabel akses private mode (v2.0, FR-013/FR-014)

| Variabel | Default | Arti | Batas valid |
|---|---|---|---|
| `BOT_MODE` | `public` | `public` = semua user boleh download (seperti MVP v1.0); `private` = hanya user terdaftar yang boleh download & pakai `/setUser` | `public` \| `private` |
| `OWNER_USER_ID` | - | Owner/admin utama; wajib diisi bila `BOT_MODE=private`. Bot fail-closed (semua download ditolak) bila kosong di private mode | integer positip atau kosong |
| `AUTHORIZED_USER_IDS` | - | Seed whitelist tambahan, comma-separated (contoh: `11111111,22222222`); kosong = tidak ada seed | string angka dipisah koma, tanpa spasi |
| `USERS_FILE` | `users.json` | Path file JSON persisten untuk daftar user terdaftar | string, jangan commit ke repo |

Catatan mode: `BOT_MODE=public` (default) = semua user bebas download seperti v1.0;
tiga var whitelist di atas hanya berlaku saat `BOT_MODE=private`. Daftar efektif = union(
`OWNER_USER_ID`, `AUTHORIZED_USER_IDS`, isi `USERS_FILE`). Untuk pemakaian pribadi:
set `BOT_MODE=private` + `OWNER_USER_ID` di `.env`. Cek ID via `/getID`.

### Variabel statistik & notifikasi (v2.2, FR-021)

| Variabel | Default | Arti | Batas valid |
|---|---|---|---|
| `ADMIN_NOTIFY_CHAT_ID` | - | Chat target notifikasi user baru; kosong = fallback `OWNER_USER_ID` | integer positip atau kosong |
| `STATS_FILE` | `stats.json` | File JSON persisten untuk hitungan user unik + counter | string, jangan commit ke repo |

### Variabel antrean (v2.2, FR-022)

| Variabel | Default | Arti | Batas valid |
|---|---|---|---|
| `QUEUE_MAX_SIZE` | `20` | Kapasitas antrean in-process; bila penuh handler menolak cepat `🚦 Server sedang penuh, coba lagi sebentar.` | `>= 1` |
| `MAX_QUEUE_WAIT_SECONDS` | `60` | Batas waktu tunggu job sebelum dibatalkan → `⌛ Permintaanmu kedaluwarsa di antrean. Kirim ulang, ya.` | `>= 1` |

File `USERS_FILE` dan `STATS_FILE` memuat identifier pribadi → sensitif: jangan
di-commit, gunakan `chmod 600`, dan pastikan tercantum di `.dockerignore`.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Isi `TELEGRAM_BOT_TOKEN` di `.env` dengan token dari **@BotFather** (`/newbot`).
Jangan pernah menaruh token asli di file yang bisa di-diff: `.env` sudah ada di
`.gitignore` dan repo ini publik.

Untuk private mode (opsional), tambahkan:

```bash
BOT_MODE=private
OWNER_USER_ID=<your_telegram_id>   # dapatkan via /getID setelah bot berjalan
AUTHORIZED_USER_IDS=               # opsional, kosongkan bila tidak ada
```

## Run

```bash
python -m app.main
```

Bot polling (`getUpdates`), tidak butuh webhook/domain. Log INFO `application
built` lalu `polling started` menandakan boot sukses. Token salah →
`telegram.error.InvalidToken` dan proses exit (rc=1).

## Docker

Build image (basis `python:3.12-slim` + `ffmpeg` + `procps`, user non-root
`appuser` uid 10001, `HEALTHCHECK` `pgrep -f "python -m app.main"` tiap 30s):

```bash
docker build -t reelsdownloader .
```

Jalankan, semua var dari `--env-file`, `DOWNLOAD_DIR` sudah di-set di image ke
`/app/downloads` dan di-mount sebagai volume. Bila `BOT_MODE=private`, arahkan
`USERS_FILE` dan `STATS_FILE` ke volume yang bisa ditulis (mis. `/app/data/`)
karena `/app` di image dimiliki `appuser` uid 10001; contoh:
`USERS_FILE=/app/data/users.json` dengan volume `-v "$PWD/data:/app/data"`.

```bash
docker run --rm --env-file .env -v "$PWD/downloads:/app/downloads" reelsdownloader
```

Var bisa juga lewat `-e` satu per satu:

```bash
docker run -d --name reelsdownloader --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
  -e DOWNLOAD_DIR=/app/downloads \
  -e MAX_CONCURRENT_DOWNLOADS=2 \
  -e MAX_FILE_SIZE_MB=50 \
  -e RATE_LIMIT_SECONDS=10 \
  -e LOG_LEVEL=INFO \
  -e BOT_MODE=public \
  -e OWNER_USER_ID= \
  -e AUTHORIZED_USER_IDS= \
  -e USERS_FILE=users.json \
  -e ADMIN_NOTIFY_CHAT_ID= \
  -e STATS_FILE=stats.json \
  -e QUEUE_MAX_SIZE=20 \
  -e MAX_QUEUE_WAIT_SECONDS=60 \
  -v "$PWD/downloads:/app/downloads" \
  reelsdownloader
```

Catatan operasional:
- Satu container = satu proses (`CMD` exec form, `python -m app.main`), supaya
  `Semaphore` dan rate limiter in-memory valid. Menjalankan banyak replika
  berarti tiap replika punya limit sendiri.
- `.dockerignore` mengecualikan `tests/`, `docs/`, `.env`, `.env.*`, `.venv`,
  `AGENTS.md`, `users.json*`, `stats.json*` dari build context, token tidak
  pernah masuk image.
- Cek health: `docker inspect --format '{{json .State.Health}}' <container>`.
- Log: `docker logs -f <container>`. Hentikan: `docker stop <container>`
  (SIGTERM, tanpa core file).

## Deploy 24/7 di VPS

Docker (rekomendasi, sudah termasuk FFmpeg):

```bash
git clone git@github.com:ndeso17/ReelsDownloader.git && cd ReelsDownloader
docker build -t reelsdownloader .
cp .env.example .env && chmod 600 .env && $EDITOR .env   # isi token
mkdir -p /srv/reelsdownloader/downloads
docker run -d --name reelsdownloader --restart unless-stopped \
  --env-file .env -v /srv/reelsdownloader/downloads:/app/downloads \
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

`--restart unless-stopped` / `Restart=always` menjaga bot hidup; satu URL gagal
tidak menghentikan proses (exception tertangkap per job, NFR Reliability).
Status 24/7 di VPS nyata masih perlu diverifikasi manusia (PRD §8 butir 9
`MANUAL-VERIFY`).

## Test & lint

```bash
ruff check .
ruff format --check .
.venv/bin/python -m pytest -q --tb=short
```

Semua test jalan tanpa akses Instagram/Facebook/TikTok nyata (yt-dlp dan bot di-mock).
`tests/test_wp13.py` otomatis *skip* bila daemon Docker/image tidak ada.

## Ops

### Tuning antrean (FR-022)

| Situasi | Rekomendasi |
|---|---|
| Server sering penuh di jam ramai | Naikkan `QUEUE_MAX_SIZE` (default 20) |
| User komplain request kedaluwarsa | Naikkan `MAX_QUEUE_WAIT_SECONDS` (default 60) |
| RAM terbatas, worker antri lama | Turunkan `MAX_CONCURRENT_DOWNLOADS` (default 2) |
| Ingin tolak lebih agresif | Perkecil `QUEUE_MAX_SIZE`; pastikan >= 1 |

Antrean in-memory: reset saat restart, tidak dibagi antar replika (NFR
Reliability). Rate limiter per-user (FR-011) tetap lapis PERTAMA; antrean =
kontrol beban global lapis kedua.

### Monitoring statistik

Command admin `/stats` menampilkan:
- Total user unik (per `STATS_FILE`, bertahan antar restart)
- Total permintaan diproses (counter sejak restart)
- Total ditolak - rate limit / akses / antrean penuh (counter sejak restart)
- Kedalaman antrean saat ini (`queue.qsize()` / `QUEUE_MAX_SIZE`)

Notifikasi realtime dikirim ke `ADMIN_NOTIFY_CHAT_ID`; kosong = fallback
`OWNER_USER_ID`. Bila keduanya kosong, notifikasi dilewati (log saja).

### Privasi file sensitif

`USERS_FILE` dan `STATS_FILE` memuat identifier Telegram:
- Jangan di-commit ke repo
- Gunakan `chmod 600` pada host
- Pastikan termuat di `.dockerignore`/volume agar tidak masuk image

### Command reference

| Command | Akses | Keterangan |
|---|---|---|
| `/start` | Publik | Welcome message + daftar command singkat |
| `/help` | Publik | Panduan penggunaan bot |
| `/getID` | Publik | Balas user ID numerik pengirim |
| `/menu` | Publik | Tampilkan menu lengkap + status akses |
| `/advance` | Terdaftar (private mode) | Mulai dialog pilih tipe (Video/Audio) + kualitas + resolusi |
| `/cancel` | Terdaftar (private mode) | Batalkan dialog advance aktif |
| `/setUser add/remove/list` | Owner (`OWNER_USER_ID` saja) | Kelola whitelist user (hanya aktif di `BOT_MODE=private`) |
| `/stats` | Owner (`OWNER_USER_ID` saja) | Statistik pemakaian bot |

## Troubleshooting

9 kondisi error FR-009 dan pesan yang dilihat user:

| Kondisi | Pesan bot | Penyebab / langkah |
|---|---|---|
| URL tidak valid | `❌ URL tidak valid` | URL tidak bisa diparse; minta link lengkap `https://...` |
| URL tidak didukung | `❌ URL tidak didukung. Kirim link Instagram/Facebook/TikTok.` | Domain di luar whitelist 10 host (penolakan di jalur validasi membalas `Host tidak didukung: '<host>'`) |
| Video private | `🔒 Video private/terbatas.` | Akun privat / butuh login / age-restricted. Bot **tidak** mengakali login (PRD §6/§9) |
| Video tidak ditemukan | `🔍 Video tidak ditemukan.` | Post dihapus / URL salah / extractor tidak mendukung format itu |
| Download gagal | `⚠️ Gagal mengunduh.` | Jaringan/sumber bermasalah; cek `docker logs` untuk traceback |
| FFmpeg gagal | `⚠️ Gagal memproses video.` | Mapping tersedia untuk `FFmpegFailedError`. Catatan akurat: jalur yt-dlp saat ini memetakan pesan extractor ke private/tidak ditemukan/gagal-unduh, jadi kegagalan merge paling sering muncul sebagai `⚠️ Gagal mengunduh.` - pastikan `ffmpeg` tersedia di host/image |
| File terlalu besar | `📏 File terlalu besar.` | Melebihi `MAX_FILE_SIZE_MB` (default 50). Naikkan nilainya bila perlu |
| Upload Telegram gagal | `⚠️ Gagal mengirim ke Telegram.` | API Telegram menolak (token, jaringan, atau batas ukuran/format Telegram). Detail di log |
| Timeout | `⏱️ Timeout.` | Job melebihi 60 dtk (`DOWNLOAD_TIMEOUT_SECONDS`) atau socket/http 30 dtk |

Pesan tambahan di luar 9 kondisi FR-009 (kontrol alur):

| Kondisi | Pesan bot | Sumber |
|---|---|---|
| Rate limit | `Terlalu sering; coba lagi dalam N.N detik` | FR-011 - dikirim langsung dari handler (`str(exc)`), tanpa emoji |
| Queue penuh | `🚦 Server sedang penuh, coba lagi sebentar.` | FR-022 - antrean mencapai `QUEUE_MAX_SIZE`; naikkan `QUEUE_MAX_SIZE` atau kurangi beban |
| Job kedaluwarsa | `⌛ Permintaanmu kedaluwarsa di antrean. Kirim ulang, ya.` | FR-022 - job menunggu > `MAX_QUEUE_WAIT_SECONDS`; kemungkinan antrean sangat padat |
| Dialog kedaluwarsa | `⌛ Sesi pilihan berakhir. Kirim link lagi (dengan /advance bila mau mode advance).` | FR-019 - TTL 120 detik dialog advance terlampaui |

Masalah umum lain:

- **Bot tidak merespons sama sekali** → token salah (`InvalidToken` di log),
  bot di-block, atau polling belum hidup (`polling started` tidak muncul).
- **`ValidationError` saat boot** → nama var di luar 14 var PRD §5, salah satu
  nilai literal (`LOG_LEVEL`, `BOT_MODE`), atau batas numeric (`MAX_CONCURRENT_DOWNLOADS`,
  `MAX_FILE_SIZE_MB`, `QUEUE_MAX_SIZE`, `MAX_QUEUE_WAIT_SECONDS`) < 1.
- **`File hasil download tidak ditemukan` / merge error di Docker** → FFmpeg
  tidak ada atau volume `/app/downloads` tidak bisa ditulis (`appuser` uid 10001).
- **Download tampak mengantri lama** → semua slot `MAX_CONCURRENT_DOWNLOADS`
  terpakai; naikkan hanya bila RAM/CPU VPS cukup.
- **Instagram/Facebook/TikTok berhenti mendukung** → biasanya perubahan platform
  di sisi extractor `yt-dlp`; `pip install -U yt-dlp` lalu rebuild image.
- **`/setUser` tidak aktif di public mode** → ini normal. Ubah
  `BOT_MODE=private` di `.env` dan restart bot bila ingin mengunci akses.
- **Notifikasi user baru tidak sampai** → cek `ADMIN_NOTIFY_CHAT_ID` dan
  `OWNER_USER_ID`; bila kosong keduanya notifikasi dilewati (hanya di-log).
- **Dialog advance tidak bisa dilanjutkan setelah restart** → state `DialogState`
  bersifat in-memory; restart = reset. Kirim `/advance` ulang.

## Batasan

Sesuai PRD §6 (Not Included) bukan bug, memang di luar MVP:

- Tanpa database, tanpa akun user permanen, tanpa riwayat download persisten, tanpa
  quota/statistik untuk user umum (statistik hanya admin, PRD §7), tanpa admin dashboard, tanpa pembayaran.
- Tanpa Redis dan tanpa worker terpisah (ARSITEKTUR.md menggambarkan itu untuk
  V2 lanjut, bukan target V2.2 ini).
- Tanpa autentikasi Instagram/Facebook/TikTok dan tanpa scraping akun privat.
- Kualitas video/audio bisa dipilih lewat `/advance` (FR-015..FR-018), tetapi
  tanpa progres persen dan tanpa thumbnail kustom.
- Domain didukung terbatas pada 10 host whitelist (`instagram.com`,
  `www.instagram.com`, `facebook.com`, `www.facebook.com`, `m.facebook.com`,
  `fb.watch`, `tiktok.com`, `www.tiktok.com`, `vm.tiktok.com`,
  `vt.tiktok.com`); dukungan aktual bergantung pada kemampuan extractor
  `yt-dlp` dan perubahan platform (PRD §2, §9).
- Limit concurrency/rate bersifat in-memory: reset saat restart dan tidak
  dibagi antar replika.
- Antrean (FR-022) in-memory: reset saat restart, tidak dibagi antar replika;
  job yang menunggu terlalu lama akan kedaluwarsa.
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
