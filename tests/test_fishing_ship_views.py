"""선사 노트 화면·API (4단계 spec §4)."""
from tests.test_fishing_views import _csrf, _login

API = '/admin/api/fishing/ships'


def _make_ship(name='가나다호', **kw):
    from db import db
    from models import FishingShip
    ship = FishingShip(name=name, **kw)
    db.session.add(ship)
    db.session.commit()
    return ship.id


def test_page_and_api_require_login(client, app):
    with app.app_context():
        sid = _make_ship()
    rv = client.get('/admin/fishing/ships')
    assert rv.status_code == 302 and rv.headers['Location'].endswith('/admin')
    assert client.get(API + '/notes').status_code == 403
    assert client.get(f'{API}/{sid}').status_code == 403
    assert client.put(f'{API}/{sid}', json={'name': 'x'}).status_code == 403


def test_notes_detail_and_update_round_trip(client, app, monkeypatch):
    with app.app_context():
        sid = _make_ship(region='여수')
        _make_ship('안 간 배')
        from datetime import date
        from db import db
        from models import FishingTrip
        db.session.add(FishingTrip(ship_id=sid, trip_date=date(2025, 10, 2), status='done', cost=100000))
        db.session.commit()
    _login(client, monkeypatch)
    notes = client.get(API + '/notes').get_json()
    assert [s['name'] for s in notes['ships']] == ['가나다호']
    assert 'boats' in notes and notes['regions'] == ['여수']
    assert client.get(API + '/notes?year=2025').get_json()['summary']['spent'] == 100000
    assert client.get(API + '/notes?year=2024').get_json()['ships'] == []
    assert client.get(API + '/notes?year=abc').status_code == 400

    detail = client.get(f'{API}/{sid}').get_json()['ship']
    assert detail['tag'] == '1회' and len(detail['visits']) == 1

    h = {'X-CSRFToken': _csrf(client)}
    assert client.put(f'{API}/{sid}', json={'name': '가나다2호'}).status_code == 400   # CSRF 없음
    rv = client.put(f'{API}/{sid}', json={'name': '가나다2호', 'region': '군산', 'memo': '메모'}, headers=h)
    assert rv.status_code == 200
    ship = rv.get_json()['ship']
    assert (ship['name'], ship['region'], ship['memo']) == ('가나다2호', '군산', '메모')

    rv = client.put(f'{API}/{sid}', json={'name': ''}, headers=h)
    assert rv.status_code == 400 and rv.get_json()['field'] == 'name'


def test_missing_ship_is_404(client, monkeypatch):
    _login(client, monkeypatch)
    h = {'X-CSRFToken': _csrf(client)}
    assert client.get(f'{API}/999').status_code == 404
    assert client.put(f'{API}/999', json={'name': 'x'}, headers=h).status_code == 404


def test_search_api_still_works(client, monkeypatch):
    _login(client, monkeypatch)
    assert 'ships' in client.get(API + '?q=').get_json()


def test_page_renders_with_active_menu(client, monkeypatch):
    _login(client, monkeypatch)
    html = client.get('/admin/fishing/ships').get_data(as_text=True)
    assert 'id="ship-app"' in html
    assert html.count('aria-current="page"') == 1
    assert 'href="/admin/fishing/ships"' in html
