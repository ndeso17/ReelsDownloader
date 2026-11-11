"""Aturan topic forum ShortVideo (FR-023, WP-25).

Bot ini dipakai dua-duanya: DM pribadi (perilaku v2.2 tidak berubah) dan satu
topic forum di grup cloud-drive. Di grup, bot HANYA melayani pesan yang masuk
di topic ShortVideo; pesan di topic lain atau di General diabaikan diam-diam
supaya bot tidak berisik di grup yang sama dengan bot lain.

Semua nilai chat/topic adalah KONSTANTA (bukan env var baru): AGENTS.md §2
mengunci daftar env var di PRD §5, jadi penambahan konfigurasi grup tidak boleh
menambah nama env.

Modul ini murni (tanpa I/O jaringan) supaya mudah diuji; handler hanya memanggil
`is_allowed()`, `send_kwargs()`, `actor_key()`, dan `dialog_key()`.
"""

from __future__ import annotations

from typing import Any

from telegram import Update
from telegram.ext.filters import UpdateFilter

__all__ = [
    "IN_SCOPE",
    "SHORTVIDEO_CHAT_ID",
    "SHORTVIDEO_THREAD_ID",
    "ShortVideoScope",
    "actor_key",
    "dialog_key",
    "is_allowed",
    "is_group",
    "is_shortvideo_topic",
    "send_kwargs",
]

#: ID supergroup cloud-drive (`https://t.me/c/3934750896/...`).
SHORTVIDEO_CHAT_ID = -1003934750896
#: `message_thread_id` topic "ShortVideo" (dibuat 2026, judul awal ReelsDownloader).
SHORTVIDEO_THREAD_ID = 20732

_GROUP_TYPES = ("group", "supergroup")


def _message_of(update: Any) -> Any:
    """Pesan efektif dari `Message` atau `CallbackQuery` (duck typing)."""
    message = getattr(update, "effective_message", None)
    if message is None:
        message = getattr(update, "message", None)
    if message is None:
        query = getattr(update, "callback_query", None)
        message = getattr(query, "message", None) if query is not None else None
    return message


def _chat_of(update: Any) -> Any:
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        message = _message_of(update)
        chat = getattr(message, "chat", None) if message is not None else None
    return chat


def is_group(update: Any) -> bool:
    """True bila update datang dari group/supergroup (bukan DM)."""
    chat = _chat_of(update)
    return getattr(chat, "type", None) in _GROUP_TYPES


def _thread_id(update: Any) -> int | None:
    message = _message_of(update)
    value = getattr(message, "message_thread_id", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def is_shortvideo_topic(update: Any) -> bool:
    """True bila update berasal dari topic ShortVideo di grup cloud-drive."""
    chat = _chat_of(update)
    if getattr(chat, "id", None) != SHORTVIDEO_CHAT_ID:
        return False
    return _thread_id(update) == SHORTVIDEO_THREAD_ID


def is_allowed(update: Any) -> bool:
    """Gerbang lokasi: DM selalu boleh; grup hanya topic ShortVideo."""
    if not is_group(update):
        return True
    return is_shortvideo_topic(update)


class ShortVideoScope(UpdateFilter):
    """Filter PTB: lolos hanya DM atau topic ShortVideo (dipakai di `main.py`).

    Dipasang sebagai `filters=` di setiap CommandHandler/MessageHandler supaya
    command di General/topic lain di grup diabaikan diam-diam, tanpa mengubah
    callback handler yang dibandingkan identitasnya oleh test.
    """

    def __init__(self) -> None:
        super().__init__(name="ShortVideoScope")

    def filter(self, update: Update) -> bool:
        return is_allowed(update)


#: Instance tunggal filter scope (PTB memakai instance, bukan kelas).
IN_SCOPE = ShortVideoScope()


def send_kwargs(update: Any) -> dict[str, int]:
    """Kwarg kirim pesan supaya balasan tetap di topic (kosong untuk DM)."""
    if not is_shortvideo_topic(update):
        return {}
    thread_id = _thread_id(update)
    return {"message_thread_id": thread_id} if thread_id is not None else {}


def _user_id(update: Any) -> int | None:
    user = getattr(update, "effective_user", None)
    if user is None:
        query = getattr(update, "callback_query", None)
        user = getattr(query, "from_user", None) if query is not None else None
    value = getattr(user, "id", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def actor_key(update: Any) -> int:
    """Kunci rate limiter: DM per chat, grup per user (grup = satu chat bersama).

    Tanpa pemisahan ini, satu anggota yang mengirim link akan memicu
    `RateLimitedError` untuk semua anggota lain di topic yang sama.
    """
    chat_id = getattr(_chat_of(update), "id", 0)
    if not is_group(update):
        return int(chat_id)
    user_id = _user_id(update)
    return user_id if user_id is not None else int(chat_id)


def dialog_key(update: Any) -> int:
    """Kunci state dialog: DM per chat, grup per user (satu topic dipakai bersama)."""
    return actor_key(update)
