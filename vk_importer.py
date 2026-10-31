import os
import sys
import re
import json
import time
from pathlib import Path

# ----------------------------------------------------------------------
# НАСТРОЙКИ
# ----------------------------------------------------------------------
VK_SERVICE_TOKEN = "172115a1172115a1172115a13e14655f4a11721172115a17de5d8616bec7494e0bce0d5"

# Домен группы ВК (vk.com/fp78ru)
COMMUNITY_DOMAINS = [
    'fp78ru'
]

# Пути к файлам
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
SPOTS_FILE = DATA_DIR / 'spots.json'


# ----------------------------------------------------------------------


def extract_image_url(post):
    """Извлекает ссылку на самое крупное изображение из прикреплений поста."""
    if 'attachments' not in post:
        return None

    for attach in post['attachments']:
        if attach.get('type') == 'photo':
            photo = attach['photo']
            sizes = photo.get('sizes', [])
            if sizes:
                sorted_sizes = sorted(sizes, key=lambda x: x.get('width', 0), reverse=True)
                return sorted_sizes[0].get('url')
    return None


def clean_text(text):
    """Очищает текст от хештегов и служебных ссылок VK."""
    if not text:
        return ""
    text = re.sub(r'#\w+', '', text)
    text = re.sub(r'\[club\d+\|([^\]]+)\]', r'\1', text)
    text = re.sub(r'\[id\d+\|([^\]]+)\]', r'\1', text)
    return text.strip()


def load_existing_spots():
    """Загружает существующие отчеты из JSON файла."""
    if not DATA_DIR.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not SPOTS_FILE.exists():
        with open(SPOTS_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return []

    try:
        with open(SPOTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_spots(spots_list):
    """Сохраняет массив отчетов в JSON файл."""
    with open(SPOTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(spots_list, f, ensure_ascii=False, indent=2)


def import_all_vk_posts():
    """Загружает МАКСИМАЛЬНО ВСЕ посты из VK и сохраняет их в spots.json."""
    if not VK_SERVICE_TOKEN:
        print("[-] Ошибка: Укажите VK_SERVICE_TOKEN!")
        return

    import vk_api

    vk_session = vk_api.VkApi(token=VK_SERVICE_TOKEN)
    vk = vk_session.get_api()

    existing_spots = load_existing_spots()
    existing_ids = {spot.get('vk_post_id') for spot in existing_spots if 'vk_post_id' in spot}

    next_id = max([spot.get('id', 0) for spot in existing_spots], default=0) + 1
    total_imported = 0

    for domain in COMMUNITY_DOMAINS:
        print(f"\n[+] Начинаем ПОЛНУЮ выгрузку сообщества: vk.com/{domain}...")

        offset = 0
        batch_size = 100
        community_imported = 0

        while True:
            try:
                response = vk.wall.get(domain=domain, count=batch_size, offset=offset)
                items = response.get('items', [])
                total_wall_posts = response.get('count', 0)

                if not items:
                    break

                for post in items:
                    post_id = post.get('id')
                    text = post.get('text', '')
                    image_url = extract_image_url(post)

                    # Пропускаем ПОЛНОСТЬЮ пустые посты (где нет ни текста, ни картинок)
                    if not text and not image_url:
                        continue

                    # Пропускаем дубликаты по уникальному ID поста ВК
                    if post_id in existing_ids:
                        continue

                    cleaned_text = clean_text(text)

                    # Формируем заголовок
                    if cleaned_text:
                        title_line = cleaned_text.split('\n')[0][:60].strip()
                        title = title_line if title_line else f"Отчёт с водоёма №{post_id}"
                    else:
                        title = f"Фотоотчёт с водоёма №{post_id}"

                    new_spot = {
                        "id": next_id,
                        "vk_post_id": post_id,
                        "name": title,
                        "location": "Рыбацкая точка (vk.com/fp78ru)",
                        "type": "Отчет с водоема",
                        "description": (cleaned_text[:250] + "...") if len(cleaned_text) > 250 else (
                                    cleaned_text or "Фотоотчёт с водоёма."),
                        "features": cleaned_text or "Без текстового описания.",
                        "image": image_url
                    }

                    existing_spots.append(new_spot)
                    existing_ids.add(post_id)
                    next_id += 1
                    community_imported += 1
                    total_imported += 1

                # Сохраняем промежуточные результаты в JSON
                save_spots(existing_spots)
                print(
                    f"  [прогресс] Проверено постов: {offset + len(items)} из {total_wall_posts} | Добавлено новых: {community_imported}")

                offset += batch_size
                time.sleep(0.35)

            except Exception as e:
                print(f"  [-] Ошибка при загрузке блока постов (offset={offset}): {e}")
                break

        print(f"[✓] Завершена выгрузка vk.com/{domain}. Добавлено отчетов: {community_imported}")

    print(f"\n[УСПЕХ] Импорт завершен! Всего отчетов в базе/JSON: {len(existing_spots)}")


if __name__ == "__main__":
    import_all_vk_posts()