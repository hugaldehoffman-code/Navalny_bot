from aiogram import Router, F
from aiogram.types import Message
from config import bot, logger, BUTTON_PROMPTS
# ИСПРАВЛЕНО: подтягиваем логику ИИ из папки services
from services.ai import transcribe_audio, process_ai_reply

router = Router()

@router.message(F.voice | F.audio)
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