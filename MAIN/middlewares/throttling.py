import time
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from config import VIP_USERS, USER_MESSAGE_LOGS, LIMIT_WINDOW, LIMIT_MESSAGES, BOT_INFO

class ThrottlingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if not user or user.id in VIP_USERS:
            return await handler(event, data)

        user_id = user.id
        if isinstance(event, Message):
            is_private = event.chat.type == "private"
            text = event.text or event.caption or "" if hasattr(event, 'text') else ""
            
            is_reply = event.reply_to_message and event.reply_to_message.from_user.id == BOT_INFO["id"]
            is_mention = BOT_INFO["username"] and f"@{BOT_INFO['username']}".lower() in text.lower()
            is_command = text.startswith("/")
            
            if not (is_private or is_reply or is_mention or is_command):
                return await handler(event, data)

        current_time = time.time()
        user_timestamps = USER_MESSAGE_LOGS[user_id]

        while user_timestamps and user_timestamps[0] < current_time - LIMIT_WINDOW:
            user_timestamps.pop(0)

        if len(user_timestamps) >= LIMIT_MESSAGES:
            wait_time = int(LIMIT_WINDOW - (current_time - user_timestamps[0]))
            if isinstance(event, Message):
                await event.reply(f"Камон, чувак, притормози. Подожди еще {wait_time} сек!")
            elif isinstance(event, CallbackQuery):
                await event.answer(f"Лимит! Подожди {wait_time} сек.", show_alert=True)
            return

        user_timestamps.append(current_time)
        return await handler(event, data)