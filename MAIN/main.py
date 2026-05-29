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
import random  # <-- Не забудь импортировать random на самом верху main.py
from collections import defaultdict

# Структура для каждого чата: { chat_id: {"current": 0, "target": 142} }
group_message_counters = defaultdict(lambda: {
    "current": 0, 
    "target": random.randint(100, 200)  # Первое случайное число в диапазоне около 150
})


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


@dp.message(F.text, ~F.text.startswith("/"))
async def text_handler(message: Message):
    # Игнорируем сообщения от других ботов
    if message.from_user and message.from_user.is_bot:
        return

    text = message.text
    chat_id = message.chat.id
    is_private = message.chat.type == "private"
    
    # 1. Проверяем, является ли сообщение ответом (реплаем) на сообщение этого бота
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_INFO["id"]
    
    # 2. Проверяем упоминание через юзернейм бота (@username_bot)
    bot_username = BOT_INFO["username"]
    is_mention = False
    if bot_username:
        is_mention = f"@{bot_username}".lower() in text.lower()
        
    # 3. Триггер на любые формы имени и фамилии (RegEx)
    # Ловит: Навальный, Навального, Алексея, Леша, Лехе, Навальным и т.д.
    name_pattern = r"\b(навальн[а-яё]*|алексей[а-яё]*|лёш[а-яё]+|леш[а-яё]+|лёх[а-яё]+|лех[а-яё]+)\b"
    is_keyword_trigger = bool(re.search(name_pattern, text.lower()))
    
    # 4. Проверяем альтернативные команды текстового общения
    is_command_msg = text.lower().startswith(("/message", "/msg"))
    
    # Железные условия, при которых бот обязан среагировать
    must_reply = is_private or is_reply or is_mention or is_command_msg or is_keyword_trigger
    
    # 5. Динамический рандом ("как сглыпа") для групп и супергрупп
    is_random_lucky = False
    if not must_reply and message.chat.type in ("group", "supergroup"):
        # Добавляем 1 сообщение в счетчик этой группы
        group_message_counters[chat_id]["current"] += 1
        
        # Если достигли секретной случайной цели
        if group_message_counters[chat_id]["current"] >= group_message_counters[chat_id]["target"]:
            is_random_lucky = True
            
            # Генерируем новую цель на следующий круг (от 100 до 200, в среднем 150)
            new_target = random.randint(100, 200)
            logger.info(
                f"Рандомный триггер сработал в чате {chat_id} на {group_message_counters[chat_id]['current']}-м сообщении. "
                f"Следующая цель установлена: через {new_target} собщ."
            )
            
            # Сбрасываем текущий шаг и сохраняем новую цель
            group_message_counters[chat_id]["current"] = 0
            group_message_counters[chat_id]["target"] = new_target

    # Если ни один из триггеров не сработал — игнорируем сообщение
    if not (must_reply or is_random_lucky):
        return

    # Очищаем текст от префиксов команд и юзернеймов (чтобы ИИ получал чистый контекст)
    if is_command_msg:
        text = re.sub(r"(?i)^/(message|msg)(?:@[^\s]+)?\s*", "", text).strip()
    elif is_mention and bot_username:
        text = re.sub(rf"(?i)@{bot_username}\s*", "", text).strip()
        
    # Обработка ситуаций, когда текст остался пустым после очистки
    if not text and not is_reply:
        if not is_private:
            # Если бота просто тегнули в группе без текста, ИИ ответит на дефолтное приветствие
            text = "Привет" 
        else:
            text = "Что?"

    # Отправляем сообщение в сервис обработки ИИ
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