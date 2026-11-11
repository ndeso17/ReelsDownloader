"""Statistik pemakaian bot + notifikasi admin realtime (FR-021, SC 17).

Satu rumah untuk state counter dan pengiriman notifikasi user baru (AGENTS.md §4.2):
handler hanya memanggil, tidak menduplikasi logika atau teks pesan.

Penyimpanan mengadopsi pola `app/services/user_store.py` (WP-15 + REWORK-R1/R2), bukan
menyalin ulang bug-nya: `tempfile.mkstemp` di direktori target (nama tmp UNIK per
penulisan) -> isi -> `flush` -> `os.fsync(fd)` -> `chmod 0600` -> `os.replace` (atomik
di volume yang sama) -> `fsync` direktori parent. Mode 0600 wajib: `stats.json` memuat
identifier pribadi (PRD FR-021 bagian Privasi).

Kontrak kegagalan (PRD FR-021 NFR Reliability): statistik TIDAK boleh mematikan bot.
`load()` file hilang/rusak -> mulai nol + `logger.warning`; `save()` `OSError` ->
`logger.error` + return `False`, tidak pernah raise; `notify_new_user` membungkus
`bot.send_message` dengan `try/except Exception` sehingga `RetryAfter`, `Forbidden`,
atau `NetworkError` hanya menjadi `logger.warning`.

API sync/IO untuk level penyimpanan; pemanggil async membungkus dengan
`asyncio.to_thread` (AGENTS.md §4.4). Tidak ada dependensi baru; stdlib only.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "MSG_NEW_USER_ADMIN",
    "Stats",
    "build_new_user_message",
    "notify_new_user",
]

#: Mode berkas statistik: 0600 (PRD FR-021 Privasi; memuat identifier pribadi).
FILE_MODE = 0o600

#: Pola pesan notifikasi admin (PRD FR-021; teks persis PLAN T-162). `total` sudah
#: termasuk user yang baru tercatat, jadi `/start` pertama memberi `Total user: 1`.
MSG_NEW_USER_ADMIN = (
    "🆕 User baru memakai bot\n"
    "ID: {user_id}\n"
    "Nama: {first_name}\n"
    "Username: @{username}\n"
    "Total user: {total}"
)


def _now_iso() -> str:
    """Waktu UTC sekarang sebagai ISO-8601 (kolom `first_seen`)."""
    return datetime.now(UTC).isoformat()


def _text_of(value: Any) -> str:
    """Nilai Telegram (bisa `None`) -> string bersih tanpa `None` literal."""
    if value is None:
        return ""
    return str(value).strip()


def build_new_user_message(user: Any, total: int) -> str:
    """Susun teks notifikasi admin untuk satu user baru.

    `user` = objek `update.effective_user` (butuh atribut `id`, `first_name`,
    `username`). Nama/username kosong atau `None` tampil sebagai `-` (persis pola
    PLAN T-162: `{first_name or '-'}` / `@{username or '-'}`).
    """
    first_name = _text_of(getattr(user, "first_name", "")) or "-"
    username = _text_of(getattr(user, "username", "")).removeprefix("@") or "-"
    return MSG_NEW_USER_ADMIN.format(
        user_id=getattr(user, "id", user),
        first_name=first_name,
        username=username,
        total=int(total),
    )


async def notify_new_user(bot: Any, settings: Any, text: str) -> None:
    """Kirim notifikasi user baru ke chat admin (fire-and-forget dari `/start`).

    Target = `settings.admin_chat_id` (`ADMIN_NOTIFY_CHAT_ID`, fallback
    `OWNER_USER_ID`, sudah dijamin property `config.Settings`). Keduanya kosong ->
    hanya `logger.info`, bukan error, tidak ada pengiriman. Kegagalan kirim apa pun
    (termasuk `RetryAfter`, `Forbidden`, `NetworkError`) -> `logger.warning` dan
    TIDAK pernah propagate: balasan `/start` dan counter user tidak boleh terganggu.
    """
    chat_id = getattr(settings, "admin_chat_id", None)
    if chat_id is None:
        logger.info("admin chat tidak diset, tanpa notifikasi")
        return
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:  # kontrak FR-021: statistik/notifikasi tak pernah crash bot
        logger.warning("notifikasi admin gagal (chat %s): %s", chat_id, exc)


class Stats:
    """State in-memory statistik pemakaian + persistensi atomik ke `stats.json`.

    Skema snapshot (PLAN T-161): `{total_users, processed, rejected,
    rejected_reasons: {reason: int}, first_seen: {str(user_id): iso_ts}}`.

    `first_seen` adalah penjaga anti-spam: `record_user` hanya `True` sekali per ID
    seumur hidup, sehingga satu user menghasilkan tepat satu notifikasi (SC 17).
    """

    def __init__(self) -> None:
        self.processed: int = 0
        self.rejected: int = 0
        self.rejected_reasons: dict[str, int] = {}
        self.first_seen: dict[str, str] = {}

    # ------------------------------------------------------------------ helpers

    @property
    def total_users(self) -> int:
        """Jumlah user unik yang pernah tercatat (BUKAN jumlah pesan)."""
        return len(self.first_seen)

    @staticmethod
    def _key(user_id: Any) -> str:
        """Kunci `first_seen`: ID numerik sebagai string desimal (aman > 2^53)."""
        return str(int(user_id))

    # ------------------------------------------------------------------ mutators

    def record_user(
        self,
        user_id: Any,
        first_name: str = "",
        username: str = "",
    ) -> bool:
        """Catat user; `True` bila ini kemunculan PERTAMA, `False` bila sudah ada.

        `first_name`/`username` diterima untuk kompatibilitas panggilan handler dan
        sengaja TIDAK disimpan: identitas itu milik `users.json` (WP-15), sedangkan
        `stats.json` hanya menyimpan ID + waktu kemunculan pertama (minimasi PII).
        """
        try:
            key = self._key(user_id)
        except (TypeError, ValueError):
            logger.warning("record_user dengan user_id non-numerik diabaikan: %r", user_id)
            return False
        if key in self.first_seen:
            return False
        self.first_seen[key] = _now_iso()
        return True

    def inc_processed(self) -> None:
        """Satu permintaan selesai diproses (job tuntas tanpa exception)."""
        self.processed += 1

    def inc_rejected(self, reason: str) -> None:
        """Satu permintaan ditolak/gagal, dihitung per alasan (`reason` string tetap)."""
        self.rejected += 1
        key = str(reason)
        self.rejected_reasons[key] = self.rejected_reasons.get(key, 0) + 1

    # ------------------------------------------------------------------ serialisasi

    def snapshot(self) -> dict[str, Any]:
        """Salinan snapshot siap-JSON (tidak ada referensi mutable yang bocor)."""
        return {
            "total_users": self.total_users,
            "processed": self.processed,
            "rejected": self.rejected,
            "rejected_reasons": dict(self.rejected_reasons),
            "first_seen": dict(self.first_seen),
        }

    def _adopt(self, data: dict[str, Any]) -> None:
        """Pasang kolom yang persist ke state; sisanya sengaja dimulai dari nol.

        Keputusan Executor (dicatat di Log WP-16, dijamin konsisten oleh `/stats`):

        * PERSIST antar restart: `first_seen` (himpunan ID unik) sehingga
          `total_users` dan anti-spam notifikasi (SC 17) bertahan hidup restart,
          sesuai PRD FR-021 "himpunan ID unik + counter, tetap ada setelah restart".
        * SEJAK RESTART (direset saat `load`, TIDAK dipulihkan dari berkas):
          `processed`, `rejected`, `rejected_reasons`. Berkas tetap MENYIMPAN
          nilainya sebagai jejak audit run terakhir, tetapi angka hidup bot selalu
          dimulai dari nol agar label `/stats` ("sejak restart") tidak menyesatkan.
          `rejected_reasons` ikut direset supaya rinciannya selalu cocok dengan
          total `rejected` yang ditampilkan.
        """
        self.processed = 0
        self.rejected = 0
        self.rejected_reasons = {}
        raw_first = data.get("first_seen")
        if isinstance(raw_first, dict):
            self.first_seen = {str(key): str(value) for key, value in raw_first.items()}
        else:
            logger.warning("stats file tidak punya `first_seen` object, user unik nol")

    def load(self, path: str | os.PathLike[str]) -> None:
        """Muat snapshot dari `path` ke instance ini (in-place, tanpa raise).

        Berkas hilang / rusak / JSON bukan object -> state tetap nol +
        `logger.warning`: bot wajib tetap hidup (PRD FR-021 NFR Reliability).
        """
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            logger.warning("stats file %s tidak ada, mulai dengan angka nol", path)
            return
        except (OSError, ValueError) as exc:
            logger.warning("stats file %s tidak terbaca (%s), mulai dengan angka nol", path, exc)
            return
        if not isinstance(data, dict):
            logger.warning("stats file %s bukan JSON object, mulai dengan angka nol", path)
            return
        self._adopt(data)

    @classmethod
    def load_or_new(cls, path: str | os.PathLike[str]) -> Stats:
        """`Stats()` lalu `load(path)`; selalu mengembalikan objek berguna (T-166)."""
        stats = cls()
        stats.load(path)
        return stats

    # ------------------------------------------------- persistensi (pola WP-15)

    @staticmethod
    def _fsync_dir(directory: str) -> None:
        """`fsync` direktori parent agar entri hasil `os.replace` ikut awet.

        Best effort: sebagian platform menolak `fsync` pada handle direktori; kasus
        itu tidak boleh menggagalkan penyimpanan.
        """
        try:
            dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            logger.debug("fsync direktori %s ditolak platform", directory)
        finally:
            os.close(dir_fd)

    @staticmethod
    def _unlink_quietly(path: str) -> None:
        """Hapus tmp sisa kegagalan; abaikan bila sudah hilang."""
        try:
            os.unlink(path)
        except OSError:
            pass

    def save(self, path: str | os.PathLike[str]) -> bool:
        """Tulis atomik dan durable: tmp unik -> flush+fsync -> chmod 0600 -> replace.

        Meniru `user_store.save_users` (WP-15 + REWORK-R1/R2): `mkstemp` di direktori
        target memberi nama tmp UNIK per penulisan (dua penulis tidak berbagi tmp),
        `chmod 0600` sebelum `os.replace` menutup jendela mode 0644, `fsync` isi
        sebelum rename, lalu `fsync` direktori.

        `OSError` -> `logger.error` + return `False`, TIDAK pernah raise: state
        in-memory tetap benar dan bot harus terus melayani (FR-021). tmp sisa
        kegagalan dibersihkan, jadi tidak pernah ada `stats.json*.tmp` yatim.
        """
        target = os.fspath(path)
        parent = os.path.dirname(os.path.abspath(target))
        payload = self.snapshot()

        fd, tmp = -1, None
        try:
            fd, tmp = tempfile.mkstemp(
                prefix=f"{os.path.basename(target)}.", suffix=".tmp", dir=parent
            )
            os.close(fd)
            fd = -1
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.flush()
                os.chmod(tmp, FILE_MODE)
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except OSError as exc:
            logger.error("gagal menyimpan stats file %s: %s", target, exc)
            if fd != -1:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp is not None:
                self._unlink_quietly(tmp)
            return False

        self._fsync_dir(parent)
        return True
