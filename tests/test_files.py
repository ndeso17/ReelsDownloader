"""Test utilitas file WP-07 (FR-008, NFR Security).

Assert T-073 ditulis VERBATIM dari teks PLAN.md — jangan "dibetulkan" kalau gagal:
kalau assert ini merah, yang salah implementasinya, bukan testnya (AGENTS.md §3.2
"hapus/sunting test agar hijau" = dilarang).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.files import clean_dir, sanitize_filename, sanitize_metadata

# 8 blacklisted chars: / : \ * ? " < > | (T-072 dan T-073 menyebut set yang sama).
DANGEROUS = '/:*?\\"><>|'


def test_sanitize_filename_t073_verbatim() -> None:
    # T-073: assert eksplisit dari PLAN.md, karakter-per-karakter.
    assert sanitize_filename("Video/Title: *invalid*") == "Video_Title_ _invalid_"


@pytest.mark.parametrize("char", list(DANGEROUS))
def test_sanitize_filename_replaces_each_blacklisted_char(char: str) -> None:
    assert sanitize_filename(f"a{char}b") == "a_b"


def test_sanitize_filename_keeps_safe_chars_and_spaces() -> None:
    # Spasi bukan char berbahaya (T-073); huruf/angka/underscore/dash/dot aman.
    assert sanitize_filename("Reel 2026_final-v1.mp4") == "Reel 2026_final-v1.mp4"


def test_sanitize_filename_truncates_to_100_chars() -> None:
    out = sanitize_filename("x" * 250)
    assert len(out) == 100
    assert out == "x" * 100


def test_sanitize_filename_truncation_applied_after_replacement() -> None:
    # Semua char terganti -> hasil tetap terpotong 100.
    assert sanitize_filename("/" * 150) == "_" * 100


def test_sanitize_filename_empty_string() -> None:
    assert sanitize_filename("") == ""


def test_clean_dir_empties_directory(tmp_path: Path) -> None:
    # T-074: dir kosong setelahnya.
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.txt").write_text("b")
    clean_dir(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_clean_dir_empty_dir_is_noop(tmp_path: Path) -> None:
    clean_dir(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_clean_dir_missing_path_does_not_raise(tmp_path: Path) -> None:
    clean_dir(tmp_path / "tidak-ada")


def test_clean_dir_only_targets_directory_itself(tmp_path: Path) -> None:
    other = tmp_path / "lain"
    other.mkdir()
    (other / "keep.txt").write_text("keep")
    target = tmp_path / "target"
    target.mkdir()
    (target / "drop.txt").write_text("drop")
    clean_dir(target)
    assert list(target.iterdir()) == []
    assert (other / "keep.txt").read_text() == "keep"


def test_sanitize_metadata_strips_control_chars_t075() -> None:
    # T-075: control chars hilang.
    assert sanitize_metadata({"title": "Test\x00\x01"}) == {"title": "Test"}


def test_sanitize_metadata_strips_c0_and_del_range() -> None:
    # NUL, BEL (0x07), HT, LF, US (0x1f), DEL (0x7f) semua strip.
    dirty = "a\x00b\x07c\x09d\x0ae\x1fb\x7fz"
    assert sanitize_metadata({"caption": dirty})["caption"] == "abcdebz"


def test_sanitize_metadata_truncates_each_field_to_100_chars() -> None:
    out = sanitize_metadata({"title": "t" * 300, "uploader": "u" * 300})
    assert out["title"] == "t" * 100
    assert out["uploader"] == "u" * 100


def test_sanitize_metadata_keeps_non_string_values() -> None:
    meta = {"duration": 42.5, "width": 1080, "live": False, "view_count": None}
    assert sanitize_metadata(meta) == meta


def test_sanitize_metadata_returns_new_dict_empty_input() -> None:
    assert sanitize_metadata({}) == {}
