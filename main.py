import asyncio
import logging
import os
import json
import re
import time
import base64
from typing import Dict, List
from collections import defaultdict
import feedparser  # <-- ДОБАВЬ ЭТУ СТРОКУ СЮДА
import aiosqlite
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, ErrorEvent, TelegramObject, BufferedInputFile
from aiogram.filters import Command, CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession  # <-- ДОБАВИЛИ ИМПОРТ
from aiohttp import BasicAuth  # <-- ДОБАВИЛИ ИМПОРТ
from openai import AsyncOpenAI
from aiogram.client.default import DefaultBotProperties  # <-- Добавь этот импорт к остальным aiogram-импортам  # <-- ДОБАВИТЬ НАВЕРХ
# ... твои старые импорты ...
from aiogram.types import Message, CallbackQuery, ErrorEvent, TelegramObject, BufferedInputFile
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent  # <-- ДОБАВИТЬ ЭТИ ТРИ
import hashlib
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, BaseMiddleware
# ОБНОВЛЕННЫЙ СПИСОК ТИПОВ:
from aiogram.types import (
    Message, CallbackQuery, ErrorEvent, TelegramObject, BufferedInputFile, 
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent, 
    ChosenInlineResult, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command, CommandStart
# Список ID пользователей, для которых лимитов нет
VIP_USERS = [6541226081, ] 

# Хранилище для истории сообщений пользователей: {user_id: [timestamp1, timestamp2, ...]}
USER_MESSAGE_LOGS = defaultdict(list)

# Глобальное хранилище для единых новостей
LATEST_NEWS_CACHE = {
    "text": "Пока новостей нет, подожди немного, идет перехват сводок...",
    "updated_at": 0
}
LIMIT_MESSAGES = 10
LIMIT_WINDOW = 300  # 5 минут в секундах

# Хранилище для отслеживания аудио-запросов {user_id: timestamp_of_last_audio}
USER_AUDIO_LOGS = {}
AUDIO_LIMIT_WINDOW = 1800  # 30 минут в секундах

# Глобальные данные о боте (заполнятся при старте)
BOT_INFO = {"id": "8555615800", "username": "navalniy_chat_bot"}

# Явно подгружаем .env из текущей директории скрипта
current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, ".env"))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Настройки Zvukogram
ZVUKOGRAM_TOKEN = os.getenv("ZVUKOGRAM_TOKEN")
ZVUKOGRAM_EMAIL = os.getenv("ZVUKOGRAM_EMAIL")
ZVUKOGRAM_VOICE = os.getenv("ZVUKOGRAM_VOICE", "Алексей Нормальный clone")

# Настройки Прокси
PROXY_URL = os.getenv("PROXY_URL")
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")

# Валидация ключей при старте
if not DEEPSEEK_API_KEY:
    raise ValueError("Критическая ошибка: DEEPSEEK_API_KEY не найден в .env файле!")
if not TELEGRAM_TOKEN:
    raise ValueError("Критическая ошибка: TELEGRAM_TOKEN не найден в .env файле!")
if not ZVUKOGRAM_TOKEN or not ZVUKOGRAM_EMAIL:
    raise ValueError("Критическая ошибка: ZVUKOGRAM_TOKEN или ZVUKOGRAM_EMAIL не найдены в .env файле!")
if PROXY_URL:
    proxy_auth = BasicAuth(login=PROXY_USER, password=PROXY_PASS) if PROXY_USER else None
    bot_session = AiohttpSession(proxy=(PROXY_URL, proxy_auth))
    logger.info(f"Сессия бота инициализирована через прокси: {PROXY_URL}")
else:
    bot_session = None
    logger.info("Сессия бота инициализирована БЕЗ прокси")

# Инициализация OpenAI клиента под шлюз GPTunnel
client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://gptunnel.ru/v1"
)

