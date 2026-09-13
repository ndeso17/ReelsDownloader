# Dockerfile: ReelsDownloader MVP (WP-13)
#
# Kontrak: AGENTS.md §2 (Python 3.11+, FFmpeg dipakai yt-dlp, config dari env),
# PRD §4/§5 (6 env var), §7 NFR Reliability + Security, Struktur.md.
#
# MANUAL-VERIFY (Docker): SC PRD §8 butir 9 ("jalan 24/7 di VPS") TIDAK bisa
# diotomasi, jadi dijalankan manusia dengan resep ini lalu dicatat di
# docs/agents/PLAN.md (bagian Log WP-13):
#   1. docker build -t reelsdownloader:wp13 .                      -> exit 0
#   2. docker run --rm -e TELEGRAM_BOT_TOKEN '<token dummy>' \
#        -v "$PWD/downloads:/app/downloads" reelsdownloader:wp13 \
#        timeout 60 python -m app.main
#      -> log INFO "application built" muncul, tidak ada ImportError/
#         ValidationError/traceback kode aplikasi.
#   3. docker stop <id> -> container berhenti bersih, tanpa file core.
#   4. docker inspect --format '{{json .Config.Healthcheck}}' -> probe ada.
#   Nilai token dummy diisi dari shell saat run, TIDAK ditulis di file ini.

FROM python:3.12-slim

# T-131: log langsung flush ke docker logs, tanpa cache pip (NFR Reliability).
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# T-132: FFmpeg untuk merge yt-dlp (bukan pip install manual). procps = pgrep
# untuk HEALTHCHECK di bawah. no-install-recommends + hapus lists = image kecil.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        procps \
    && rm -rf /var/lib/apt/lists/*

# T-133: requirements lebih dulu supaya layer dependency kena cache saat app/ berubah.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy hanya yang dibutuhkan runtime: app/, pyproject.toml (konvensi ruff/pytest),
# downloads/.gitkeep. tests/, docs/, scripts/, AGENTS.md, .env dikecualikan
# .dockerignore (WP-02) supaya token/ artefak dev tidak pernah masuk image.
COPY app/ ./app/
COPY pyproject.toml ./
COPY downloads/.gitkeep ./downloads/

# T-134: user non-root supaya proses bot tidak bisa membaca kredensial proses lain.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/downloads \
    && chown -R appuser:appuser /app

USER appuser

# T-134: satu-satunya var yang di-set = DOWNLOAD_DIR (salah satu 6 var PRD §5).
# 5 var lain, termasuk token, wajib dari `docker run -e`: tidak di-bake.
ENV DOWNLOAD_DIR=/app/downloads

# AGENTS §2.7: folder hasil download sebagai volume agar artefak tidak hilang di layer.
VOLUME ["/app/downloads"]

# HEALTHCHECK tanpa network call ke Telegram: probe hanya menguji proses
# `python -m app.main` masih hidup (exec form -> tidak ada shell pembungkus yang
# bikin pgrep mencocok dirinya sendiri). start-period menahan false-positive saat boot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["pgrep", "-f", "python -m app.main"]

# T-135: exec form + single process -> asyncio.Semaphore in-memory valid (FR-010).
CMD ["python", "-m", "app.main"]
