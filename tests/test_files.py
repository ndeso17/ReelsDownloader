"""Test utilitas file WP-07 (FR-008, NFR Security).

Assert T-073 ditulis VERBATIM dari teks PLAN.md — jangan "dibetulkan" kalau gagal:
kalau assert ini merah, yang salah implementasinya, bukan testnya (AGENTS.md §3.2
"hapus/sunting test agar hijau" = dilarang).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.utils.files import (
    clean_dir,
    ensure_clean_dir,
    safe_remove,
    sanitize_filename,
    sanitize_metadata,
)

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


# ===== T-091: safe_remove (FR-008, WP-09) =====


def test_safe_remove_removes_existing_file(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x")
    safe_remove(f)
    assert not f.exists()


def test_safe_remove_silent_on_missing_file(tmp_path: Path) -> None:
    f = tmp_path / "missing.txt"
    # FileNotFoundError seharusnya ditelan tanpa raise.
    safe_remove(f)
    assert not f.exists()


def test_safe_remove_raises_on_permission_error(tmp_path: Path) -> None:

    f = tmp_path / "locked.txt"
    f.write_text("data")
    # Parent directory read-only so unlink can't update directory entry.
    orig = tmp_path.stat().st_mode
    tmp_path.chmod(0o555)
    try:
        with pytest.raises(OSError):
            safe_remove(f)
    finally:
        tmp_path.chmod(orig)


# ===== T-092: ensure_clean_dir (FR-008, WP-09) =====


def test_ensure_clean_dir_removes_old_files_keeps_new(tmp_path: Path) -> None:
    old = tmp_path / "old.mp4"
    old.write_bytes(b"x")
    # Backdate mtime 2 hari lalu.
    old_ts = time.time() - 172800
    os.utime(str(old), (old_ts, old_ts))

    new = tmp_path / "new.mp4"
    new.write_bytes(b"y")

    ensure_clean_dir(tmp_path, max_age_seconds=86400)

    assert not old.exists()
    assert new.exists()


def test_ensure_clean_dir_keeps_fresh_files_within_threshold(tmp_path: Path) -> None:
    f = tmp_path / "fresh.mp4"
    f.write_bytes(b"data")
    ensure_clean_dir(tmp_path, max_age_seconds=86400)
    assert f.exists()


def test_ensure_clean_dir_ignores_subdirectories(tmp_path: Path) -> None:
    subdir = tmp_path / "sub"
    subdir.mkdir()
    ensure_clean_dir(tmp_path, max_age_seconds=86400)
    assert subdir.exists()


def test_ensure_clean_dir_empty_dir_no_error(tmp_path: Path) -> None:
    ensure_clean_dir(tmp_path, max_age_seconds=86400)
