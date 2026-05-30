"""
Тесты для FailoverAiohttpSession.

Запуск:
    pip install pytest pytest-asyncio
    pytest MAIN/tests/test_proxy_session.py -v
"""

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import aiohttp
import pytest

# Добавляем MAIN в sys.path, чтобы импортировать proxy_session без установки пакета
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from proxy_session import FailoverAiohttpSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

HTTP_PROXY_1 = "http://1.2.3.4:8000"
HTTP_PROXY_2 = "http://5.6.7.8:3128"
SOCKS5_PROXY = "socks5://user:pass@9.10.11.12:1080"


def make_session(proxies=None) -> FailoverAiohttpSession:
    """Вспомогательная фабрика сессии."""
    if proxies is None:
        proxies = [HTTP_PROXY_1, HTTP_PROXY_2]
    return FailoverAiohttpSession(proxies=proxies)


# ---------------------------------------------------------------------------
# 1. Инициализация
# ---------------------------------------------------------------------------


class TestInit:
    def test_raises_on_empty_proxies(self):
        with pytest.raises(ValueError, match="пустым"):
            FailoverAiohttpSession(proxies=[])

    def test_initial_index_is_zero(self):
        session = make_session()
        assert session._proxy_index == 0

    def test_stores_proxies_list(self):
        proxies = [HTTP_PROXY_1, HTTP_PROXY_2]
        session = make_session(proxies)
        assert session._proxies == proxies

    def test_current_proxy_is_first(self):
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        assert session._current_proxy_url == HTTP_PROXY_1


# ---------------------------------------------------------------------------
# 2. Определение типа прокси
# ---------------------------------------------------------------------------


class TestProxyTypeDetection:
    def test_http_is_not_socks(self):
        session = make_session()
        assert session._is_socks("http://1.2.3.4:8000") is False

    def test_https_is_not_socks(self):
        session = make_session()
        assert session._is_socks("https://1.2.3.4:8000") is False

    def test_socks5_detected(self):
        session = make_session()
        assert session._is_socks("socks5://1.2.3.4:1080") is True

    def test_socks5_uppercase_detected(self):
        session = make_session()
        assert session._is_socks("SOCKS5://1.2.3.4:1080") is True

    def test_get_http_proxy_returns_url_for_http(self):
        session = make_session()
        assert session._get_http_proxy(HTTP_PROXY_1) == HTTP_PROXY_1

    def test_get_http_proxy_returns_none_for_socks5(self):
        session = make_session()
        assert session._get_http_proxy(SOCKS5_PROXY) is None


# ---------------------------------------------------------------------------
# 3. Коннекторы
# ---------------------------------------------------------------------------


class TestMakeConnector:
    def test_http_proxy_returns_none_connector(self):
        session = make_session()
        connector = session._make_connector(HTTP_PROXY_1)
        assert connector is None

    def test_socks5_raises_without_library(self):
        session = make_session()
        with patch("proxy_session._SOCKS_AVAILABLE", False):
            with pytest.raises(ImportError, match="aiohttp-socks"):
                session._make_connector(SOCKS5_PROXY)

    def test_socks5_creates_proxy_connector(self):
        session = make_session()
        mock_connector = MagicMock()
        with patch("proxy_session._SOCKS_AVAILABLE", True):
            with patch("proxy_session.ProxyConnector") as MockPC:
                MockPC.from_url.return_value = mock_connector
                result = session._make_connector(SOCKS5_PROXY)
                MockPC.from_url.assert_called_once_with(SOCKS5_PROXY, rdns=True)
                assert result is mock_connector


# ---------------------------------------------------------------------------
# 4. Ротация прокси
# ---------------------------------------------------------------------------


class TestRotation:
    @pytest.mark.asyncio
    async def test_rotate_increments_index(self):
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        await session._rotate_proxy()
        assert session._proxy_index == 1

    @pytest.mark.asyncio
    async def test_rotate_wraps_around(self):
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        session._proxy_index = 1
        await session._rotate_proxy()
        assert session._proxy_index == 0  # wraparound

    @pytest.mark.asyncio
    async def test_rotate_closes_existing_session(self):
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        mock_aiohttp_session = MagicMock()
        mock_aiohttp_session.closed = False
        mock_aiohttp_session.close = AsyncMock()
        session._session = mock_aiohttp_session

        await session._rotate_proxy()

        mock_aiohttp_session.close.assert_awaited_once()
        assert session._session is None

    @pytest.mark.asyncio
    async def test_rotate_logs_warning(self, caplog):
        import logging
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        with caplog.at_level(logging.WARNING, logger="proxy_session"):
            await session._rotate_proxy()
        assert HTTP_PROXY_1 in caplog.text
        assert HTTP_PROXY_2 in caplog.text


