"""WP-12 gerbang keamanan statis (T-121, T-122, T-123; NFR Security; AGENTS.md §5).

Scan hanya teks sumber via `pathlib` + `re` + `ast` — tanpa subprocess, tanpa
network (AGENTS.md §4.6). Pola ditulis agar tidak match pada file test ini
sendiri: scan bahaya dibatasi ke `app/`, dan regex dibangun dari fragmen.

Risiko PLAN WP-12: false-positive pada docstring/komentar (mis.
`app/services/downloader.py` menulis "bukan subprocess") → baris non-kode
(docstring + komentar) dikecualikan dari scan `app/`.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"

#: Bahaya nyata = di jalur kode (bukan docstring/komentar). AGENTS.md §5.
DANGEROUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("shell=True", re.compile(r"\bshell\s*=\s*True\b")),
    ("os.system(", re.compile(r"\bos\.system\s*\(")),
    ("subprocess", re.compile(r"\bsub" + r"process\b")),
    ("eval(", re.compile(r"\beval\s*\(")),
    ("exec(", re.compile(r"\bexec\s*\(")),
    ("f-string yt-dlp", re.compile(r"""f["']yt-dlp""")),
]

#: Jalur request tidak boleh memblokir event loop (T-123, NFR Performance).
#: Scan TEKS penuh di handlers/ + services/ — docstring pun dilarang menyebut
#: modul sinkron ini (AGR: semua I/O = `async def` / `asyncio.to_thread`).
BLOCKING_IO_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("time.sleep(", re.compile(r"\btime\.sleep\s*\(")),
    ("requests.", re.compile(r"\brequests" + r"\.")),
    ("httpx.Client(", re.compile(r"\bhttpx\.Client\s*\(")),
]

#: `TELEGRAM_BOT_TOKEN=<literal panjang>` adalah indikasi token nyata di kode.
_LONG_ASSIGN_RE = re.compile(r"TELEGRAM_BOT_TOKEN\W{0,3}[=:]\W?[\"']([^\"']{21,})[\"']")

#: Bentuk token Telegram asli: `<digits>:<30+ karakter base64url>` (AGENTS.md §5).
_REAL_TOKEN_SHAPE_RE = re.compile(r"\b\d{8,15}:[A-Za-z0-9_-]{30,}")


def _python_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in str(p))


def _non_code_lines(text: str) -> set[int]:
    """Nomor baris docstring dan komentar — bukan kode yang tereksekusi."""
    excluded: set[int] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return excluded
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            excluded.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                excluded.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError):
        pass
    return excluded


# ---------------- T-121: tidak ada panggilan berbahaya di app/ ----------------


@pytest.mark.parametrize(("label", "pattern"), DANGEROUS_PATTERNS)
def test_app_free_of_dangerous_exec_apis(label: str, pattern: re.Pattern[str]) -> None:
    """T-121 (NFR Security, AGENTS.md §5).

    Larangan: shell=True, os.system, subprocess, eval/exec, f-string yt-dlp.
    """
    offenders: list[str] = []
    for path in _python_files(APP_DIR):
        text = path.read_text(encoding="utf-8")
        non_code = _non_code_lines(text)
        for m in pattern.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            if line_no in non_code:
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not offenders, f"{label} ditemukan di jalur kode app/: {offenders}"


# ---------------- T-122: hygiene token ----------------


@pytest.mark.parametrize("dir_name", ["app", "tests"])
def test_no_long_bot_token_literal(dir_name: str) -> None:
    """T-122 (SC §8 butir 8): literal `TELEGRAM_BOT_TOKEN=*** > 20 char
    dilarang di `app/` maupun `tests/`."""
    offenders: list[str] = []
    for path in _python_files(ROOT / dir_name):
        text = path.read_text(encoding="utf-8")
        for m in _LONG_ASSIGN_RE.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line_no} (len={len(m.group(1))})")
    assert not offenders, f"Literal token panjang di {dir_name}/: {offenders}"


@pytest.mark.parametrize("dir_name", ["app", "tests"])
def test_no_real_token_shape_anywhere(dir_name: str) -> None:
    """Bentuk token Telegram asli (`\\d+:...{30,}`) dilarang di sumber.

    Termasuk di docstring/komentar.
    """
    offenders: list[str] = []
    for path in _python_files(ROOT / dir_name):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if _REAL_TOKEN_SHAPE_RE.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not offenders, f"Pola token nyata di {dir_name}/: {offenders}"


def test_settings_token_is_secretstr_and_never_leaks() -> None:
    """T-122: `Settings.telegram_bot_token` = `SecretStr`.

    `repr`/`model_dump()` tidak membuka nilai. Semua string di bawah dummy —
    bukan kredensial, hanya umpan uji anti-bocor.
    """
    dummy_value = "dum-token-value"  # dipecah: hindari trigger scanner
    settings = Settings(
        telegram_bot_token=SecretStr(dummy_value),  # noqa: S105
        _env_file=None,
    )
    assert isinstance(settings.telegram_bot_token, SecretStr)
    assert dummy_value not in repr(settings)
    assert dummy_value not in str(settings)
    assert dummy_value not in str(settings.model_dump())
    assert dummy_value not in str(settings.model_dump(mode="json"))
    # "**********" = redaksi SecretStr, bukan kredensial.
    assert settings.model_dump(mode="json")["telegram_bot_token"] == "**********"  # noqa: S105


# ---------------- T-123: jalur request tidak memblokir ----------------


@pytest.mark.parametrize(("label", "pattern"), BLOCKING_IO_PATTERNS)
def test_handlers_and_services_are_non_blocking(label: str, pattern: re.Pattern[str]) -> None:
    """T-123 (NFR Performance): `app/handlers/` + `app/services/` bebas I/O sinkron."""
    offenders: list[str] = []
    for sub in ("handlers", "services"):
        for path in _python_files(APP_DIR / sub):
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not offenders, f"{label} ditemukan di jalur request: {offenders}"
