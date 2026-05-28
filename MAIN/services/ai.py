import re
import time
import base64
import aiohttp
from aiogram.types import Message, BufferedInputFile
from config import (
    client, bot, logger, ZVUKOGRAM_TOKEN, ZVUKOGRAM_EMAIL, ZVUKOGRAM_VOICE,
    SYSTEM_PROMPT, ERROR_FALLBACK_TEXT, VIP_USERS, USER_AUDIO_LOGS, AUDIO_LIMIT_WINDOW
)
from database import save_context, get_context

# СИНТЕЗ РЕЧИ
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

# АНАЛИЗ КАРТИНКИ (qwen3.5-flash)
async def analyze_image_vision(image_bytes: bytes) -> str:
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    try:
        response = await client.chat.completions.create(
            model="qwen3.5-flash",  
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Опиши очень кратко и понятно, что происходит на этой картинке. Если на фото есть известные люди, политики, мировые лидеры или блогеры, ОБЯЗАТЕЛЬНО назови их имена и фамилии. Если на картинке есть текст, напиши его."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            max_tokens=150
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Vision API error (qwen3.5-flash): {e}")
        return "Не удалось распознать объекты на фото."

# РАСПОЗНАВАНИЕ АУДИО (gemini-2.0-flash)
async def transcribe_audio(audio_bytes: bytes) -> str:
    base64_audio = base64.b64encode(audio_bytes).decode('utf-8')
    try:
        response = await client.chat.completions.create(
            model="gemini-2.0-flash",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Перепиши этот аудиоклип дословно в виде текста на русском языке. Не добавляй никаких своих комментариев."},
                        {"type": "input_audio", "input_audio": {"data": base64_audio, "format": "wav"}}
                    ]
                }
            ],
            max_tokens=250
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка распознавания аудио через Gemini: {e}")
        return ""

# ГЕНЕРАЦИЯ ОТВЕТА
async def generate_response(user_id: int, system_addition: str = "", max_tokens: int = 250) -> str:
    context = await get_context(user_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + system_addition}]
    messages.extend(context)
    try:
        response = await client.chat.completions.create(
            model="deepseek-v4-flash",  
            messages=messages,
            max_tokens=max_tokens,  
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return ERROR_FALLBACK_TEXT

# ОБРАБОТЧИК AI ОТВЕТОВ
async def process_ai_reply(message: Message, system_addition: str, trigger_text: str, max_tokens: int = 250):
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
                await message.reply(f"Камон, генерировать голос слишком дорого для ФБК! Следующее аудио можно заказать через {left_time // 60} мин. А пока держи ответ текстом.")
                wants_voice = False 
            else:
                USER_AUDIO_LOGS[user_id] = current_time
    else:
        clean_text = trigger_text.strip()
    
    if clean_text:
        await save_context(user_id, clean_text, is_user=True)
        
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    response_text = await generate_response(user_id, system_addition, max_tokens=max_tokens)
    
    if wants_voice:
        await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
        voice_file = await generate_voice_reply(response_text)
        if voice_file:
            if not is_private:
                await message.reply_voice(voice=voice_file)
            else:
                await message.answer_voice(voice=voice_file)
        else:
            await message.reply(f"(Голос не сгенерировался, пишу текстом):\n\n{response_text}", parse_mode="HTML")
    else:
        if not is_private:
            await message.reply(response_text, parse_mode="HTML")
        else:
            await message.answer(response_text, parse_mode="HTML")
            
    await save_context(user_id, response_text, is_user=False)