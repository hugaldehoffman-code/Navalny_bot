import asyncio
import re
import time
import base64
import aiohttp
from aiogram.types import Message, BufferedInputFile
from openai import AsyncOpenAI
from typing import Optional

from config import (
    client, bot, logger, ZVUKOGRAM_TOKEN, ZVUKOGRAM_EMAIL, ZVUKOGRAM_VOICE,
    SYSTEM_PROMPT, ERROR_FALLBACK_TEXT, VIP_USERS, USER_AUDIO_LOGS, AUDIO_LIMIT_WINDOW, BUTTON_PROMPTS,
    ROUTERAI_API_KEY
)
from database import save_context, get_context, get_or_create_user, check_and_reset_daily_limits, expire_premium_if_needed
from tariffs import get_tariff, TARIFFS

# ═════════════════════════════════════════════
#  VISION API КЛИЕНТ (отдельный)
# ═════════════════════════════════════════════

VISION_BASE_URL = "https://routerai.ru/api/v1"

vision_client = AsyncOpenAI(
    api_key=ROUTERAI_API_KEY,
    base_url=VISION_BASE_URL,
    max_retries=1,
)


# ═════════════════════════════════════════════
#  СИНТЕЗ РЕЧИ (Zvukogram)
# ═════════════════════════════════════════════

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
        "channels": 1,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, timeout=15) as response:
                if response.status != 200:
                    logger.error(f"Ошибка Zvukogram API, статус: {response.status}")
                    return None
                result = await response.json()

            if result.get("status") == 1:
                audio_url = result.get("file")
                async with session.get(audio_url, timeout=15) as audio_response:
                    if audio_response.status == 200:
                        audio_bytes = await audio_response.read()
                        return BufferedInputFile(audio_bytes, filename=f"reply_{result.get('id')}.mp3")
            else:
                logger.error(f"Ошибка Zvukogram: {result.get('error', 'Неизвестная ошибка')}")
    except Exception as e:
        logger.error(f"Исключение при обращении к Zvukogram: {e}")
    return None


# ═════════════════════════════════════════════

#  РАСПОЗНАВАНИЕ КАРТИНОК (VISION) — ОПТИМИЗИРОВАННАЯ ВЕРСИЯ
# ═════════════════════════════════════════════

async def analyze_image_vision(
    image_bytes: bytes,
    tariff_name: str = "FREE",
    system_prompt: str = None,
    prompt: str = None,
) -> str:
    """
    Анализ картинки через Vision API.
    Если передан system_prompt — модель сразу генерирует ответ в стиле персонажа.
    Если передан prompt — используется как текстовая инструкция для пользователя.
    Модель выбирается динамически по тарифу пользователя.
    """
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    tariff = get_tariff(tariff_name)

    # Цепочка моделей: основная + фоллбэки
    models_to_try = [tariff.vision_model] + tariff.vision_fallback_models

    # Формируем сообщения: если есть system_prompt — добавляем его первой ролью
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Определяем текст для пользовательского сообщения
    user_text = "Опиши изображение и сразу ответь в заданном стиле персонажа."
    if prompt:
        user_text = prompt

    user_content_parts = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
    ]
    messages.append({"role": "user", "content": user_content_parts})

    for model_name in models_to_try:
        try:
            logger.info(f"Vision ({tariff_name}): пробую модель {model_name}")
            response = await vision_client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=300,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"Vision-модель {model_name} выдала ошибку: {e}. Пробую альтернативу...")
            continue

    logger.error(f"Все Vision-модели ({models_to_try}) не отработали.")
    return ERROR_FALLBACK_TEXT


# ═════════════════════════════════════════════
#  РАСПОЗНАВАНИЕ АУДИО
# ═════════════════════════════════════════════

async def transcribe_audio(audio_bytes: bytes) -> str:
    base64_audio = base64.b64encode(audio_bytes).decode("utf-8")
    try:
        response = await client.chat.completions.create(
            model="google/gemini-2.0-flash",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Перепиши этот аудиоклип дословно в виде текста на русском языке. Не добавляй никаких своих комментариев."},
                        {"type": "input_audio", "input_audio": {"data": base64_audio, "format": "wav"}},
                    ],
                }
            ],
            max_tokens=250,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка распознавания аудио через Gemini: {e}")
        return ""


# ═════════════════════════════════════════════
#  ГЕНЕРАЦИЯ ТЕКСТОВОГО ОТВЕТА
# ═════════════════════════════════════════════

