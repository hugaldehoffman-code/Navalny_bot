"""Одноразовый скрипт рассылки — апология за простой + промо-лимиты."""
import asyncio
import aiosqlite
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

DB_NAME = "bot_database.db"

MSG = (
    "⚡️ <b>Важное объявление</b>\n\n"
    "Друзья, последние 10 дней бот молчал — не потому что снова арестовали, а из-за технического сбоя: "
    "протухли настройки соединения, и связь с Telegram пропала. Проблема устранена, всё работает.\n\n"
    "В качестве извинения — на ближайшую неделю (до 24 июня) лимиты для всех бесплатных пользователей "
    "увеличены в 1.5 раза: <b>75 текстовых и 10 медиа</b> запросов в день вместо обычных 50/7.\n\n"
    "Если есть вопросы, баги или идеи — пишите в поддержку, там же можно предложить что добавить в бота:\n"
    "👉 https://t.me/anonaskbot?start=brq1glqmc2zh3v0\n\n"
    "Приношу извинения за вынужденный перерыв. Продолжаем."
)


async def main():
    import os
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан")

    bot = Bot(token=token)

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()

    user_ids = [r["user_id"] for r in rows]
    print(f"Рассылаем {len(user_ids)} пользователям...")

    ok, fail = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, MSG, parse_mode="HTML", disable_web_page_preview=True)
            ok += 1
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            print(f"  skip {uid}: {e}")
            fail += 1
        await asyncio.sleep(0.05)  # ~20 msg/s, well within limits

    print(f"Готово: {ok} доставлено, {fail} пропущено.")
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
