import aiohttp
from aiogram.types import BufferedInputFile
from config import logger, ZVUKOGRAM_TOKEN, ZVUKOGRAM_EMAIL, ZVUKOGRAM_VOICE

async def generate_voice_reply(text: str) -> BufferedInputFile | None:
    url = "https://zvukogram.com/index.php?r=api/text"
    data = {
        "token": ZVUKOGRAM_TOKEN, "email": ZVUKOGRAM_EMAIL, "voice": ZVUKOGRAM_VOICE,
        "text": text, "format": "mp3", "speed": 1, "sample_rate": 24000, "bitrate": 192, "channels": 1
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, timeout=15) as response:
                if response.status != 200: 
                    return None
                result = await response.json()
                
            if result.get("status") == 1:
                audio_url = result.get("file")
                async with session.get(audio_url, timeout=15) as audio_response:
                    if audio_response.status == 200:
                        return BufferedInputFile(await audio_response.read(), filename=f"reply_{result.get('id')}.mp3")
    except Exception as e:
        logger.error(f"Исключение при обращении к Zvukogram: {e}")
    return None