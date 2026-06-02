"""
Тесты бота: database, middlewares, handlers.

Запуск:
    pytest MAIN/tests/test_bot.py -v
"""
import sys
import os
import asyncio
import time
import atexit
import tempfile
from datetime import datetime, timedelta
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Подменяем config до импорта модулей бота
import types

# Temp-file DB: unlike ":memory:", a file path shares state across
# multiple aiosqlite.connect() calls within the same test run.
_TEST_DB_FILE = tempfile.mktemp(suffix=".test.db")
atexit.register(lambda: os.unlink(_TEST_DB_FILE) if os.path.exists(_TEST_DB_FILE) else None)

fake_config = types.ModuleType("config")
fake_config.DB_NAME              = _TEST_DB_FILE
fake_config.logger               = MagicMock()
fake_config.SYSTEM_PROMPT        = "You are Navalny"
fake_config.BUTTON_PROMPTS       = {"chat": "short", "news": "", "joke": "", "merch": "",
                                    "food": "", "complaint": "", "leaks": "", "vision_comment": "", "sud": ""}
fake_config.ERROR_FALLBACK_TEXT  = "FALLBACK"
fake_config.BOT_STATE            = {"is_paused": False, "mute_until": 0}
fake_config.ADMIN_PASSWORD       = "secret"
fake_config.VIP_USERS            = set()
fake_config.BOT_INFO             = {"id": 999, "username": "navalny_bot"}
fake_config.USER_MESSAGE_LOGS    = defaultdict(list)
fake_config.LIMIT_WINDOW         = 60
fake_config.LIMIT_MESSAGES       = 5
fake_config.USER_AUDIO_LOGS      = {}
fake_config.AUDIO_LIMIT_WINDOW   = 1800
fake_config.ZVUKOGRAM_TOKEN      = "zvuk_tok"
fake_config.ZVUKOGRAM_EMAIL      = "test@mail.com"
fake_config.ZVUKOGRAM_VOICE      = "TestVoice"
fake_config.ROUTERAI_API_KEY     = "fake_key"
fake_config.bot                  = AsyncMock()
fake_config.client               = AsyncMock()
sys.modules["config"] = fake_config

