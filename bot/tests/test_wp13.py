"""WP-13, Docker image contract tests (T-131..T-136).

Bukti terotomasi untuk Dockerfile: base `python:3.12-slim`, ffmpeg via apt (bukan pip),
urutan layer cache, non-root `USER appuser` + `DOWNLOAD_DIR`, `CMD` exec form,
HEALTHCHECK probe tanpa network ke Telegram, dan `.dockerignore` (WP-02) aktif
sehingga tests/docs/.env tidak ikut dibaked ke image.

Prasyarat: daemon Docker + image sudah di-build (`docker build -t reelsdownloader:wp13 .`).
Tanpa keduanya test di-SKIP (bukan gagal): AGENTS §4.6 melarang test yang butuh layanan
eksternal untuk bisa lulus, jadi gerbang mutu §6 tetap hijau di mesin tanpa Docker.

Token: hanya string dummy pendek `***`, BUKAN format token nyata
`\\d+:[A-Za-z0-9_-]{35}` (AGENTS §5a). Tidak ada kredensial asli di file ini.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

IMAGE = "reelsdownloader:wp13"
# String dummy pendek, BUKAN format token nyata (AGENTS §5a).
DUMMY_BOT_SECRET = "***"  # noqa: S105 - nilai dummy, bukan kredensial
ROOT = Path(__file__).resolve().parents[1]


def _docker(*args: str, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    argv = ["docker", *args]  # noqa: S607 - binary dari PATH, argv statis (bukan input user)
    return subprocess.run(  # noqa: S603 - daftar argv, tanpa shell=True
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _require_docker_image() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed")
    probe = _docker("image", "inspect", IMAGE, "--format", "{{.Id}}", timeout=30)
    if probe.returncode != 0:
        pytest.skip(f"image {IMAGE} not built (run: docker build -t {IMAGE} .)")


@pytest.fixture(name="require_image", autouse=False)
def fixture_require_image() -> None:
    _require_docker_image()


def _inspect(label: str) -> str:
    r = _docker("image", "inspect", IMAGE, "--format", label, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ---------------------------------------------------------------- T-131


def test_t131_base_is_python_312_slim(require_image: None) -> None:
    """Base = python:3.12-slim: PYTHON_VERSION 3.12.x + varian slim (tanpa compiler)."""
    envs = json.loads(_inspect("{{json .Config.Env}}"))
    pyver = next((e.split("=", 1)[1] for e in envs if e.startswith("PYTHON_VERSION=")), "")
    assert pyver.startswith("3.12."), f"PYTHON_VERSION={pyver!r}, expected 3.12.x"
    r = _docker(
        "run",
        "--rm",
        "--entrypoint",
        "sh",
        IMAGE,
        "-c",
        "grep VERSION_CODENAME /etc/os-release; command -v gcc || echo NO_GCC",
    )
    assert "trixie" in r.stdout, r.stdout + r.stderr
    assert "NO_GCC" in r.stdout, "image membawa compiler -> bukan varian slim"


def test_t131_runtime_env_flags(require_image: None) -> None:
    envs = json.loads(_inspect("{{json .Config.Env}}"))
    assert "PYTHONUNBUFFERED=1" in envs
    assert "PIP_NO_CACHE_DIR=1" in envs


# ---------------------------------------------------------------- T-132


def test_t132_ffmpeg_binary_works(require_image: None) -> None:
    """ffmpeg harus benar-benar jalan di image (dipakai yt-dlp untuk merge, NFR Reliability)."""
    r = _docker("run", "--rm", "--entrypoint", "ffmpeg", IMAGE, "-version", timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("ffmpeg version"), r.stdout[:200]


def test_t132_ffmpeg_comes_from_apt_not_pip(require_image: None) -> None:
    layers = _docker("history", "--no-trunc", "--format", "{{.CreatedBy}}", IMAGE).stdout
    apt_lines = [ln for ln in layers.splitlines() if "apt-get install" in ln]
    assert any("ffmpeg" in ln for ln in apt_lines), "ffmpeg tidak di-install via apt-get"
    assert not any("pip install" in ln and "ffmpeg" in ln for ln in layers.splitlines()), (
        "ffmpeg dilarang dipasang via pip"
    )


# ---------------------------------------------------------------- T-133


def test_t133_requirements_installed_before_app_copy(require_image: None) -> None:
    """Layer requirements.txt+pip lebih tua dari COPY app/ -> cache valid saat kode berubah.

    `docker history` mencetak layer terbaru lebih dulu, jadi index kecil = layer baru.
    """
    layers = _docker(
        "history", "--no-trunc", "--format", "{{.CreatedBy}}", IMAGE
    ).stdout.splitlines()
    order = {
        "app": next(i for i, ln in enumerate(layers) if ln.startswith("COPY app/")),
        "pip": next(i for i, ln in enumerate(layers) if "pip install" in ln),
        "req": next(i for i, ln in enumerate(layers) if ln.startswith("COPY requirements.txt")),
    }
    assert order["app"] < order["pip"] < order["req"], f"urutan layer salah: {order}"


def test_t133_dev_artifacts_not_baked(require_image: None) -> None:
    """.dockerignore aktif: tests/, docs/, AGENTS.md, .env, .venv TIDAK ada di image."""
    r = _docker(
        "run",
        "--rm",
        "--entrypoint",
        "sh",
        IMAGE,
        "-c",
        "for p in tests docs AGENTS.md .env .venv scripts; do "
        "[ -e /app/$p ] && echo BAKED:$p; done; "
        "ls /app; echo SCAN_DONE",
    )
    assert "SCAN_DONE" in r.stdout, r.stderr
    assert "BAKED:" not in r.stdout, f"artefak dev masuk image:\n{r.stdout}"
    for expected in ("app", "downloads", "pyproject.toml", "requirements.txt"):
        assert expected in r.stdout, f"{expected} hilang dari /app"


# ---------------------------------------------------------------- T-134


def test_t134_download_dir_env_and_volume(require_image: None) -> None:
    envs = json.loads(_inspect("{{json .Config.Env}}"))
    assert "DOWNLOAD_DIR=/app/downloads" in envs
    volumes = json.loads(_inspect("{{json .Config.Volumes}}"))
    assert "/app/downloads" in volumes


def test_t134_runs_as_non_root_with_writable_downloads(require_image: None) -> None:
    assert _inspect("{{.Config.User}}") == "appuser"
    r = _docker(
        "run",
        "--rm",
        "--entrypoint",
        "sh",
        IMAGE,
        "-c",
        "id -u; touch /app/downloads/wp13-probe && rm /app/downloads/wp13-probe && echo WRITABLE",
    )
    out = r.stdout + r.stderr
    assert out.splitlines()[0].strip() == "10001", f"expected uid 10001, got: {out!r}"
    assert "WRITABLE" in out, f"/app/downloads tidak bisa ditulis appuser: {out}"


# ---------------------------------------------------------------- T-135 + HEALTHCHECK


def test_t135_cmd_is_exec_form_single_process(require_image: None) -> None:
    cmd = json.loads(_inspect("{{json .Config.Cmd}}"))
    assert cmd == ["python", "-m", "app.main"], f"CMD salah: {cmd}"


def test_healthcheck_probe_defined_without_network(require_image: None) -> None:
    hc = json.loads(_inspect("{{json .Config.Healthcheck}}"))
    assert hc.get("Test"), "HEALTHCHECK tidak ada"
    probe = " ".join(hc["Test"])
    assert "pgrep" in probe, f"probe harus cek proses, bukan: {probe}"
    for forbidden in ("curl", "wget", "python -c", "telegram", "http"):
        assert forbidden not in probe.lower(), f"HEALTHCHECK mengandung network call {forbidden!r}"


def test_healthcheck_probe_negative_control(require_image: None) -> None:
    """Probe harus GAGAL saat proses target tidak hidup (bukan trivially true).

    Exec-form `pgrep` langsung: tidak ada shell pembungkus yang cmdline-nya bisa self-match.
    """
    r = _docker("run", "--rm", "--entrypoint", "pgrep", IMAGE, "-f", "python -m app.main")
    assert r.returncode == 1, f"probe harus rc=1 tanpa proses target, dapat rc={r.returncode}"


def test_healthcheck_reaches_healthy_without_restart_loop(require_image: None) -> None:
    """Bukti SC §8 butir 9: proses hidup -> status `healthy`, `RestartCount=0` (no crash-loop).

    Proses pengganti (`sleep` dengan argv[0] di-alias) dipakai supaya test tidak butuh
    jaringan Telegram; probe hanya melihat nama proses di /proc.
    """
    name = "wp13-hc-contract"
    _docker("rm", "-f", name)
    try:
        started = _docker(
            "run",
            "-d",
            "--name",
            name,
            "--entrypoint",
            "bash",
            IMAGE,
            "-c",
            'exec -a "python -m app.main" sleep 300',
        )
        assert started.returncode == 0, started.stderr
        deadline = time.monotonic() + 120
        status = ""
        while time.monotonic() < deadline:
            time.sleep(5)
            status = _docker("inspect", name, "--format", "{{.State.Health.Status}}").stdout.strip()
            if status == "healthy":
                break
        assert status == "healthy", f"health tidak mencapai 'healthy' (terakhir: {status!r})"
        assert _docker("inspect", name, "--format", "{{.RestartCount}}").stdout.strip() == "0"
    finally:
        _docker("rm", "-f", name)


# ---------------------------------------------------------------- T-136


def test_t136_dummy_token_boots_then_exits_nonzero(require_image: None) -> None:
    """Kriteria terima WP-13: `timeout 20 python -m app.main` dengan token dummy ->
    log `application built` muncul, TANPA ImportError/ValidationError (dependensi image
    lengkap), lalu exit non-zero karena `InvalidToken` (expected, token dummy ditolak
    api.telegram.org)."""
    r = _docker(
        "run",
        "--rm",
        "-e",
        f"TELEGRAM_BOT_TOKEN={DUMMY_BOT_SECRET}",
        "--entrypoint",
        "timeout",
        IMAGE,
        "20",
        "python",
        "-m",
        "app.main",
        timeout=150,
    )
    out = r.stdout + r.stderr
    assert "application built" in out, f"log startup hilang:\n{out[:800]}"
    assert "ImportError" not in out, out[:800]
    assert "ValidationError" not in out, out[:800]
    assert r.returncode != 0, "exit seharusnya non-zero (token dummy ditolak)"
    assert "InvalidToken" in out, f"expected InvalidToken, rc={r.returncode}:\n{out[:800]}"


def test_t136_manual_verify_recipe_documented_in_dockerfile() -> None:
    """T-136: komentar MANUAL-VERIFY (resep untuk manusia, SC §8 butir 9) ada di Dockerfile.

    Tidak butuh Docker -> selalu jalan, termasuk di mesin tanpa daemon.
    """
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "MANUAL-VERIFY" in text
    for step in ("docker build", "timeout 60", "docker stop", "TELEGRAM_BOT_TOKEN"):
        assert step in text, f"langkah MANUAL-VERIFY {step!r} tidak terdokumentasi"
    # Token dummy saja: tidak boleh ada pola token nyata.
    assert not re.search(r"\d{8,}:[A-Za-z0-9_-]{30,}", text), "Dockerfile memuat token nyata"
