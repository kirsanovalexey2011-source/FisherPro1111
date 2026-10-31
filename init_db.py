import json
import os
from app import db, app, Fish

# Map латинских семейств на русские названия
FAMILY_MAP = {
    # Осетровые и угревые
    "Acipenseridae": "Осетровые",
    "Anguillidae": "Угревые",

    # Сомообразные и змееголовые
    "Bagridae": "Косатовые",
    "Siluridae": "Сомовые",
    "Ictaluridae": "Икталуровые (Кошачьи сомы)",
    "Channidae": "Змееголовые",

    # Окунеобразные и солнечники
    "Centrarchidae": "Ушастые окуни (Центрарховые)",
    "Percidae": "Окуневые",
    "Sinipercidae": "Китайские окуни",
    "Odontobutidae": "Головешковые",
    "Gobiidae": "Бычковые",

    # Сельдевые, вьюновые и карповые
    "Clupeidae": "Сельдевые",
    "Cobitidae": "Вьюновые",
    "Cyprinidae": "Карповые",
    "Nemacheilidae": "Гольцовые",

    # Подкаменщики и байкальские рыбы
    "Cottidae": "Рогатковые (Керчаковые)",
    "Cottocomephoridae": "Желтокрылковые (Глубинные широколобки)",
    "Comephoridae": "Голомяночные",

    # Колюшковые, корюшковые и тресковые
    "Gasterosteidae": "Колюшковые",
    "Osmeridae": "Корюшковые",
    "Lotidae": "Налимовые",

    # Лососеобразные, хариусовые, сиговые
    "Salmonidae": "Лососевые",
    "Thymallidae": "Хариусовые",
    "Coregonidae": "Сиговые",
    "Esocidae": "Щуковые",
    "Umbridae": "Умбровые",

    # Прочие
    "Petromyzontidae": "Миноговые",
    "Pleuronectidae": "Камбаловые",
    "Polyodontidae": "Веслоносые"
}

def init_database():
    json_path = 'fishes.json'

    if not os.path.exists(json_path):
        print(f"Ошибка: Файл {json_path} не найден!")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        fishes_data = json.load(f)

    with app.app_context():
        db.create_all()
        valid_columns = {column.name for column in Fish.__table__.columns}

        for fish_dict in fishes_data:
            filtered_dict = {k: v for k, v in fish_dict.items() if k in valid_columns}

            if 'id' not in filtered_dict:
                continue

            # --- НОРМАЛИЗАЦИЯ СЕМЕЙСТВА ---
            current_family = filtered_dict.get('family')
            if current_family in FAMILY_MAP:
                filtered_dict['family'] = FAMILY_MAP[current_family]

            existing = db.session.get(Fish, filtered_dict['id'])

            if not existing:
                db.session.add(Fish(**filtered_dict))
            else:
                for key, value in filtered_dict.items():
                    setattr(existing, key, value)

        db.session.commit()
        print("База данных успешно обновлена с нормализованными семействами!")

if __name__ == '__main__':
    init_database()