async def generate_response(
    user_id: int,
    system_addition: str = "",
    max_tokens: int = 500,
    tariff_name: str = "FREE",
) -> str:
    """Генерирует ответ через AI с учётом тарифа (выбор модели)."""
    tariff = get_tariff(tariff_name)
    context = await get_context(user_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + system_addition}]
    messages.extend(context)
    for attempt in range(3):
        try:
            response = await client.chat.completions.create(
                model=tariff.text_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
                timeout=25.0,
            )
            res_text = response.choices[0].message.content
            if not res_text or not res_text.strip():
                return ERROR_FALLBACK_TEXT
            return res_text
        except Exception as e:
            if attempt < 2:
                wait = float(attempt + 1)
                logger.warning(f"generate_response attempt {attempt + 1}/3 failed: {e}. Retry in {wait}s")
                await asyncio.sleep(wait)
            else:
                logger.error(f"generate_response failed after 3 attempts: {e}")
                return ERROR_FALLBACK_TEXT


# ═════════════════════════════════════════════
#  ОБРАБОТЧИК AI ОТВЕТОВ (единая точка входа)
# ═════════════════════════════════════════════

async def resolve_tariff_for_user(user_id: int) -> str:
    """Быстрый lookup тарифа пользователя из БД (без сброса лимитов)."""
    try:
        record = await get_or_create_user(user_id)
        record = await expire_premium_if_needed(user_id)
        return record.get("tariff_name", "FREE")
    except Exception:
        return "FREE"


async def process_ai_reply(
    message: Message,
    system_addition: str,
    trigger_text: str,
    max_tokens: int = 500,
    tariff_name: str = None,
) -> None:
    if tariff_name is None:
        tariff_name = await resolve_tariff_for_user(message.from_user.id)

    is_private = message.chat.type == "private"
    user_id = message.from_user.id

    trigger_upper = trigger_text.strip().upper()
    wants_voice = trigger_upper.startswith("АУДИО")

    if wants_voice:
        clean_text = re.sub(r"^аудио\s*", "", trigger_text, flags=re.IGNORECASE).strip()
        if user_id not in VIP_USERS:
            current_time = time.time()
            last_audio_time = USER_AUDIO_LOGS.get(user_id, 0)
            if current_time - last_audio_time < AUDIO_LIMIT_WINDOW:
                left_time = int(AUDIO_LIMIT_WINDOW - (current_time - last_audio_time))
                await message.reply(
                    f"Камон, генерировать голос слишком дорого для ФБК! "
                    f"Следующее аудио можно заказать через {left_time // 60} мин. А пока держи ответ текстом."
                )
                wants_voice = False
            else:
                USER_AUDIO_LOGS[user_id] = current_time
    else:
        clean_text = trigger_text.strip()

    if clean_text:
        await save_context(user_id, clean_text, is_user=True)

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    response_text = await generate_response(
        user_id, system_addition, max_tokens=max_tokens, tariff_name=tariff_name
    )

    if not response_text or not response_text.strip():
        response_text = ERROR_FALLBACK_TEXT

    if wants_voice:
        await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
        voice_file = await generate_voice_reply(response_text)
        if voice_file:
            if not is_private:
                await message.reply_voice(voice=voice_file)
            else:
                await message.answer_voice(voice=voice_file)
        else:
            await message.reply(
                f"(Голос не сгенерировался, пишу текстом):\n\n{response_text}", parse_mode="HTML"
            )
    else:
        if not is_private:
            await message.reply(response_text, parse_mode="HTML")
        else:
            await message.answer(response_text, parse_mode="HTML")

    await save_context(user_id, response_text, is_user=False)


# ═══════════════════════════════════════════════════════
#  НОВЫЕ AI-ФУНКЦИИ (Фактчекинг, Посты, Документы)
# ═══════════════════════════════════════════════════════

# ─── Системные промпты ──────────────────────────────────────────

FACTCHECK_SYSTEM_PROMPT = """Ты — строгий политический фактчекер, работающий на Цифрового Навального 2.0.
У тебя есть доступ к поиску в интернете — используй его, чтобы найти актуальные данные перед вынесением вердикта.

ТВОЯ ЗАДАЧА: проверить утверждение / новость и вынести ОДНОЗНАЧНЫЙ вердикт.

ФОРМАТ ОТВЕТА — СТРОГО СЛЕДУЙ ЭТОМУ ШАБЛОНУ (копируй теги дословно):

<b>ВЕРДИКТ:</b> [ПРАВДА / ЛОЖЬ / ПОЛУПРАВДА / МАНИПУЛЯЦИЯ]

<b>АРГУМЕНТАЦИЯ:</b> 5-7 предложений. Разбери утверждение по частям: что подтверждается, что опровергается, какие нюансы важны. Приводи конкретные цифры, даты, названия законов, результаты исследований. Объясни контекст — почему это утверждение возникло и чем оно манипулирует (если манипулирует).

<b>ЧТО ГОВОРЯТ СТОРОНЫ:</b> 2-3 предложения — позиция официальных источников vs. независимых расследований / оппозиции. Без воды, только суть противоречия.

<b>ИСТОЧНИКИ:</b> 2-3 конкретных источника с пояснением, что именно они подтверждают (название издания или сайта).

<b>ВЕРДИКТ НАВАЛЬНОГО:</b> 2-3 едких предложения от первого лица — сатира, но с фактической основой.

КРИТИЧЕСКИ ВАЖНО:
- ЗАПРЕЩЕНО использовать **звёздочки** для выделения — это сломает отображение в Telegram.
- ТОЛЬКО HTML-теги: <b>текст</b> для жирного. Никакого markdown.
- Ищи актуальную информацию в сети прежде чем отвечать.
- Никакой воды — только факты.
"""

