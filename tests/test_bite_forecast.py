import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app import app, calculate_bite_forecast, db, get_weather_for_location


@pytest.fixture()
def client():
    app.config.update(TESTING=True, SECRET_KEY='forecast-test-secret', SQLALCHEMY_DATABASE_URI='sqlite://')
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def sample_values():
    return {'temperature': '18', 'pressure': '745', 'pressure_trend': 'stable',
            'wind': '3', 'cloud': '45', 'precipitation': 'light',
            'time_of_day': 'morning', 'fish_group': 'predatory', 'water_type': 'lake'}


def test_forecast_returns_explained_bounded_index():
    result = calculate_bite_forecast(sample_values())
    assert 0 <= result['score'] <= 100
    assert result['title'] == 'Хорошие условия'
    assert result['factors']
    assert result['water_label'] == 'озеро'


@pytest.mark.parametrize('field,value', [
    ('temperature', '100'), ('pressure', '0'), ('wind', '-1'),
    ('cloud', '101'), ('temperature', 'nan'),
])
def test_forecast_rejects_invalid_numeric_values(field, value):
    values = sample_values()
    values[field] = value
    with pytest.raises(ValueError):
        calculate_bite_forecast(values)


def test_forecast_rejects_unknown_select_values():
    values = sample_values()
    values['fish_group'] = 'not-a-fish'
    with pytest.raises(ValueError):
        calculate_bite_forecast(values)


def test_forecast_page_get_and_post(client):
    response = client.get('/bite-forecast')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'Прогноз клёва' in page
    token = re.search(r'name="_csrf_token" value="([^"]+)"', page).group(1)
    response = client.post('/bite-forecast', data={'_csrf_token': token, **sample_values()})
    assert response.status_code == 200
    assert 'Индекс условий' in response.get_data(as_text=True)



def test_forecast_uses_season_and_year():
    values = sample_values()
    values.update(season='summer', year='2026')
    summer = calculate_bite_forecast(values)
    values['season'] = 'winter'
    winter = calculate_bite_forecast(values)
    assert summer['score'] > winter['score']
    assert summer['season_label'] == 'лето'
    assert summer['year'] == '2026'


def test_weather_lookup_returns_local_time_and_weather(monkeypatch):
    from datetime import datetime, timedelta

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    previous = now - timedelta(hours=2)
    payload = {
        'current': {
            'time': now.isoformat(), 'temperature_2m': 12.5,
            'precipitation': 0.2, 'rain': 0.2, 'showers': 0,
            'snowfall': 0, 'weather_code': 3, 'cloud_cover': 60,
            'pressure_msl': 1008,
            'wind_speed_10m': 10.8
        },
        'hourly': {
            'time': [previous.isoformat(), now.isoformat()],
            'pressure_msl': [1004, 1008]
        }
    }
    monkeypatch.setattr('app._fetch_weather_json', lambda url: payload)
    result = get_weather_for_location('Нева')
    assert result['location'] == 'Нева'
    assert result['temperature'] == 12.5
    assert result['wind'] == 3.0
    assert result['pressure_trend'] == 'rising'
    assert result['year'] == now.year
    assert result['season'] in ('spring', 'summer', 'autumn', 'winter')


def test_weather_api_handles_invalid_place(client, monkeypatch):
    monkeypatch.setattr('app.get_weather_for_location', lambda place: (_ for _ in ()).throw(ValueError('Место не найдено.')))
    response = client.get('/api/weather?location=unknown-place')
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Место не найдено.'
