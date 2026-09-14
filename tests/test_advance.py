"""Test mode advance WP-19 (FR-015..FR-019, SC 16), tanpa network (AGENTS.md §4.6).

Handler selalu `await` (asyncio_mode=auto). Update/bot MagicMock; keyboard
InlineKeyboardMarkup asli; jam dialog via `time_source` injeksi (pola
`UserRateLimiter`; freezegun dilarang). Job hasil admit dibaca langsung dari
`bot_data["queue"]` (workers diblokir sentinel, tidak ada eksekusi nyata).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import InlineKeyboardMarkup

from app.config import Settings
from app.handlers.account import advance_callback, advance_command, cancel_command
from app.handlers.download import ACK_TEXT, download_handler
from app.services.access import MSG_ACCESS_DENIED
from app.services.advance import (
    Selection,
    audio_opts,
    quality_note,
    resolve_selection,
    video_format,
)
from app.services.dialog import (
    ANSWER_STALE,
    CANCEL_MENU,
    DIALOG_TTL_SECONDS,
    MODE_OFF_TEXT,
    MODE_TEXT,
    MSG_EXPIRED,
    PROMPT_QUALITY,
    PROMPT_TYPE,
    STEP_LINK,
    STEP_QUALITY,
    STEP_TYPE,
    DialogState,
    choice_keyboard,
    parse_callback,
)
from app.services.downloader import build_ydl_opts
from app.services.uploader import build_caption
from tests.queue_support import JobCollector

VALID_URL = "https://www.instagram.com/reel/ABC123/"
CHAT = 123456


def _make_update(text: str, chat_id: int = CHAT, user_id: int = 999):
    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    return update


def _make_callback(data: str, chat_id: int = CHAT, user_id: int = 999):
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    update.effective_message = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    return update


def _make_context(settings, *, dialog=None):
    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    ctx = MagicMock()
    ctx.bot_data = {
        "settings": settings,
        "rate_limiter": limiter,
        "users": {},
        "dialog": dialog,
        "workers": ["test-owned-no-spawn"],
    }
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def _settings(tmp_path, *, bot_mode="public", owner_user_id=None):
    dl = tmp_path / "dl"
    dl.mkdir()
    return Settings.model_construct(
        telegram_bot_token=" ".join(["dummy", "token"]),
        log_level="INFO",
        download_dir=str(dl),
        max_file_size_mb=50,
        max_concurrent_downloads=2,
        rate_limit_seconds=10,
        bot_mode=bot_mode,
        owner_user_id=owner_user_id,
        queue_max_size=20,
        max_queue_wait_seconds=60,
    )


def _advance_state(dlg, chat_id=CHAT, **fields):
    dlg.set(chat_id, **{"step": STEP_TYPE, "url": VALID_URL, **fields})
    return dlg


# ================= dialog state (T-191) =================


class TestDialogState:
    def test_set_get_active(self):
        clock = [0.0]
        d = DialogState(time_source=lambda: clock[0])
        d.set(1, url="u", step=STEP_TYPE)
        assert d.active(1) is True
        assert d.get(1).url == "u"

    def test_ttl_expires_after_120(self):
        clock = [0.0]
        d = DialogState(time_source=lambda: clock[0])
        d.set(1, step=STEP_LINK)
        assert d.active(1) is True
        clock[0] = DIALOG_TTL_SECONDS + 1.0
        assert d.is_expired(1) is True
        assert d.get(1) is None
        assert d.active(1) is False

    def test_refresh_on_set(self):
        clock = [0.0]
        d = DialogState(time_source=lambda: clock[0])
        d.set(1, step=STEP_LINK)
        clock[0] = 100.0
        d.set(1, step=STEP_TYPE)
        clock[0] = 150.0  # 50dtk sejak refresh terakhir: masih hidup
        assert d.active(1) is True
        clock[0] = 221.0
        assert d.active(1) is False

    def test_clear_returns_whether_existed(self):
        d = DialogState()
        assert d.clear(99) is False
        d.set(99, step=STEP_LINK)
        assert d.clear(99) is True
        assert d.get(99) is None

    def test_chat_isolation(self):
        d = DialogState()
        d.set(1, url="urlA", step=STEP_TYPE)
        d.set(2, url="urlB", step=STEP_QUALITY)
        assert d.get(1).url == "urlA" and d.get(1).step == STEP_TYPE
        assert d.get(2).url == "urlB" and d.get(2).step == STEP_QUALITY


# ================= keyboard + callback parser (T-191) =================


class TestChoiceKeyboard:
    def test_type_keyboard_has_video_audio_cancel(self):
        kb = choice_keyboard(STEP_TYPE)
        flat = [b.text for row in kb.inline_keyboard for b in row]
        assert "🎬 Video" in flat and "🎵 Audio" in flat and "✖️ Batalkan" in flat

    def test_quality_keyboard_video_labels(self):
        kb = choice_keyboard(STEP_QUALITY, tipe="video")
        flat = [b.text for row in kb.inline_keyboard for b in row]
        assert {"Best", "1080p", "720p", "480p", "360p"} <= set(flat)

    def test_quality_keyboard_audio_labels(self):
        kb = choice_keyboard(STEP_QUALITY, tipe="audio")
        flat = [b.text for row in kb.inline_keyboard for b in row]
        assert {"320 kbps", "192 kbps", "128 kbps"} <= set(flat)

    def test_callback_data_compact_under_64_bytes(self):
        for step, tipe in ((STEP_TYPE, None), (STEP_QUALITY, "video"), (STEP_QUALITY, "audio")):
            kb = choice_keyboard(step, tipe)
            for row in kb.inline_keyboard:
                for button in row:
                    assert len(button.callback_data.encode("utf-8")) <= 64

    def test_unknown_step_raises(self):
        with pytest.raises(ValueError):
            choice_keyboard("nope")


class TestParseCallback:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            ("ad:mode:video", ("mode", "video")),
            ("ad:mode:audio", ("mode", "audio")),
            ("ad:q:best", ("q", "best")),
            ("ad:q:1080", ("q", "1080")),
            ("ad:q:720", ("q", "720")),
            ("ad:a:320", ("a", "320")),
            ("ad:a:192", ("a", "192")),
            ("ad:a:128", ("a", "128")),
            ("ad:cancel", ("cancel", None)),
        ],
    )
    def test_valid(self, data, expected):
        assert parse_callback(data) == expected

    @pytest.mark.parametrize(
        "data",
        ["ad:mode:hack", "ad:q:999", "ad:a:64", "ad:x:1", "cancel", "bad:mode:video", ""],
    )
    def test_invalid_returns_none(self, data):
        assert parse_callback(data) is None


# ================= advance.py murni (T-193) =================


class TestAdvanceConversion:
    def test_video_format_table_fr017(self):
        assert video_format("best") == "bestvideo+bestaudio/best"
        assert video_format(None) == "bestvideo+bestaudio/best"
        assert video_format("1080") == "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        assert video_format("720") == "bestvideo[height<=720]+bestaudio/best[height<=720]"

    def test_video_format_rejects_unknown(self):
        with pytest.raises(ValueError):
            video_format("144")

    def test_audio_opts_fr017_audio_branch(self):
        opts = audio_opts("192")
        assert opts["format"] == "bestaudio/best"
        pp = opts["postprocessors"][0]
        assert pp["key"] == "FFmpegExtractAudio"
        assert pp["preferredcodec"] == "mp3"
        assert pp["preferredquality"] == "192"

    def test_quality_note_only_on_fallback(self):
        assert quality_note("720", 480) == "(720p→480p)"
        assert quality_note("720", 720) is None
        assert quality_note("720", 1080) is None
        assert quality_note("best", 480) is None
        assert quality_note("720", None) is None

    def test_resolve_selection(self):
        state_v = type("S", (), {"tipe": "video", "kualitas": "720"})()
        assert resolve_selection(state_v) == Selection(mode="video", quality="720")
        state_a = type("S", (), {"tipe": "audio", "kualitas": "192"})()
        assert resolve_selection(state_a) == Selection(mode="audio", bitrate="192")
        assert resolve_selection(None) is None
        assert resolve_selection(type("S", (), {"tipe": None, "kualitas": None})()) is None

    def test_build_caption_variants(self):
        assert build_caption("t", VALID_URL) == "🎬 t\n\nSource: Instagram"
        assert build_caption("t", VALID_URL, audio=True) == "🎵 t\n\nSource: Instagram"
        cap = build_caption("t", VALID_URL, note="(720p→480p)")
        assert cap == "🎬 t\n\nSource: Instagram (720p→480p)"


# ================= /advance command (T-192, FR-015) =================


class TestAdvanceCommand:
    async def test_public_replies_mode_text_no_keyboard(self, tmp_path):
        ctx = _make_context(_settings(tmp_path), dialog=DialogState())
        update = _make_update("/advance")
        await advance_command(update, ctx)
        call = update.message.reply_text.call_args
        assert call.args == (MODE_TEXT,)
        assert "reply_markup" not in call.kwargs
        state = ctx.bot_data["dialog"].get(CHAT)
        assert state is not None and state.step == STEP_LINK

    async def test_private_non_whitelist_denied_no_state(self, tmp_path):
        settings = _settings(tmp_path, bot_mode="private", owner_user_id=1)
        dlg = DialogState()
        ctx = _make_context(settings, dialog=dlg)
        update = _make_update("/advance", user_id=999)
        await advance_command(update, ctx)
        assert update.message.reply_text.call_args.args == (MSG_ACCESS_DENIED,)
        assert dlg.get(CHAT) is None

    async def test_second_advance_toggles_off(self, tmp_path):
        dlg = DialogState()
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        await advance_command(_make_update("/advance"), ctx)
        assert dlg.active(CHAT) is True
        second = _make_update("/advance")
        await advance_command(second, ctx)
        assert dlg.active(CHAT) is False
        assert second.message.reply_text.call_args.args == (MODE_OFF_TEXT,)


class TestCancelCommand:
    async def test_slash_cancel_clears_state_and_replies_menu(self, tmp_path):
        dlg = _advance_state(DialogState())
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        update = _make_update("/cancel")
        await cancel_command(update, ctx)
        assert dlg.get(CHAT) is None
        assert update.message.reply_text.call_args.args == (CANCEL_MENU,)


# ================= intake dialog branch (T-195, FR-015/FR-016) =================


class TestDownloadDialogBranch:
    async def test_valid_url_opens_type_dialog_instead_of_queue(self, tmp_path):
        dlg = DialogState()
        dlg.set(CHAT, step=STEP_LINK)
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        update = _make_update(VALID_URL)
        await download_handler(update, ctx)
        state = dlg.get(CHAT)
        assert state.url == VALID_URL and state.step == STEP_TYPE
        call = update.message.reply_text.call_args
        assert call.args == (PROMPT_TYPE,)
        assert isinstance(call.kwargs["reply_markup"], InlineKeyboardMarkup)
        assert ctx.bot_data.get("queue") is None

    async def test_new_url_replaces_live_session(self, tmp_path):
        dlg = _advance_state(DialogState(), tipe="video", kualitas="720")
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        await download_handler(_make_update(VALID_URL), ctx)
        state = dlg.get(CHAT)
        assert state.step == STEP_TYPE and state.tipe is None

    async def test_no_session_enqueues_default_without_selection(self, tmp_path):
        ctx = _make_context(_settings(tmp_path), dialog=DialogState())
        collector = JobCollector()
        with collector.install():
            await download_handler(_make_update(VALID_URL), ctx)
            assert collector.scheduled == 1
            assert collector.jobs[0].selection is None
            assert collector.jobs[0].url == VALID_URL
            collector.close_pending()


# ================= advance_callback chain (T-192, FR-016..FR-019) =================


class TestAdvanceCallback:
    async def test_mode_video_switches_to_video_quality_keyboard(self, tmp_path):
        dlg = _advance_state(DialogState())
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        update = _make_callback("ad:mode:video")
        await advance_callback(update, ctx)
        state = dlg.get(CHAT)
        assert state.tipe == "video" and state.step == STEP_QUALITY
        edit = update.callback_query.edit_message_text.call_args
        assert edit.kwargs["text"] == PROMPT_QUALITY
        labels = [b.text for r in edit.kwargs["reply_markup"].inline_keyboard for b in r]
        assert "720p" in labels and "320 kbps" not in labels

    async def test_mode_audio_switches_to_bitrate_keyboard(self, tmp_path):
        dlg = _advance_state(DialogState())
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        update = _make_callback("ad:mode:audio")
        await advance_callback(update, ctx)
        state = dlg.get(CHAT)
        assert state.tipe == "audio" and state.step == STEP_QUALITY
        labels = [
            b.text
            for r in update.callback_query.edit_message_text.call_args.kwargs[
                "reply_markup"
            ].inline_keyboard
            for b in r
        ]
        assert "192 kbps" in labels and "1080p" not in labels

    async def test_video_final_enqueues_selection_and_acks(self, tmp_path):
        dlg = _advance_state(DialogState(), step=STEP_QUALITY, tipe="video")
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        update = _make_callback("ad:q:720")
        await advance_callback(update, ctx)
        job = ctx.bot_data["queue"].get_nowait()
        assert job.url == VALID_URL
        assert job.selection == Selection(mode="video", quality="720")
        assert job.chat_id == CHAT
        assert dlg.get(CHAT) is None  # sekali-pakai (FR-015:478)
        sent = [c.kwargs["text"] for c in ctx.bot.send_message.call_args_list]
        assert ACK_TEXT in sent
        recap = update.callback_query.edit_message_text.call_args.kwargs["text"]
        assert "Video · 720p" in recap
        assert build_ydl_opts(str(VALID_URL), 10, job.selection)["format"] == (
            "bestvideo[height<=720]+bestaudio/best[height<=720]"
        )

    async def test_audio_final_builds_mp3_opts_via_selection(self, tmp_path):
        dlg = _advance_state(DialogState(), step=STEP_QUALITY, tipe="audio")
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        await advance_callback(_make_callback("ad:a:192"), ctx)
        job = ctx.bot_data["queue"].get_nowait()
        assert job.selection == Selection(mode="audio", bitrate="192")
        opts = build_ydl_opts(str(tmp_path / "dl"), 50 * 1024 * 1024, job.selection)
        assert opts["format"] == "bestaudio/best"
        assert opts["postprocessors"][0]["preferredquality"] == "192"
        assert opts["max_filesize"] is None

    async def test_expired_session_answered_and_notified(self, tmp_path):
        clock = [0.0]
        dlg = DialogState(time_source=lambda: clock[0])
        dlg.set(CHAT, url=VALID_URL, step=STEP_TYPE)
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        clock[0] = DIALOG_TTL_SECONDS + 1.0
        update = _make_callback("ad:mode:video")
        await advance_callback(update, ctx)
        assert update.callback_query.answer.call_args.args == (ANSWER_STALE,)
        sent = [c.kwargs["text"] for c in ctx.bot.send_message.call_args_list]
        assert MSG_EXPIRED in sent
        assert ctx.bot_data.get("queue") is None

    async def test_link_after_expiry_uses_default_path(self, tmp_path):
        clock = [0.0]
        dlg = DialogState(time_source=lambda: clock[0])
        dlg.set(CHAT, step=STEP_LINK)
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        clock[0] = DIALOG_TTL_SECONDS + 1.0
        collector = JobCollector()
        with collector.install():
            await download_handler(_make_update(VALID_URL), ctx)
            assert collector.scheduled == 1
            assert collector.jobs[0].selection is None
            collector.close_pending()

    async def test_cancel_button_clears_and_replies_menu(self, tmp_path):
        dlg = _advance_state(DialogState(), tipe="video")
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        update = _make_callback("ad:cancel")
        await advance_callback(update, ctx)
        assert dlg.get(CHAT) is None
        update.callback_query.edit_message_reply_markup.assert_awaited_once()
        sent = [c.kwargs["text"] for c in ctx.bot.send_message.call_args_list]
        assert CANCEL_MENU in sent
        assert "/getID" in CANCEL_MENU and "/menu" in CANCEL_MENU and "/start" in CANCEL_MENU

    async def test_stale_keyboard_from_previous_step(self, tmp_path):
        dlg = _advance_state(DialogState())  # step=type; tap kualitas = keyboard basi
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        update = _make_callback("ad:q:720")
        await advance_callback(update, ctx)
        assert update.callback_query.answer.call_args.args == (ANSWER_STALE,)
        assert dlg.get(CHAT).step == STEP_TYPE
        assert ctx.bot_data.get("queue") is None

    async def test_two_chats_parallel_no_leak(self, tmp_path):
        dlg = DialogState()
        dlg.set(11, url="https://www.instagram.com/reel/A/", step=STEP_QUALITY, tipe="video")
        dlg.set(22, url="https://www.facebook.com/reel/B/", step=STEP_TYPE)
        ctx = _make_context(_settings(tmp_path), dialog=dlg)
        await advance_callback(_make_callback("ad:q:480", chat_id=11), ctx)
        job = ctx.bot_data["queue"].get_nowait()
        assert job.chat_id == 11
        assert job.selection == Selection(mode="video", quality="480")
        other = dlg.get(22)
        assert other.step == STEP_TYPE and other.tipe is None and other.kualitas is None

    async def test_mode_default_selection_none_opts_identik(self, tmp_path):
        ctx = _make_context(_settings(tmp_path), dialog=DialogState())
        collector = JobCollector()
        with collector.install():
            await download_handler(_make_update(VALID_URL), ctx)
            job = collector.jobs[0]
            collector.close_pending()
        assert job.selection is None
        opts = build_ydl_opts(str(tmp_path / "dl"), 10)
        assert opts["format"] == "bestvideo+bestaudio/best"
        assert opts["merge_output_format"] == "mp4"
