import json
import re
import time
import urllib.request
import urllib.parse

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def clean_title(text):
    """Очищает название вида от скобок и лишних символов."""
    if not text:
        return ""
    text = re.sub(r'\(.*?\)', '', text)
    text = text.split('/')[0]
    return text.strip()


def get_lovlu_image(fish_name):
    """Ищет фото рыбы на сайте lovlu.ru."""
    cleaned_name = clean_title(fish_name)
    encoded_query = urllib.parse.quote(cleaned_name)
    search_url = f"https://lovlu.ru/fishes?search={encoded_query}"

    req = urllib.request.Request(search_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8', errors='ignore')

            # Ищем прямые ссылки на оригиналы картинок: /uploads/fish_main/file/.../original.jpg
            matches = re.findall(r'/uploads/fish_main/file/\d+/[^\s"\']+\.(?:jpg|jpeg|png)', html, re.IGNORECASE)
            if matches:
                image_path = matches[0]
                if not image_path.startswith('http'):
                    return f"https://lovlu.ru{image_path}"
                return image_path
    except Exception:
        pass
    return None


def get_wikipedia_image(title, lang='ru'):
    """Фолбэк: поиск фото на Википедии."""
    if not title:
        return None

    encoded_title = urllib.parse.quote(title)
    url = f"https://{lang}.wikipedia.org/w/api.php?action=query&titles={encoded_title}&prop=pageimages&format=json&pithumbsize=800&redirects=1"

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            pages = data.get('query', {}).get('pages', {})
            for page_id, page_data in pages.items():
                if page_id != "-1" and 'thumbnail' in page_data:
                    return page_data['thumbnail']['source']
    except Exception:
        pass
    return None


def fetch_image_for_fish(fish):
    rus_name = fish.get('name', '')
    clean_rus = clean_title(rus_name)
    latin_name = clean_title(fish.get('latin_name') or fish.get('subspecies'))

    # 1. Пробуем получить фото с lovlu.ru по русскому названию
    img = get_lovlu_image(rus_name)
    if img:
        return img, 'lovlu.ru'

    # 2. Если на lovlu.ru не нашли, используем Википедию
    for query, lang in [(latin_name, 'ru'), (clean_rus, 'ru'), (latin_name, 'en')]:
        if query:
            img = get_wikipedia_image(query, lang=lang)
            if img:
                return img, 'Wikipedia'

    return None, None


def update_json_images():
    with open('fishes.json', 'r', encoding='utf-8') as f:
        fishes = json.load(f)

    updated_count = 0
    total = len(fishes)

    print("🚀 Начинаем поиск изображений (приоритет: lovlu.ru)...\n")

    for idx, fish in enumerate(fishes, start=1):
        rus_name = fish.get('name')
        latin_name = fish.get('latin_name') or fish.get('subspecies')

        print(f"[{idx}/{total}] Поиск: {rus_name}...")

        img_url, source = fetch_image_for_fish(fish)

        if img_url:
            fish['image'] = img_url
            updated_count += 1
            print(f"  ✅ Найдено [{source}]: {img_url}")
        else:
            print("  ❌ Изображение не найдено")

        time.sleep(0.5)

    with open('fishes.json', 'w', encoding='utf-8') as f:
        json.dump(fishes, f, ensure_ascii=False, indent=2)

    print(f"\n🎉 Завершено! Успешно обновлено изображений: {updated_count}/{total}")


if __name__ == '__main__':
    update_json_images()