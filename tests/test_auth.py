import re
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine, inspect

from app import app, db, User, Spot, Like, Comment, safe_next_url
from scripts.migrate_auth_schema import migrate_user_auth_columns


@pytest.fixture()
def client():
    app.config.update(
        TESTING=True,
        SECRET_KEY='test-secret-key',
        SQLALCHEMY_DATABASE_URI='sqlite://',
        WTF_CSRF_ENABLED=False,
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def csrf_token(response):
    match = re.search(r'name="_csrf_token" value="([^"]+)"', response.get_data(as_text=True))
    assert match, "CSRF token was not rendered"
    return match.group(1)


def test_registration_login_and_logout(client):
    response = client.get('/register')
    token = csrf_token(response)
    response = client.post('/register', data={
        '_csrf_token': token,
        'username': 'TestAngler',
        'email': 'angler@example.com',
        'password': 'a-strong-password-123',
    }, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username='TestAngler').one()
        assert user.check_password('a-strong-password-123')
        assert user.password_reset_token_hash is None

    response = client.post('/logout', data={'_csrf_token': token}, follow_redirects=False)
    assert response.status_code == 302

    response = client.get('/login')
    token = csrf_token(response)
    response = client.post('/login', data={
        '_csrf_token': token,
        'identity': 'angler@example.com',
        'password': 'a-strong-password-123',
    }, follow_redirects=False)
    assert response.status_code == 302


def test_password_recovery_for_legacy_account_is_one_time(client):
    with app.app_context():
        legacy_user = User(username='LegacyAngler', email='legacy@example.com')
        db.session.add(legacy_user)
        db.session.commit()

    captured = {}
    with patch('app.send_password_reset_email', side_effect=lambda user, token: captured.update(token=token)):
        response = client.get('/forgot-password')
        token = csrf_token(response)
        response = client.post('/forgot-password', data={
            '_csrf_token': token,
            'email': 'legacy@example.com',
        }, follow_redirects=False)
        assert response.status_code == 302

    reset_token = captured['token']
    response = client.get('/reset-password/' + reset_token)
    token = csrf_token(response)
    response = client.post('/reset-password/' + reset_token, data={
        '_csrf_token': token,
        'password': 'new-secure-password-456',
        'password_confirmation': 'new-secure-password-456',
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        user = User.query.filter_by(username='LegacyAngler').one()
        assert user.check_password('new-secure-password-456')
        assert user.password_reset_token_hash is None

    response = client.get('/reset-password/' + reset_token, follow_redirects=False)
    assert response.status_code == 302


def test_safe_next_url_rejects_external_redirects():
    assert safe_next_url('/profile') == '/profile'
    assert safe_next_url('https://attacker.example') is None
    assert safe_next_url('//attacker.example/path') is None
    assert safe_next_url('/\\\\attacker.example') is None
    assert safe_next_url('/%5c%5cattacker.example') is None


def test_additive_migration_preserves_legacy_user_data():
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                'CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) NOT NULL, email VARCHAR(120) NOT NULL)'
            )
            connection.exec_driver_sql(
                "INSERT INTO users (id, username, email) VALUES (1, 'OldAngler', 'old@example.com')"
            )

        migrate_user_auth_columns(engine)
        migrate_user_auth_columns(engine)  # Migration is idempotent.

        inspector = inspect(engine)
        columns = {column['name']: column for column in inspector.get_columns('users')}
        assert {'password_hash', 'password_reset_token_hash', 'password_reset_sent_at', 'email_verified', 'email_verification_token_hash', 'email_verification_sent_at', 'pending_email', 'email_change_token_hash', 'email_change_sent_at'} <= set(columns)
        assert columns['password_hash']['nullable'] is True

        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                'SELECT id, username, email, password_hash FROM users WHERE id = 1'
            ).one()
        assert row.id == 1
        assert row.username == 'OldAngler'
        assert row.email == 'old@example.com'
        assert row.password_hash is None
    finally:
        engine.dispose()


def test_profile_dashboard_and_password_settings(client):
    response = client.get('/register')
    token = csrf_token(response)
    response = client.post('/register', data={
        '_csrf_token': token,
        'username': 'ProfileAngler',
        'email': 'profile@example.com',
        'password': 'original-secure-password',
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        user = User.query.filter_by(username='ProfileAngler').one()
        spot = Spot(title='Утренняя рыбалка', waterbody='Ладога', fish_caught='Окунь', description='Поймал окуня', user_id=user.id)
        db.session.add(spot)
        db.session.flush()
        db.session.add(Like(user_id=user.id, spot_id=str(spot.id)))
        db.session.add(Comment(user_id=user.id, spot_id=str(spot.id), text='Отличный клёв!'))
        db.session.commit()

    response = client.get('/user/ProfileAngler')
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Отчёты о рыбалке' in page
    assert 'Отличный клёв!' in page
    assert 'Утренняя рыбалка' in page
    assert 'Отчётов с уловом' in page
    assert 'Водоёмов посещено' in page
    assert 'Видов рыбы отмечено' in page

    response = client.get('/user/edit')
    token = csrf_token(response)
    response = client.post('/user/edit', data={
        '_csrf_token': token,
        'bio': 'Люблю ловить на спиннинг.',
        'favorite_tackle': 'Спиннинг',
        'current_password': 'original-secure-password',
        'new_password': 'updated-secure-password',
        'password_confirmation': 'updated-secure-password',
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        user = User.query.filter_by(username='ProfileAngler').one()
        assert user.bio == 'Люблю ловить на спиннинг.'
        assert user.favorite_tackle == 'Спиннинг'
        assert user.check_password('updated-secure-password')
        assert not user.check_password('original-secure-password')


def test_avatar_upload_accepts_image_signature_and_rejects_fake_image(client, tmp_path, monkeypatch):
    from io import BytesIO
    from werkzeug.datastructures import FileStorage
    from app import save_profile_avatar

    monkeypatch.setattr(app, 'static_folder', str(tmp_path))
    valid = FileStorage(stream=BytesIO(b'\x89PNG\r\n\x1a\n' + b'fake-test-payload'), filename='avatar.png')
    saved_path = save_profile_avatar(valid)
    assert saved_path.startswith('uploads/avatars/')
    assert (tmp_path / saved_path).is_file()

    invalid = FileStorage(stream=BytesIO(b'not-an-image'), filename='avatar.png')
    with pytest.raises(ValueError):
        save_profile_avatar(invalid)



def test_email_verification_link_is_one_time(client):
    captured = {}
    with patch('app.send_email_verification', side_effect=lambda user, token: captured.update(token=token)):
        response = client.get('/register')
        token = csrf_token(response)
        response = client.post('/register', data={
            '_csrf_token': token,
            'username': 'VerifyAngler',
            'email': 'verify@example.com',
            'password': 'a-strong-password-123',
        }, follow_redirects=False)
        assert response.status_code == 302

    verify_token = captured['token']
    response = client.get('/verify-email/' + verify_token, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username='VerifyAngler').one()
        assert user.email_verified is True
        assert user.email_verification_token_hash is None

    response = client.get('/verify-email/' + verify_token, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username='VerifyAngler').one()
        assert user.email_verified is True


def test_email_change_requires_password_and_new_address_confirmation(client):
    captured = {}
    with patch('app.send_email_verification'):
        response = client.get('/register')
        token = csrf_token(response)
        response = client.post('/register', data={
            '_csrf_token': token,
            'username': 'ChangeAngler',
            'email': 'before@example.com',
            'password': 'a-strong-password-123',
        }, follow_redirects=False)
        assert response.status_code == 302

    response = client.get('/user/edit')
    token = csrf_token(response)
    response = client.post('/user/email/change', data={
        '_csrf_token': token,
        'new_email': 'after@example.com',
        'current_password_for_email': 'wrong-password',
    }, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username='ChangeAngler').one()
        assert user.email == 'before@example.com'
        assert user.pending_email is None

    with patch('app.send_email_change_confirmation', side_effect=lambda user, token: captured.update(token=token)):
        response = client.post('/user/email/change', data={
            '_csrf_token': token,
            'new_email': 'after@example.com',
            'current_password_for_email': 'a-strong-password-123',
        }, follow_redirects=False)
        assert response.status_code == 302

    with app.app_context():
        user = User.query.filter_by(username='ChangeAngler').one()
        assert user.email == 'before@example.com'
        assert user.pending_email == 'after@example.com'

    response = client.get('/confirm-email-change/' + captured['token'], follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username='ChangeAngler').one()
        assert user.email == 'after@example.com'
        assert user.pending_email is None
        assert user.email_verified is True
        assert user.email_change_token_hash is None
