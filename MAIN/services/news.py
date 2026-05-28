import asyncio
import time
import feedparser
from config import logger, LATEST_NEWS_CACHE

async def update_news_task():
    """Фоновая цикличная задача парсинга новостей (RSS)"""
    rss_url = "https://www.vedomosti.ru/rss/news.xml" 
    while True:
        try:
            logger.info("Обновление единой ленты новостей...")
            loop = asyncio.get_running_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, rss_url)
            if feed.entries:
                news_items = [f"- {entry.title}" for entry in feed.entries[:5]]
                LATEST_NEWS_CACHE["text"] = "\n".join(news_items)
                LATEST_NEWS_CACHE["updated_at"] = time.time()
                logger.info("Единая лента новостей успешно обновлена.")
        except Exception as e:
            logger.error(f"Ошибка при парсинге новостей: {e}")
        await asyncio.sleep(1800)