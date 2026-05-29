import asyncio
import re
import random
from collections import defaultdict
from aiogram import F
from aiogram.types import Message, ErrorEvent

from config import bot, dp, logger, BOT_INFO, ERROR_FALLBACK_TEXT, BUTTON_PROMPTS
from database import init_db, save_context

from middlewares.throttling import ThrottlingMiddleware
from middlewares.admin_control import AdminControlMiddleware
from middlewares.limits_middleware import LimitsMiddleware
from services.news import update_news_task

from services.ai import process_ai_reply, analyze_image_vision

from handlers import commands, callbacks, media, inline


group_message_counters = defaultdict(lambda: {
    "current": 0,
    "target": random.randint(100, 200)
})


@dp.errors()
async def global_errors_handler(event: ErrorEvent):
    logger.error(f"Критическое исключение: {event.exception}", exc_info=True)
    update = event.update
    if update.message:
        await update.message.answer(ERROR_FALLBACK_TEXT)


@dp.message(F.new_chat_members)
async def on_bot_added(message: Message):
    for user in message.new_chat_members:
        if user.id == BOT_INFO["id"]:
            await message.answer(
                "Привет! Я — Цифровой Навальный. Чтобы услышать меня, пишите в начале сообщения слово <b>АУДИО</b>.",
                parse_mode="HTML"
            )
            break


def should_bot_respond(message: Message) -> tuple[bool, str]:
    text = message.text or message.caption or ""
    chat_id = message.chat.id
    is_private = message.chat.type == "private"

    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_INFO["id"]

    bot_username = BOT_INFO["username"]
    is_mention = False
    if bot_username:
        is_mention = f"@{bot_username}".lower() in text.lower()

    name_pattern = r"\b(навальн[а-яё]*|алексей[а-яё]*|лёш[а-яё]+|леш[а-яё]+|лёх[а-яё]+|лех[а-яё]+)\b"
    is_keyword_trigger = bool(re.search(name_pattern, text.lower()))

    is_command_msg = text.lower().startswith(("/message", "/msg"))

    must_reply = is_private or is_reply or is_mention or is_command_msg or is_keyword_trigger

    is_random_lucky = False
    if not must_reply and message.chat.type in ("group", "supergroup"):
        group_message_counters[chat_id]["current"] += 1
        if group_message_counters[chat_id]["current"] >= group_message_counters[chat_id]["target"]:
            is_random_lucky = True
            new_target = random.randint(100, 200)
            logger.info(f"Рандом сработал в чате {chat_id}. Следующая цель: через {new_target} собщ.")
            group_message_counters[chat_id]["current"] = 0
            group_message_counters[chat_id]["target"] = new_target

    if not (must_reply or is_random_lucky):
        return False, text

    if is_command_msg:
        text = re.sub(r"(?i)^/(message|msg)(?:@[^\s]+)?\s*", "", text).strip()
    elif is_mention and bot_username:
        text = re.sub(rf"(?i)@{bot_username}\s*", "", text).strip()

    if not text and not is_reply:
        text = "Привет" if not is_private else "Что?"

    return True, text


@dp.message(F.text, ~F.text.startswith("/"))
async def text_handler(message: Message):
    if message.from_user and message.from_user.is_bot:
        return

    should_respond, clean_text = should_bot_respond(message)
    if not should_respond:
        return

    await process_ai_reply(message, system_addition=BUTTON_PROMPTS["chat"], trigger_text=clean_text)


@dp.message(F.photo)
async def photo_handler(message: Message):
    if message.from_user and message.from_user.is_bot:
        return

    should_respond, clean_text = should_bot_respond(message)
    if not should_respond:
        return

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    image_bytes = downloaded_file.read()

    image_description = await analyze_image_vision(image_bytes)

    user_content = f"[Фото: {image_description}]"
    if message.caption:
        user_content += f" Подпись: {clean_text}"

    await process_ai_reply(message, system_addition=BUTTON_PROMPTS["vision_comment"], trigger_text=user_content)


async def main():
    await init_db()

    bot_me = await bot.get_me()
    BOT_INFO["id"] = bot_me.id
    BOT_INFO["username"] = bot_me.username
    logger.info(f"Запущен бот: @{BOT_INFO['username']}")

    dp.message.middleware(AdminControlMiddleware())
    dp.callback_query.middleware(AdminControlMiddleware())

    dp.message.middleware(LimitsMiddleware())
    dp.callback_query.middleware(LimitsMiddleware())

    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())

    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(media.router)
    dp.include_router(inline.router)

    asyncio.create_task(update_news_task())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
