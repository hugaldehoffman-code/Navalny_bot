import re
from aiogram import Router, F
from aiogram.types import Message
from config import bot, logger, BUTTON_PROMPTS, BOT_INFO
from services.ai import transcribe_audio, process_ai_reply

router = Router()

_NAME_PATTERN = re.compile(
    r"\b(навальн[а-яё]*|алексей[а-яё]*|лёш[а-яё]*|леш[а-яё]*|лёх[а-яё]*|лех[а-яё]*|новичк[а-яё]*)\b",
    re.IGNORECASE,
)

def _is_addressed_to_bot(message: Message) -> bool:
    """Голосовое адресовано боту: личка, реплай на бота, @упоминание или триггер-слово в caption."""
    if message.chat.type == "private":
        return True
    if message.reply_to_message and message.reply_to_message.from_user.id == BOT_INFO.get("id"):
        return True
    caption = (message.caption or "").lower()
    bot_username = BOT_INFO.get("username", "")
    if bot_username and f"@{bot_username}".lower() in caption:
        return True
    if _NAME_PATTERN.search(caption):
        return True
    return False


@router.message(F.voice | F.audio)
async def voice_handler(message: Message):
    if not _is_addressed_to_bot(message):
        return

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