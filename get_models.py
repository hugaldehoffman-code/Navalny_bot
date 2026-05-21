import asyncio
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Загружаем переменные из .env
current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, ".env"))

async def fetch_all_models():
    # Инициализируем клиент с вашим URL шлюза
    client = AsyncOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://gptunnel.ru/v1"
    )
    
    try:
        print("Получаем список моделей от GPTunnel...")
        # Метод библиотеки, который делает запрос к v1/models
        models_page = await client.models.list()
        
        print("\n--- ДОСТУПНЫЕ МОДЕЛИ ---")
        # Перебираем полученные данные и выводим только их ID (названия для кода)
        for model in models_page.data:
            print(f"• {model.id}")
        print("------------------------\n")
            
    except Exception as e:
        print(f"Не удалось получить список. Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(fetch_all_models())