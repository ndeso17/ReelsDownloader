# ReelsDownloader — Telegram Reels Downloader (Instagram / Facebook)

Bot Telegram MVP: kirim URL video **publik** Instagram atau Facebook, bot
memvalidasi domain, mengunduh dengan `yt-dlp` (FFmpeg merge lewat yt-dlp),
mengirim video balik dengan caption, lalu menghapus file sementara.

Tanpa database, tanpa Redis, tanpa worker, tanpa login Instagram/Facebook —
itu scope V2 (PRD §6/§7). Koncurrency di-handle `asyncio.Semaphore` in-process.

Stack: Python 3.11+ (dev/image: 3.12), `python-telegram-bot` 22.8,
`yt-dlp` 2026.8.19, `pydantic-settings` 2.15.0.

## Fitur

| FR | Perilaku user (persis seperti diimplementasi) |
|---|---|
| FR-001 | `/start` → "👋 Instagram/Facebook Downloader" + instruksi + contoh URL |
| FR-002 | `/help` → daftar perintah dan contoh URL |
| FR-003 | URL di tengah teks biasa diambil otomatis (regex `https?://\S+`), tanpa command khusus. Teks tanpa URL → bot membalas panduan `/start` |
| FR-004 | Hanya 6 host: `instagram.com`, `www.instagram.com`, `facebook.com`, `www.facebook.com`, `m.facebook.com`, `fb.watch`. Host lain → balasan `Host tidak didukung: '<host>'`; scheme bukan http/https → `Scheme tidak didukung: '<scheme>'` |
| FR-005 | yt-dlp via Python API, format `bestvideo+bestaudio/best`, merge output `mp4`, `noplaylist`, timeout socket/http 30 dtk, hard-cap job 60 dtk |
| FR-006 | Metadata dibaca: `title`, `duration`, `uploader`, `webpage_url`, `ext`, `filesize` |
| FR-007 | Caption `🎬 {title}` baris kosong `Source: Instagram`/`Source: Facebook`. Kirim via `send_video`; bila ukuran > `MAX_FILE_SIZE_MB` → fallback `send_document` |
| FR-008 | `downloads/` dibersihkan di blok `finally` — sukses maupun gagal |
| FR-009 | 9 kondisi error dipetakan ke pesan ramah (lihat Troubleshooting); traceback lengkap hanya ke log |
| FR-010 | Maks `MAX_CONCURRENT_DOWNLOADS` job (download+upload+cleanup) serentak; sisanya mengantri |
| FR-011 | Per chat: request kedua dalam `RATE_LIMIT_SECONDS` ditolak dengan `Terlalu sering; coba lagi dalam N.N detik` |

Ack `⏳ Sedang memproses...` terkirim **sebelum** semaphore diambil, jadi
response awal tetap cepat (< 2 dtk, NFR Performance) walau semua slot busy.

## Environment variables

Persis 6 var PRD §5 — tidak ada var lain yang dibaca (`extra="forbid"`).
Nilai di luar rentang sah → `ValidationError` saat boot.

| Variabel | Default | Arti | Batas valid |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(wajib)* | Token bot dari @BotFather. Disimpan sebagai `SecretStr`, tidak pernah tercetak di log/dump | — |
| `DOWNLOAD_DIR` | `downloads` | Direktori file sementara + volume download | — |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | Jumlah unduhan aktif serentak (`asyncio.Semaphore`) | `>= 1` |
| `MAX_FILE_SIZE_MB` | `50` | Batas ukuran file; dicek sebelum download (metadata) dan saat upload (fallback document) | `>= 1` |
| `RATE_LIMIT_SECONDS` | `10` | Jeda minimum antar request per chat | `>= 0` |
| `LOG_LEVEL` | `INFO` | Level logging stdlib | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |

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

## Run

```bash
python -m app.main
```

Bot polling (`getUpdates`) — tidak butuh webhook/domain. Log INFO `application
built` lalu `polling started` menandakan boot sukses. Token salah →
`telegram.error.InvalidToken` dan proses exit (rc=1).

## Docker

Build image (basis `python:3.12-slim` + `ffmpeg` + `procps`, user non-root
`appuser` uid 10001, `HEALTHCHECK` `pgrep -f "python -m app.main"` tiap 30s):

```bash
docker build -t reelsdownloader .
```

Jalankan — 5 var dari `--env-file`, `DOWNLOAD_DIR` sudah di-set di image ke
`/app/downloads` dan di-mount sebagai volume:

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
  -v "$PWD/downloads:/app/downloads" \
  reelsdownloader
