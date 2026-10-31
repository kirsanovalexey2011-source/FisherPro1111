import json
import sqlite3

# Читаем JSON и обновляем внешние ссылки
with open('fishes.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Заменяем битые ссылки Unsplash на стабильные фото с Википедии/Wikimedia
WIKI_IMAGES = {
    "northern-pike": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Esox_lucius_Zool_Mus_Kiel.jpg/800px-Esox_lucius_Zool_Mus_Kiel.jpg",
    "amur-pike": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Esox_reichertii.jpg/800px-Esox_reichertii.jpg",
    "river-perch": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/07/Perca_fluatilis_Prague_Vltava_2.jpg/800px-Perca_fluatilis_Prague_Vltava_2.jpg",
    "zander": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e8/Sander_lucioperca_Prague_Vltava_3.jpg/800px-Sander_lucioperca_Prague_Vltava_3.jpg",
    "wels-catfish": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/82/Silurus_glanis_01.jpg/800px-Silurus_glanis_01.jpg",
    "crucian-gold": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Carassius_carassius_Prague_Vltava_1.jpg/800px-Carassius_carassius_Prague_Vltava_1.jpg",
    "default": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0a/Fish_icon.svg/800px-Fish_icon.svg.png"
}

for fish in data:
    fish['image'] = WIKI_IMAGES.get(fish['id'], WIKI_IMAGES['default'])

with open('fishes.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("fishes.json обновлен!")