from database import (
    init_db,
    save_context,
    get_context,
    clear_context,
    get_or_create_user,
    check_and_reset_daily_limits,
    update_tariff,
    expire_premium_if_needed,
    increment_text_usage,
    increment_media_usage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def fresh_db():
    """Чистая БД перед каждым тестом: DROP + CREATE."""
    import aiosqlite
    async with aiosqlite.connect(fake_config.DB_NAME) as db:
        await db.execute("DROP TABLE IF EXISTS user_contexts")
        await db.execute("DROP TABLE IF EXISTS users")
        await db.commit()
    await init_db()
    yield


# ---------------------------------------------------------------------------
# 1. DATABASE — контексты
# ---------------------------------------------------------------------------

class TestContext:
    @pytest.mark.asyncio
    async def test_get_empty_context(self):
        assert await get_context(1) == []

    @pytest.mark.asyncio
    async def test_save_and_get_context(self):
        await save_context(1, "Привет", is_user=True)
        ctx = await get_context(1)
        assert len(ctx) == 1
        assert ctx[0]["role"] == "user"
        assert ctx[0]["content"] == "Привет"

    @pytest.mark.asyncio
    async def test_context_role_assistant(self):
        await save_context(1, "Ответ", is_user=False)
        ctx = await get_context(1)
        assert ctx[0]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_context_trimmed_to_8(self):
        for i in range(12):
            await save_context(1, f"msg {i}", is_user=True)
        ctx = await get_context(1)
        assert len(ctx) == 8
        assert ctx[-1]["content"] == "msg 11"

    @pytest.mark.asyncio
    async def test_clear_context(self):
        await save_context(1, "data", is_user=True)
        await clear_context(1)
        assert await get_context(1) == []

    @pytest.mark.asyncio
    async def test_clear_nonexistent_context_no_error(self):
        await clear_context(999)  # не должно падать


# ---------------------------------------------------------------------------
# 2. DATABASE — пользователи и тарифы
# ---------------------------------------------------------------------------

class TestUsers:
    @pytest.mark.asyncio
    async def test_create_user_defaults(self):
        user = await get_or_create_user(42, "testuser")
        assert user["user_id"] == 42
        assert user["tariff_name"] == "FREE"
        assert user["daily_text_used"] == 0
        assert user["daily_media_used"] == 0

    @pytest.mark.asyncio
    async def test_get_existing_user(self):
        await get_or_create_user(42, "first")
        user = await get_or_create_user(42, "second")
        assert user["user_id"] == 42

    @pytest.mark.asyncio
    async def test_update_tariff_sets_premium(self):
        await get_or_create_user(42)
        await update_tariff(42, "VIP_LITE", 30)
        user = await get_or_create_user(42)
        assert user["tariff_name"] == "VIP_LITE"
        assert user["premium_until"] is not None

    @pytest.mark.asyncio
    async def test_update_tariff_creates_user_if_missing(self):
        await update_tariff(999, "VIP_PRO", 30)
        user = await get_or_create_user(999)
        assert user["tariff_name"] == "VIP_PRO"

    @pytest.mark.asyncio
    async def test_increment_text_usage(self):
        await get_or_create_user(42)
        await increment_text_usage(42)
        await increment_text_usage(42)
        user = await get_or_create_user(42)
        assert user["daily_text_used"] == 2

    @pytest.mark.asyncio
    async def test_increment_media_usage(self):
        await get_or_create_user(42)
        await increment_media_usage(42)
        user = await get_or_create_user(42)
        assert user["daily_media_used"] == 1

    @pytest.mark.asyncio
    async def test_reset_daily_limits_new_day(self):
        import aiosqlite
        await get_or_create_user(42)
        await increment_text_usage(42)
        # Ставим вчерашнюю дату
        async with aiosqlite.connect(":memory:"):
            pass
        from database import DB_NAME
        import aiosqlite as aio
        async with aio.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET last_request_date = '2000-01-01', daily_text_used = 10 WHERE user_id = 42"
            )
            await db.commit()
        user = await check_and_reset_daily_limits(42)
        assert user["daily_text_used"] == 0

    @pytest.mark.asyncio
    async def test_expire_premium_resets_to_free(self):
        await get_or_create_user(42)
        # Устанавливаем истёкший премиум
        expired = (datetime.now() - timedelta(days=1)).isoformat()
        import aiosqlite as aio
        from database import DB_NAME
        async with aio.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET tariff_name = 'VIP_LITE', premium_until = ? WHERE user_id = 42",
                (expired,)
            )
            await db.commit()
        user = await expire_premium_if_needed(42)
        assert user["tariff_name"] == "FREE"
        assert user["premium_until"] is None

    @pytest.mark.asyncio
    async def test_expire_premium_keeps_active(self):
        await get_or_create_user(42)
        future = (datetime.now() + timedelta(days=10)).isoformat()
        import aiosqlite as aio
        from database import DB_NAME
        async with aio.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET tariff_name = 'VIP_PRO', premium_until = ? WHERE user_id = 42",
                (future,)
            )
            await db.commit()
        user = await expire_premium_if_needed(42)
        assert user["tariff_name"] == "VIP_PRO"


# ---------------------------------------------------------------------------
# 3. THROTTLING MIDDLEWARE
# ---------------------------------------------------------------------------

