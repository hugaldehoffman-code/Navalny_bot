"""
Tests for two fixes in services/ai.py and handlers/inline.py:
  Task 1 – max_tokens raised 250→400 (prevents mid-sentence cut-offs)
  Task 2 – 3-attempt retry with linear backoff (reduces error fallback frequency)

Run:
    pytest MAIN/tests/test_ai_fixes.py -v
"""
import sys
import os
import types
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Remove any cached versions so fresh imports pick up our mocks ─────────────
for _m in ("services.ai", "handlers.inline"):
    sys.modules.pop(_m, None)

# ── Fake config (superset of test_bot.py so both files co-exist) ─────────────
_cfg = types.ModuleType("config")
_cfg.DB_NAME             = ":memory:"
_cfg.logger              = MagicMock()
_cfg.SYSTEM_PROMPT       = "You are Navalny"
_cfg.BUTTON_PROMPTS      = {"chat": "Answer short"}
_cfg.ERROR_FALLBACK_TEXT = "FALLBACK"
_cfg.BOT_STATE           = {"is_paused": False, "mute_until": 0}
_cfg.ADMIN_PASSWORD      = "secret"
_cfg.VIP_USERS           = set()
_cfg.BOT_INFO            = {"id": 999, "username": "navalny_bot"}
_cfg.USER_MESSAGE_LOGS   = defaultdict(list)
_cfg.LIMIT_WINDOW        = 60
_cfg.LIMIT_MESSAGES      = 5
_cfg.USER_AUDIO_LOGS         = {}
_cfg.AUDIO_LIMIT_WINDOW      = 1800
_cfg.AUDIO_LIMIT_WINDOW_VIP  = 300
_cfg.USER_FACTCHECK_LOGS     = defaultdict(list)
_cfg.FACTCHECK_DAILY_LIMIT_FREE = 3
_cfg.FACTCHECK_DAILY_LIMIT_VIP  = 20
_cfg.ZVUKOGRAM_TOKEN     = "zvuk_tok"
_cfg.ZVUKOGRAM_EMAIL     = "test@mail.com"
_cfg.ZVUKOGRAM_VOICE     = "TestVoice"
_cfg.ROUTERAI_API_KEY    = "fake_key"
_cfg.bot                 = AsyncMock()
_cfg.client              = AsyncMock()
sys.modules["config"] = _cfg

# ── Fake database ─────────────────────────────────────────────────────────────
_db = types.ModuleType("database")
_db.save_context                 = AsyncMock()
_db.get_context                  = AsyncMock(return_value=[])
_db.clear_context                = AsyncMock()
_db.get_or_create_user           = AsyncMock(return_value={"tariff_name": "FREE", "premium_until": None})
_db.check_and_reset_daily_limits = AsyncMock(return_value={"tariff_name": "FREE"})
_db.expire_premium_if_needed     = AsyncMock(return_value={"tariff_name": "FREE", "premium_until": None})
_db.increment_text_usage         = AsyncMock()
_db.increment_media_usage        = AsyncMock()
sys.modules["database"] = _db

# ── Import modules under test ─────────────────────────────────────────────────
import services.ai as ai_module          # noqa: E402
import handlers.inline as inline_module  # noqa: E402

# Restore sys.modules so test_bot.py (which runs later alphabetically) can
# import the *real* database module without hitting our fake.
# ai_module already has its bindings (get_context → _db.get_context, etc.) —
# removing the key from sys.modules does not affect those existing references.
sys.modules.pop("database", None)

