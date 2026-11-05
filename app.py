import json
import os
import math
import re
import secrets
import hmac
import hashlib
import smtplib
import uuid
from email.message import EmailMessage
from urllib.parse import urlsplit, urlencode
from urllib.request import urlopen
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

try:
    import folium
except ImportError:
    folium = None

app = Flask(__name__)

# --- НАСТРОЙКИ ПРИЛОЖЕНИЯ И БАЗЫ ДАННЫХ ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fish-expert-dev-key-change-before-deploy')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '').lower() == 'true'
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024 + 64 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


def get_csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


@app.context_processor
def inject_csrf_token():
    return {'csrf_token': get_csrf_token}


def validate_csrf():
    submitted = request.form.get('_csrf_token', '')
    expected = session.get('_csrf_token', '')
    if not submitted or not expected or not hmac.compare_digest(submitted, expected):
        abort(400, description='Недействительный токен безопасности формы. Обновите страницу и повторите попытку.')


def safe_next_url(target):
    if not target:
        return None
    parsed = urlsplit(target)
    if (parsed.scheme or parsed.netloc or not target.startswith('/') or target.startswith('//')
            or '\\' in target or re.search(r'(?i)%5c', target)
            or any(ord(char) < 32 or ord(char) == 127 for char in target)):
        return None
    return target

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
    password_hash = db.Column(db.String(255), nullable=True)
    password_reset_token_hash = db.Column(db.String(64), nullable=True)
    password_reset_sent_at = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, nullable=True, default=False)
    email_verification_token_hash = db.Column(db.String(64), nullable=True)
    email_verification_sent_at = db.Column(db.DateTime, nullable=True)
    pending_email = db.Column(db.String(120), nullable=True)
    email_change_token_hash = db.Column(db.String(64), nullable=True)
    email_change_sent_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return bool(self.password_hash) and check_password_hash(self.password_hash, password)

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
    type = db.Column(db.String(50), nullable=True)
    region = db.Column(db.String(255), nullable=True)
    location = db.Column(db.String(255), nullable=True)
    fishes_json = db.Column(db.Text, nullable=True)
    methods = db.Column(db.Text, nullable=True)
    features = db.Column(db.Text, nullable=True)
    images_json = db.Column(db.Text, nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lon = db.Column(db.Float, nullable=True)


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

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('user_profile', username=current_user.username))
    if request.method == 'POST':
        validate_csrf()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not 3 <= len(username) <= 64 or not re.fullmatch(r'[A-Za-z0-9_.-]+', username):
            flash('Имя пользователя: 3–64 символа, только латинские буквы, цифры, точка, дефис и подчёркивание.', 'error')
        elif len(email) > 120 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            flash('Укажите корректный адрес электронной почты.', 'error')
        elif not 10 <= len(password) <= 1024:
            flash('Пароль должен содержать от 10 до 1024 символов.', 'error')
        elif User.query.filter(db.or_(db.func.lower(User.username) == username.lower(), db.func.lower(User.email) == email)).first():
            flash('Пользователь с таким именем или email уже существует.', 'error')
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash('Пользователь с таким именем или email уже существует.', 'error')
            else:
                login_user(user)
                try:
                    verification_token = make_one_time_email_token(user, 'verify')
                    send_email_verification(user, verification_token)
                    flash('Аккаунт создан. Проверьте почту и подтвердите адрес.', 'success')
                except Exception:
                    app.logger.exception('Could not send registration verification email')
                    flash('Аккаунт создан, но письмо подтверждения отправить не удалось. Его можно запросить в настройках профиля.', 'info')
                return redirect(url_for('user_profile', username=user.username))
    return render_template('auth.html', mode='register')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('user_profile', username=current_user.username))
    if request.method == 'POST':
        validate_csrf()
        identity = request.form.get('identity', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter(
            db.or_(db.func.lower(User.username) == identity.lower(),
                   db.func.lower(User.email) == identity.lower())
        ).first() if identity else None
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get('remember')))
            flash('Вы успешно вошли.', 'success')
            return redirect(safe_next_url(request.args.get('next')) or url_for('user_profile', username=user.username))
        if user and not user.password_hash:
            flash('Для этого старого аккаунта пароль ещё не настроен. Обратитесь к администратору для безопасного восстановления доступа.', 'error')
        else:
            flash('Неверный логин или пароль.', 'error')
    return render_template('auth.html', mode='login')


def send_password_reset_email(user, token):
    host = os.environ.get('SMTP_HOST')
    sender = os.environ.get('SMTP_FROM') or os.environ.get('SMTP_USER')
    if not host or not sender:
        raise RuntimeError('SMTP is not configured')

    port = int(os.environ.get('SMTP_PORT', '587'))
    message = EmailMessage()
    message['Subject'] = 'Восстановление пароля — ФишЭксперт'
    message['From'] = sender
    message['To'] = user.email
    public_base_url = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
    parsed_base_url = urlsplit(public_base_url)
    if (parsed_base_url.scheme not in ('https', 'http') or not parsed_base_url.netloc
            or parsed_base_url.username or parsed_base_url.password
            or (parsed_base_url.scheme == 'http' and parsed_base_url.hostname not in ('localhost', '127.0.0.1'))):
        raise RuntimeError('PUBLIC_BASE_URL must be a valid HTTPS URL')
    reset_url = public_base_url + url_for('reset_password', token=token)
    message.set_content(
        'Чтобы задать новый пароль, откройте ссылку (действует 30 минут):\n'
        + reset_url
        + '\nЕсли вы не запрашивали восстановление, просто проигнорируйте письмо.'
    )

    username = os.environ.get('SMTP_USER')
    password = os.environ.get('SMTP_PASSWORD')
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)


def make_reset_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='fish-expert-password-reset-v1')


