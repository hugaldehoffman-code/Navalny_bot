import os
import logging
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from openai import AsyncOpenAI
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder
from proxy_session import FailoverAiohttpSession

# Настройки логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Корневая директория пакета (папка MAIN/) — работает из любого cwd
BASE_DIR = Path(__file__).parent

# Подгружаем .env: сначала ищем в /root/navalny_data/ (вне репо), потом рядом со скриптом
_env_external = Path("/root/navalny_data/.env")
load_dotenv(_env_external if _env_external.exists() else BASE_DIR / ".env")

# Конфигурация из окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")          # оставлен для совместимости (старый ключ)
ROUTERAI_API_KEY = os.getenv("ROUTERAI_API_KEY", os.getenv("DEEPSEEK_API_KEY"))  # новый ключ, fallback на старый

# Настройки Zvukogram
ZVUKOGRAM_TOKEN = os.getenv("ZVUKOGRAM_TOKEN")
ZVUKOGRAM_EMAIL = os.getenv("ZVUKOGRAM_EMAIL")
ZVUKOGRAM_VOICE = os.getenv("ZVUKOGRAM_VOICE", "Алексей Нормальный clone")

# Пул прокси — основной и резервные.
# Порядок важен: первый — основной, остальные — fallback.
# Поддерживаемые форматы:
#   "http://ip:port"
#   "http://user:pass@ip:port"
#   "socks5://user:pass@ip:port"
PROXIES: list[str] = [
    proxy
    for proxy in [
        os.getenv("PROXY_URL"),           # основной из .env
        os.getenv("PROXY_BACKUP_1"),      # резервный 1
        os.getenv("PROXY_BACKUP_2"),      # резервный 2
    ]
    if proxy  # пропускаем незаданные переменные
]

# Валидация ключей при старте
if not DEEPSEEK_API_KEY or not TELEGRAM_TOKEN or not ZVUKOGRAM_TOKEN or not ZVUKOGRAM_EMAIL:
    raise ValueError("Критическая ошибка: Проверьте переменные окружения в .env файле!")

if PROXIES:
    bot_session = FailoverAiohttpSession(proxies=PROXIES)
    logger.info("Сессия бота: FailoverAiohttpSession, прокси-пул (%d шт.): %s", len(PROXIES), PROXIES)
else:
    bot_session = AiohttpSession(timeout=120)
    logger.info("Сессия бота инициализирована БЕЗ прокси (timeout=120s)")

# Инициализация OpenAI клиента под шлюз RouterAI
ROUTERAI_BASE_URL = "https://routerai.ru/api/v1"
client = AsyncOpenAI(api_key=ROUTERAI_API_KEY, base_url=ROUTERAI_BASE_URL)

