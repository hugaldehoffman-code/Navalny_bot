import time
import requests
from bs4 import BeautifulSoup

# Исходная страница со списком всех текстов
BASE_URL = "https://4oge.ru/russkij-jazyk/826-gotovye-szhatye-izlozhenija-po-tekstam-fipi.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_izlozheniya_links():
    print("Собираем ссылки на изложения...")
    response = requests.get(BASE_URL, headers=HEADERS)
    if response.status_code != 200:
        print(f"Ошибка загрузки главной страницы: {response.status_code}")
        return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Ищем блок с текстом статьи, где находятся все ссылки
    # На 4oge основной текст обычно лежит в блоке с классом ftext или основном контенте
    content_div = soup.find('div', class_='ftext') or soup.find('article')
    
    links = []
    if content_div:
        for a_tag in content_div.find_all('a', href=True):
            # Фильтруем ссылки, чтобы брать только переходы на внутренние страницы изложений
            if "/russkij-jazyk/" in a_tag['href'] and a_tag['href'] != BASE_URL:
                links.append((a_tag.text.strip(), a_tag['href']))
    
    # Удаляем дубликаты, если они есть, сохраняя порядок
    seen = set()
    unique_links = []
    for text, url in links:
        if url not in seen:
            seen.add(url)
            unique_links.append((text, url))
            
    print(f"Найдено уникальных ссылок: {len(unique_links)}")
    return unique_links

def parse_single_page(url):
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            return "Не удалось загрузить страницу."
        
        soup = BeautifulSoup(response.text, 'html.parser')
        content_div = soup.find('div', class_='ftext') or soup.find('article')
        
        if content_div:
            # Очищаем текст от лишних элементов (кнопок соцсетей, рекламы, если они внутри)
            for share_div in content_div.find_all('div', class_='share'): 
                share_div.decompose()
            return content_div.get_text(separator="\n", strip=True)
        return "Текст изложения не найден на странице."
    except Exception as e:
        return f"Ошибка при разборе страницы: {e}"

def main():
    links = get_izlozheniya_links()
    if not links:
        print("Список ссылок пуст. Завершение работы.")
        return

    filename = "Все_изложения_ОГЭ_2026.txt"
    
    with open(filename, "w", encoding="utf-8") as file:
        for index, (title, url) in enumerate(links, 1):
            print(f"Скачиваю [{index}/{len(links)}]: {title}...")
            
            # Скачиваем содержимое страницы
            page_text = parse_single_page(url)
            
            # Записываем в файл с красивым разделителем
            file.write(f"{'='*60}\n")
            file.write(f"№ {index}. {title}\n")
            file.write(f"Ссылка: {url}\n")
            file.write(f"{'='*60}\n\n")
            file.write(page_text)
            file.write("\n\n\n")
            
            # Пауза в 1 секунду, чтобы сайт не заблокировал за слишком частые запросы
            time.sleep(1)
            
    print(f"\nГотово! Все тексты успешно объединены и сохранены в файл: {filename}")

if __name__ == "__main__":
    main()