def get_reset_user(token):
    try:
        payload = make_reset_serializer().loads(token, max_age=1800)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or not payload.get('user_id') or not payload.get('nonce'):
        return None
    user = db.session.get(User, payload['user_id'])
    if not user or not user.password_reset_token_hash or not user.password_reset_sent_at:
        return None
    token_hash = hashlib.sha256(payload['nonce'].encode('utf-8')).hexdigest()
    if not hmac.compare_digest(user.password_reset_token_hash, token_hash):
        return None
    return user


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        validate_csrf()
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter(db.func.lower(User.email) == email).first() if email else None
        if user and (not user.password_reset_sent_at or (datetime.utcnow() - user.password_reset_sent_at).total_seconds() >= 60):
            nonce = secrets.token_urlsafe(32)
            user.password_reset_token_hash = hashlib.sha256(nonce.encode('utf-8')).hexdigest()
            user.password_reset_sent_at = datetime.utcnow()
            db.session.commit()
            token = make_reset_serializer().dumps({'user_id': user.id, 'nonce': nonce})
            try:
                send_password_reset_email(user, token)
            except Exception:
                app.logger.exception('Could not send password reset email')
                user.password_reset_token_hash = None
                user.password_reset_sent_at = None
                db.session.commit()
        flash('Если аккаунт с таким email существует, мы отправили инструкцию по восстановлению.', 'info')
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = get_reset_user(token)
    if not user:
        flash('Ссылка недействительна или срок её действия истёк. Запросите новую.', 'error')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        validate_csrf()
        password = request.form.get('password', '')
        confirmation = request.form.get('password_confirmation', '')
        if not 10 <= len(password) <= 1024:
            flash('Пароль должен содержать от 10 до 1024 символов.', 'error')
        elif password != confirmation:
            flash('Пароли не совпадают.', 'error')
        else:
            user.set_password(password)
            user.password_reset_token_hash = None
            user.password_reset_sent_at = None
            db.session.commit()
            flash('Пароль обновлён. Теперь войдите с новым паролем.', 'success')
            return redirect(url_for('login'))
    return render_template('reset_password.html')




def make_email_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='fish-expert-email-confirm-v1')


def make_one_time_email_token(user, purpose):
    nonce = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(nonce.encode('utf-8')).hexdigest()
    if purpose == 'verify':
        user.email_verification_token_hash = token_hash
        user.email_verification_sent_at = datetime.utcnow()
    elif purpose == 'change':
        user.email_change_token_hash = token_hash
        user.email_change_sent_at = datetime.utcnow()
    else:
        raise ValueError('Unknown email token purpose')
    db.session.commit()
    return make_email_serializer().dumps({'user_id': user.id, 'nonce': nonce, 'purpose': purpose})


def send_account_email(recipient, subject, body):
    host = os.environ.get('SMTP_HOST')
    sender = os.environ.get('SMTP_FROM') or os.environ.get('SMTP_USER')
    if not host or not sender:
        raise RuntimeError('SMTP is not configured')
    public_base_url = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
    parsed = urlsplit(public_base_url)
    if (parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password
            or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1'))):
        raise RuntimeError('PUBLIC_BASE_URL must be a valid HTTPS URL')
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = sender
    message['To'] = recipient
    message.set_content(body)
    username = os.environ.get('SMTP_USER')
    password = os.environ.get('SMTP_PASSWORD')
    port = int(os.environ.get('SMTP_PORT', '587'))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)


def send_email_verification(user, token):
    link = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/') + url_for('verify_email', token=token)
    send_account_email(
        user.email, 'Подтверждение почты — ФишЭксперт',
        'Чтобы подтвердить адрес электронной почты, откройте ссылку (действует 24 часа):\n'
        + link + '\nЕсли вы не создавали аккаунт, проигнорируйте это письмо.'
    )


def send_email_change_confirmation(user, token):
    link = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/') + url_for('confirm_email_change', token=token)
    send_account_email(
        user.pending_email, 'Подтверждение нового адреса — ФишЭксперт',
        'Чтобы подтвердить новый адрес электронной почты, откройте ссылку (действует 24 часа):\n'
        + link + '\nЕсли вы не запрашивали смену адреса, проигнорируйте это письмо.'
    )


def get_email_token_user(token, purpose):
    try:
        payload = make_email_serializer().loads(token, max_age=86400)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or payload.get('purpose') != purpose:
        return None
    user = db.session.get(User, payload.get('user_id'))
    if not user or not payload.get('nonce'):
        return None
    nonce_hash = hashlib.sha256(payload['nonce'].encode('utf-8')).hexdigest()
    stored = user.email_verification_token_hash if purpose == 'verify' else user.email_change_token_hash
    if not stored or not hmac.compare_digest(stored, nonce_hash):
        return None
    return user


@app.route('/verify-email/<token>')
def verify_email(token):
    user = get_email_token_user(token, 'verify')
    if not user:
        flash('Ссылка подтверждения недействительна или устарела. Запросите новую в настройках профиля.', 'error')
    else:
        user.email_verified = True
        user.email_verification_token_hash = None
        user.email_verification_sent_at = None
        db.session.commit()
        flash('Электронная почта успешно подтверждена.', 'success')
    if current_user.is_authenticated:
        return redirect(url_for('edit_profile'))
    return redirect(url_for('login'))


@app.route('/user/email/resend', methods=['POST'])
@login_required
def resend_email_verification():
    validate_csrf()
    if current_user.email_verified:
        flash('Электронная почта уже подтверждена.', 'info')
    elif current_user.email_verification_sent_at and (datetime.utcnow() - current_user.email_verification_sent_at).total_seconds() < 60:
        flash('Повторное письмо можно запросить через минуту.', 'error')
    else:
        token = make_one_time_email_token(current_user, 'verify')
        try:
            send_email_verification(current_user, token)
            flash('Письмо для подтверждения отправлено.', 'success')
        except Exception:
            app.logger.exception('Could not send email verification')
            current_user.email_verification_token_hash = None
            current_user.email_verification_sent_at = None
            db.session.commit()
            flash('Не удалось отправить письмо. Проверьте настройки почтового сервера.', 'error')
    return redirect(url_for('edit_profile'))


