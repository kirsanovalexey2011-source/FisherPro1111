import re
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine, inspect

from app import app, db, User, safe_next_url
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
        assert {'password_hash', 'password_reset_token_hash', 'password_reset_sent_at'} <= set(columns)
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