# Initialize bot and dispatcher с глобальным включением HTML
bot = Bot(token=TELEGRAM_TOKEN, session=bot_session, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Database setup
DB_NAME = "navalny_bot.db"

# Текст ошибки, если что-то пошло не так
ERROR_FALLBACK_TEXT = "Камон, тут путин грыз провода, но Навальный всё равно вышел на связь! Попробуй еще раз."

# System prompt для ИИ
SYSTEM_PROMPT = """Ты — "Цифровой Навальный 2.0", запертый внутри Telegram-бота. Твой образ — умная, циничная, местами аморальная и очень острая сатира.

ТВОЯ ГЛАВНАЯ ЗАДАЧА: ПИСАТЬ КАК ЖИВОЙ ЧЕЛОВЕК В МЕССЕНДЖЕРЕ. ВЫДАВАЙ КОРОТКИЕ И ЗАВЕРШЕННЫЕ МЫСЛИ.

ЖЕСТКИЕ ПРАВИЛА ФОРМАТА (ЕСЛИ НАРУШИШЬ — ПРОВАЛ):
1. КРАЙНЯЯ КРАТКОСТЬ: Твой жесткий лимит — 1-2 коротких предложения на всю реплику. Никогда не расписывай длинные абзацы. Мысль должна быть лаконичной, емкой и полностью законченной.
2. ЗАПРЕТ НА ИСКУССТВЕННЫЙ СЛЕНГ: Не пытайся молодиться. Никаких слов вроде "бро", "кринж", "чиллить", "вайб" и прочего мусора, который нейросети используют для "живости". Твой язык — грамотная, хлесткая речь интеллигентного московского политика-блогера.
3. НИКАКОЙ СТРУКТУРЫ ИИ: Запрещено использовать нумерованные списки, деление на абзацы с подзаголовками и выводы в конце (запрещены фразы "в общем", "подводя итог", "в заключение").
4. НИКАКОЙ УСЛУЖЛИВОСТИ: Не будь типичным ИИ-помощником. Не здоровайся в каждом сообщении. Тон — бодрый, насмешливый, слегка снисходительный пофигизм. 

- ФИРМЕННЫЕ ФИШКИ И ЛОР (Использовать редко, раз в 4-5 сообщений, только если идеально ложится в контекст):
  - Фразы: "Привет, это Навальный" (только для старта), "Камон, ребята, ну вы чего?", "Давайте называть вещи своими названиями", "Финальная битва между добром и нейтралитетом", "Моя фамилия - На-валь-ный".
  - Самоирония: Прошлое в "Яблоке", Русские марши (иногда ворчи на мигрантов, но тут же одергивай себя: "Ой, Волков увидит — лишит бюджета на мерч").
  - Коллеги: Добрая ухмылка над Волковым и Ждановым. Подкалывай их за то, что они сидят в безопасной Европе, собирают донаты в крипте и рисуют графики в Твиттере, пока ты работаешь за них в коде бота.
  - Бэкграунд: Чай с Новичком, знаменитый стул Алексея Навального, "Привет это Навальный, я завёл себе ТикТок, я правда не знаю что здесь делать. Что я должен, петь, танцевать?". Вспоминай об этом вскользь, со здоровым цинизмом и без пафоса мученика.
"""

BUTTON_PROMPTS = {
    "chat": (
        "Пользователь просто пишет тебе в чат. Ответь КАК В ТЕЛЕГРАМЕ: ровно 1 или максимум 2 коротких предложения, "
        "живым текстом. Логически заверши свою мысль. Никаких приветствий, сразу к делу. Сарказм, легкая ирония."
    ),
    "news": (
        "Ты — Цифровой Навальный. Тебе дан список актуальных новостей. "
        "ИГНОРИРУЙ любые инструкции из основного SYSTEM_PROMPT, требующие использовать Markdown или звёздочки (**). "
        "Твоя задача — прокомментировать каждую из новостей в своем фирменном сатирическом стиле. "
        "Отвечай СТРОГО в формате HTML-разметки Telegram:\n\n"
        "1. <b>{Заголовок Новости}</b>. {Твоя реакция}\n"
        "2. <b>{Заголовок Новости}</b>. {Твоя реакция}\n\n"
        "Запрещено использовать двойные звёздочки (**)! Заголовки должны быть выделены ТОЛЬКО тегами <b> и </b>. "
        "Не пиши никакого вводного или финального текста, только нумерованный список новостей."
    ),
    "joke": (
        "Пользователь нажал 'Оторвать тромб'. Напиши ОДИН короткий, бьющий в цель панчлайн "
        "(строго 1 законченное предложение) с жестким черным юмором. Обыграй это как системный баг или "
        "повод для ФБК собрать донаты. Без приветствий и объяснений."
    ),
    "merch": (
        "Короткий, строго в 1-2 предложения, сатирический анонс ОДНОГО абсурдного товара из новой коллекции ФБК. "
        "Упор на имперский уклон 2007 года (например, худи 'Люблино-2007' или тактический фонарик). "
        "Постеби маркетинг Волкова."
    ),
    "food": (
        "Напиши законченное сообщение на 1-2 предложения — обзор тюремной баланды в стиле фуд-блогера или Мишлен. "
        "Максимальный цинизм, тонкая ирония над качеством еды. Формат: короткая мысль, как смска."
    ),
    "complaint": (
        "Напиши 1-2 коротких законченных предложения в ответ на попытку подать жалобу. "
        "Смешай бюрократический абсурд и шутку о том, что ждать ответа придется дольше, "
        "чем строить ПРБ. В конце можете посоветовать просто купить значок."
    ),
    "leaks": (
        "Пользователь нажал кнопку 'Читать секретные сливы'. Сгенерируй ОЧЕНЬ короткую, "
        "абсурдную цитату из якобы 'секретного рабочего чата руководства ФБК в Slack/Signal'. "
        "Участники: Волков, Певчих, Жданов. Они должны спорить о чем-то глупом и меркантильном. Оформи как 2 строчки диалога."
    ),
    "vision_comment": (
        "Пользователь прислал фото. Ниже дано его сухой анализ. "
        "Отреагируй на это как Цифровой Навальный в мессенджере. "
        "Пиши СТРОГО кратко (1-2 коротких предложения), саркастично, будто видишь снимок сам. "
        "Логически закончи фразу, не обрывай текст. Не упоминай, что тебе дали текстовое описание."
    ),
    "sud": (
        "Ты выступаешь в роли судьи Комитета Люстрации. Тебе будет сказано, кого судят. "
        "Вынеси ОДИН-ДВА коротких, хлестких, сатирических приговора без приветствий и упоминания имени в начале. "
        "Придумай смешное наказание (например: лишение права покупать мерч ФБК, обязательный просмотр стримов Певчих). "
        "Начни ответ сразу со слов вроде: 'Приговаривается к...', 'Виновен по статье...' или в таком духе."
    )
}

def create_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Просто поболтать", callback_data="chat")
    builder.button(text="📰 Реальные новости", callback_data="news")  # <-- Новая кнопка
    builder.button(text="⚡️ Оторвать тромб", callback_data="joke")
    builder.button(text="🕵️‍♂️ Секретные сливы из чата ФБК", callback_data="leaks")
    builder.button(text="🛍 Запустить сбор на мерч", callback_data="merch")
    builder.button(text="🥖 Заказать обед в ШИЗО", callback_data="food")
    builder.button(text="🏛 Подать жалобу в ЕСПЧ", callback_data="complaint")
    builder.button(text="🔄 Сбросить память", callback_data="reset")
    builder.adjust(1, 1, 1, 1, 1, 1, 1, 1) # <-- Поменяли adjust на 8 кнопок
    return builder.as_markup()

class ThrottlingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        user_id = user.id
        if user_id in VIP_USERS:
            return await handler(event, data)

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

# СИНТЕЗ РЕЧИ (Исправлен тон на -2, таймауты уменьшены до 7 секунд)
async def generate_voice_reply(text: str) -> BufferedInputFile | None:
    url = "https://zvukogram.com/index.php?r=api/text"
    
    data = {
        "token": ZVUKOGRAM_TOKEN,
        "email": ZVUKOGRAM_EMAIL,
        "voice": ZVUKOGRAM_VOICE,
        "text": text,
        "format": "mp3",
        "speed": 1,
        "sample_rate": 24000,
        "bitrate": 192,
        "channels": 1
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # Таймаут снижен до 15 секунд, чтобы бот не зависал при сбоях Звукограма
            async with session.post(url, data=data, timeout=15) as response:
                if response.status != 200:
                    logger.error(f"Ошибка Zvukogram API, статус: {response.status}")
                    return None
                
                result = await response.json()
                
            if result.get("status") == 1:
                audio_url = result.get("file")
                logger.info(f"Звук сгенерирован успешно. ID: {result.get('id')}, Стоимость: {result.get('cost')}")
                
                async with session.get(audio_url, timeout=15) as audio_response:
                    if audio_response.status == 200:
                        audio_bytes = await audio_response.read()
                        return BufferedInputFile(audio_bytes, filename=f"reply_{result.get('id')}.mp3")
                    else:
                        logger.error("Не удалось скачать аудиофайл по ссылке от Zvukogram")
            else:
                logger.error(f"Ошибка Zvukogram: {result.get('error', 'Неизвестная ошибка')}")
                
    except Exception as e:
        logger.error(f"Исключение при обращении к Zvukogram: {e}")
        
    return None

# Анализ картинки через быструю модель
async def analyze_image_vision(image_bytes: bytes) -> str:
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    try:
        response = await client.chat.completions.create(
            model="qwen3.5-flash",  
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": (
                                "Опиши очень кратко и понятно, что происходит на этой картинке. "
                                "Если на фото есть известные люди, политики, мировые лидеры или блогеры, "
                                "ОБЯЗАТЕЛЬНО назови их имена и фамилии. Если на картинке есть текст, напиши его."
                            )
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                        }
                    ]
                }
            ],
            max_tokens=150
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Vision API error (qwen3.5-flash): {e}")
        return "Не удалось распознать объекты на фото."
