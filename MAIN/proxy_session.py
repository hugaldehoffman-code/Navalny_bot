import asyncio
import logging
from typing import Optional, TYPE_CHECKING

import aiohttp
from aiogram.client.session.aiohttp import AiohttpSession

try:
    from aiohttp_socks import ProxyConnector
    _SOCKS_AVAILABLE = True
except ImportError:
    _SOCKS_AVAILABLE = False

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.methods import TelegramMethod
    from aiogram.methods.base import TelegramType

logger = logging.getLogger(__name__)


class FailoverAiohttpSession(AiohttpSession):
    """
    AiohttpSession с автоматической ротацией прокси при сбоях.
    Поддерживает HTTP и SOCKS5 прокси.
    При таймауте или сетевой ошибке переключается на следующий прокси из пула
    и повторяет запрос — прозрачно для бота.
    """

    def __init__(self, proxies: list[str], **kwargs):
        if not proxies:
            raise ValueError("Список прокси не может быть пустым")
        self._proxies = proxies
        self._proxy_index = 0
        # Инициализируем родителя без прокси — управляем коннектором сами
        super().__init__(**kwargs)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @property
    def _current_proxy_url(self) -> str:
        return self._proxies[self._proxy_index]

    def _is_socks(self, url: str) -> bool:
        return url.lower().startswith("socks5://")

    def _make_connector(self, proxy_url: str) -> Optional[aiohttp.BaseConnector]:
        """Возвращает ProxyConnector для SOCKS5 или None для HTTP."""
        if self._is_socks(proxy_url):
            if not _SOCKS_AVAILABLE:
                raise ImportError(
                    "Установите aiohttp-socks для использования SOCKS5 прокси: "
                    "pip install aiohttp-socks"
                )
            return ProxyConnector.from_url(proxy_url, rdns=True)
        return None

    def _get_http_proxy(self, proxy_url: str) -> Optional[str]:
        """Возвращает URL только для HTTP прокси; для SOCKS5 — None."""
        return None if self._is_socks(proxy_url) else proxy_url

    # ------------------------------------------------------------------ #
    #  Session lifecycle                                                    #
    # ------------------------------------------------------------------ #

    async def create_session(self) -> aiohttp.ClientSession:
        """Создаёт сессию с коннектором под текущий прокси."""
        if self._session and not self._session.closed:
            return self._session

        proxy_url = self._current_proxy_url
        connector = self._make_connector(proxy_url)

        # Для HTTP-прокси aiogram передаёт proxy= в каждый запрос; коннектор не нужен.
        # Для SOCKS5 коннектор несёт весь routing — proxy= в запросе не используется.
        self.proxy = self._get_http_proxy(proxy_url)

        self._session = aiohttp.ClientSession(
            connector=connector or aiohttp.TCPConnector(),
            json_serialize=self._json_serialize,
        )
        return self._session

    async def _close_current_session(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None  # type: ignore[assignment]

    async def _rotate_proxy(self) -> None:
        """Закрывает текущую сессию и переключается на следующий прокси."""
        old_url = self._current_proxy_url
        await self._close_current_session()
        self._proxy_index = (self._proxy_index + 1) % len(self._proxies)
        new_url = self._current_proxy_url
        logger.warning(
            "Прокси недоступен: %s — переключаемся на %s", old_url, new_url
        )

    # ------------------------------------------------------------------ #
    #  Core override                                                        #
    # ------------------------------------------------------------------ #

    async def make_request(
        self,
        bot: "Bot",
        method: "TelegramMethod[TelegramType]",
        timeout: Optional[aiohttp.ClientTimeout] = None,
    ) -> "TelegramType":
        max_attempts = min(len(self._proxies), 3)
        last_error: Exception = RuntimeError("Пул прокси пуст")

        for attempt in range(1, max_attempts + 1):
            try:
                return await super().make_request(bot, method, timeout)
            except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                last_error = exc
                logger.warning(
                    "Попытка %d/%d через %s не удалась (%s: %s). %s",
                    attempt,
                    max_attempts,
                    self._current_proxy_url,
                    type(exc).__name__,
                    exc,
                    "Ротируем прокси..." if attempt < max_attempts else "Попытки исчерпаны.",
                )
                if attempt < max_attempts:
                    await self._rotate_proxy()

        raise last_error
