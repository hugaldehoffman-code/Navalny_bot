from aiogram import Router, F
from aiogram.types import CallbackQuery
# Глобальные модули в корне импортируются обычным образом
from config import BUTTON_PROMPTS, LATEST_NEWS_CACHE, create_main_keyboard
from database import clear_context
# ИСПРАВЛЕНО: импортируем из папки services
from services.ai import process_ai_reply

router = Router()

@router.callback_query(F.data == "chat")
async def chat_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("💬 Напиши мне в чат! Если хочешь голосовой ответ, начни сообщение со слова АУДИО")

@router.callback_query(F.data == "joke")
async def joke_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("⚡️ Оторвать тромб...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["joke"], trigger_text="")

@router.callback_query(F.data == "news")
async def news_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("📰 Изучаю свежую прессу и готовлю разбор...")
    
    current_news = LATEST_NEWS_CACHE["text"]
    trigger_text = f"Вот главные новости на сегодня:\n{current_news}\n\nРазбери их по пунктам."
    
    await process_ai_reply(
        callback.message, 
        system_addition=BUTTON_PROMPTS["news"], 
        trigger_text=trigger_text,
        max_tokens=1000  
    )

@router.callback_query(F.data == "leaks")
async def leaks_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🕵️‍♂️ Перехватываю трафик...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["leaks"], trigger_text="")

@router.callback_query(F.data == "merch")
async def merch_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🛍 Генерирую анонс...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["merch"], trigger_text="")

@router.callback_query(F.data == "food")
async def food_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🥖 Оцениваю меню...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["food"], trigger_text="")

@router.callback_query(F.data == "complaint")
async def complaint_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🏛 Отправляю запрос...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["complaint"], trigger_text="")

@router.callback_query(F.data == "reset")
async def reset_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🔄 Память сброшена!")
    await callback.message.answer("Выбери, что ты хочешь сделать:", reply_markup=create_main_keyboard())