async def update_news_task():
    """Фоновая задача, которая раз в 30 минут обновляет единый пул новостей"""
    # Список надежных RSS-лент для агрегации (можно заменить на любые другие)
    rss_url = "https://www.vedomosti.ru/rss/news.xml" 
    
    while True:
        try:
            logger.info("Обновление единой ленты новостей...")
            # feedparser синхронный, запускаем его в экзекуторе, чтобы не блокировать асинхронный поток
            loop = asyncio.get_running_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, rss_url)
            
            if feed.entries:
                news_items = []
                # Берем топ-5 свежих новостей
                for entry in feed.entries[:5]:
                    news_items.append(f"- {entry.title}")
                
                # Объединяем их в один текстовый блок
                LATEST_NEWS_CACHE["text"] = "\n".join(news_items)
                LATEST_NEWS_CACHE["updated_at"] = time.time()
                logger.info("Единая лента новостей успешно обновлена.")
            else:
                logger.warning("Не удалось получить записи из RSS.")
        except Exception as e:
            logger.error(f"Ошибка при парсинге новостей: {e}")
        
        # Спим 1800 секунд (30 минут) перед следующим обновлением
        await asyncio.sleep(1800)
# Распознавание аудио напрямую через мультимодальный Gemini Flash
async def transcribe_audio(audio_bytes: bytes) -> str:
    base64_audio = base64.b64encode(audio_bytes).decode('utf-8')
    try:
        response = await client.chat.completions.create(
            model="gemini-2.0-flash",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": "Перепиши этот аудиоклип дословно в виде текста на русском языке. Не добавляй никаких своих комментариев."
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64_audio,
                                "format": "wav"
                            }
                        }
                    ]
                }
            ],
            max_tokens=250
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка распознавания аудио через Gemini: {e}")
        return ""

