import json

import pytest
from src.app import create_app
from db import db as _db
from db import initialize_shared_boats
from models import Boat

@pytest.fixture
def app(tmp_path):
    app = create_app({
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'TESTING': True,
    })
    with app.app_context():
        _db.drop_all()
        _db.create_all()
    yield app

@pytest.fixture
def client(app):
    return app.test_client()

def test_index(client):
    rv = client.get('/')
    assert rv.status_code == 200


def test_status_without_date_renders_empty_lookup_page(client):
    rv = client.get('/status')

    assert rv.status_code == 200
    assert '예약 현황 조회' in rv.get_data(as_text=True)


def test_status_uses_limited_workers_for_all_registered_boats(app):
    """동시 조회 스레드 수의 기본값과 환경변수 롤백 경로를 고정한다.

    Phase A0 에서 4 -> 24 로 올렸다. 근거는 실측이다(2026-09, Render):
    배당 지연 약 6.6초이고 CPU 가 아니라 IO 대기가 지배적이라 스레드 수에
    거의 선형으로 개선된다. 71척 기준 4워커면 약 117초가 걸려 gunicorn
    timeout 에 잘렸다.
    """
    assert app.config['STATUS_MAX_WORKERS'] == 24


def test_status_max_workers_can_be_overridden_by_env(monkeypatch):
    """운영에서 문제가 생기면 재배포 없이 환경변수로 되돌릴 수 있어야 한다."""
    monkeypatch.setenv('STATUS_MAX_WORKERS', '6')
    other = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'TESTING': True})
    assert other.config['STATUS_MAX_WORKERS'] == 6

    monkeypatch.setenv('STATUS_MAX_WORKERS', 'not-a-number')
    fallback = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'TESTING': True})
    assert fallback.config['STATUS_MAX_WORKERS'] == 24


def test_api_status_returns_every_registered_boat(app, monkeypatch):
    from routes import views

    with app.app_context():
        _db.session.query(Boat).delete()
        for index in range(62):
            _db.session.add(Boat(
                name=f'테스트호{index}',
                url=f'https://example.com/{index}',
                city='여수' if index >= 58 else '인천',
                port='돌산항' if index >= 58 else '남항(인천항)',
            ))
        _db.session.commit()

    monkeypatch.setattr(
        views,
        'check_single_boat',
        lambda *args, **kwargs: {'entries': []},
    )

    response = app.test_client().post('/api/status', data={
        'year': '2026',
        'month': '10',
        'day': '3',
        'regions': '전체',
    })

    assert response.status_code == 200
    lines = [json.loads(l) for l in response.get_data(as_text=True).strip().splitlines() if l.strip()]
    results = [l for l in lines if l.get('type') not in ('start', 'end')]
    assert len(results) == 62
    # 종료 마커가 있어야 프론트가 '완주'와 '중간에 잘림'을 구분할 수 있다
    assert lines[-1] == {'type': 'end', 'total': 62, 'completed': 62, 'missing': []}


def test_api_status_filters_multiple_regions_and_boats(app, monkeypatch):
    from routes import views
    from werkzeug.datastructures import MultiDict

    with app.app_context():
        _db.session.query(Boat).delete()
        for index in range(16):
            _db.session.add(Boat(name=f'여수호{index}', url=f'https://example.com/yeosu/{index}', city='여수', port='국동항'))
        for index in range(4):
            _db.session.add(Boat(name=f'고흥호{index}', url=f'https://example.com/goheung/{index}', city='고흥', port='녹동방파제'))
        _db.session.commit()

    monkeypatch.setattr(views, 'check_single_boat', lambda *args, **kwargs: {'entries': []})
    response = app.test_client().post('/api/status', data=MultiDict([
        ('year', '2026'), ('month', '10'), ('day', '3'),
        ('regions', '여수'), ('regions', '고흥'),
        *[("boats", f'여수호{index}') for index in range(16)],
        *[("boats", f'고흥호{index}') for index in range(4)],
    ]))

    assert response.status_code == 200
    lines = [json.loads(l) for l in response.get_data(as_text=True).splitlines() if l.strip()]
    result_lines = [l for l in lines if l.get('type') not in ('start', 'end')]
    assert len(result_lines) == 20
    assert lines[-1]['type'] == 'end' and lines[-1]['completed'] == 20


def test_existing_boats_are_treated_as_initial_shared_data(app):
    with app.app_context():
        boat = Boat(name='팀만수호', url='https://example.com', city='인천', port='남항(인천항)', note='seed', is_shared=None)
        _db.session.add(boat)
        _db.session.commit()

        initialize_shared_boats()

        refreshed = Boat.query.get(boat.id)
        assert refreshed.is_shared is True


def test_initialize_shared_boats_seed_default_data_when_db_is_empty(app):
    with app.app_context():
        _db.session.query(Boat).delete()
        _db.session.commit()

        initialize_shared_boats()

        boats = Boat.query.order_by(Boat.id).all()
        assert len(boats) >= 1
        assert all(boat.is_shared is True for boat in boats)


def test_initialize_shared_boats_runs_only_once(app):
    with app.app_context():
        _db.session.query(Boat).delete()
        _db.session.commit()

        initialize_shared_boats()
        first_count = Boat.query.count()

        initialize_shared_boats()
        second_count = Boat.query.count()

        assert first_count == second_count

# To run the application, use the following commands:
# cd C:\Workspace\python_ship\fishing-boat-reservation-app
# python -m venv .venv
# .\.venv\Scripts\Activate.ps1
# python -m pip install --upgrade pip
# python -m pip install -r requirements.txt
# cd src
# python app.py
# Then open a browser and go to: http://127.0.0.1:5000