```

Catatan operasional:
- Satu container = satu proses (`CMD` exec form, `python -m app.main`), supaya
  `Semaphore` dan rate limiter in-memory valid. Menjalankan banyak replika
  berarti tiap replika punya limit sendiri.
- `.dockerignore` mengecualikan `tests/`, `docs/`, `.env`, `.venv`, `AGENTS.md`
  dari build context — token tidak pernah masuk image.
- Cek health: `docker inspect --format '{{json .State.Health}}' <container>`.
- Log: `docker logs -f <container>`. Hentikan: `docker stop <container>`
  (SIGTERM, tanpa core file).

## Deploy 24/7 di VPS

Docker (rekomendasi — sudah termasuk FFmpeg):

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
Status 24/7 di VPS nyata masih perlu diverifikasi manusia (PRD §8 butir 9 —
`MANUAL-VERIFY`).

## Test & lint

```bash
ruff check .
ruff format --check .
.venv/bin/python -m pytest -q --tb=short
```

Semua test jalan tanpa akses Instagram/Facebook nyata (yt-dlp dan bot di-mock).
`tests/test_wp13.py` otomatis *skip* bila daemon Docker/image tidak ada.

## Troubleshooting

9 kondisi error FR-009 dan pesan yang dilihat user:

| Kondisi | Pesan bot | Penyebab / langkah |
|---|---|---|
| URL tidak valid | `❌ URL tidak valid` | URL tidak bisa diparse; minta link lengkap `https://...` |
| URL tidak didukung | `❌ URL tidak didukung. Kirim link Instagram/Facebook.` | Domain di luar 6 host whitelist (penolakan di jalur validasi membalas `Host tidak didukung: '<host>'`) |
| Video private | `🔒 Video private/terbatas.` | Akun privat / butuh login / age-restricted. Bot **tidak** mengakali login (PRD §9) |
| Video tidak ditemukan | `🔍 Video tidak ditemukan.` | Post dihapus / URL salah / extractor tidak mendukung format itu |
| Download gagal | `⚠️ Gagal mengunduh.` | Jaringan/sumber bermasalah; cek `docker logs` untuk traceback |
| FFmpeg gagal | `⚠️ Gagal memproses video.` | Mapping tersedia untuk `FFmpegFailedError`. Catatan akurat: jalur yt-dlp saat ini memetakan pesan extractor ke private/tidak ditemukan/gagal-unduh, jadi kegagalan merge paling sering muncul sebagai `⚠️ Gagal mengunduh.` — pastikan `ffmpeg` tersedia di host/image |
| File terlalu besar | `📏 File terlalu besar.` | Melebihi `MAX_FILE_SIZE_MB` (default 50). Naikkan nilainya bila perlu |
| Upload Telegram gagal | `⚠️ Gagal mengirim ke Telegram.` | API Telegram menolak (token, jaringan, atau batas ukuran/format Telegram). Detail di log |
| Timeout | `⏱️ Timeout.` | Job melebihi 60 dtk (`DOWNLOAD_TIMEOUT_SECONDS`) atau socket/http 30 dtk |
| Rate limit | `Terlalu sering; coba lagi dalam N.N detik` | FR-011 — request kedua dalam jendela `RATE_LIMIT_SECONDS`; pesan dikirim langsung dari handler (`str(exc)`), tanpa emoji |
| Lainnya | `⚠️ Terjadi kesalahan. Coba lagi sebentar lagi.` | Exception tak terklasifikasi; traceback di log |

Masalah umum lain:

- **Bot tidak merespons sama sekali** → token salah (`InvalidToken` di log),
  bot di-block, atau polling belum hidup (`polling started` tidak muncul).
- **`ValidationError` saat boot** → nama var di luar 6 var PRD §5, `LOG_LEVEL`
  salah satu dari 4 nilai, atau `MAX_CONCURRENT_DOWNLOADS`/`MAX_FILE_SIZE_MB` < 1.
- **`File hasil download tidak ditemukan` / merge error di Docker** → FFmpeg
  tidak ada atau volume `/app/downloads` tidak bisa ditulis (`appuser` uid 10001).
- **Download tampak mengantri lama** → semua slot `MAX_CONCURRENT_DOWNLOADS`
  terpakai; naikkan hanya bila RAM/CPU VPS cukup.
- **Instagram/FB berhenti mendukung** → biasanya perubahan platform di sisi
  extractor `yt-dlp`; `pip install -U yt-dlp` lalu rebuild image.

## Batasan

Sesuai PRD §6 (Not Included) — bukan bug, memang di luar MVP:

- Tanpa database, tanpa akun user, tanpa riwayat download persisten, tanpa
  quota/statistik, tanpa admin dashboard, tanpa pembayaran.
- Tanpa Redis dan tanpa worker terpisah (ARSITEKTUR.md menggambarkan itu untuk
  V2, bukan target MVP).
- Tanpa autentikasi Instagram/Facebook dan tanpa scraping akun privat.
- Kualitas video tidak bisa dipilih, tanpa progres persen, tanpa thumbnail.
- Domain didukung terbatas pada 6 host whitelist; dukungan aktual bergantung
  pada kemampuan extractor `yt-dlp` dan perubahan platform (PRD §2, §9).
- Limit concurrency/rate bersifat in-memory: reset saat restart dan tidak
  dibagi antar replika.
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
