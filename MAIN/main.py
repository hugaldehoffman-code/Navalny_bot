import asyncio
import re
from aiogram import F
from aiogram.types import Message, ErrorEvent

# Импорт конфигурации, бота и баз данных
from config import bot, dp, logger, BOT_INFO, ERROR_FALLBACK_TEXT, BUTTON_PROMPTS
from database import init_db, save_context

# Middleware и сервисы
from middlewares.throttling import ThrottlingMiddleware
from middlewares.admin_control import AdminControlMiddleware
from services.news import update_news_task
from services.ai import process_ai_reply

# Роутеры из внутренней папки handlers
from handlers import commands, callbacks, media, inline


# Глобальный обработчик ошибок
@dp.errors()
async def global_errors_handler(event: ErrorEvent):
    logger.error(f"Критическое исключение: {event.exception}", exc_info=True)
    update = event.update
    if update.message:
        await update.message.answer(ERROR_FALLBACK_TEXT)


# Приветствие при добавлении бота в чаты
@dp.message(F.new_chat_members)
async def on_bot_added(message: Message):
    for user in message.new_chat_members:
        if user.id == BOT_INFO["id"]:
            await message.answer(
                "Привет! Я — Цифровой Навальный. Чтобы услышать меня, пишите в начале сообщения слово <b>АУДИО</b>.", 
                parse_mode="HTML"
            )
            break


# Обработчик текстовых сообщений
@dp.message(F.text, ~F.text.startswith("/"))
async def text_handler(message: Message):
    # Игнорируем сообщения от других ботов
    if message.from_user and message.from_user.is_bot:
        return

    text = message.text
    is_private = message.chat.type == "private"
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_INFO["id"]
    
    bot_username = BOT_INFO["username"]
    is_mention = False
    if bot_username:
        is_mention = f"@{bot_username}".lower() in text.lower()
        
    is_command_msg = text.lower().startswith(("/message", "/msg"))
    
    # Если это не приват, не ответ на сообщение бота, не упоминание и не спец-команда — игнорируем
    if not (is_private or is_reply or is_mention or is_command_msg):
        return

    # Очищаем текст от префиксов команд и упоминаний
    if is_command_msg:
        text = re.sub(r"(?i)^/(message|msg)(?:@[^\s]+)?\s*", "", text).strip()
    elif is_mention and bot_username:
        text = re.sub(rf"(?i)@{bot_username}\s*", "", text).strip()
        
    # Если текст остался пустым (например, просто тегнули бота)
    if not text and not is_reply:
        if not is_private:
            return 
        text = "Что?"

    # Отправляем в AI core
    await process_ai_reply(message, system_addition=BUTTON_PROMPTS["chat"], trigger_text=text)


# Главная функция запуска
async def main():
    await init_db()
    
    bot_me = await bot.get_me()
    BOT_INFO["id"] = bot_me.id
    BOT_INFO["username"] = bot_me.username
    logger.info(f"Запущен бот: @{BOT_INFO['username']}")
    
    # Регистрация Middlewares (ИСПРАВЛЕНО)
    dp.message.middleware(AdminControlMiddleware())
    dp.callback_query.middleware(AdminControlMiddleware())
    
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())  # <-- Тут была ошибка
    
    # Подключение роутеров
    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(media.router)
    dp.include_router(inline.router)
    
    # Запуск фоновой задачи обновления новостей
    asyncio.create_task(update_news_task())
    
    # Старт поллинга
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())