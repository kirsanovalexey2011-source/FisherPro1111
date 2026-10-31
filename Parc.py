import json
import os
import requests

API_URL = "https://app.nordkroft.ru/api/Map/locations"

# Сохраняем сразу в подпапку data/
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
TARGET_FILE = os.path.join(DATA_DIR, 'spots.json')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://app.nordkroft.ru/map"
}


def fetch_and_import():
    print(f"Загрузка точек с {API_URL}...")
    try:
        response = requests.get(API_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        items = response.json()
    except Exception as e:
        print(f"Ошибка загрузки данных: {e}")
        return

    print(f"Получено {len(items)} мест от сервера. Обработка...")

    existing = []
    if os.path.exists(TARGET_FILE):
        try:
            with open(TARGET_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            existing = []

    # Множество для исключения дубликатов по координатам
    known_coords = {
        (round(float(s['lat']), 4), round(float(s['lon']), 4))
        for s in existing if 'lat' in s and 'lon' in s
    }

    added_count = 0
    for item in items:
        coords = item.get("coordinates")
        if not coords or len(coords) < 2:
            continue

        try:
            lat = float(coords[0])
            lon = float(coords[1])
        except (ValueError, TypeError):
            continue

        if lat == 0 or lon == 0:
            continue

        place_id = item.get("placeId")
        title = item.get("name") or "Рыболовное место Nordkroft"
        description = item.get("description") or "Сведения о месте ловли с карты Nordkroft."

        # Безопасное извлечение типа водоема
        raw_water = item.get("waterSpace")
        if isinstance(raw_water, list) and raw_water:
            waterbody = ", ".join(map(str, raw_water)).capitalize()
        elif isinstance(raw_water, str) and raw_water.strip():
            waterbody = raw_water.capitalize()
        else:
            waterbody = "Водоём СПб/ЛО"

        # Безопасное извлечение рыбы
        fishes = item.get("caughtFishes", [])
        if isinstance(fishes, list) and fishes:
            fish_str = ", ".join(map(str, fishes)).capitalize()
        else:
            fish_str = "Разная рыба"

        # Способы ловли
        prefs = item.get("userPreferences", [])
        if isinstance(prefs, list) and prefs:
            tackle_info = ", ".join(map(str, prefs))
        else:
            tackle_info = "Спиннинг / Поплавок / Фидер"

        coord_key = (round(lat, 4), round(lon, 4))
        if coord_key not in known_coords:
            existing.append({
                "id": f"nord_{place_id}",
                "title": title,
                "description": description,
                "waterbody": waterbody,
                "fish_caught": fish_str,
                "tackle": tackle_info,
                "lat": lat,
                "lon": lon,
                "source": "Nordkroft"
            })
            known_coords.add(coord_key)
            added_count += 1

    with open(TARGET_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"Успех! Файл сохранен по пути: {TARGET_FILE}")
    print(f"Добавлено {added_count} новых мест (всего в базе: {len(existing)}).")


if __name__ == '__main__':
    fetch_and_import()