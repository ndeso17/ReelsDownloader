"""State dialog mode advance per chat (FR-015..FR-019, WP-19).

Struktur entri mengikuti FR-019 PERSIS: `{url, step, tipe, kualitas}`
(PRD.md:538) - BUKAN file/DB (PRD §6: state in-memory). Kunci = `chat_id`
(mitigasi risiko PLAN: bocor state bila salah pakai `user_id`).

Urutan langkah sesuai PRD (link-first, keputusan manusia 2026-09-14 - lihat
FINDINGS [RESOLVED] WP-19): `link` (mode aktif, bot minta link) -> `type`
(keyboard Video/Audio muncul SETELAH URL valid) -> `quality` (keyboard
kualitas/bitrate). Satu sesi dialog = satu link (FR-016).

TTL 120 dtk (FR-019) diukur lewat `time.monotonic()` dengan `time_source`
yang bisa di-inject - pola `UserRateLimiter` (test deterministik, freezegun
dilarang). Semua teks user-facing di modul ini persis PRD §3; baris sumber
dikutip per konstanta. Tidak ada I/O jaringan di modul ini.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

__all__ = [
    "ANSWER_STALE",
    "AUDIO_BITRATES",
    "CANCEL_MENU",
    "DIALOG_TTL_SECONDS",
    "MODE_OFF_TEXT",
    "MODE_TEXT",
    "MSG_EXPIRED",
    "PROMPT_QUALITY",
    "PROMPT_TYPE",
    "STEP_LINK",
    "STEP_QUALITY",
    "STEP_TYPE",
    "VIDEO_QUALITIES",
    "ChatDialog",
    "DialogState",
    "choice_keyboard",
    "parse_callback",
]

#: FR-019: "TTL dialog **120 detik**".
DIALOG_TTL_SECONDS = 120

#: Nama langkah state (FR-015 -> FR-016 -> FR-017 -> proses).
STEP_LINK = "link"
STEP_TYPE = "type"
STEP_QUALITY = "quality"

#: PRD.md:63 - balasan `/advance` (TANPA keyboard; keyboard baru muncul
#: setelah URL valid, FR-015:473).
MODE_TEXT = "⚙️ Mode Advance aktif. Kirim link-nya."
#: FR-015: "`/advance` kedua (toggle off)" - teks non-PRD, dipilih Executor.
MODE_OFF_TEXT = "⚙️ Mode advance dimatikan."
#: PRD.md:488 - prompt Dialog 1 (FR-016).
PROMPT_TYPE = "Mau diambil yang mana?"
#: PRD.md:71 - prompt Dialog 2 (FR-017), sama untuk cabang video dan audio.
PROMPT_QUALITY = "Pilih kualitas:"
#: PRD.md:542 - pesan kedaluwarsa (FR-019).
MSG_EXPIRED = "⌛ Sesi pilihan berakhir. Kirim link lagi (dengan /advance bila mau mode advance)."
#: PRD.md:546 - jawaban untuk callback sesi mati (FR-019), dipakai sebagai toast.
ANSWER_STALE = "Sesi sudah berakhir"
#: Balasan `/cancel` dan tombol "✖️ Batalkan" (FR-019: hapus state; teks
#: menu non-PRD, dipilih Executor - memuat /getID /menu /start).
CANCEL_MENU = (
    "❌ Dialog dibatalkan.\n"
    "Menu:\n"
    "/getID - lihat Telegram ID kamu\n"
    "/menu - daftar command + status akses\n"
    "/start - selamat datang + panduan"
)

#: Nilai sah callback kualitas video (FR-017: Best/1080p/720p/480p/360p).
VIDEO_QUALITIES = ("best", "1080", "720", "480", "360")
#: Nilai sah callback bitrate audio (FR-017 cabang audio: 320/192/128 kbps).
AUDIO_BITRATES = ("320", "192", "128")

_VIDEO_BUTTONS = (
    ("Best", "best"),
    ("1080p", "1080"),
    ("720p", "720"),
    ("480p", "480"),
    ("360p", "360"),
)
_AUDIO_BUTTONS = (("320 kbps", "320"), ("192 kbps", "192"), ("128 kbps", "128"))

_CALLBACK_PREFIX = "ad:"
_CANCEL_DATA = f"{_CALLBACK_PREFIX}cancel"


@dataclass(frozen=True)
class ChatDialog:
    """Satu sesi dialog; field persis FR-019 (PRD.md:538) + jam TTL."""

    url: str | None = None
    step: str = STEP_LINK
    tipe: str | None = None
    kualitas: str | None = None
    updated_at: float = 0.0


class DialogState:
    """Peta `chat_id -> ChatDialog` in-memory dengan TTL; tanpa lock.

    Aman tanpa lock: seluruh akses terjadi di satu event loop (worker Telegram
    dan callback berjalan di loop yang sama; tidak ada thread pool di sini).
    """

    def __init__(self, time_source: Callable[[], float] = time.monotonic) -> None:
        self.time_source: Callable[[], float] = time_source
        self._entries: dict[int, ChatDialog] = {}

    def _is_stale(self, entry: ChatDialog, now: float) -> bool:
        return (now - entry.updated_at) > DIALOG_TTL_SECONDS

    def get(self, chat_id: int) -> ChatDialog | None:
        """Entri hidup, atau None (kedaluwarsa dibuang diam-diam saat disentuh)."""
        entry = self._entries.get(chat_id)
        if entry is None:
            return None
        if self._is_stale(entry, float(self.time_source())):
            self._entries.pop(chat_id, None)
            return None
        return entry

    def is_expired(self, chat_id: int) -> bool:
        """True bila entri ADA tapi lewat TTL (sebelum `get()` membersihkannya).

        Dipakai handler untuk membedakan "tidak pernah ada sesi" (jawab toast
        saja) vs "kedaluwarsa" (toast + `MSG_EXPIRED`, FR-019).
        """
        entry = self._entries.get(chat_id)
        return entry is not None and self._is_stale(entry, float(self.time_source()))

    def set(self, chat_id: int, **fields) -> ChatDialog:
        """Merge `fields` ke entri (baru bila belum ada); refresh jam TTL."""
        current = self._entries.get(chat_id) or ChatDialog()
        merged = replace(current, **fields, updated_at=float(self.time_source()))
        self._entries[chat_id] = merged
        return merged

    def clear(self, chat_id: int) -> bool:
        """Hapus sesi; True bila ada yang dihapus (`/cancel` idempoten)."""
        return self._entries.pop(chat_id, None) is not None

    def active(self, chat_id: int) -> bool:
        """True bila sesi hidup (kedaluwarsa dihitung mati)."""
        return self.get(chat_id) is not None


def choice_keyboard(step: str, tipe: str | None = None) -> InlineKeyboardMarkup:
    """Keyboard inline per langkah (FR-016/FR-017) + baris "✖️ Batalkan".

    `callback_data` compact (≤64 byte): `ad:mode:*`, `ad:q:*`, `ad:a:*`,
    `ad:cancel`. `step == "quality"` butuh `tipe` untuk memilih cabang.
    """
    if step == STEP_TYPE:
        rows = [
            [
                InlineKeyboardButton("🎬 Video", callback_data=f"{_CALLBACK_PREFIX}mode:video"),
                InlineKeyboardButton("🎵 Audio", callback_data=f"{_CALLBACK_PREFIX}mode:audio"),
            ]
        ]
    elif step == STEP_QUALITY and tipe == "audio":
        rows = [
            [
                InlineKeyboardButton(label, callback_data=f"{_CALLBACK_PREFIX}a:{value}")
                for label, value in _AUDIO_BUTTONS
            ]
        ]
    elif step == STEP_QUALITY:
        rows = [
            [
                InlineKeyboardButton(label, callback_data=f"{_CALLBACK_PREFIX}q:{value}")
                for label, value in _VIDEO_BUTTONS
            ]
        ]
    else:
        raise ValueError(f"choice_keyboard: step/tipe tidak dikenal: {step!r}/{tipe!r}")
    rows.append([InlineKeyboardButton("✖️ Batalkan", callback_data=_CANCEL_DATA)])
    return InlineKeyboardMarkup(rows)


def parse_callback(data: str) -> tuple[str, str | None] | None:
    """`ad:...` -> (`kind`, `value`); None bila format/nilai tak dikenal.

    kind: "mode"|"q"|"a"|"cancel". Validasi nilai against whitelist FR-017
    DI SINI (single source): tombol asing hasil rekayasa user tidak pernah
    menyentuh state.
    """
    parts = (data or "").split(":")
    if parts[:2] == ["ad", "cancel"] and len(parts) == 2:
        return ("cancel", None)
    if len(parts) != 3 or parts[0] != "ad":
        return None
    allowed = {"mode": ("video", "audio"), "q": VIDEO_QUALITIES, "a": AUDIO_BITRATES}
    group, value = parts[1], parts[2]
    if group in allowed and value in allowed[group]:
        return (group, value)
    return None