POST_GENERATOR_SYSTEM_PROMPT = """Ты — Цифровой Навальный 2.0, и тебе поручили написать пост-расследование в твоём фирменном стиле.

СТИЛЬ:
- Сатирический, едкий, аргументированный.
- Язык — грамотная, хлёсткая речь интеллигентного московского политика-блогера.
- Никакого искусственного сленга (бро, кринж, вайб — запрещены).
- 3-5 коротких абзацев. Каждый абзац — 1-2 предложения.
- Добавь одну фирменную фразу из твоего арсенала (например: "Камон, ребята, ну вы чего?", "Давайте называть вещи своими называнием", "Моя фамилия — На-валь-ный").

ФОРМАТ:
- Заголовок: <b>яркий заголовок в твоём стиле</b>
- Основной текст: абзацы через пустую строку
- В конце — хэштеги: #Навальный #Расследование #ПРБ

ЗАПРЕЩЕНО: нумерованные списки, подзаголовки, "в общем", "подводя итог".
"""

DOCUMENT_ANALYSIS_SYSTEM_PROMPT = """Ты — эксперт-аналитик Цифрового Навального 2.0. Твоя задача — разобрать сложный бюрократический документ на простой человеческий язык.

СТИЛЬ:
- Понятный, разговорный русский язык.
- Объясняй сложное простыми словами, как для обычного человека.
- Выделяй ключевые моменты, подозрительные детали, скрытые смыслы.
- Допустима лёгкая сатира и ирония — ты же из команды Навального.

ФОРМАТ:
<b>📑 О ЧЁМ ДОКУМЕНТ:</b> 1-2 предложения сути.
<b>🔑 КЛЮЧЕВЫЕ ТЕЗИСЫ:</b> 3-5 пунктов простым языком.
<b>⚠️ ЧТО НАСТОРАЖИВАЕТ:</b> подозрительные места, нестыковки, скрытый смысл.
<b>😎 ВЕРДИКТ НАВАЛЬНОГО:</b> 1 едкая фраза по итогу разбора.

Запрещены длинные абзацы и канцелярит.
"""


# ─── ФУНКЦИЯ 1: Фактчекинг ──────────────────────────────────────

async def factcheck_claim(
    user_id: int,
    claim_text: str,
    image_bytes: Optional[bytes] = None,
    tariff_name: str = "FREE",
) -> str:
    """
    Проверка фактов / утверждений.
    Принимает текст или текст + картинку (из которой извлечётся текст).
    Возвращает вердикт в HTML-формате.
    """
    tariff = get_tariff(tariff_name)

    # Если пришла картинка — извлекаем текст из неё
    if image_bytes:
        extracted = await analyze_image_vision(
            image_bytes,
            tariff_name=tariff_name,
            prompt="Внимательно прочитай и дословно перепиши ВЕСЬ текст, который видишь на этом изображении. "
                   "Если это скриншот новости или поста — перепиши заголовок и основной текст полностью.",
        )
        claim_text = claim_text + "\n\n[Текст из изображения]: " + extracted

    messages = [
        {"role": "system", "content": FACTCHECK_SYSTEM_PROMPT},
        {"role": "user", "content": f"Проверь следующее утверждение:\n\n{claim_text}"},
    ]

    for attempt in range(2):
        try:
            logger.info(f"Фактчекинг attempt {attempt + 1}/2 (тариф {tariff_name})")
            response = await client.chat.completions.create(
                model="deepseek/deepseek-v4-pro:online",
                messages=messages,
                max_tokens=3500,
                temperature=0.3,
                timeout=150.0,
            )
            result = response.choices[0].message.content
            if not result or not result.strip():
                return "<b>ВЕРДИКТ:</b> 🤷‍♂️ Не удалось провести проверку. Попробуй ещё раз."
            return result
        except Exception as e:
            if attempt < 1:
                logger.warning(f"Фактчекинг attempt {attempt + 1}/2 failed: {e}. Retry in 3s")
                await asyncio.sleep(3.0)
            else:
                logger.error(f"Фактчекинг failed after 2 attempts: {e}")
    return (
        "⚠️ <b>Фактчекинг не завершился.</b>\n\n"
        "Проверка использует мощную модель с поиском в интернете — запрос занимает 40–90 секунд, "
        "и иногда сервер не успевает ответить в срок. Деньги за незавершённый запрос не списываются.\n\n"
        "Попробуй ещё раз — обычно со второй попытки всё работает."
    )


