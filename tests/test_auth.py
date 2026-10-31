import re
from unittest.mock import patch

import pytest

from app import app, db, User


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
