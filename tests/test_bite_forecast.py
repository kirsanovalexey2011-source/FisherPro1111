import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app import app, calculate_bite_forecast, db


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
