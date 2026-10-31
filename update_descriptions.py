import sys
import json
import os
from pathlib import Path
import wikipediaapi

# Добавляем корень проекта в путь
sys.path.append(str(Path(__file__).resolve().parent))

from app import app, db, Fish

# Настраиваем клиент Википедии (указываем User-Agent согласно правилам Wikipedia API)
wiki = wikipediaapi.Wikipedia(
    user_agent='FishingPortalBot/1.0 (contact@example.com)',
    language='ru'
)


def get_wiki_data(fish_name, subspecies=None):
    """
    Ищет страницу в Википедии по названию или научному названию рыбы.
    Возвращает краткое/полное описание и прямую ссылку на изображение, если есть.
    """
    page = None

    # 1. Пробуем найти по латинскому/научному названию (subspecies)
    if subspecies:
        page = wiki.page(subspecies)

    # 2. Если не найдено или нет subspecies — ищем по русскому названию
    if not page or not page.exists():
        page = wiki.page(fish_name)

    if not page.exists():
        # 3. Попытка поиска без лишних уточняющих слов
        clean_name = fish_name.split('(')[0].strip()
        page = wiki.page(clean_name)

    if page.exists():
        # Выбираем описание (первые 3-4 абзаца или весь summary)
        summary = page.summary
        if summary and len(summary.strip()) > 50:
            return {
                'description': summary.strip(),
                'title': page.title,
                'url': page.fullurl
            }

    return None


def update_fish_descriptions_and_json():
    with app.app_context():
        fishes = Fish.query.all()
        print(f"[+] Найдено рыб в базе: {len(fishes)}")

        updated_count = 0

        for fish in fishes:
            print(f"\n[?] Поиск информации для: {fish.name} ({fish.subspecies or 'без латыни'})...")

            wiki_data = get_wiki_data(fish.name, fish.subspecies)

            if wiki_data:
                # Обновляем описание в объекте модели
                fish.description = wiki_data['description']

                # Если у рыбы нет короткого описания, можно взять первые 150 символов
                if not fish.short_desc:
                    fish.short_desc = wiki_data['description'][:150] + "..."

                updated_count += 1
                print(f"  [✓] Описание обновлено с Википедии (Статья: '{wiki_data['title']}')")
            else:
                print(f"  [-] Не удалось найти подходящую статью в Википедии для '{fish.name}'")

        if updated_count > 0:
            db.session.commit()
            print(f"\n[УСПЕХ] Успешно обновлено описаний в базе данных: {updated_count}")

            # Синхронизируем изменения с fishes.json, чтобы данные не терялись при пересоздании БД
            sync_to_json()
        else:
            print("\n[INFO] Изменений не требуется.")


def sync_to_json():
    """Сохраняет актуальные данные из базы SQLite обратно в файл fishes.json."""
    json_path = os.path.join(app.root_path, 'data', 'fishes.json')
    if not os.path.exists(json_path):
        json_path = os.path.join(app.root_path, 'fishes.json')

    if not os.path.exists(json_path):
        print("[-] Файл fishes.json не найден для синхронизации.")
        return

    with app.app_context():
        fishes = Fish.query.all()
        fish_columns = [column.name for column in Fish.__table__.columns]

        fishes_list = []
        for f in fishes:
            fish_dict = {col: getattr(f, col) for col in fish_columns}
            fishes_list.append(fish_dict)

        with open(json_path, 'w', encoding='utf-8') as file:
            json.dump(fishes_list, file, ensure_ascii=False, indent=4)

        print(f"[+] Файл {json_path} успешно синхронизирован с БД.")


if __name__ == "__main__":
    update_fish_descriptions_and_json()