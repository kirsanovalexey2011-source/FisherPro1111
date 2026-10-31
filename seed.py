import sys
import json
import os
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.append(str(Path(__file__).resolve().parent))

from app import app, db, Fish


def load_fishes_from_json():
    """Загрузка полной базы рыб из JSON-файла."""
    possible_paths = [
        os.path.join(app.root_path, 'data', 'fishes.json'),
        os.path.join(app.root_path, 'fishes.json'),
        Path(__file__).resolve().parent / 'data' / 'fishes.json',
        Path(__file__).resolve().parent / 'fishes.json'
    ]

    for path in possible_paths:
        if os.path.exists(path):
            print(f"[+] Найден JSON-файл: {path}")
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)

    print("[-] Ошибка: файл fishes.json не найден!")
    return []


def seed_database():
    with app.app_context():
        print("[+] Пересоздаем таблицы базы данных...")
        db.drop_all()  # Сбрасываем старые таблицы с некорректной структурой
        db.create_all()  # Создаем с нуля

        fishes_data = load_fishes_from_json()

        if not fishes_data:
            print("[!] Нет данных для импорта.")
            return

        # Получаем список колонок, определенных в модели Fish в app.py
        fish_columns = {column.name for column in Fish.__table__.columns}

        added_count = 0
        for fish_dict in fishes_data:
            # Оставляем только те поля из JSON, которые есть в модели Fish
            filtered_data = {k: v for k, v in fish_dict.items() if k in fish_columns}

            # Если в JSON нет ключа id, или он пустой — пропускаем или даем заполниться
            if not filtered_data.get('id'):
                continue

            fish = Fish(**filtered_data)
            db.session.add(fish)
            added_count += 1

        db.session.commit()
        print(f"\n[УСПЕХ] База успешно заполнена из fishes.json! Добавлено рыб: {added_count}")


if __name__ == "__main__":
    seed_database()