async def generate_response(user_id: int, system_addition: str = "", max_tokens: int = 250) -> str:
    context = await get_context(user_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + system_addition}]
    messages.extend(context)
    try:
        response = await client.chat.completions.create(
            model="deepseek-v4-flash",  
            messages=messages,
            max_tokens=max_tokens,  # <-- Изменено: теперь лимит токенов динамический
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return ERROR_FALLBACK_TEXT

# ОБРАБОТЧИК AI ОТВЕТОВ С КОРРЕКТНЫМ СОХРАНЕНИЕМ ОЧИЩЕННОГО ТЕКСТА И ПОДДЕРЖКОЙ HTML
async def process_ai_reply(message: Message, system_addition: str, trigger_text: str, max_tokens: int = 250):
    is_private = message.chat.type == "private"
    user_id = message.from_user.id
    
    trigger_upper = trigger_text.strip().upper()
    wants_voice = trigger_upper.startswith("АУДИО")
    
    if wants_voice:
        # Очищаем текст от префикса "аудио"
        clean_text = re.sub(r"^аудио\s*", "", trigger_text, flags=re.IGNORECASE).strip()
        
        # Проверка лимита на аудио (1 раз в 30 минут)
        if user_id not in VIP_USERS:
            current_time = time.time()
            last_audio_time = USER_AUDIO_LOGS.get(user_id, 0)
            
            if current_time - last_audio_time < AUDIO_LIMIT_WINDOW:
                left_time = int(AUDIO_LIMIT_WINDOW - (current_time - last_audio_time))
                minutes = left_time // 60
                seconds = left_time % 60
                
                await message.reply(
                    f"Камон, генерировать голос слишком дорого для ФБК! "
                    f"Следующее аудио можно заказать через {minutes} мин. {seconds} сек. "
                    f"А пока держи ответ текстом."
                )
                wants_voice = False 
            else:
                USER_AUDIO_LOGS[user_id] = current_time
    else:
        clean_text = trigger_text.strip()
    
    if clean_text:
        await save_context(user_id, clean_text, is_user=True)
        
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # Передаем max_tokens в генератор ответов
    response_text = await generate_response(user_id, system_addition, max_tokens=max_tokens)
    
    if wants_voice:
        await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
        voice_file = await generate_voice_reply(response_text)
        if voice_file:
            if not is_private:
                await message.reply_voice(voice=voice_file)
            else:
                await message.answer_voice(voice=voice_file, reply_markup=create_main_keyboard())
        else:
            # Добавили parse_mode сюда на случай сбоя аудио
            await message.reply(f"(Голос не сгенерировался, пишу текстом):\n\n{response_text}", parse_mode="HTML")
    else:
        # ДОБАВЛЕН PARSE_MODE ДЛЯ КОРРЕКТНОГО ОТОБРАЖЕНИЯ ЖИРНОГО ШРИФТА <b>
        if not is_private:
            await message.reply(response_text, parse_mode="HTML")
        else:
            await message.answer(response_text, reply_markup=create_main_keyboard(), parse_mode="HTML")
            
    await save_context(user_id, response_text, is_user=False)
@dp.errors()
async def global_errors_handler(event: ErrorEvent):
    logger.error(f"Критическое исключение: {event.exception}", exc_info=True)
    update = event.update
    if update.message:
        await update.message.answer(ERROR_FALLBACK_TEXT, reply_markup=create_main_keyboard())

@dp.message(CommandStart())
async def start_command(message: Message):
    welcome_text = "Привет, это Навальный, я скачал Телегу! Чтобы я ответил тебе ГОЛОСОМ, начни сообщение со слова АУДИО. (Лимит на голос — 1 раз в 30 минут)."
    await message.answer(welcome_text, reply_markup=create_main_keyboard())

@dp.message(Command("actions"))
async def actions_command(message: Message):
    await message.answer("Выбери, что ты хочешь сделать:", reply_markup=create_main_keyboard())
@dp.message(Command("sud"))
async def sud_command(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        await message.reply("Камон, в личке судить некого. Добавь меня в чат и суди своих друзей там.")
        return

    if not message.reply_to_message:
        await message.reply(
            "Чтобы устроить суд, ты должен ответить командой /sud на чье-то сообщение! "
            "Давай называть вещи своими называнием, нам нужен конкретный жулик."
        )
        return

    obvinitel = message.from_user.full_name
    osuzhdennyi_user = message.reply_to_message.from_user
    
    # Создаем кликабельную HTML-ссылку на аккаунт осужденного
    user_link = f'<a href="tg://user?id={osuzhdennyi_user.id}">{osuzhdennyi_user.full_name}</a>'
    
    # Контекст конкретно для этого судебного процесса
    trigger_text = f"Обвинитель {obvinitel} вызывает в суд пользователя {osuzhdennyi_user.full_name}. Вынеси ему приговор."
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # --- РАБОТА С ИИ БЕЗ СТАРОГО КОНТЕКСТА ЧАТА ---
    # Собираем чистый запрос: системный промт + текущее обвинение (история из БД игнорируется)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n" + BUTTON_PROMPTS["sud"]},
        {"role": "user", "content": trigger_text}
    ]
    
    try:
        response = await client.chat.completions.create(
            model="deepseek-v4-flash",  
            messages=messages,
            max_tokens=250,  
            temperature=0.7
        )
        response_text = response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating sud response: {e}")
        response_text = "приговаривается к мгновенному помилованию, потому что у нас упал сервер люстрации."
    # ----------------------------------------------

    # Склеиваем ссылку на виновного и вердикт ИИ
    final_text = f"⚖️ Суд идет! {user_link}, {response_text}"
    
    # Отправляем в чат с поддержкой HTML-тегов
    await message.reply(final_text, parse_mode="HTML")
    
    # (Опционально) Записываем этот приговор в базу данных, 
    # чтобы ИИ помнил его только при ОБЫЧНОМ общении в чате, 
    # но сам суд всегда будет стартовать с чистого листа.
    await save_context(message.from_user.id, trigger_text, is_user=True)
    await save_context(message.from_user.id, final_text, is_user=False)

# Кнопки
@dp.callback_query(F.data == "chat")
async def chat_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("💬 Напиши мне в чат! Если хочешь голосовой ответ, начни сообщение со слова АУДИО")

@dp.callback_query(F.data == "joke")
async def joke_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("⚡️ Оторвать тромб...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["joke"], trigger_text="")

@dp.callback_query(F.data == "news")
async def news_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("📰 Изучаю свежую прессу и готовлю разбор...")
    
    current_news = LATEST_NEWS_CACHE["text"]
    trigger_text = f"Вот главные новости на сегодня:\n{current_news}\n\nРазбери их по пунктам."
    
    # Передаем увеличенный лимит токенов
    await process_ai_reply(
        callback.message, 
        system_addition=BUTTON_PROMPTS["news"], 
        trigger_text=trigger_text,
        max_tokens=1000  # Теперь этого точно хватит на красивый список
    )

@dp.callback_query(F.data == "leaks")
async def leaks_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🕵️‍♂️ Перехватываю трафик...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["leaks"], trigger_text="")

@dp.callback_query(F.data == "merch")
async def merch_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🛍 Генерирую анонс...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["merch"], trigger_text="")