@app.route('/user/email/change', methods=['POST'])
@login_required
def request_email_change():
    validate_csrf()
    new_email = request.form.get('new_email', '').strip().lower()
    password = request.form.get('current_password_for_email', '')
    if not current_user.check_password(password):
        flash('Для смены почты укажите верный текущий пароль.', 'error')
    elif not re.fullmatch(r'[^\\s@]+@[^\\s@]+\\.[^\\s@]+', new_email) or len(new_email) > 120:
        flash('Укажите корректный новый адрес электронной почты.', 'error')
    elif new_email == current_user.email.lower():
        flash('Это уже адрес, указанный в аккаунте.', 'info')
    elif User.query.filter(db.func.lower(User.email) == new_email).first():
        flash('Этот адрес уже используется другим аккаунтом.', 'error')
    elif current_user.email_change_sent_at and (datetime.utcnow() - current_user.email_change_sent_at).total_seconds() < 60:
        flash('Повторный запрос смены почты можно отправить через минуту.', 'error')
    else:
        current_user.pending_email = new_email
        token = make_one_time_email_token(current_user, 'change')
        try:
            send_email_change_confirmation(current_user, token)
            flash('Отправили письмо на новый адрес. Он изменится после подтверждения ссылки.', 'success')
        except Exception:
            app.logger.exception('Could not send email change confirmation')
            current_user.pending_email = None
            current_user.email_change_token_hash = None
            current_user.email_change_sent_at = None
            db.session.commit()
            flash('Не удалось отправить письмо. Проверьте настройки почтового сервера.', 'error')
    return redirect(url_for('edit_profile'))


@app.route('/confirm-email-change/<token>')
def confirm_email_change(token):
    user = get_email_token_user(token, 'change')
    if not user or not user.pending_email:
        flash('Ссылка смены адреса недействительна или устарела.', 'error')
    elif User.query.filter(db.func.lower(User.email) == user.pending_email.lower()).filter(User.id != user.id).first():
        user.pending_email = None
        user.email_change_token_hash = None
        user.email_change_sent_at = None
        db.session.commit()
        flash('Этот адрес уже занят другим аккаунтом. Запросите смену адреса заново.', 'error')
    else:
        user.email = user.pending_email
        user.pending_email = None
        user.email_verified = True
        user.email_change_token_hash = None
        user.email_change_sent_at = None
        user.email_verification_token_hash = None
        user.email_verification_sent_at = None
        db.session.commit()
        flash('Адрес электронной почты успешно изменён и подтверждён.', 'success')
    if current_user.is_authenticated and current_user.id == (user.id if user else None):
        return redirect(url_for('edit_profile'))
    return redirect(url_for('login'))


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    validate_csrf()
    logout_user()
    flash('Вы вышли из аккаунта.', 'success')
    return redirect(url_for('index'))


def save_profile_avatar(upload):
    if not upload or not upload.filename:
        return None
    extension = os.path.splitext(upload.filename)[1].lower()
    allowed_signatures = {
        '.jpg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.jpeg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.png': lambda data: data.startswith(b'\x89PNG\r\n\x1a\n'),
        '.webp': lambda data: data.startswith(b'RIFF') and data[8:12] == b'WEBP',
        '.gif': lambda data: data.startswith((b'GIF87a', b'GIF89a')),
    }
    validator = allowed_signatures.get(extension)
    if not validator:
        raise ValueError('Поддерживаются только изображения JPG, PNG, WEBP и GIF.')
    header = upload.stream.read(12)
    upload.stream.seek(0)
    if not validator(header):
        raise ValueError('Файл не похож на изображение выбранного формата.')
    filename = f'{uuid.uuid4().hex}{extension}'
    relative_dir = os.path.join('uploads', 'avatars')
    absolute_dir = os.path.join(app.static_folder, relative_dir)
    os.makedirs(absolute_dir, exist_ok=True)
    upload.save(os.path.join(absolute_dir, filename))
    return os.path.join(relative_dir, filename).replace(os.sep, '/')


