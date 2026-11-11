"""Konversi pilihan advance -> opts yt-dlp (FR-017, FR-018, SC 16, WP-19).

Satu rumah untuk semua pemetaan pilihan-dialog; downloader hanya memanggil
fungsi di sini (dipisah agar bisa di-mock terpisah, PLAN T-193). FFmpeg
DIEKSTRAK lewat postprocessor yt-dlp - tidak ada subprocess manual (AGENTS
§2: "FFmpeg dipanggil yt-dlp"). Tidak ada I/O sama sekali di modul ini.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "AUDIO_CAPTION",
    "SELECTION_QUALITIES",
    "SELECTION_BITRATES",
    "Selection",
    "audio_opts",
    "quality_note",
    "resolve_selection",
    "video_format",
]

#: Nilai `kualitas`/`bitrate` yang sah di `Selection` (pintu validasi
#: kedua setelah `parse_callback`; state dirakit kode, bukan user).
SELECTION_QUALITIES = ("best", "1080", "720", "480", "360")
SELECTION_BITRATES = ("320", "192", "128")

#: FR-018: caption audio `🎵 {title}` (dipakai uploader WP-19).
AUDIO_CAPTION = "🎵 {title}"


@dataclass(frozen=True)
class Selection:
    """Pilihan final user: mode + kualitas video / bitrate audio (≥1 diisi)."""

    mode: str  # "video" | "audio"
    quality: str | None = None  # SELECTION_QUALITIES
    bitrate: str | None = None  # SELECTION_BITRATES

    def validate(self) -> Selection:
        if self.mode not in ("video", "audio"):
            raise ValueError(f"Selection.mode tidak sah: {self.mode!r}")
        if self.mode == "video":
            if self.quality not in SELECTION_QUALITIES:
                raise ValueError(f"Selection.quality tidak sah: {self.quality!r}")
        elif self.bitrate not in SELECTION_BITRATES:
            raise ValueError(f"Selection.bitrate tidak sah: {self.bitrate!r}")
        return self


def video_format(quality: str | None) -> str:
    """`-fmt` yt-dlp per pilihan (tabel FR-017, PRD.md:506-514).

    `best`/None => format default v1.0 (`bestvideo+bestaudio/best`) -
    SC 16: jalur default identik.
    """
    if quality in (None, "best"):
        return "bestvideo+bestaudio/best"
    if quality in SELECTION_QUALITIES:
        return f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
    raise ValueError(f"video_format: kualitas tidak dikenal: {quality!r}")


def audio_opts(bitrate: str) -> dict:
    """Opts tambahan untuk audio-only: format audio + postprocessor mp3.

    FR-017: "yt-dlp format audio terbaik + FFmpeg postprocessor
    `FFmpegExtractAudio` ke `mp3` dengan bitrate terpilih."
    """
    if bitrate not in SELECTION_BITRATES:
        raise ValueError(f"audio_opts: bitrate tidak dikenal: {bitrate!r}")
    return {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }
        ],
    }


def quality_note(quality_diminta: str | None, actual_height: int | None) -> str | None:
    """Catatan caption saat hasil ≠ permintaan (FR-017, PRD.md:516).

    None bila terpenuhi / mode best / tinggi hasil tidak diketahui; selain
    itu `"(720p→480p)"` persis gaya contoh PRD.
    """
    if quality_diminta in (None, "best") or actual_height is None:
        return None
    target = int(quality_diminta)
    actual = int(actual_height)
    if actual >= target:
        return None
    # FR-017: kualitas diminta TIDAK tersedia di sumber (yt-dlp memilih
    # tertinggi yang <= pilihan) -> beri tahu `(720p→480p)` di caption.
    return f"({quality_diminta}p→{actual}p)"


def resolve_selection(dialog_state) -> Selection | None:
    """`ChatDialog` (step `quality`, pilihan final) -> `Selection` | None.

    None = jalur default (perilaku identik v1.0, SC 16): dipanggil saat state
    kosong/tidak final. Menerima objek apa pun ber-atribut `tipe`/`kualitas`
    (duck typing, mudah di-mock di test).
    """
    tipe = getattr(dialog_state, "tipe", None)
    kualitas = getattr(dialog_state, "kualitas", None)
    if tipe == "video" and kualitas is not None:
        return Selection(mode="video", quality=kualitas).validate()
    if tipe == "audio" and kualitas is not None:
        return Selection(mode="audio", bitrate=kualitas).validate()
    return None
