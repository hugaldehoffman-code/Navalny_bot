import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BufferedInputFile
from aiogram.enums import ChatType
import aiohttp
from urllib.parse import quote

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8555615800:AAFO15jr0uaorKbko8rayEmdGgOld2d2ryg"
ZVUKOGRAM_TOKEN = "4cb42dc3-1fc6-453e-b914-ad38ee948491"
ZVUKOGRAM_EMAIL = "bbcxjhm2.0@gmail.com"
# Точное имя голоса, подтвержденное поддержкой
VOICE_NAME = "Алексей Нормальный clone"  
# -------------------------------------------

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def text_to_speech(text: str) -> bytes | None:
    """Отправляет текст в Звукограм и выводит JSON ответа в консоль."""
    api_url = "https://zvukogram.com/index.php?r=api/text"
    
    payload = {
        "token": ZVUKOGRAM_TOKEN,
        "email": ZVUKOGRAM_EMAIL,
        "voice": VOICE_NAME,
        "text": text
    }
    
    async with aiohttp.ClientSession() as session:
        logging.info(f"Отправка запроса к API Звукограма. Голос: '{VOICE_NAME}'")
        
        async with session.post(api_url, data=payload) as response:
            if response.status != 200:
                logging.error(f"Сервер Звукограма вернул HTTP код: {response.status}")
                return None
            
            try:
                # Получаем ответ в формате JSON напрямую
                result = await response.json()
                
                # Выводим JSON красивой структурой в консоль бота
                import json
                print("\n" + "="*50)
                print("=== JSON ОТВЕТ ОТ ЗВУКОГРАМА ===")
                print(json.dumps(result, ensure_ascii=False, indent=4))
                print("="*50 + "\n")
                
            except Exception as e:
                logging.error(f"Не удалось распарсить JSON: {e}")
                return None
            
            # Проверяем, вернул ли сервер корректный рабочий ID (больше нуля)
            # Если id равен 0 или равен "0", значит таска не создалась
            task_id = result.get("id")
            if not task_id or str(task_id) == "0" or result.get("error"):
                logging.error(f"Генерация отклонена сервером. Задача НЕ создана в истории.")
                return None
            
            # Если файл каким-то чудом готов сразу
            if result.get("file"):
                file_url = result.get("file")
                async with session.get(file_url) as file_res:
                    if file_res.status == 200:
                        return await file_res.read()
        
        # Шаг 2: Опрос статуса, если первый этап выдал реальный ID (не 0)
        status_url = "https://zvukogram.com/index.php?r=api/result"
        check_payload = {
            "token": ZVUKOGRAM_TOKEN,
            "email": ZVUKOGRAM_EMAIL,
            "id": task_id
        }
        
        logging.info(f"Начинаем опрос статуса для созданного ID: {task_id}")
        for _ in range(15):  
            await asyncio.sleep(2)
            async with session.post(status_url, data=check_payload) as res:
                if res.status == 200:
                    status_result = await res.json()
                    current_status = str(status_result.get("status"))
                    
                    if status_result.get("file") and current_status in ["1", "2"]:
                        file_url = status_result.get("file")
                        async with session.get(file_url) as file_res:
                            if file_res.status == 200:
                                return await file_res.read()
                                
                    elif current_status == "-1":  
                        logging.error(f"Ошибка в процессе генерации таски {task_id}: {status_result}")
                        return None
                        
        return None
    
# Принимаем сообщения ТОЛЬКО в ЛС бота
@dp.message(F.text, F.chat.type == ChatType.PRIVATE)
async def handle_private_message(message: Message):
    if message.text.startswith("/"):
        if message.text == "/start":
            await message.answer("Привет! Напиши мне любой текст в ЛС, и я пришлю его в виде голосового сообщения.")
        return

    # Эмуляция записи голосового сообщения в Telegram
    await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
    status_msg = await message.answer("⏳ Озвучиваю текст клонированным голосом...")
    
    audio_bytes = await text_to_speech(message.text)
    
    if audio_bytes:
        await status_msg.delete()
        # Превращаем скачанные байты в аудиофайл для Telegram
        voice_file = BufferedInputFile(audio_bytes, filename="voice.mp3")
        await message.answer_voice(voice=voice_file)
    else:
        await status_msg.edit_text("❌ Не удалось озвучить текст через клон голоса. Проверьте логи консоли.")

async def main():
    print("Бот успешно запущен и ожидает сообщений исключительно в ЛС!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())