class TestThrottlingMiddleware:
    def _make_middleware(self):
        from middlewares.throttling import ThrottlingMiddleware
        # clear() keeps the same object; reassigning would break the module's
        # already-imported reference to USER_MESSAGE_LOGS
        fake_config.USER_MESSAGE_LOGS.clear()
        return ThrottlingMiddleware()

    def _make_message(self, user_id=1, chat_type="private", text="hello"):
        from aiogram.types import Message
        # spec=Message makes isinstance(msg, Message) return True via _spec_class,
        # which is required for middleware branches that call event.reply().
        msg = MagicMock(spec=Message)
        msg.from_user = MagicMock(id=user_id)
        msg.chat = MagicMock(type=chat_type)
        msg.text = text
        msg.caption = None
        msg.reply_to_message = None
        msg.reply = AsyncMock()
        return msg

    @pytest.mark.asyncio
    async def test_passes_first_message(self):
        mw = self._make_middleware()
        handler = AsyncMock(return_value="ok")
        msg = self._make_message()
        data = {"event_from_user": MagicMock(id=1)}
        result = await mw(handler, msg, data)
        assert result == "ok"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_blocks_after_limit(self):
        mw = self._make_middleware()
        user_id = 77
        # Заполняем лог до предела
        fake_config.USER_MESSAGE_LOGS[user_id] = [time.time()] * fake_config.LIMIT_MESSAGES

        handler = AsyncMock()
        msg = self._make_message(user_id=user_id)
        data = {"event_from_user": MagicMock(id=user_id)}
        await mw(handler, msg, data)
        handler.assert_not_awaited()
        msg.reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_vip_bypasses_throttle(self):
        mw = self._make_middleware()
        user_id = 88
        # Patch the module-level VIP_USERS that the middleware has already imported;
        # reassigning fake_config.VIP_USERS would not affect the bound reference.
        import middlewares.throttling as throttle_mod
        fake_config.USER_MESSAGE_LOGS[user_id] = [time.time()] * 100

        handler = AsyncMock(return_value="ok")
        msg = self._make_message(user_id=user_id)
        data = {"event_from_user": MagicMock(id=user_id)}
        with patch.object(throttle_mod, "VIP_USERS", {user_id}):
            result = await mw(handler, msg, data)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_old_timestamps_cleaned(self):
        mw = self._make_middleware()
        user_id = 55
        # Старые метки (вне окна) — не должны блокировать
        fake_config.USER_MESSAGE_LOGS[user_id] = [time.time() - 999] * fake_config.LIMIT_MESSAGES

        handler = AsyncMock(return_value="ok")
        msg = self._make_message(user_id=user_id)
        data = {"event_from_user": MagicMock(id=user_id)}
        result = await mw(handler, msg, data)
        assert result == "ok"


# ---------------------------------------------------------------------------
# 4. LIMITS MIDDLEWARE
# ---------------------------------------------------------------------------

class TestLimitsMiddleware:
    def _make_middleware(self):
        from middlewares.limits_middleware import LimitsMiddleware
        return LimitsMiddleware()

    def _make_message(self, user_id=1, chat_type="private", text="hello",
                      has_photo=False, has_voice=False):
        msg = MagicMock()
        msg.from_user = MagicMock(id=user_id, username="test", full_name="Test")
        msg.chat = MagicMock(type=chat_type)
        msg.text = text
        msg.caption = None
        msg.reply_to_message = None
        msg.photo = [MagicMock()] if has_photo else None
        msg.voice = MagicMock() if has_voice else None
        msg.audio = None
        msg.document = None
        msg.video = None
        msg.video_note = None
        msg.answer = AsyncMock()
        msg.reply = AsyncMock()
        return msg

    @pytest.mark.asyncio
    async def test_service_command_bypasses_limits(self):
        mw = self._make_middleware()
        handler = AsyncMock(return_value="ok")
        msg = self._make_message(text="/start")
        data = {"event_from_user": MagicMock(id=1, username="u", full_name="U")}
        result = await mw(handler, msg, data)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_text_limit_exceeded_blocks(self):
        await get_or_create_user(42)
        # Выжигаем лимит вручную
        import aiosqlite as aio
        from database import DB_NAME
        from tariffs import get_tariff
        limit = get_tariff("FREE").daily_text_limit
        async with aio.connect(DB_NAME) as db:
            import datetime as dt
            today = str(dt.date.today())
            await db.execute(
                "UPDATE users SET daily_text_used = ?, last_request_date = ? WHERE user_id = 42",
                (limit, today)
            )
            await db.commit()

        mw = self._make_middleware()
        handler = AsyncMock()
        msg = self._make_message(user_id=42)
        data = {"event_from_user": MagicMock(id=42, username="u", full_name="U")}
        await mw(handler, msg, data)
        handler.assert_not_awaited()
        msg.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_media_counted_separately(self):
        await get_or_create_user(43)
        mw = self._make_middleware()
        handler = AsyncMock(return_value="ok")
        msg = self._make_message(user_id=43, has_photo=True)
        data = {"event_from_user": MagicMock(id=43, username="u", full_name="U")}
        await mw(handler, msg, data)
        user = await get_or_create_user(43)
        assert user["daily_media_used"] == 1
        assert user["daily_text_used"] == 0

    @pytest.mark.asyncio
    async def test_vip_user_bypasses_limits(self):
        fake_config.VIP_USERS = {99}
        mw = self._make_middleware()
        handler = AsyncMock(return_value="ok")
        msg = self._make_message(user_id=99)
        data = {"event_from_user": MagicMock(id=99, username="u", full_name="U")}
        result = await mw(handler, msg, data)
        assert result == "ok"
        fake_config.VIP_USERS = set()