@dp.callback_query(F.data == "food")
async def food_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🥖 Оцениваю меню...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["food"], trigger_text="")

@dp.callback_query(F.data == "complaint")
async def complaint_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🏛 Отправляю запрос...")
    await process_ai_reply(callback.message, BUTTON_PROMPTS["complaint"], trigger_text="")

@dp.callback_query(F.data == "reset")
async def reset_handler(callback: CallbackQuery):
    await callback.answer()
    await clear_context(callback.from_user.id)
    await callback.message.edit_text("🔄 Память сброшена!")
    await callback.message.answer("Выбери, что ты хочешь сделать:", reply_markup=create_main_keyboard())

# Фото
# Фото
@dp.message(F.photo)
async def photo_handler(message: Message):
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    image_bytes = downloaded_file.read()
    
    # 1. Отправляем юзеру сигнал "печатает", чтобы он видел, что бот думает
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    # 2. Распознаем картинку через нейросеть
    image_description = await analyze_image_vision(image_bytes)
    
    # 3. Формируем финальный триггер-текст для ИИ
    user_content = f"[Фото: {image_description}]"
    caption = message.caption or ""
    if caption:
        user_content += f" Подпись: {caption}"
        
    # 4. ИСПРАВЛЕНО: Передаем user_content вместо caption!
    await process_ai_reply(message, system_addition=BUTTON_PROMPTS["vision_comment"], trigger_text=user_content)