# ---------------------------------------------------------------------------
# 5. make_request — успешный запрос
# ---------------------------------------------------------------------------


class TestMakeRequestSuccess:
    @pytest.mark.asyncio
    async def test_returns_result_on_first_attempt(self):
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        bot = MagicMock()
        method = MagicMock()
        expected = MagicMock()

        with patch.object(
            session.__class__.__bases__[0],  # AiohttpSession
            "make_request",
            new=AsyncMock(return_value=expected),
        ):
            result = await session.make_request(bot, method)

        assert result is expected
        assert session._proxy_index == 0  # прокси не менялся

    @pytest.mark.asyncio
    async def test_no_rotation_on_success(self):
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        rotate_spy = AsyncMock()
        session._rotate_proxy = rotate_spy

        with patch.object(
            session.__class__.__bases__[0],
            "make_request",
            new=AsyncMock(return_value="ok"),
        ):
            await session.make_request(MagicMock(), MagicMock())

        rotate_spy.assert_not_awaited()


# ---------------------------------------------------------------------------
# 6. make_request — ротация при ошибках
# ---------------------------------------------------------------------------


class TestMakeRequestFailover:
    @pytest.mark.asyncio
    async def test_rotates_on_timeout(self):
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        session._rotate_proxy = AsyncMock()

        # Первый вызов — таймаут, второй — успех
        with patch.object(
            session.__class__.__bases__[0],
            "make_request",
            side_effect=[asyncio.TimeoutError(), "ok"],
        ):
            result = await session.make_request(MagicMock(), MagicMock())

        assert result == "ok"
        session._rotate_proxy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rotates_on_client_error(self):
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        session._rotate_proxy = AsyncMock()

        with patch.object(
            session.__class__.__bases__[0],
            "make_request",
            side_effect=[aiohttp.ClientError(), "ok"],
        ):
            result = await session.make_request(MagicMock(), MagicMock())

        assert result == "ok"
        session._rotate_proxy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_after_all_attempts_exhausted(self):
        proxies = [HTTP_PROXY_1, HTTP_PROXY_2, "http://3.3.3.3:80"]
        session = make_session(proxies)
        session._rotate_proxy = AsyncMock()

        with patch.object(
            session.__class__.__bases__[0],
            "make_request",
            side_effect=asyncio.TimeoutError("dead"),
        ):
            with pytest.raises(asyncio.TimeoutError):
                await session.make_request(MagicMock(), MagicMock())

        # Ротаций должно быть на 1 меньше, чем попыток (последняя не ротирует)
        assert session._rotate_proxy.await_count == 2

    @pytest.mark.asyncio
    async def test_max_attempts_capped_at_3(self):
        """Даже при 10 прокси попыток не более 3."""
        proxies = [f"http://10.0.0.{i}:80" for i in range(10)]
        session = make_session(proxies)
        session._rotate_proxy = AsyncMock()

        call_count = 0

        async def failing_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise asyncio.TimeoutError()

        with patch.object(
            session.__class__.__bases__[0],
            "make_request",
            side_effect=failing_request,
        ):
            with pytest.raises(asyncio.TimeoutError):
                await session.make_request(MagicMock(), MagicMock())

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_network_error_not_caught(self):
        """ValueError не должен перехватываться — это не сетевая ошибка."""
        session = make_session([HTTP_PROXY_1, HTTP_PROXY_2])
        session._rotate_proxy = AsyncMock()

        with patch.object(
            session.__class__.__bases__[0],
            "make_request",
            side_effect=ValueError("unexpected"),
        ):
            with pytest.raises(ValueError, match="unexpected"):
                await session.make_request(MagicMock(), MagicMock())

        session._rotate_proxy.assert_not_awaited()


# ---------------------------------------------------------------------------
# 7. create_session
# ---------------------------------------------------------------------------


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_reuses_open_session(self):
        session = make_session()
        mock_aiohttp = MagicMock()
        mock_aiohttp.closed = False
        session._session = mock_aiohttp

        result = await session.create_session()
        assert result is mock_aiohttp

    @pytest.mark.asyncio
    async def test_sets_http_proxy_for_http_url(self):
        """_get_http_proxy возвращает URL для HTTP — проверяем напрямую."""
        session = make_session([HTTP_PROXY_1])
        result = session._get_http_proxy(HTTP_PROXY_1)
        assert result == HTTP_PROXY_1

    @pytest.mark.asyncio
    async def test_sets_no_proxy_attr_for_socks5(self):
        """_get_http_proxy возвращает None для SOCKS5 — проверяем напрямую."""
        session = make_session([SOCKS5_PROXY])
        result = session._get_http_proxy(SOCKS5_PROXY)
        assert result is None