# ---------------------------------------------------------------------------
# 5. HANDLERS — команды
# ---------------------------------------------------------------------------

class TestCommandHandlers:
    def _make_message(self, user_id=1, text="/start", chat_type="private"):
        msg = MagicMock()
        msg.from_user = MagicMock(id=user_id, username="u", full_name="User", is_bot=False)
        msg.chat = MagicMock(type=chat_type)
        msg.text = text
        msg.answer = AsyncMock()
        msg.reply = AsyncMock()
        msg.reply_to_message = None
        return msg

    @pytest.mark.asyncio
    async def test_start_sends_welcome(self):
        from handlers.commands import start_command
        msg = self._make_message()
        await start_command(msg)
        msg.answer.assert_awaited_once()
        call_args = msg.answer.call_args[0][0]
        assert "Навальный" in call_args

    @pytest.mark.asyncio
    async def test_actions_sends_keyboard(self):
        from handlers.commands import actions_command
        msg = self._make_message(text="/actions")
        await actions_command(msg)
        msg.answer.assert_awaited_once()
        # Убеждаемся что передана клавиатура
        kwargs = msg.answer.call_args[1]
        assert "reply_markup" in kwargs

    @pytest.mark.asyncio
    async def test_help_sends_message(self):
        from handlers.commands import help_command
        await get_or_create_user(1)
        msg = self._make_message(text="/help")

        with patch("handlers.commands._get_user_status", new=AsyncMock(return_value={
            "tariff_name": "FREE",
            "daily_text_used": 5,
            "daily_media_used": 1,
            "premium_until": None,
        })):
            await help_command(msg)
        msg.answer.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "FREE" in text or "Бесплатный" in text

    @pytest.mark.asyncio
    async def test_factcheck_no_args_sends_hint(self):
        from handlers.commands import factcheck_command
        msg = self._make_message(text="/factcheck")
        msg.reply_to_message = None

        with patch("handlers.commands._get_user_status", new=AsyncMock(return_value={
            "tariff_name": "FREE", "daily_text_used": 0, "daily_media_used": 0, "premium_until": None
        })):
            await factcheck_command(msg)
        msg.reply.assert_awaited_once()
        assert "factcheck" in msg.reply.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_post_no_args_sends_hint(self):
        from handlers.commands import post_command
        msg = self._make_message(text="/post")
        msg.reply_to_message = None

        with patch("handlers.commands._get_user_status", new=AsyncMock(return_value={
            "tariff_name": "FREE", "daily_text_used": 0, "daily_media_used": 0, "premium_until": None
        })):
            await post_command(msg)
        msg.reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_control_wrong_password(self):
        from handlers.commands import control_command
        msg = self._make_message(text="/control wrongpass pause")
        msg.text = "/control wrongpass pause"
        await control_command(msg)
        msg.reply.assert_awaited_once()
        assert "Неверный" in msg.reply.call_args[0][0]

    @pytest.mark.asyncio
    async def test_control_pause(self):
        from handlers.commands import control_command
        fake_config.BOT_STATE["is_paused"] = False
        msg = self._make_message(text="/control secret pause")
        msg.text = "/control secret pause"
        await control_command(msg)
        assert fake_config.BOT_STATE["is_paused"] is True

    @pytest.mark.asyncio
    async def test_control_resume(self):
        from handlers.commands import control_command
        fake_config.BOT_STATE["is_paused"] = True
        msg = self._make_message(text="/control secret resume")
        msg.text = "/control secret resume"
        await control_command(msg)
        assert fake_config.BOT_STATE["is_paused"] is False

    @pytest.mark.asyncio
    async def test_sud_private_chat_reply(self):
        from handlers.commands import sud_command
        msg = self._make_message(chat_type="private", text="/sud")
        await sud_command(msg)
        msg.reply.assert_awaited_once()
        assert "личке" in msg.reply.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_sud_group_no_reply_sends_hint(self):
        from handlers.commands import sud_command
        msg = self._make_message(chat_type="group", text="/sud")
        msg.reply_to_message = None
        await sud_command(msg)
        msg.reply.assert_awaited_once()
        assert "ответь" in msg.reply.call_args[0][0].lower()
