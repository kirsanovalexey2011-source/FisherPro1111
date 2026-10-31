import json
import os
import math
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

try:
    import folium
except ImportError:
    folium = None

app = Flask(__name__)

# --- НАСТРОЙКИ ПРИЛОЖЕНИЯ И БАЗЫ ДАННЫХ ---
app.config['SECRET_KEY'] = 'fish-expert-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

YANDEX_API_KEY = "ТВОЙ_КЛЮЧ_API"

FAMILY_TRANSLATIONS = {
    'Acipenseridae': 'Осетровые',
    'Anguillidae': 'Угревые',
    'Bagridae': 'Косаковые (Багровые)',
    'Balitoridae': 'Балиторовые',
    'Catostomidae': 'Чукучановые',
    'Centrarchidae': 'Ушастые окуни',
    'Channidae': 'Змееголовые',
    'Clupeidae': 'Сельдевые',
    'Cobitidae': 'Вьюновые',
    'Comephoridae': 'Голомяновые',
    'Coregonidae': 'Сиговые',
    'Cottidae': 'Керчаковые (Подкаменщики)',
    'Cottocomephoridae': 'Желтокрылковые (Байкальские подкаменщики)',
    'Cyprinidae': 'Карповые',
    'Esocidae': 'Щуковые',
    'Gadidae': 'Тресковые',
    'Gasterosteidae': 'Колюшковые',
    'Gobiidae': 'Бычковые',
    'Ictaluridae': 'Кошачьи сомы (Икталуровые)',
    'Lotidae': 'Налимовые',
    'Nemacheilidae': 'Немахиловые (Усатые гольцы)',
    'Odontobutidae': 'Головешковые',
    'Osmeridae': 'Корюшковые',
    'Percidae': 'Окуневые',
    'Petromyzontidae': 'Миноговые',
    'Pleuronectidae': 'Камбаловые',
    'Salmonidae': 'Лососёвые',
    'Sciaenidae': 'Горбылевые',
    'Siluridae': 'Сомовые',
    'Scombridae': 'Скумбриевые',
    'Thymallidae': 'Хариусовые',
}


# --- МОДЕЛИ ДАННЫХ (ЭТАП 2: СОЦИАЛКА) ---

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    avatar = db.Column(db.String(255), default='default_avatar.png')
    bio = db.Column(db.Text, nullable=True)
    favorite_tackle = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    likes = db.relationship('Like', backref='user', lazy='dynamic')


class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    spot_id = db.Column(db.String(100), nullable=False)  # Подходит как для DB, так и для JSON spot_id


class Like(db.Model):
    __tablename__ = 'likes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    spot_id = db.Column(db.String(100), nullable=False)

    __table_args__ = (db.UniqueConstraint('user_id', 'spot_id', name='unique_user_spot_like'),)


class Fish(db.Model):
    __tablename__ = 'fishes'

    id = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subspecies = db.Column(db.String(100), nullable=True)
    family = db.Column(db.String(100), nullable=True)
    rarity = db.Column(db.String(100), nullable=True)
    short_desc = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    difficulty = db.Column(db.String(50), nullable=True)
    taste = db.Column(db.String(50), nullable=True)
    baits = db.Column(db.String(255), nullable=True)
    tackle = db.Column(db.String(255), nullable=True)
    methods = db.Column(db.String(255), nullable=True)
    habitat_region = db.Column(db.String(255), nullable=True)
    habitat = db.Column(db.String(255), nullable=True)
    image = db.Column(db.String(500), nullable=True)


