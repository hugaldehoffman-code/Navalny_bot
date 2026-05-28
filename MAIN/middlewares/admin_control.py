import time
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from config import BOT_STATE

class AdminControlMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        # Проверяем, является ли входящее событие командой управления от админа
        is_control_command = False
        if isinstance(event, Message) and event.text:
            if event.text.strip().startswith("/control"):
                is_control_command = True

        current_time = time.time()

        # Если бот на паузе ИЛИ текущее время меньше времени окончания мута
        if BOT_STATE["is_paused"] or current_time < BOT_STATE["mute_until"]:
            # ИСКЛЮЧЕНИЕ: Если это команда управления — пропускаем её, чтобы админ мог снять паузу
            if is_control_command:
                return await handler(event, data)
            
            # Для всех остальных случаев — СИЛЕНТ-ДРОП (просто прерываем выполнение)
            # Telegram засчитает, что бот принял сообщение, и стирает его со своих серверов
            if isinstance(event, CallbackQuery):
                await event.answer("Бот временно отключен администратором.", show_alert=False)
            return  # Важно: НЕ вызываем handler(event, data), сообщение испаряется

        # Если ограничений нет — бот работает в штатном режиме
        return await handler(event, data)