@app.route('/user/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        validate_csrf()
        bio = request.form.get('bio', '').strip()
        favorite_tackle = request.form.get('favorite_tackle', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        password_confirmation = request.form.get('password_confirmation', '')
        avatar_upload = request.files.get('avatar')
        errors = []
        if len(bio) > 1000 or len(favorite_tackle) > 100:
            errors.append('Описание должно быть не длиннее 1000 символов, снасть — 100 символов.')
        changing_password = bool(current_password or new_password or password_confirmation)
        if changing_password:
            if not current_user.check_password(current_password):
                errors.append('Текущий пароль указан неверно.')
            elif not 10 <= len(new_password) <= 1024:
                errors.append('Новый пароль должен содержать от 10 до 1024 символов.')
            elif new_password != password_confirmation:
                errors.append('Новый пароль и подтверждение не совпадают.')
        try:
            new_avatar = save_profile_avatar(avatar_upload) if avatar_upload and avatar_upload.filename else None
        except ValueError as exc:
            errors.append(str(exc))
            new_avatar = None
        if errors:
            for error in errors:
                flash(error, 'error')
        else:
            if 'bio' in request.form:
                current_user.bio = bio or None
            if 'favorite_tackle' in request.form:
                current_user.favorite_tackle = favorite_tackle or None
            if new_avatar:
                current_user.avatar = new_avatar
            if changing_password:
                current_user.set_password(new_password)
                current_user.password_reset_token_hash = None
                current_user.password_reset_sent_at = None
            db.session.commit()
            flash('Изменения профиля сохранены.', 'success')
            return redirect(url_for('user_profile', username=current_user.username))
    return render_template('edit_profile.html')




@app.route('/user/<username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    # Profile statistics are calculated from existing tables; no new schema is required.
    db_spots = Spot.query.filter_by(user_id=user.id).order_by(Spot.id.desc()).all()
    total_likes = sum(Like.query.filter_by(spot_id=str(spot.id)).count() for spot in db_spots)
    comments = Comment.query.filter_by(user_id=user.id).order_by(Comment.created_at.desc()).limit(10).all()
    total_comments = Comment.query.filter_by(user_id=user.id).count()
    total_likes_given = Like.query.filter_by(user_id=user.id).count()
    caught_fish = [spot.fish_caught.strip() for spot in db_spots if spot.fish_caught and spot.fish_caught.strip()]
    total_fish_reports = len(caught_fish)
    fish_variety = len({fish.casefold() for fish in caught_fish})
    waterbody_variety = len({spot.waterbody.strip().casefold() for spot in db_spots if spot.waterbody and spot.waterbody.strip()})

    return render_template(
        'profile.html', profile_user=user, spots=db_spots,
        total_spots=len(db_spots), total_likes=total_likes,
        comments=comments, total_comments=total_comments,
        total_likes_given=total_likes_given,
        total_fish_reports=total_fish_reports,
        fish_variety=fish_variety,
        waterbody_variety=waterbody_variety
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

    all_spots = list(load_spots())
    all_spots.extend(
        database_spot_to_dict(item)
        for item in Spot.query.order_by(Spot.id.desc()).all()
    )
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
        for database_spot in Spot.query.all():
            if database_spot.fish_caught:
                _CACHE['fishes_list'].append(database_spot.fish_caught)
            if database_spot.waterbody:
                _CACHE['places_list'].append(database_spot.waterbody)
        _CACHE['fishes_list'] = sorted(set(_CACHE['fishes_list']))
        _CACHE['places_list'] = sorted(set(_CACHE['places_list']))

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


PHOTO_METADATA_MARKER = '\n\n[[FISH_EXPERT_PHOTOS:'
PHOTO_METADATA_END = ']]'


def split_report_description(description):
    description = description or ''
    if PHOTO_METADATA_MARKER not in description:
        return description, []
    visible_text, metadata = description.rsplit(PHOTO_METADATA_MARKER, 1)
    try:
        photos = json.loads(metadata.split(PHOTO_METADATA_END, 1)[0])
        if not isinstance(photos, list):
            photos = []
        photos = [path for path in photos if isinstance(path, str) and path.startswith('uploads/reports/')]
    except (ValueError, TypeError):
        photos = []
    return visible_text, photos


def report_photos_from_uploads():
    uploads = [item for item in request.files.getlist('photos') if item and item.filename]
    if len(uploads) > 5:
        raise ValueError('Можно прикрепить не более 5 фотографий к одному отчёту.')

    allowed = {
        '.jpg': (b'\xff\xd8\xff',),
        '.jpeg': (b'\xff\xd8\xff',),
        '.png': (b'\x89PNG\r\n\x1a\n',),
        '.webp': (b'RIFF',),
        '.gif': (b'GIF87a', b'GIF89a')
    }
    saved = []
    total_size = 0
    target_dir = os.path.join(app.static_folder, 'uploads', 'reports')
    os.makedirs(target_dir, exist_ok=True)

    try:
        for upload in uploads:
            extension = os.path.splitext(upload.filename)[1].lower()
            signatures = allowed.get(extension)
            if not signatures:
                raise ValueError('Поддерживаются только JPG, PNG, WEBP и GIF.')
            header = upload.stream.read(12)
            upload.stream.seek(0)
            valid = any(header.startswith(signature) for signature in signatures)
            if extension == '.webp':
                valid = valid and header[8:12] == b'WEBP'
            if not valid:
                raise ValueError('Один из файлов не похож на изображение заявленного формата.')

            content = upload.read()
            upload.stream.seek(0)
            total_size += len(content)
            if total_size > 3 * 1024 * 1024:
                raise ValueError('Общий размер фотографий не должен превышать 3 МБ.')
            filename = f'{uuid.uuid4().hex}{extension}'
            with open(os.path.join(target_dir, filename), 'wb') as image_file:
                image_file.write(content)
            saved.append('uploads/reports/' + filename)
    except Exception:
        for relative_path in saved:
            try:
                os.remove(os.path.join(app.static_folder, relative_path))
            except OSError:
                pass
        raise
    return saved


def database_spot_to_dict(spot):
    description, images = split_report_description(spot.description)
    lines = description.splitlines()
    metadata = {}
    for line in lines:
        if ': ' in line:
            key, value = line.split(': ', 1)
            metadata[key] = value
    return {
        'id': f'db-{spot.id}',
        'title': spot.title or 'Отчёт с рыбалки',
        'name': spot.title or 'Отчёт с рыбалки',
        'description': description,
        'waterbody': spot.waterbody or 'Водоём не указан',
        'waterbody_clean': clean_waterbody_name(spot.waterbody or ''),
        'fish_caught': spot.fish_caught or 'Не указана',
        'fish_clean': spot.fish_caught or 'Не указана',
        'tackle_clean': metadata.get('Снасть / оснастка', metadata.get('Наживка / приманка', 'Не указана')),
        'date': metadata.get('Дата ловли', ''),
        'lat': spot.lat,
        'lon': spot.lon,
        'images': [url_for('static', filename=path) for path in images],
        'cover_image': url_for('static', filename=images[0]) if images else None
    }


@app.route('/spot/<spot_id>')
def spot_detail(spot_id):
    if str(spot_id).startswith('db-'):
        try:
            db_id = int(str(spot_id)[3:])
        except ValueError:
            abort(404)
        database_spot = db.session.get(Spot, db_id)
        spot = database_spot_to_dict(database_spot) if database_spot else None
    else:
        spot = next((s for s in load_spots() if str(s.get('id')) == str(spot_id)), None)

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
    validate_csrf()
    title = request.form.get('title', '').strip()
    waterbody = request.form.get('waterbody', '').strip() or title
    fish = request.form.get('fish_species', '').strip() or request.form.get('fish', '').strip()
    notes = request.form.get('info', '').strip() or request.form.get('text', '').strip()
    lat = request.form.get('lat', '').strip()
    lon = request.form.get('lon', '').strip()

    if not title or not notes:
        flash('Укажите название отчёта и добавьте заметки о рыбалке.', 'error')
        return redirect(url_for('map_page'))

    try:
        latitude, longitude = float(lat), float(lon)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError
    except (TypeError, ValueError):
        flash('Поставьте точку на карте, чтобы сохранить корректные координаты.', 'error')
        return redirect(url_for('map_page'))

    details = []
    for label, value in (
        ('Дата ловли', request.form.get('catch_date', '').strip()),
        ('Время', ' — '.join(filter(None, (request.form.get('start_time', '').strip(),
                                          request.form.get('end_time', '').strip())))),
        ('Наживка / приманка', request.form.get('bait', '').strip()),
        ('Снасть / оснастка', request.form.get('tackle', '').strip())
    ):
        if value:
            details.append(f'{label}: {value}')

    try:
        photos = report_photos_from_uploads()
    except ValueError as error:
        flash(str(error), 'error')
        return redirect(url_for('map_page'))
    except OSError:
        app.logger.exception('Could not store fishing report photos')
        flash('Не удалось сохранить фотографии. Проверьте свободное место и права на запись.', 'error')
        return redirect(url_for('map_page'))

    description = notes[:4000]
    if details:
        description += '\n\n' + '\n'.join(details)
    if photos:
        description += PHOTO_METADATA_MARKER + json.dumps(photos, ensure_ascii=False) + PHOTO_METADATA_END

    new_spot = Spot(
        title=title[:200],
        waterbody=waterbody[:100],
        fish_caught=fish[:100],
        description=description,
        lat=latitude,
        lon=longitude,
        user_id=current_user.id if current_user.is_authenticated else None
    )
    try:
        db.session.add(new_spot)
        db.session.commit()
    except Exception:
        db.session.rollback()
        for relative_path in photos:
            try:
                os.remove(os.path.join(app.static_folder, relative_path))
            except OSError:
                pass
        app.logger.exception('Could not save fishing report')
        flash('Не удалось сохранить отчёт. Попробуйте ещё раз.', 'error')
        return redirect(url_for('map_page'))

    _CACHE.pop('normalized_spots', None)
    _CACHE.pop('map_reports', None)
    _CACHE.pop('species_list', None)
    _CACHE.pop('fishes_list', None)
    _CACHE.pop('places_list', None)
    flash('Отчёт успешно опубликован на карте.', 'success')
    return redirect(url_for('spot_detail', spot_id=f'db-{new_spot.id}'))


@app.route('/map')
def map_page():
    reports = []
    species_set = set()

    for s in load_spots():
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
            'lon': s['lon'],
            'url': url_for('spot_detail', spot_id=s.get('id')) if s.get('id') else None
        })

    # Include database reports and link each marker to its own report page.
    for spot in Spot.query.filter(Spot.lat.isnot(None), Spot.lon.isnot(None)).all():
        fish_sp = spot.fish_caught or 'Не указана'
        if fish_sp != 'Не указана':
            species_set.add(fish_sp)
        visible_description, _ = split_report_description(spot.description)
        reports.append({
            'id': f'db-{spot.id}',
            'title': spot.title or 'Отчёт с рыбалки',
            'waterbody': spot.waterbody or 'Водоём не указан',
            'fish_species': fish_sp,
            'info': visible_description,
            'lat': spot.lat,
            'lon': spot.lon,
            'url': url_for('spot_detail', spot_id=f'db-{spot.id}')
        })

    return render_template(
        'map.html',
        reports=reports,
        species_list=sorted(species_set),
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


def waterbody_to_dict(item):
    try:
        fishes = json.loads(item.fishes_json or '[]')
    except (ValueError, TypeError):
        fishes = []
    try:
        images = json.loads(item.images_json or '[]')
    except (ValueError, TypeError):
        images = []
    return {
        'id': f'db-{item.id}',
        'name': item.name,
        'type': item.type or 'Водоём',
        'region': item.region or '',
        'location': item.location or item.region or '',
        'description': item.description or '',
        'fishes': fishes if isinstance(fishes, list) else [],
        'methods': item.methods or '',
        'features': item.features or '',
        'images': images if isinstance(images, list) else [],
        'image': (images[0] if isinstance(images, list) and images else ''),
        'lat': item.lat,
        'lon': item.lon
    }


@app.route('/waters')
@app.route('/water')
def waters():
    search_query = request.args.get('search', '').strip().casefold()
    selected_region = request.args.get('region', '').strip()
    selected_fish = request.args.get('fish', '').strip()
    selected_type = request.args.get('type', '').strip()

    records = [waterbody_to_dict(item) for item in Waterbody.query.order_by(Waterbody.region, Waterbody.name).all()]
    if not records:
        records = load_json_file('waterbodies.json')

    filtered = []
    for item in records:
        haystack = ' '.join((item.get('name', ''), item.get('region', ''), item.get('location', ''),
                             item.get('description', ''))).casefold()
        if search_query and search_query not in haystack:
            continue
        if selected_region and item.get('region') != selected_region:
            continue
        if selected_fish and selected_fish not in (item.get('fishes') or []):
            continue
        if selected_type and item.get('type') != selected_type:
            continue
        filtered.append(item)

    regions = sorted({item.get('region', '') for item in records if item.get('region')})
    fishes = sorted({fish for item in records for fish in (item.get('fishes') or [])})
    types = sorted({item.get('type', '') for item in records if item.get('type')})
    return render_template(
        'waters.html', waterbodies=filtered, regions=regions, fishes=fishes, types=types,
        selected_search=search_query, selected_region=selected_region,
        selected_fish=selected_fish, selected_type=selected_type,
        total_waterbodies=len(records)
    )


@app.route('/water/<wb_id>')
def water_detail(wb_id):
    wb = None
    if str(wb_id).startswith('db-'):
        try:
            database_id = int(str(wb_id)[3:])
        except ValueError:
            abort(404)
        database_item = db.session.get(Waterbody, database_id)
        wb = waterbody_to_dict(database_item) if database_item else None
    else:
        wb = next((item for item in load_json_file('waterbodies.json')
                   if str(item.get('id')) == str(wb_id)), None)
    if not wb:
        return "Водоём не найден", 404
    return render_template('water_detail.html', wb=wb)


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



def _fetch_weather_json(url):
    """Fetch public Open-Meteo JSON with a short timeout."""
    with urlopen(url, timeout=8) as response:
        return json.loads(response.read().decode('utf-8'))


def get_weather_for_location(location):
    """Resolve a city/waterbody and return current local weather from Open-Meteo."""
    location = str(location or '').strip()
    if not location or len(location) > 120:
        raise ValueError('Укажите город или водоём (до 120 символов).')

    coords = None
    normalized = location.casefold()
    for known_name, known_coords in KNOWN_COORDS.items():
        if known_name in normalized or normalized in known_name:
            coords = known_coords
            place_name = location
            break
    else:
        query = urlencode({'name': location, 'count': 1, 'language': 'ru', 'format': 'json'})
        geo = _fetch_weather_json('https://geocoding-api.open-meteo.com/v1/search?' + query)
        results = geo.get('results') or []
        if not results:
            raise ValueError('Место не найдено. Попробуйте указать ближайший город.')
        place = results[0]
        coords = (float(place['latitude']), float(place['longitude']))
        place_name = ', '.join(part for part in (place.get('name'), place.get('admin1'), place.get('country')) if part)

    params = {
        'latitude': coords[0], 'longitude': coords[1],
        'current': 'temperature_2m,precipitation,rain,showers,snowfall,weather_code,cloud_cover,pressure_msl,surface_pressure,wind_speed_10m',
        'hourly': 'pressure_msl',
        'forecast_days': 1, 'past_days': 1, 'timezone': 'auto'
    }
    weather = _fetch_weather_json('https://api.open-meteo.com/v1/forecast?' + urlencode(params))
    current = weather.get('current') or {}
    if not current or current.get('temperature_2m') is None:
        raise ValueError('Сервис погоды не вернул текущие условия для этого места.')

    local_time = datetime.fromisoformat(str(current.get('time')).replace('Z', '+00:00'))
    hour = local_time.hour
    time_of_day = 'night' if hour < 5 or hour >= 22 else ('morning' if hour < 10 else ('day' if hour < 17 else 'evening'))
    month = local_time.month
    northern = coords[0] >= 0
    if northern:
        season = 'winter' if month in (12, 1, 2) else ('spring' if month in (3, 4, 5) else ('summer' if month in (6, 7, 8) else 'autumn'))
    else:
        season = 'summer' if month in (12, 1, 2) else ('autumn' if month in (3, 4, 5) else ('winter' if month in (6, 7, 8) else 'spring'))

    pressure_hpa = current.get('pressure_msl')
    hourly = weather.get('hourly') or {}
    times, pressures = hourly.get('time') or [], hourly.get('pressure_msl') or []
    previous = []
    for stamp, pressure in zip(times, pressures):
        try:
            point_time = datetime.fromisoformat(str(stamp))
            if 1 <= (local_time - point_time).total_seconds() / 3600 <= 4 and pressure is not None:
                previous.append(float(pressure))
        except (TypeError, ValueError):
            continue
    trend = 'stable'
    if pressure_hpa is not None and previous:
        delta = float(pressure_hpa) - previous[-1]
        trend = 'rising' if delta >= 1.5 else ('falling' if delta <= -1.5 else 'stable')

    precipitation = float(current.get('precipitation') or 0)
    rain_snow = float(current.get('rain') or 0) + float(current.get('showers') or 0) + float(current.get('snowfall') or 0)
    precip_level = 'heavy' if max(precipitation, rain_snow) >= 2.5 else ('light' if max(precipitation, rain_snow) > 0 else 'none')
    return {
        'location': place_name, 'temperature': round(float(current['temperature_2m']), 1),
        'pressure': round(float(pressure_hpa) * 0.750061683, 1) if pressure_hpa is not None else None,
        'wind': round(float(current.get('wind_speed_10m') or 0) / 3.6, 1),
        'cloud': int(current.get('cloud_cover') or 0), 'pressure_trend': trend,
        'precipitation': precip_level, 'time_of_day': time_of_day,
        'season': season, 'local_time': local_time.strftime('%d.%m.%Y %H:%M'),
        'year': local_time.year, 'month': month, 'weather_code': current.get('weather_code')
    }


@app.route('/api/weather')
def bite_forecast_weather():
    try:
        return jsonify(get_weather_for_location(request.args.get('location', '')))
    except (ValueError, OSError, TimeoutError, json.JSONDecodeError) as error:
        app.logger.warning('Weather lookup failed: %s', error)
        return jsonify({'error': str(error) or 'Не удалось получить погоду.'}), 400


def calculate_bite_forecast(data):
    """Return an explainable heuristic index, not a catch probability."""
    limits = {'temperature': (-10, 40), 'pressure': (680, 800), 'wind': (0, 25), 'cloud': (0, 100)}
    values = {}
    for key, bounds in limits.items():
        try:
            value = float(data.get(key, ''))
        except (TypeError, ValueError):
            raise ValueError('Проверьте числовые значения погодных условий.')
        if not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
            raise ValueError(f'Параметр {key}: допустимый диапазон {bounds[0]}–{bounds[1]}.')
        values[key] = value
    allowed = {
        'pressure_trend': ('rising', 'stable', 'falling'),
        'precipitation': ('none', 'light', 'heavy'),
        'time_of_day': ('morning', 'day', 'evening', 'night'),
        'fish_group': ('predatory', 'peaceful', 'coldwater'),
        'water_type': ('river', 'lake'),
    }
    selected = {}
    for key, options in allowed.items():
        value = str(data.get(key, '')).strip().lower()
        if value not in options:
            raise ValueError('Выберите все параметры прогноза из списка.')
        selected[key] = value
    score, factors = 50, []
    def add(points, positive, negative, neutral=None):
        nonlocal score
        score += points
        factors.append(('Плюс' if points > 0 else ('Минус' if points < 0 else 'Нейтрально'), positive if points > 0 else (negative if points < 0 else (neutral or positive))))
    p = values['pressure']
    add(8 if 735 <= p <= 755 else (-8 if p < 720 or p > 770 else 0), 'Давление в умеренном диапазоне.', 'Давление заметно отклоняется от умеренного диапазона.', 'Давление без резких отклонений.')
    trend = {'rising': 4, 'stable': 7, 'falling': -7}[selected['pressure_trend']]
    add(trend, 'Давление растёт или остаётся стабильным.', 'Падающее давление может сопровождаться переменой погоды.')
    wind = values['wind']
    wind_points = 8 if 1 <= wind <= 5 else (3 if wind <= 8 else (-8 if wind <= 14 else -16))
    add(wind_points, 'Ветер слабый или умеренный.', 'Сильный ветер может осложнить ловлю и снизить комфорт.')
    cloud = values['cloud']
    cloud_points = 5 if 25 <= cloud <= 75 else (-4 if cloud < 10 or cloud > 95 else 0)
    add(cloud_points, 'Переменная облачность может быть комфортной.', 'Очень ясное или сплошь пасмурное небо — неблагоприятный фактор.', 'Облачность не даёт выраженного преимущества.')
    add({'none': 0, 'light': 4, 'heavy': -10}[selected['precipitation']], 'Небольшие осадки иногда совпадают с активностью рыбы.', 'Сильные осадки ухудшают условия и безопасность.', 'Осадков нет.')
    preferred = {'predatory': (10, 22), 'peaceful': (16, 26), 'coldwater': (6, 18)}[selected['fish_group']]
    temp = values['temperature']
    temp_points = 8 if preferred[0] <= temp <= preferred[1] else (-7 if temp < preferred[0] - 8 or temp > preferred[1] + 8 else 0)
    add(temp_points, 'Температура подходит выбранной группе рыб по общей шкале.', 'Температура далеко от ориентировочного диапазона.', 'Температура не даёт выраженного преимущества.')
    add({'morning': 8, 'day': 0, 'evening': 8, 'night': 2}[selected['time_of_day']], 'Утро или вечер часто удобны для наблюдения активности.', 'Ночной период зависит от вида и водоёма.', 'Дневная активность зависит от вида и сезона.')
    season = str(data.get('season', '')).strip().lower()
    if season in ('spring', 'summer', 'autumn', 'winter'):
        seasonal_points = {
            'predatory': {'spring': 5, 'summer': 1, 'autumn': 7, 'winter': -4},
            'peaceful': {'spring': 3, 'summer': 7, 'autumn': 2, 'winter': -6},
            'coldwater': {'spring': 3, 'summer': -5, 'autumn': 4, 'winter': 5},
        }[selected['fish_group']][season]
        season_names = {'spring': 'весна', 'summer': 'лето', 'autumn': 'осень', 'winter': 'зима'}
        add(seasonal_points, f'Сезон ({season_names[season]}) в целом подходит выбранной группе рыб.', f'Сезон ({season_names[season]}) может снижать активность выбранной группы.', 'Сезонный фактор нейтрален.')
    score = max(0, min(100, int(round(score))))
    if score >= 75:
        level, title, advice = 'high', 'Хорошие условия', 'Можно планировать рыбалку и подбирать тактику под водоём.'
    elif score >= 60:
        level, title, advice = 'fair', 'Условия выше среднего', 'Есть смысл попробовать рыбалку, меняя глубину и приманки.'
    elif score >= 45:
        level, title, advice = 'moderate', 'Умеренные условия', 'Клёв может быть нестабильным. Экспериментируйте с наживкой.'
    else:
        level, title, advice = 'low', 'Сложные условия', 'Уделите внимание безопасности и рассмотрите другое время.'
    return {'score': score, 'level': level, 'title': title, 'advice': advice, 'factors': factors,
            'fish_label': {'predatory': 'хищная рыба', 'peaceful': 'мирная рыба', 'coldwater': 'холодолюбивая рыба'}[selected['fish_group']],
            'water_label': {'river': 'река', 'lake': 'озеро'}[selected['water_type']],
            'season': season if season in ('spring', 'summer', 'autumn', 'winter') else None,
            'season_label': {'spring': 'весна', 'summer': 'лето', 'autumn': 'осень', 'winter': 'зима'}.get(season),
            'year': str(data.get('year') or datetime.now().astimezone().year)}


@app.route('/bite-forecast', methods=['GET', 'POST'])
def bite_forecast():
    forecast = None
    now = datetime.now().astimezone()
    form_values = {'temperature': '18', 'pressure': '745', 'pressure_trend': 'stable', 'wind': '3', 'cloud': '45', 'precipitation': 'none', 'time_of_day': 'morning', 'season': '', 'year': str(now.year), 'location': '', 'fish_group': 'predatory', 'water_type': 'lake'}
    if request.method == 'POST':
        validate_csrf()
        form_values.update({key: request.form.get(key, '') for key in form_values})
        try:
            forecast = calculate_bite_forecast(form_values)
        except ValueError as error:
            flash(str(error), 'error')
    return render_template('bite_forecast.html', forecast=forecast, form_values=form_values,
                           current_date=now.strftime('%d.%m.%Y'), current_year=now.year)


@app.route('/gear-advisor', methods=['GET', 'POST'])
def gear_advisor():
    """Подбор снастей по выбранной целевой рыбе на основе локального каталога."""
    fishes_data = load_json_file('fishes.json')
    tackle_data = load_json_file('tackle.json')
    selected_fish_id = (request.values.get('fish') or '').strip()
    selected_fish = next(
        (item for item in fishes_data if str(item.get('id')) == selected_fish_id),
        None
    )
    recommendations = []

    if selected_fish:
        fish_name = str(selected_fish.get('name') or '').strip().casefold()
        for item in tackle_data:
            target_fish = item.get('target_fish') or []
            if isinstance(target_fish, str):
                target_fish = [target_fish]
            if any(fish_name == str(target).strip().casefold() for target in target_fish):
                recommendations.append(item)

        # Если в каталоге нет точного совпадения, показываем подходы из карточки рыбы.
        if not recommendations:
            fish_tackle = selected_fish.get('tackle') or ''
            fish_baits = selected_fish.get('baits') or ''
            recommendations.append({
                'id': None,
                'title': 'Рекомендации из энциклопедии рыб',
                'category': 'Базовый комплект',
                'fishing_type': selected_fish.get('methods') or 'Уточните способ ловли',
                'description': 'В каталоге пока нет снастей с точным совпадением по этому виду. Используйте рекомендации ниже как отправную точку.',
                'tips': 'Рекомендуемые снасти: ' + str(fish_tackle) + '. Приманки и наживки: ' + str(fish_baits) + '.'
            })

    return render_template(
        'gear_advisor.html',
        fishes=fishes_data,
        selected_fish=selected_fish,
        recommendations=recommendations
    )


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Безопасная additive-миграция: добавляет только nullable-столбец.
        # Существующие пользователи и данные не удаляются и не перезаписываются.
        user_columns = {column['name'] for column in inspect(db.engine).get_columns('users')}
        additive_columns = {
            'password_hash': 'VARCHAR(255)',
            'password_reset_token_hash': 'VARCHAR(64)',
            'password_reset_sent_at': 'DATETIME',
            'email_verified': 'BOOLEAN',
            'email_verification_token_hash': 'VARCHAR(64)',
            'email_verification_sent_at': 'DATETIME',
            'pending_email': 'VARCHAR(120)',
            'email_change_token_hash': 'VARCHAR(64)',
            'email_change_sent_at': 'DATETIME',
        }
        with db.engine.begin() as connection:
            for column_name, column_type in additive_columns.items():
                if column_name not in user_columns:
                    connection.exec_driver_sql(
                        f'ALTER TABLE users ADD COLUMN {column_name} {column_type}'
                    )

        # Additive migration for the waterbody catalogue. Existing rows are retained.
        waterbody_columns = {column['name'] for column in inspect(db.engine).get_columns('waterbodies')}
        waterbody_additions = {
            'type': 'VARCHAR(50)', 'region': 'VARCHAR(255)', 'location': 'VARCHAR(255)',
            'fishes_json': 'TEXT', 'methods': 'TEXT', 'features': 'TEXT',
            'images_json': 'TEXT', 'lat': 'FLOAT', 'lon': 'FLOAT'
        }
        with db.engine.begin() as connection:
            for column_name, column_type in waterbody_additions.items():
                if column_name not in waterbody_columns:
                    connection.exec_driver_sql(
                        f'ALTER TABLE waterbodies ADD COLUMN {column_name} {column_type}'
                    )

        # Seed only missing names; existing catalogue rows and user reports are not deleted.
        seed_records = load_json_file('waterbodies.json') + load_json_file('waterbodies_catalog.json')
        for record in seed_records:
            name = str(record.get('name') or '').strip()
            if not name:
                continue
            existing = Waterbody.query.filter(db.func.lower(Waterbody.name) == name.casefold()).first()
            images = record.get('images') or ([record.get('image')] if record.get('image') else [])
            if existing:
                # Fill only blank fields so a previously edited record is never overwritten.
                if not existing.description and record.get('description'):
                    existing.description = record['description']
                if not existing.type and record.get('type'):
                    existing.type = record['type']
                if not existing.region and record.get('region'):
                    existing.region = record['region']
                if not existing.location and record.get('location'):
                    existing.location = record['location']
                if not existing.fishes_json and record.get('fishes'):
                    existing.fishes_json = json.dumps(record['fishes'], ensure_ascii=False)
                if not existing.methods and record.get('methods'):
                    existing.methods = record['methods']
                if not existing.features and record.get('features'):
                    existing.features = record['features']
                if not existing.images_json and images:
                    existing.images_json = json.dumps(images, ensure_ascii=False)
                if existing.lat is None and record.get('lat') is not None:
                    existing.lat = record['lat']
                if existing.lon is None and record.get('lon') is not None:
                    existing.lon = record['lon']
                continue
            db.session.add(Waterbody(
                name=name[:100],
                description=record.get('description', ''),
                type=record.get('type', 'Водоём'),
                region=record.get('region', ''),
                location=record.get('location', record.get('region', '')),
                fishes_json=json.dumps(record.get('fishes') or [], ensure_ascii=False),
                methods=record.get('methods', ''),
                features=record.get('features', ''),
                images_json=json.dumps(images, ensure_ascii=False),
                lat=record.get('lat'),
                lon=record.get('lon')
            ))
        db.session.commit()
    app.run(debug=True)