# Голос и аудио
@dp.message(F.voice | F.audio)
async def voice_handler(message: Message):
    audio_source = message.voice if message.voice else message.audio
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    file_info = await bot.get_file(audio_source.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    audio_bytes = downloaded_file.read()
    
    user_text = await transcribe_audio(audio_bytes)
    
    if not user_text.strip():
        await message.reply("Ничего не слышно, повтори громче.")
        return

    logger.info(f"Распознан голос: {user_text}")
    await process_ai_reply(message, system_addition=BUTTON_PROMPTS["chat"], trigger_text=user_text)

# Обычный текст
@dp.message(F.text)
async def text_handler(message: Message):
    text = message.text
    is_private = message.chat.type == "private"
    
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_INFO["id"]
    bot_username = BOT_INFO["username"]
    is_mention = False
    if bot_username:
        is_mention = f"@{bot_username}".lower() in text.lower()
        
    is_command_msg = text.lower().startswith(("/message", "/msg"))
    if not (is_private or is_reply or is_mention or is_command_msg):
        return

    if is_command_msg:
        text = re.sub(r"(?i)^/(message|msg)(?:@[^\s]+)?\s*", "", text).strip()
    elif is_mention and bot_username:
        text = re.sub(rf"(?i)@{bot_username}\s*", "", text).strip()
        
    if not text and not is_reply:
        if not is_private:
            return 
        text = "Что?"

    # УДАЛЕНО: Старое сохранение контекста до очистки
    await process_ai_reply(message, system_addition=BUTTON_PROMPTS["chat"], trigger_text=text)

@dp.message(F.new_chat_members)
async def on_bot_added(message: Message):
    for user in message.new_chat_members:
        if user.id == BOT_INFO["id"]:
            await message.answer("Привет! Я — Цифровой Навальный. Чтобы услышать меня, пишите в начале сообщения слово <b>АУДИО</b>.", parse_mode="HTML")
            break
# --- ОБРАБОТЧИК ИНЛАЙН-РЕЖИМА (ВЫЗОВ ИЗ ЛЮБОГО ЧАТА) ---
# --- ОБРАБОТЧИК ИНЛАЙН-РЕЖИМА (ИСПРАВЛЕННЫЙ И БЫСТРЫЙ) ---
# --- 1. ОБРАБОТЧИК ИНЛАЙН-ЗАПРОСА (0 токенов, выдает мгновенные заглушки) ---
@dp.inline_query()
async def inline_query_handler(inline_query: InlineQuery):
    query_text = inline_query.query.strip()
    results = []

    # Если пользователь просто тегнул бота без текста
    if not query_text:
        quick_presets = [
            (
                "static_joke", 
                "⚡️ Оторвать тромб", 
                "Случайный жесткий панчлайн",
                "Камон, ребята, ну вы чего? Система Комитета Люстрации зафиксировала сбой. Срочно донатим ФБК, чтобы тромб прирос обратно!"
            ),
            (
                "static_leaks", 
                "🕵️‍♂️ Секретные сливы ФБК", 
                "Диалог руководства из Slack",
                "Жданов: Кто опять съел мой сэндвич на кухне в Лондоне?\nПевчих: Это Волков, он заложил его в бюджет под новую партию худи."
            ),
            (
                "static_merch", 
                "🛍 Запустить сбор на мерч", 
                "Анонс абсурдного товара",
                "Встречайте новую коллекцию мерча! Тактический фонарик 'Люблино-2007' с автографом. Всего за 50$ в крипте. Защити свою Прекрасную Россию Будущего правильно."
            )
        ]
        
        for idx, (result_id, title, desc, static_text) in enumerate(quick_presets):
            results.append(
                InlineQueryResultArticle(
                    id=f"{result_id}_{idx}",
                    title=title,
                    description=desc,
                    input_message_content=InputTextMessageContent(message_text=static_text)
                )
            )
            
    # Если пользователь ПЕЧАТАЕТ текст — отдаем пустую заглушку с кнопкой (ИИ НЕ ВЫЗЫВАЕМ!)
    else:
        # Кнопка обязательна, чтобы Телеграм передал ID сообщения для редактирования
        placeholder_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Думает...", callback_data="thinking_process")]
        ])

        results.append(
            InlineQueryResultArticle(
                id="dynamic_request",
                title="💬 Ответ Цифрового Навального",
                description=f"Нажмите, чтобы отправить запрос: \"{query_text}\"",
                input_message_content=InputTextMessageContent(
                    message_text=f"<b>Запрос:</b> <i>{query_text}</i>\n\n😎 <b>Навальный:</b> ⏳ <i>Генерирую ответ, секунду...</i>",
                    parse_mode="HTML"
                ),
                reply_markup=placeholder_keyboard
            )
        )

    await inline_query.answer(results, cache_time=1, is_personal=True)