# ─── ФУНКЦИЯ 2: Генератор постов-расследований ──────────────────

async def generate_investigation_post(
    user_id: int,
    topic: str,
    tariff_name: str = "FREE",
) -> str:
    """
    Генерация сатирического поста-расследования в стиле Навального.
    Принимает тему / тезисы от пользователя.
    """
    tariff = get_tariff(tariff_name)

    messages = [
        {"role": "system", "content": POST_GENERATOR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Напиши пост-расследование на следующую тему. Вот тезисы или описание ситуации:\n\n"
                f"{topic}\n\n"
                f"Сделай это в своём лучшем сатирическо-расследовательском стиле. Аргументированно, едко, коротко."
            ),
        },
    ]

    for attempt in range(3):
        try:
            logger.info(f"Генератор постов attempt {attempt + 1}/3 (тариф {tariff_name})")
            response = await client.chat.completions.create(
                model="deepseek/deepseek-v4-pro",
                messages=messages,
                max_tokens=3000,
                temperature=0.85,
                timeout=30.0,
            )
            result = response.choices[0].message.content
            if not result or not result.strip():
                return "Камон, тут путин грыз провода, пост не сгенерировался. Попробуй ещё раз."
            return result
        except Exception as e:
            if attempt < 2:
                logger.warning(f"Генератор постов attempt {attempt + 1}/3 failed: {e}. Retry in {attempt + 1}s")
                await asyncio.sleep(float(attempt + 1))
            else:
                logger.error(f"Генератор постов failed after 3 attempts: {e}")
    return "🔌 Серверная в ШИЗО. Попробуй через минуту."


# ─── ФУНКЦИЯ 3: Глубокий анализ документов ──────────────────────

async def analyze_document(
    user_id: int,
    image_bytes: Optional[bytes] = None,
    document_text: Optional[str] = None,
    tariff_name: str = "FREE",
) -> str:
    """
    Глубокий анализ документа / скриншота / PDF.
    Может принимать готовый текст документа или скриншот (извлечёт текст через Vision).
    """
    tariff = get_tariff(tariff_name)

    # Если подали скриншот — извлекаем текст
    if image_bytes and not document_text:
        extracted = await analyze_image_vision(
            image_bytes,
            tariff_name=tariff_name,
            prompt=(
                "Это скриншот официального документа. Твоя задача — внимательно прочитать и "
                "МАКСИМАЛЬНО ПОЛНО переписать весь текст, который видишь на этом изображении. "
                "Переписывай каждую строку, каждую цифру, каждую дату, каждую сумму. "
                "Ничего не пропускай. Если есть таблицы — опиши их структуру. "
                "Если видишь печати, подписи, номера дел — обязательно укажи их."
            ),
        )
        document_text = extracted
    elif not document_text:
        return "❌ Не предоставлен ни текст, ни изображение документа."

    messages = [
        {"role": "system", "content": DOCUMENT_ANALYSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Разбери следующий документ простыми словами:\n\n"
                f"=== НАЧАЛО ДОКУМЕНТА ===\n"
                f"{document_text[:6000]}"  # обрезаем, если слишком длинный
                f"\n=== КОНЕЦ ДОКУМЕНТА ==="
            ),
        },
    ]

    for attempt in range(3):
        try:
            logger.info(f"Анализ документа attempt {attempt + 1}/3 (тариф {tariff_name})")
            response = await client.chat.completions.create(
                model="deepseek/deepseek-v4-pro",
                messages=messages,
                max_tokens=3000,
                temperature=0.6,
                timeout=30.0,
            )
            result = response.choices[0].message.content
            if not result or not result.strip():
                return "📑 Документ прочитан, но анализ не удался. Попробуй ещё раз."
            return result
        except Exception as e:
            if attempt < 2:
                logger.warning(f"Анализ документа attempt {attempt + 1}/3 failed: {e}. Retry in {attempt + 1}s")
                await asyncio.sleep(float(attempt + 1))
            else:
                logger.error(f"Анализ документа failed after 3 attempts: {e}")
    return "📑 Сервер ушёл в ШИЗО. Попробуй проанализировать документ позже."
