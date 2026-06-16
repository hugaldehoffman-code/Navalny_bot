"""
Middleware контроля дневных лимитов по тарифам.

Логика работы:
1. Пропускает VIP_USERS (админ-байпасс).
2. Сервисные команды (/help, /start, /actions, /control, /sud) — пропускает без учёта.
3. CallbackQuery — пропускает без учёта (UI-навигация).
4. Создаёт/подтягивает пользователя из БД, сбрасывает лимиты при смене дня.
5. Проверяет, не истёк ли премиум (откат на FREE).
6. Определяет тип запроса (текст / медиа).
7. Сверяет счётчик с дневным лимитом тарифа.
8. Если лимит исчерпан — отправляет сообщение с предложением купить VIP и останавливает обработку.
9. Если лимит ОК — инкрементирует счётчик и передаёт объект пользователя в data["user_record"].
"""
import datetime

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import VIP_USERS, BOT_INFO, logger

# Временный 1.5× бонус к лимитам FREE после аварийного простоя (до 24 июня 2026)
_PROMO_UNTIL = datetime.date(2026, 6, 24)
from database import (
    get_or_create_user,
    check_and_reset_daily_limits,
    expire_premium_if_needed,
    increment_text_usage,
    increment_media_usage,
)
from tariffs import TARIFFS, STARS_PRICES, get_tariff

# Сервисные команды, которые не расходуют лимит
SERVICE_COMMANDS = {"/start", "/help", "/actions", "/control", "/sud", "/pay", "/buy", "/tariff", "/game"}


class LimitsMiddleware(BaseMiddleware):
    """
    Middleware проверки дневных лимитов по тарифу пользователя.

    Устанавливается на message и callback_query.
    Результат проверки записывается в data["user_record"] для использования в хэндлерах.
    """

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Админ-байпасс: VIP_USERS не подчиняются лимитам
        if user.id in VIP_USERS:
            return await handler(event, data)

        # Callback-запросы (кнопки) — не считаются за лимит
        if isinstance(event, CallbackQuery):
            return await handler(event, data)

        # Сервисные команды — не расходуют лимит
        if isinstance(event, Message) and event.text:
            cmd = event.text.strip().split()[0].lower()
            if cmd in SERVICE_COMMANDS:
                return await handler(event, data)

        # Определяем, должен ли запрос считаться (только прямые обращения к боту)
        if isinstance(event, Message):
            if not self._should_count(event):
                return await handler(event, data)

        # ═══════════ ОСНОВНАЯ ЛОГИКА ПРОВЕРКИ ═══════════
        user_id = user.id
        username = user.username or user.full_name or str(user_id)

        # 1. Создать или получить пользователя
        user_record = await get_or_create_user(user_id, username)

        # 2. Сбросить дневные счётчики если новый день
        user_record = await check_and_reset_daily_limits(user_id)

        # 3. Проверить, не истёк ли премиум
        user_record = await expire_premium_if_needed(user_id)

        tariff_name = user_record["tariff_name"]
        tariff = get_tariff(tariff_name)

        # Временный промо-множитель 1.5× для FREE до _PROMO_UNTIL
        promo_active = tariff_name == "FREE" and datetime.date.today() < _PROMO_UNTIL
        promo_factor = 1.5 if promo_active else 1.0

        def _effective_limit(base: int) -> int:
            return int(base * promo_factor) if base != -1 else -1

        # 4. Определить тип запроса
        request_type = self._detect_request_type(event)

        # 5. Проверить лимит
        if request_type == "text":
            eff_limit = _effective_limit(tariff.daily_text_limit)
            if eff_limit != -1 and user_record["daily_text_used"] >= eff_limit:
                await self._send_limit_exceeded(event, tariff_name, "text", eff_limit)
                return  # прерываем обработку
            await increment_text_usage(user_id)
            user_record["daily_text_used"] += 1

        elif request_type == "media":
            eff_limit = _effective_limit(tariff.daily_media_limit)
            if eff_limit != -1 and user_record["daily_media_used"] >= eff_limit:
                await self._send_limit_exceeded(event, tariff_name, "media", eff_limit)
                return  # прерываем обработку
            await increment_media_usage(user_id)
            user_record["daily_media_used"] += 1

        # 6. Передать user_record в хэндлер
        data["user_record"] = user_record
        data["user_tariff"] = tariff_name

        return await handler(event, data)

    def _should_count(self, event: Message) -> bool:
        """
        Считаем запрос только если:
        - Личный чат
        - Реплай на сообщение бота
        - Упоминание @username бота
        - Сообщение содержит триггер-имя (Навальный, etc.)
        """
        if event.chat and event.chat.type == "private":
            return True

        if event.reply_to_message and event.reply_to_message.from_user.id == BOT_INFO["id"]:
            return True

        text = (event.text or event.caption or "").lower()
        bot_username = BOT_INFO.get("username", "")
        if bot_username and f"@{bot_username}".lower() in text:
            return True

        import re
        name_pattern = r"\b(навальн[а-яё]*|алексей[а-яё]*|лёш[а-яё]+|леш[а-яё]+|лёх[а-яё]+|лех[а-яё]+)\b"
        if re.search(name_pattern, text):
            return True

        return False

    def _detect_request_type(self, event: Message) -> str:
        """Определить тип запроса: text или media."""
        if event.photo or event.voice or event.audio or event.document or event.video or event.video_note:
            return "media"
        return "text"

    async def _send_limit_exceeded(
        self, event: Message, current_tariff: str, limit_type: str, limit_value: int
    ) -> None:
        """Отправить сообщение о превышении лимита с предложением купить VIP."""
        limit_label = "Текстовых запросов" if limit_type == "text" else "Медиа-запросов"

        builder = InlineKeyboardBuilder()
        builder.button(text="⭐ VIP — 99 ⭐ (30 дней)", callback_data="buy_vip_lite_30")
        builder.button(text="📋 Подробнее о тарифах", callback_data="tariff_info")
        builder.adjust(1)

        msg = (
            f"{limit_label} на сегодня исчерпаны ({limit_value} из {limit_value}).\n\n"
            f"Твой тариф: <b>{TARIFFS[current_tariff].name_ru}</b>\n\n"
            f"Чтобы продолжить прямо сейчас, апгрейднись до VIP:\n"
            f"⭐ <b>VIP</b> — 99 ⭐ / 30 дней (безлимит на всё + анализ документов)\n\n"
            f"1 ⭐ ≈ 1.5–2 ₽. Принимаются Telegram Stars."
        )

        if event.chat and event.chat.type == "private":
            await event.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await event.reply(msg, reply_markup=builder.as_markup(), parse_mode="HTML")