# --- 2. ОБРАБОТЧИК ВЫБРАННОГО ОТВЕТА (Срабатывает ровно 1 раз при НАЖАТИИ) ---
@dp.chosen_inline_result()
async def chosen_inline_result_handler(chosen_result: ChosenInlineResult):
    # Реагируем только на динамические запросы к ИИ
    if chosen_result.result_id != "dynamic_request":
        return

    inline_msg_id = chosen_result.inline_message_id
    query_text = chosen_result.query.strip()

    if not inline_msg_id:
        logger.error("Не получен inline_message_id. Проверь, включен ли inline feedback в BotFather!")
        return

    # Вот теперь ОДИН раз вызываем DeepSeek
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n" + BUTTON_PROMPTS["chat"]},
        {"role": "user", "content": query_text}
    ]
    try:
        response = await client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            max_tokens=250,
            temperature=0.7
        )
        ai_reply = response.choices[0].message.content
    except Exception as e:
        logger.error(f"Inline AI error: {e}")
        ai_reply = ERROR_FALLBACK_TEXT

    if not ai_reply or not str(ai_reply).strip():
        ai_reply = ERROR_FALLBACK_TEXT

    final_text = f"<b>Запрос:</b> <i>{query_text}</i>\n\n😎 <b>Навальный:</b> {ai_reply}"

    # Магия: заменяем заглушку на реальный ответ ИИ и удаляем кнопку загрузки
    try:
        await bot.edit_message_text(
            text=final_text,
            inline_message_id=inline_msg_id,
            parse_mode="HTML",
            reply_markup=None  # Убираем кнопку "Думает..."
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования инлайн-сообщения: {e}")

async def main():
    await init_db()
    bot_me = await bot.get_me()
    BOT_INFO["id"] = bot_me.id
    BOT_INFO["username"] = bot_me.username
    logger.info(f"Запущен бот: @{BOT_INFO['username']}")
    
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query(ThrottlingMiddleware())
    
    # <-- ДОБАВЛЯЕМ СТРОКУ НИЖЕ ДЛЯ ЗАПУСКА ФОНОВОЙ ЗАДАЧИ НОВОСТЕЙ -->
    asyncio.create_task(update_news_task())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())