class Spot(db.Model):
    __tablename__ = 'spots'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    waterbody = db.Column(db.String(100), nullable=True)
    fish_caught = db.Column(db.String(100), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lon = db.Column(db.Float, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)


class Waterbody(db.Model):
    __tablename__ = 'waterbodies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


KNOWN_COORDS = {
    "нева": (59.9343, 30.3351),
    "река нева": (59.9343, 30.3351),
    "ладога": (60.1000, 31.1000),
    "ладожское озеро": (60.1000, 31.1000),
    "финский залив": (59.9800, 29.7000),
    "муринский ручей": (60.0350, 30.3850),
    "волга": (56.3269, 44.0059),
    "москва-река": (55.7558, 37.6173),
    "дамба": (59.9910, 29.7340),
    "сестрорецк": (60.0961, 29.9675)
}


class JSONPagination:
    def __init__(self, items, page, per_page):
        self.total = len(items)
        self.per_page = per_page
        self.page = page
        self.pages = max(1, int(math.ceil(self.total / float(per_page))))

        start = (page - 1) * per_page
        end = start + per_page
        self.items = items[start:end]

        self.has_prev = self.page > 1
        self.has_next = self.page < self.pages
        self.prev_num = self.page - 1 if self.has_prev else None
        self.next_num = self.page + 1 if self.has_next else None

    def iter_pages(self, left_edge=1, right_edge=1, left_current=2, right_current=2):
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
                    (num >= self.page - left_current and num <= self.page + right_current) or \
                    num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num


_CACHE = {}


def load_json_file(filename):
    if filename in _CACHE:
        return _CACHE[filename]

    paths = [
        os.path.join(app.root_path, 'data', filename),
        os.path.join(app.root_path, filename)
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    _CACHE[filename] = data
                    return data
            except Exception:
                pass
    return []


def clean_waterbody_name(raw_name):
    if not raw_name or not isinstance(raw_name, str):
        return "Неизвестный водоём"

    clean = raw_name.strip()
    clean = re.sub(r'\(vk\.com/[^\)]+\)', '', clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r'https?://[^\s]+', '', clean).strip()

    if not clean or 'vk.com' in clean.lower() or 'рыбацкая точка' in clean.lower():
        return "Неизвестный водоём"

    return clean


def is_valid_image_url(url):
    if not url or not isinstance(url, str):
        return False
    url_lower = url.lower().strip()

    if any(domain in url_lower for domain in ['rutube.ru', 'youtube.com', 'youtu.be', 'vk.com/video']):
        return False

    image_exts = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg')

    if any(ext in url_lower for ext in image_exts) or \
            'userapi.com' in url_lower or \
            'imx.vk.com' in url_lower or \
            url_lower.startswith('/static/') or \
            'user_content' in url_lower:
        return True

    return False


def normalize_spot(spot):
    raw_place = spot.get('waterbody') or spot.get('location') or spot.get('place') or ''
    spot['waterbody_clean'] = clean_waterbody_name(raw_place)
    spot['fish_clean'] = spot.get('fish_caught') or spot.get('fish') or spot.get('fish_species') or 'Не указана'
    spot['tackle_clean'] = spot.get('tackle') or spot.get('gear') or 'Не указана'

    raw_images = []
    if isinstance(spot.get('images'), list):
        raw_images.extend(spot['images'])

    for field in ['image_url', 'image', 'photo', 'cover']:
        val = spot.get(field)
        if val:
            if isinstance(val, list):
                raw_images.extend(val)
            else:
                raw_images.append(val)

    valid_images = [img for img in raw_images if is_valid_image_url(img)]

    if valid_images:
        spot['images'] = valid_images
        spot['cover_image'] = valid_images[0]
    else:
        spot['images'] = []
        spot['cover_image'] = None

    lat = spot.get('lat') or spot.get('latitude')
    lon = spot.get('lon') or spot.get('longitude')

    if lat is None or lon is None:
        text_to_check = (str(spot.get('title', '')) + " " + str(spot['waterbody_clean']) + " " + str(
            spot.get('description', ''))).lower()
        for key, coords in KNOWN_COORDS.items():
            if key in text_to_check:
                lat, lon = coords
                break

    try:
        spot['lat'] = float(lat) if lat is not None else 59.9343
        spot['lon'] = float(lon) if lon is not None else 30.3351
    except (ValueError, TypeError):
        spot['lat'] = 59.9343
        spot['lon'] = 30.3351

    return spot


def load_spots():
    if 'normalized_spots' in _CACHE:
        return _CACHE['normalized_spots']

    raw_spots = load_json_file('spots.json')
    normalized = [normalize_spot(s) for s in raw_spots]
    _CACHE['normalized_spots'] = normalized
    return normalized


# === ЭТАП 2: РОУТЫ СОЦИАЛКИ (ПРОФИЛИ, ЛАЙКИ, КОММЕНТАРИИ) ===

@app.route('/login_test')
def login_test():
    """Быстрый вход для тестирования функций социалки"""
    user = User.query.first()
    if not user:
        user = User(username='БывалыйРыбак', email='fisher@example.com', bio='Ловлю на спиннинг и фидер с 2010 года.',
                    favorite_tackle='Спиннинг')
        db.session.add(user)
        db.session.commit()
    login_user(user)
    flash(f'Вы вошли как {user.username}', 'success')
    return redirect(url_for('index'))


@app.route('/user/<username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    # Загружаем отчёты пользователя с защитой от ошибок старых таблиц БД
    db_spots = []
    try:
        db_spots = Spot.query.filter_by(user_id=user.id).all()
    except Exception:
        db.session.rollback()

    total_spots = len(db_spots)
    total_likes = 0
    for s in db_spots:
        try:
            total_likes += Like.query.filter_by(spot_id=str(s.id)).count()
        except Exception:
            db.session.rollback()

    return render_template(
        'profile.html',
        profile_user=user,
        spots=db_spots,
        total_spots=total_spots,
        total_likes=total_likes
    )


@app.route('/spot/<spot_id>/like', methods=['POST'])
def toggle_like(spot_id):
    if not current_user.is_authenticated:
        return jsonify({'error': 'Unauthorized'}), 401

    spot_id_str = str(spot_id)
    existing_like = Like.query.filter_by(user_id=current_user.id, spot_id=spot_id_str).first()

    if existing_like:
        db.session.delete(existing_like)
        liked = False
    else:
        new_like = Like(user_id=current_user.id, spot_id=spot_id_str)
        db.session.add(new_like)
        liked = True

    db.session.commit()
    total_likes = Like.query.filter_by(spot_id=spot_id_str).count()

    return jsonify({'liked': liked, 'total_likes': total_likes})


@app.route('/spot/<spot_id>/comment', methods=['POST'])
@login_required
def add_comment(spot_id):
    text = request.form.get('text', '').strip()
    if text:
        comment = Comment(text=text, user_id=current_user.id, spot_id=str(spot_id))
        db.session.add(comment)
        db.session.commit()
        flash('Комментарий добавлен!', 'success')
    return redirect(url_for('spot_detail', spot_id=spot_id))


# === ОСНОВНЫЕ МАРШРУТЫ ===

@app.route('/')
def index():
    spots = load_spots()[:3]
    fishes = Fish.query.limit(3).all()
    if not fishes:
        fishes = load_json_file('fishes.json')[:3]
    return render_template('index.html', recent_spots=spots, featured_fishes=fishes)


@app.route('/spots')
def spots():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('search', '').strip().lower()
    selected_fish = request.args.get('fish', '').strip()
    selected_place = request.args.get('place', '').strip()
    sort_order = request.args.get('sort', 'newest')

    all_spots = load_spots()
    filtered = []

    for s in all_spots:
        title = str(s.get('title') or s.get('name') or '').lower()
        desc = str(s.get('description') or s.get('content') or s.get('text') or '').lower()
        place = str(s['waterbody_clean']).lower()
        fish = str(s['fish_clean']).lower()

        if search_query and not (
                search_query in title or search_query in desc or search_query in place or search_query in fish):
            continue

        if selected_fish and selected_fish.lower() not in fish:
            continue

        if selected_place and selected_place.lower() not in place:
            continue

        filtered.append(s)

    if sort_order == 'oldest':
        filtered.sort(key=lambda x: str(x.get('date', '')))
    else:
        filtered.sort(key=lambda x: str(x.get('date', '')), reverse=True)

    pagination = JSONPagination(filtered, page=page, per_page=9)

    if 'fishes_list' not in _CACHE:
        _CACHE['fishes_list'] = sorted(list({s['fish_clean'] for s in all_spots if s['fish_clean'] != 'Не указана'}))
        _CACHE['places_list'] = sorted(
            list({s['waterbody_clean'] for s in all_spots if s['waterbody_clean'] != 'Неизвестный водоём'}))

    return render_template(
        'spots.html',
        spots=pagination.items,
        pagination=pagination,
        fishes_list=_CACHE['fishes_list'],
        places_list=_CACHE['places_list'],
        selected_search=search_query,
        selected_fish=selected_fish,
        selected_place=selected_place,
        sort_order=sort_order
    )


@app.route('/spot/<spot_id>')
def spot_detail(spot_id):
    all_spots = load_spots()
    spot = next((s for s in all_spots if str(s.get('id')) == str(spot_id)), None)
    if not spot:
        return "Отчёт не найден", 404

    spot_id_str = str(spot_id)
    comments = Comment.query.filter_by(spot_id=spot_id_str).order_by(Comment.created_at.desc()).all()
    likes_count = Like.query.filter_by(spot_id=spot_id_str).count()

    user_liked = False
    if current_user.is_authenticated:
        user_liked = Like.query.filter_by(user_id=current_user.id, spot_id=spot_id_str).first() is not None

    return render_template(
        'spot_detail.html',
        spot=spot,
        comments=comments,
        likes_count=likes_count,
        user_liked=user_liked,
        yandex_api_key=YANDEX_API_KEY
    )


spots_list = []


@app.route('/spots/add', methods=['POST'])
def add_spot():
    title = request.form.get('title')
    waterbody = request.form.get('waterbody')
    fish = request.form.get('fish')
    text = request.form.get('text')

    if title and text:
        user_id = current_user.id if current_user.is_authenticated else None
        new_spot = Spot(
            title=title,
            waterbody=waterbody,
            fish_caught=fish,
            description=text,
            user_id=user_id
        )
        db.session.add(new_spot)
        db.session.commit()
        _CACHE.pop('normalized_spots', None)

    return redirect(url_for('spots'))


@app.route('/map')
def map_page():
    all_spots = load_spots()

    if 'map_reports' not in _CACHE:
        reports = []
        species_set = set()

        for s in all_spots:
            fish_sp = s['fish_clean']
            if fish_sp != 'Не указана':
                species_set.add(fish_sp)

            reports.append({
                'id': s.get('id'),
                'title': s.get('title') or s.get('name') or 'Отчёт с рыбалки',
                'waterbody': s['waterbody_clean'],
                'fish_species': fish_sp,
                'info': s.get('description') or s.get('content') or s.get('text') or '',
                'lat': s['lat'],
                'lon': s['lon']
            })
        _CACHE['map_reports'] = reports
        _CACHE['species_list'] = sorted(list(species_set))

    return render_template(
        'map.html',
        reports=_CACHE['map_reports'],
        species_list=_CACHE['species_list'],
        yandex_api_key=YANDEX_API_KEY
    )


@app.route('/add_report', methods=['POST'])
def add_report():
    return redirect(url_for('map_page'))


@app.route('/fishes')
def fishes():
    search_query = (request.args.get('search') or request.args.get('q') or '').strip().lower()
    selected_family = request.args.get('family', '').strip().lower()
    selected_method = request.args.get('method', '').strip().lower()
    selected_region = request.args.get('region', '').strip().lower()

    if 'all_fishes' not in _CACHE:
        all_fishes_db = Fish.query.all()
        if not all_fishes_db:
            all_fishes_json = load_json_file('fishes.json')

            class DictObj:
                def __init__(self, d):
                    for k, v in d.items():
                        setattr(self, k, v)

            all_fishes_db = [DictObj(d) for d in all_fishes_json]

        families_set = set()
        methods_set = set()
        regions_set = set()

        for item in all_fishes_db:
            fam = getattr(item, 'family', None)
            if fam:
                families_set.add(str(fam).strip())

            meth = getattr(item, 'methods', None) or getattr(item, 'tackle', None)
            if meth:
                for m in re.split(r'[,;/]', str(meth)):
                    clean_m = m.strip()
                    if clean_m:
                        methods_set.add(clean_m)

            reg = getattr(item, 'habitat_region', None) or getattr(item, 'habitat', None)
            if reg:
                for r in re.split(r'[,;/]', str(reg)):
                    clean_r = r.strip()
                    if clean_r:
                        regions_set.add(clean_r)

        _CACHE['all_fishes'] = all_fishes_db
        _CACHE['families_set'] = sorted(list(families_set))
        _CACHE['methods_set'] = sorted(list(methods_set))
        _CACHE['regions_set'] = sorted(list(regions_set))

    filtered_fishes = []
    for f in _CACHE['all_fishes']:
        f_name = str(getattr(f, 'name', '') or '').lower()
        f_subspecies = str(getattr(f, 'subspecies', '') or '').lower()
        f_latin = str(getattr(f, 'latin_name', '') or '').lower()
        f_family = str(getattr(f, 'family', '') or '').lower()
        f_methods = str(getattr(f, 'methods', '') or getattr(f, 'tackle', '') or '').lower()
        f_region = str(getattr(f, 'habitat_region', '') or getattr(f, 'habitat', '') or '').lower()
        f_desc = str(getattr(f, 'description', '') or getattr(f, 'short_desc', '') or '').lower()

        if search_query and not (
                search_query in f_name or search_query in f_subspecies or search_query in f_latin or search_query in f_desc):
            continue

        if selected_family and f_family != selected_family:
            continue

        if selected_method and selected_method not in f_methods:
            continue

        if selected_region and selected_region not in f_region:
            continue

        filtered_fishes.append(f)

    return render_template(
        'fishes.html',
        fishes=filtered_fishes,
        families=_CACHE['families_set'],
        methods=_CACHE['methods_set'],
        regions=_CACHE['regions_set'],
        family_names=FAMILY_TRANSLATIONS,
        selected_search=search_query,
        selected_family=selected_family,
        selected_method=selected_method,
        selected_region=selected_region
    )


@app.route('/fish/<fish_id>')
def fish_detail(fish_id):
    fish = db.session.get(Fish, fish_id)
    if not fish:
        fishes_data = load_json_file('fishes.json')
        fish_dict = next((f for f in fishes_data if str(f.get('id')) == str(fish_id)), None)
        if fish_dict:
            class DictObj:
                def __init__(self, d):
                    for k, v in d.items():
                        setattr(self, k, v)

            fish = DictObj(fish_dict)

    if not fish:
        return "Рыба не найдена", 404

    return render_template('fish_detail.html', fish=fish, family_names=FAMILY_TRANSLATIONS)


@app.route('/waters')
@app.route('/water')
def waters():
    wb = load_json_file('waterbodies.json')
    return render_template('waters.html', waterbodies=wb)


@app.route('/water/<wb_id>')
def water_detail(wb_id):
    wb_list = load_json_file('waterbodies.json')
    wb = next((item for item in wb_list if str(item.get("id")) == str(wb_id)), None)
    if not wb:
        return "Водоём не найден", 404
    return render_template('water_detail.html', wb=wb)


@app.route('/tackle')
def tackle():
    tackle_list = load_json_file('tackle.json')
    return render_template('tackle.html', tackle_list=tackle_list)


@app.route('/tackle/<tackle_id>')
def tackle_detail(tackle_id):
    tackle_list = load_json_file('tackle.json')
    item = next((t for t in tackle_list if str(t.get('id')) == str(tackle_id)), None)
    if not item:
        return "Снасть не найдена", 404
    return render_template('tackle_detail.html', tackle=item)


@app.route('/knots')
def knots():
    return render_template('knots.html', knots=load_json_file('knots.json'))


@app.route('/knot/<knot_id>')
def knot_detail(knot_id):
    knots = load_json_file('knots.json')
    knot = next((k for k in knots if str(k.get('id')) == str(knot_id)), None)
    if not knot:
        return "Узел не найден", 404
    return render_template('knot_detail.html', knot=knot)


@app.route('/recipes')
def recipes():
    return render_template('recipes.html', recipes=load_json_file('recipes.json'))


@app.route('/recipe/<recipe_id>')
def recipe_detail(recipe_id):
    recipes = load_json_file('recipes.json')
    recipe = next((r for r in recipes if str(r.get('id')) == str(recipe_id)), None)
    if not recipe:
        return "Рецепт не найден", 404
    return render_template('recipe_detail.html', recipe=recipe)


@app.route('/contacts')
def contacts():
    return render_template('contacts.html')


@app.route('/tools')
def tools():
    return render_template('tools.html')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)