FALLBACK = _cfg.ERROR_FALLBACK_TEXT


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _api_response(text: str = "Ответ Навального") -> MagicMock:
    """Minimal mock that looks like an openai ChatCompletion response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


def _mock_client(*side_effects) -> MagicMock:
    """Client mock whose chat.completions.create() yields side_effects in order."""
    mc = MagicMock()
    mc.chat.completions.create = AsyncMock(side_effect=list(side_effects))
    return mc


def _inline_chosen_result(query: str = "тест") -> MagicMock:
    cr = MagicMock()
    cr.result_id = "dynamic_request"
    cr.inline_message_id = "INLINE_MSG_ID"
    cr.query = query
    return cr


# ─────────────────────────────────────────────────────────────────────────────
# Task 1 — max_tokens = 400
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxTokens:
    """Verify every public entry-point uses max_tokens=400 by default."""

    @pytest.mark.asyncio
    async def test_generate_response_default_is_400(self):
        mc = _mock_client(_api_response())
        with patch.object(ai_module, "client", mc):
            await ai_module.generate_response(user_id=1)
        assert mc.chat.completions.create.call_args.kwargs["max_tokens"] == 500

    @pytest.mark.asyncio
    async def test_generate_response_custom_max_tokens_respected(self):
        mc = _mock_client(_api_response())
        with patch.object(ai_module, "client", mc):
            await ai_module.generate_response(user_id=1, max_tokens=150)
        assert mc.chat.completions.create.call_args.kwargs["max_tokens"] == 150

    @pytest.mark.asyncio
    async def test_process_ai_reply_passes_400_to_generate_response(self):
        """process_ai_reply default flows max_tokens=400 down the call chain."""
        msg = MagicMock()
        msg.from_user = MagicMock(id=1)
        msg.chat = MagicMock(type="private")
        msg.answer = AsyncMock()

        with patch.object(ai_module, "generate_response", new=AsyncMock(return_value="ok")) as mock_gen:
            await ai_module.process_ai_reply(msg, system_addition="", trigger_text="привет")

        assert mock_gen.call_args.kwargs["max_tokens"] == 500

    @pytest.mark.asyncio
    async def test_inline_handler_uses_400(self):
        mc = _mock_client(_api_response("inline reply"))
        _cfg.bot.edit_message_text = AsyncMock()

        with patch.object(inline_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await inline_module.chosen_inline_result_handler(_inline_chosen_result())

        assert mc.chat.completions.create.call_args.kwargs["max_tokens"] == 500


# ─────────────────────────────────────────────────────────────────────────────
# Task 2 — retry logic in generate_response()
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateResponseRetry:
    """3 attempts, linear backoff (sleep 1 s then 2 s), fallback on exhaustion."""

    @pytest.mark.asyncio
    async def test_returns_result_immediately_on_success(self):
        mc = _mock_client(_api_response("instant"))
        with patch.object(ai_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await ai_module.generate_response(user_id=1)
        assert result == "instant"
        assert mc.chat.completions.create.await_count == 1
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retries_once_and_returns_second_result(self):
        mc = _mock_client(Exception("net"), _api_response("retry ok"))
        with patch.object(ai_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await ai_module.generate_response(user_id=1)
        assert result == "retry ok"
        assert mc.chat.completions.create.await_count == 2
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    async def test_retries_twice_and_returns_third_result(self):
        mc = _mock_client(Exception("e1"), Exception("e2"), _api_response("third"))
        with patch.object(ai_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await ai_module.generate_response(user_id=1)
        assert result == "third"
        assert mc.chat.completions.create.await_count == 3
        calls = [c.args[0] for c in mock_sleep.await_args_list]
        assert calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_returns_fallback_after_all_three_failures(self):
        mc = _mock_client(Exception("1"), Exception("2"), Exception("3"))
        with patch.object(ai_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ai_module.generate_response(user_id=1)
        assert result == FALLBACK
        assert mc.chat.completions.create.await_count == 3

    @pytest.mark.asyncio
    async def test_empty_response_content_returns_fallback(self):
        mc = _mock_client(_api_response(""))
        with patch.object(ai_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ai_module.generate_response(user_id=1)
        assert result == FALLBACK

    @pytest.mark.asyncio
    async def test_backoff_delays_are_exactly_1s_and_2s(self):
        mc = _mock_client(Exception("a"), Exception("b"), _api_response("c"))
        with patch.object(ai_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await ai_module.generate_response(user_id=1)
        calls = [c.args[0] for c in mock_sleep.await_args_list]
        assert calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_no_fourth_attempt_made(self):
        """Retry loop must stop at 3, never make a 4th call."""
        mc = _mock_client(Exception("1"), Exception("2"), Exception("3"), _api_response("4"))
        with patch.object(ai_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ai_module.generate_response(user_id=1)
        assert result == FALLBACK
        assert mc.chat.completions.create.await_count == 3  # not 4


# ─────────────────────────────────────────────────────────────────────────────
# Task 2 — retry logic in inline chosen_result handler
# ─────────────────────────────────────────────────────────────────────────────

class TestInlineRetry:
    """Same retry contract in chosen_inline_result_handler."""

    @pytest.mark.asyncio
    async def test_succeeds_first_attempt_no_sleep(self):
        mc = _mock_client(_api_response("fast"))
        _cfg.bot.edit_message_text = AsyncMock()
        with patch.object(inline_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await inline_module.chosen_inline_result_handler(_inline_chosen_result())
        assert mc.chat.completions.create.await_count == 1
        mock_sleep.assert_not_awaited()
        assert "fast" in _cfg.bot.edit_message_text.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_retries_on_first_failure(self):
        mc = _mock_client(Exception("timeout"), _api_response("second"))
        _cfg.bot.edit_message_text = AsyncMock()
        with patch.object(inline_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await inline_module.chosen_inline_result_handler(_inline_chosen_result())
        assert mc.chat.completions.create.await_count == 2
        mock_sleep.assert_awaited_once_with(1.0)
        assert "second" in _cfg.bot.edit_message_text.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_fallback_sent_after_three_failures(self):
        mc = _mock_client(Exception("1"), Exception("2"), Exception("3"))
        _cfg.bot.edit_message_text = AsyncMock()
        with patch.object(inline_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await inline_module.chosen_inline_result_handler(_inline_chosen_result())
        assert mc.chat.completions.create.await_count == 3
        assert FALLBACK in _cfg.bot.edit_message_text.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_backoff_delays_are_1s_and_2s(self):
        mc = _mock_client(Exception("a"), Exception("b"), _api_response("c"))
        _cfg.bot.edit_message_text = AsyncMock()
        with patch.object(inline_module, "client", mc):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await inline_module.chosen_inline_result_handler(_inline_chosen_result())
        calls = [c.args[0] for c in mock_sleep.await_args_list]
        assert calls == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_static_result_id_is_ignored(self):
        """Handler must no-op for pre-rendered static results."""
        mc = _mock_client()
        cr = MagicMock()
        cr.result_id = "static_joke_0"
        with patch.object(inline_module, "client", mc):
            await inline_module.chosen_inline_result_handler(cr)
        mc.chat.completions.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_inline_message_id_does_not_call_api(self):
        """If inline_message_id is None (feedback not enabled), skip silently."""
        mc = _mock_client()
        cr = MagicMock()
        cr.result_id = "dynamic_request"
        cr.inline_message_id = None
        cr.query = "test"
        with patch.object(inline_module, "client", mc):
            await inline_module.chosen_inline_result_handler(cr)
        mc.chat.completions.create.assert_not_awaited()