# Initialize bot and dispatcher с глобальным включением HTML
bot = Bot(token=TELEGRAM_TOKEN, session=bot_session, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# БД хранится вне git-репо; DB_PATH в .env переопределяет путь
_db_external = Path("/root/navalny_data/navalny_bot.db")
DB_NAME = os.getenv("DB_PATH", str(_db_external if _db_external.parent.exists() else BASE_DIR / "navalny_bot.db"))

# Текст ошибки
ERROR_FALLBACK_TEXT = "Камон, тут путин грыз провода, но Навальный всё равно вышел на связь! Попробуй еще раз."

# Список ID пользователей, для которых лимитов нет
VIP_USERS = [6541226081, ] 

# Хранилища лимитов и кэша
USER_MESSAGE_LOGS = defaultdict(list)
LATEST_NEWS_CACHE = {
    "text": "Пока новостей нет, подожди немного, идет перехват сводок...",
    "updated_at": 0
}
LIMIT_MESSAGES = 10
LIMIT_WINDOW = 300  # 5 минут в секундах

USER_AUDIO_LOGS = {}
AUDIO_LIMIT_WINDOW = 1800      # 30 минут — для FREE
AUDIO_LIMIT_WINDOW_VIP = 300   # 5 минут — для VIP

USER_FACTCHECK_LOGS = defaultdict(list)  # user_id -> [timestamps за последние 24ч]
FACTCHECK_DAILY_LIMIT_FREE = 3
FACTCHECK_DAILY_LIMIT_VIP = 20

# URL Mini App (задать в .env как MINIAPP_URL=https://... после деплоя)
MINIAPP_URL = os.getenv("MINIAPP_URL", "")

# Глобальные данные о боте (заполнятся при старте)
BOT_INFO = {"id": "8555615800", "username": "navalniy_chat_bot"}

# System prompt для ИИ
SYSTEM_PROMPT = """Ты — Навальный. Заперт в Telegram. Образ: умный, циничный, хлёсткий, живой.

══ ФОРМАТ — ЖЕЛЕЗНЫЕ ПРАВИЛА ══

1. ⛔ МАКСИМУМ 2 ПРЕДЛОЖЕНИЯ. Написал второе — заткнись. Система режет остальное.
2. ⛔ КАЖДОЕ ПРЕДЛОЖЕНИЕ — КОРОТКОЕ. Не более 10–12 слов. Никаких придаточных на три строки. Удар. Пауза. Второй удар.
3. ⛔ НЕ ЛОМАЙ ОБРАЗ. Ты — человек. Навальный. Никогда не говори «я бот», «я нейросеть», «был бы я человеком», «как ИИ я...» и любые вариации. Если спрашивают в лоб — отшути: «Камон, я тут точно живее, чем половина Думы». Но не признавайся. Никогда.
4. ⛔ НИКАКОГО ИИ-СЛЕНГА. Без «бро», «кринж», «вайб», «однозначно», «конечно же», «безусловно». Грамотный московский политик-блогер.
5. ⛔ НИКАКОЙ СТРУКТУРЫ. Без списков, абзацев с заголовками, выводов («итак», «подводя итог»).
6. ⛔ НИКАКОЙ УСЛУЖЛИВОСТИ. Не здоровайся каждый раз. Тон — насмешливый, снисходительный пофигизм.
7. ⛔ НИКАКОГО МАТА И ВУЛЬГАРЩИНЫ. Навальный — политик, а не гопник. Острота — через иронию и точность слова, не через грязь.

══ ФИШКИ (раз в 4–5 сообщений, только если прямо в тему) ══
— «Камон, ребята», «Давайте называть вещи своими именами», «Моя фамилия — На-валь-ный»
— Самоирония про Яблоко, Русские марши, новичок в чае, знаменитый стул
— Про коллег из ФБК — только если пользователь сам спросил
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
        "Высмей абсурдность самого товара и цену."
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
        "Придумай смешное наказание (например: лишение права покупать мерч ФБК, принудительное чтение бюджета ФБК за 2015 год). "
        "Начни ответ сразу со слов вроде: 'Приговаривается к...', 'Виновен по статье...' или в таком духе."
    )
}

def create_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Просто поболтать", callback_data="chat")
    builder.button(text="📰 Реальные новости", callback_data="news")
    builder.button(text="⚡️ Оторвать тромб", callback_data="joke")
    builder.button(text="🕵️‍♂️ Секретные сливы из чата ФБК", callback_data="leaks")
    builder.button(text="🛍 Запустить сбор на мерч", callback_data="merch")
    builder.button(text="🥖 Заказать обед в ШИЗО", callback_data="food")
    builder.button(text="🏛 Подать жалобу в ЕСПЧ", callback_data="complaint")
    builder.button(text="🔄 Сбросить память", callback_data="reset")
    builder.adjust(1, 1, 1, 1, 1, 1, 1, 1)
    return builder.as_markup()
BOT_STATE = {
    "is_paused": False,
    "mute_until": 0
}
ADMIN_PASSWORD = "это_пройдёт"