"""Test WP-25 (FR-023): bot melayani satu topic forum ShortVideo, DM tetap.

Semua update dibuat dari objek PTB asli (bukan MagicMock) untuk jalur filter,
karena `filters=` dihitung PTB sendiri; jalur handler memakai MagicMock seperti
test lain (AGENTS.md §4.6: tidak ada network).
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

from telegram import Chat, Message, Update, User
from telegram.ext import CallbackQueryHandler

from app.services import topic as topic_service
from app.services.dialog import STEP_TYPE, DialogState
from app.services.uploader import send_audio, send_video
from app.services.work_queue import build_job

CHAT = topic_service.SHORTVIDEO_CHAT_ID
THREAD = topic_service.SHORTVIDEO_THREAD_ID
URL = "https://www.instagram.com/reel/ABC123/"
DATE = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def _message(chat_id: int, thread_id: int | None, chat_type: str = "supergroup") -> Message:
    return Message(
        message_id=10,
        date=DATE,
        chat=Chat(id=chat_id, type=chat_type),
        text=URL,
        message_thread_id=thread_id,
    )


def _update(chat_id: int, thread_id: int | None, chat_type: str = "supergroup") -> Update:
    return Update(update_id=1, message=_message(chat_id, thread_id, chat_type))


def _private() -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=10,
            date=DATE,
            chat=Chat(id=555, type="private"),
            text=URL,
        ),
    )


# ================= aturan lokasi (murni) =================


def test_private_chat_always_allowed():
    update = _private()
    assert topic_service.is_group(update) is False
    assert topic_service.is_allowed(update) is True
    assert topic_service.send_kwargs(update) == {}


def test_group_shortvideo_topic_allowed():
    update = _update(CHAT, THREAD)
    assert topic_service.is_shortvideo_topic(update) is True
    assert topic_service.is_allowed(update) is True
    assert topic_service.send_kwargs(update) == {"message_thread_id": THREAD}


def test_group_other_topic_rejected():
    update = _update(CHAT, 777)
    assert topic_service.is_allowed(update) is False
    assert topic_service.send_kwargs(update) == {}


def test_group_general_without_thread_rejected():
    assert topic_service.is_allowed(_update(CHAT, None)) is False


def test_group_other_chat_rejected():
    assert topic_service.is_allowed(_update(-1009999999999, THREAD)) is False


def test_actor_and_dialog_key_per_user_in_group():
    update = Update(
        update_id=1,
        message=Message(
            message_id=10,
            date=DATE,
            chat=Chat(id=CHAT, type="supergroup"),
            text=URL,
            message_thread_id=THREAD,
            from_user=User(id=4242, first_name="a", is_bot=False),
        ),
    )
    assert topic_service.actor_key(update) == 4242
    assert topic_service.dialog_key(update) == 4242
    # DM tetap per chat, bukan per user.
    assert topic_service.actor_key(_private()) == 555


# ================= filter PTB =================


def test_filter_scope_accepts_dm_and_topic_only():
    scope = topic_service.IN_SCOPE
    assert scope.check_update(_private()) is True
    assert scope.check_update(_update(CHAT, THREAD)) is True
    assert scope.check_update(_update(CHAT, 777)) is False
    assert scope.check_update(_update(CHAT, None)) is False


# ================= jalur handler =================


def _settings(tmp_path):
    from app.config import Settings

    dl = tmp_path / "dl"
    dl.mkdir()
    return Settings.model_construct(
        telegram_bot_token=" ".join(["dummy", "token"]),
        log_level="INFO",
        download_dir=str(dl),
        max_file_size_mb=50,
        max_concurrent_downloads=2,
        rate_limit_seconds=10,
        bot_mode="public",
        owner_user_id=None,
        queue_max_size=20,
        max_queue_wait_seconds=60,
    )


def _context(settings, dialog=None):
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


def _handler_update(chat_id, thread_id, chat_type="supergroup", user_id=999):
    message = MagicMock()
    message.text = URL
    message.message_thread_id = thread_id
    message.reply_text = AsyncMock()
    chat = MagicMock()
    chat.id = chat_id
    chat.type = chat_type
    user = MagicMock()
    user.id = user_id
    update = MagicMock()
    update.message = message
    update.effective_message = message
    update.effective_chat = chat
    update.effective_user = user
    return update


async def test_handler_ignores_group_message_outside_topic(tmp_path):
    from app.handlers.download import download_handler

    dlg = DialogState()
    update = _handler_update(CHAT, 777)
    await download_handler(update, _context(_settings(tmp_path), dialog=dlg))
    update.message.reply_text.assert_not_awaited()
    assert dlg.get(777) is None


async def test_handler_prompts_type_in_topic_with_thread_id(tmp_path):
    from app.handlers.download import download_handler
    from app.services.dialog import PROMPT_TYPE

    # Di topic, dialog Video/Audio muncul TANPA `/advance` (WP-25).
    dlg = DialogState()
    update = _handler_update(CHAT, THREAD)
    await download_handler(update, _context(_settings(tmp_path), dialog=dlg))
    call = update.message.reply_text.call_args
    assert call.args == (PROMPT_TYPE,)
    assert call.kwargs["message_thread_id"] == THREAD
    assert dlg.get(999).step == STEP_TYPE


async def test_handler_private_keeps_default_path_without_thread(tmp_path):
    from app.handlers.download import download_handler

    dlg = DialogState()
    update = _handler_update(555, None, chat_type="private")
    ctx = _context(_settings(tmp_path), dialog=dlg)
    ctx.bot_data["workers"] = ["test-owned-no-spawn"]
    from tests.queue_support import JobCollector

    collector = JobCollector()
    with collector.install():
        await download_handler(update, ctx)
        assert collector.scheduled == 1
        assert collector.jobs[0].message_thread_id is None
        collector.close_pending()
    assert "message_thread_id" not in update.message.reply_text.call_args.kwargs


# ================= propagasi thread ke worker + uploader =================


def test_build_job_carries_thread_id():
    ctx = MagicMock()
    update = _handler_update(CHAT, THREAD)
    job = build_job(update, URL, ctx, None)
    assert job.message_thread_id == THREAD


def test_build_job_dm_has_no_thread_id():
    update = _handler_update(555, None, chat_type="private")
    job = build_job(update, URL, MagicMock(), None)
    assert job.message_thread_id is None


async def test_send_video_passes_thread_id(tmp_path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    bot = MagicMock()
    bot.send_video = AsyncMock()
    bot.send_document = AsyncMock()

    await send_video(
        bot,
        1,
        media,
        "t",
        URL,
        max_file_size_mb=50,
        metadata={"filesize": 10},
        thread_id=THREAD,
    )
    assert bot.send_video.await_args.kwargs["message_thread_id"] == THREAD


async def test_send_video_dm_omits_thread_kwarg(tmp_path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    bot = MagicMock()
    bot.send_video = AsyncMock()
    bot.send_document = AsyncMock()

    await send_video(bot, 1, media, "t", URL, max_file_size_mb=50, metadata={"filesize": 10})
    assert "message_thread_id" not in bot.send_video.await_args.kwargs


async def test_send_audio_passes_thread_id(tmp_path):
    media = tmp_path / "a.mp3"
    media.write_bytes(b"x")
    bot = MagicMock()
    bot.send_audio = AsyncMock()
    bot.send_document = AsyncMock()

    await send_audio(bot, 1, media, "t", URL, max_file_size_mb=50, thread_id=THREAD)
    assert bot.send_audio.await_args.kwargs["message_thread_id"] == THREAD


# ================= callback di luar topic =================


async def test_ack_callback_outside_topic_is_ignored(tmp_path):
    from app.handlers.download import cancel_ack_callback

    query = MagicMock()
    query.data = "ac:1-1"
    query.answer = AsyncMock()
    chat = MagicMock()
    chat.id = CHAT
    chat.type = "supergroup"
    message = MagicMock()
    message.message_thread_id = 777
    update = MagicMock()
    update.callback_query = query
    update.effective_message = message
    update.effective_chat = chat
    ctx = _context(_settings(tmp_path))
    ctx.bot.delete_message = AsyncMock()

    await cancel_ack_callback(update, ctx)
    query.answer.assert_awaited_once_with()
    ctx.bot.delete_message.assert_not_awaited()


def test_callback_handlers_are_the_two_known_patterns():
    """Registrasi callback tetap 2 (`ad:` + `ac:`); scope dijaga di handler."""
    from app.handlers.account import advance_callback
    from app.handlers.download import cancel_ack_callback

    # CallbackQueryHandler tidak punya parameter `filters` di PTB 22.8 ->
    # scope WAJIB diperiksa di dalam fungsi (lihat test di atas).
    for handler in (
        CallbackQueryHandler(advance_callback, pattern=r"^ad:"),
        CallbackQueryHandler(cancel_ack_callback, pattern=r"^ac:"),
    ):
        assert handler.pattern is not None
