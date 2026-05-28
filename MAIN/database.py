import json
import aiosqlite
from typing import List, Dict
from config import DB_NAME

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_contexts (
                user_id INTEGER PRIMARY KEY,
                context TEXT
            )
        """)
        await db.commit()

async def save_context(user_id: int, message: str, is_user: bool = True):
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

async def clear_context(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM user_contexts WHERE user_id = ?", (user_id,))
        await db.commit()