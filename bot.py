import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession  # <-- Важный импорт!
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import BasicAuth

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

TOKEN = "7806059615:AAFhBelfwpE92GK3nHmW1graHQImA1Ep65w"

# 1. Оставляем только чистый IP и ПОРТ
PROXY_URL = "http://77.83.184.109:8000" 

# 2. Логин и пароль выносим в BasicAuth
PROXY_AUTH = BasicAuth(login="wgmGhd", password="FFhgh5")

# 3. Создаем сессию ИМЕННО СЮДА передаем прокси
session = AiohttpSession(
    proxy=(PROXY_URL, PROXY_AUTH)
)

# 4. Передаем эту сессию в бота
bot = Bot(
    token=TOKEN,
    session=session,  # <-- Подключаем настроенную сессию
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer(f"Здорово, {html.bold(message.from_user.full_name)}! Я работаю через прокси.")

@dp.message()
async def echo_handler(message: Message) -> None:
    try:
        await message.send_copy(chat_id=message.chat.id)
    except TypeError:
        await message.answer("Nice try, но это я скопировать не могу.")

async def main() -> None:
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())