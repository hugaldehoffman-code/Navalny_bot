import json
import aiosqlite
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional
from config import DB_NAME, logger


async def init_db() -> None:
    """Инициализация всех таблиц БД."""
    async with aiosqlite.connect(DB_NAME) as db:
        # --- Таблица контекстов диалогов (существующая) ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_contexts (
                user_id INTEGER PRIMARY KEY,
                context TEXT
            )
        """)
        # --- Таблица пользователей (тарифы / лимиты) ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT DEFAULT NULL,
                tariff_name TEXT DEFAULT 'FREE',
                premium_until TEXT DEFAULT NULL,
                daily_text_used  INTEGER DEFAULT 0,
                daily_media_used INTEGER DEFAULT 0,
                last_request_date TEXT DEFAULT NULL,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


# ═════════════════════════════════════════════
#  СУЩЕСТВУЮЩИЕ ФУНКЦИИ КОНТЕКСТА
# ═════════════════════════════════════════════

async def save_context(user_id: int, message: str, is_user: bool = True) -> None:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT context FROM user_contexts WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        context = json.loads(row[0]) if row and row[0] else []
        role = "user" if is_user else "assistant"
        context.append({"role": role, "content": message})
        if len(context) > 8:
            context = context[-8:]
        await db.execute(
            "INSERT OR REPLACE INTO user_contexts (user_id, context) VALUES (?, ?)",
            (user_id, json.dumps(context, ensure_ascii=False))
        )
        await db.commit()


async def get_context(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT context FROM user_contexts WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return json.loads(row[0]) if row and row[0] else []


async def clear_context(user_id: int) -> None:
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM user_contexts WHERE user_id = ?", (user_id,))
        await db.commit()


# ═════════════════════════════════════════════
#  НОВЫЕ ФУНКЦИИ: ТАРИФЫ / ЛИМИТЫ / ПОЛЬЗОВАТЕЛИ
# ═════════════════════════════════════════════

async def get_or_create_user(user_id: int, username: str = None) -> dict:
    """Получить пользователя из БД или создать новую запись (по умолчанию FREE)."""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row:
            # Обновляем username если он изменился
            if username and row["username"] != username:
                await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
                await db.commit()
            return dict(row)
        # Создаём нового пользователя
        await db.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(await cursor.fetchone())


async def check_and_reset_daily_limits(user_id: int) -> dict:
    """Сбросить дневные счётчики, если наступил новый день. Возвращает актуальную запись пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        today_str = str(date.today())
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return dict(await cursor.fetchone())

        last_date = row["last_request_date"]
        if last_date != today_str:
            await db.execute(
                "UPDATE users SET daily_text_used = 0, daily_media_used = 0, last_request_date = ? WHERE user_id = ?",
                (today_str, user_id)
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return dict(await cursor.fetchone())

        return dict(row)


async def update_tariff(user_id: int, tariff_name: str, days: int) -> None:
    """Начислить премиум-тариф на указанное количество дней."""
    premium_until = (datetime.now() + timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_NAME) as db:
        # Убедимся что пользователь существует
        cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        await db.execute(
            "UPDATE users SET tariff_name = ?, premium_until = ? WHERE user_id = ?",
            (tariff_name, premium_until, user_id)
        )
        await db.commit()
        logger.info(f"Пользователь {user_id} получил тариф {tariff_name} на {days} дней до {premium_until}")


async def expire_premium_if_needed(user_id: int) -> dict:
    """Сбросить тариф на FREE, если премиум истёк. Возвращает запись пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            return await get_or_create_user(user_id)

        tariff = row["tariff_name"]
        premium_until = row["premium_until"]
        if tariff != "FREE" and premium_until:
            try:
                until_dt = datetime.fromisoformat(premium_until)
                if datetime.now() > until_dt:
                    logger.info(f"Премиум истёк у пользователя {user_id}, откат на FREE")
                    await db.execute(
                        "UPDATE users SET tariff_name = 'FREE', premium_until = NULL WHERE user_id = ?",
                        (user_id,)
                    )
                    await db.commit()
                    cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                    return dict(await cursor.fetchone())
            except (ValueError, TypeError):
                logger.warning(f"Битая дата premium_until у пользователя {user_id}: {premium_until}")
                await db.execute(
                    "UPDATE users SET tariff_name = 'FREE', premium_until = NULL WHERE user_id = ?",
                    (user_id,)
                )
                await db.commit()
                cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                return dict(await cursor.fetchone())

        return dict(row)


async def increment_text_usage(user_id: int) -> None:
    """Инкрементировать счётчик текстовых запросов."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET daily_text_used = daily_text_used + 1 WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()


async def increment_media_usage(user_id: int) -> None:
    """Инкрементировать счётчик медиа-запросов."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET daily_media_used = daily_media_used + 1 WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()
