"""출조 기록 화면·API와 admin 로그인 유지 (2단계 spec §2.4, §2.5)."""
import re

API = '/admin/api/fishing/trips'


def _csrf(client, path='/admin/service'):
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    m = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html)
    assert m, f'{path} 에서 csrf_token 을 찾지 못함'
    return m.group(1)


def _login(client, monkeypatch, remember=False):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'correct-horse')
    data = {'csrf_token': _csrf(client), 'username': 'admin', 'password': 'correct-horse'}
    if remember:
        data['remember'] = 'y'
    return client.post('/admin', data=data)


def _headers(client):
    return {'X-CSRFToken': _csrf(client)}


def _payload(**over):
    base = {'trip_date': '2026-05-02', 'status': 'done', 'ship_name': '가나다호',
            'ship_region': '가시', 'ship_port': '가항', 'cost': '90,000',
            'catches': [{'who': '나', 'species': '문어', 'count': 3}]}
    base.update(over)
    return base


def test_page_requires_login(client):
    rv = client.get('/admin/fishing/trips')
    assert rv.status_code == 302
    assert rv.headers['Location'].endswith('/admin')


def test_api_requires_login(client):
    assert client.get(API).status_code == 403
    assert client.post(API, json=_payload()).status_code == 403
    assert client.get('/admin/api/fishing/ships').status_code == 403


def test_write_without_csrf_is_rejected(client, monkeypatch):
    _login(client, monkeypatch)
    rv = client.post(API, json=_payload())
    assert rv.status_code == 400
    assert 'CSRF' in rv.get_json()['error']


def test_create_read_update_delete_round_trip(app, client, monkeypatch):
    _login(client, monkeypatch)
    headers = _headers(client)

    rv = client.post(API, json=_payload(), headers=headers)
    assert rv.status_code == 201
    trip = rv.get_json()['trip']
    assert trip['ship']['name'] == '가나다호'
    assert trip['cost'] == 90000

    rv = client.get(f"{API}/{trip['id']}")
    assert rv.status_code == 200 and rv.get_json()['trip']['id'] == trip['id']

    rv = client.put(f"{API}/{trip['id']}", json=_payload(memo='수정함', rating='again'), headers=headers)
    assert rv.status_code == 200
    assert rv.get_json()['trip']['memo'] == '수정함'

    listed = client.get(f'{API}?year=2026').get_json()
    assert [t['id'] for t in listed['trips']] == [trip['id']]
    assert listed['summary']['done'] == 1

    rv = client.delete(f"{API}/{trip['id']}", headers=headers)
    assert rv.status_code == 200
    assert client.get(f"{API}/{trip['id']}").status_code == 404


def test_validation_error_returns_field(client, monkeypatch):
    _login(client, monkeypatch)
    rv = client.post(API, json=_payload(ship_name=''), headers=_headers(client))
    assert rv.status_code == 400
    assert rv.get_json()['field'] == 'ship_name'


def test_unknown_trip_is_404(client, monkeypatch):
    _login(client, monkeypatch)
    headers = _headers(client)
    assert client.get(f'{API}/999').status_code == 404
    assert client.put(f'{API}/999', json=_payload(), headers=headers).status_code == 404
    assert client.delete(f'{API}/999', headers=headers).status_code == 404


def test_list_year_all_and_bad_year(client, monkeypatch):
    _login(client, monkeypatch)
    headers = _headers(client)
    client.post(API, json=_payload(trip_date='2025-05-02'), headers=headers)
    client.post(API, json=_payload(trip_date='2026-05-02'), headers=headers)
    assert len(client.get(f'{API}?year=all').get_json()['trips']) == 2
    assert len(client.get(f'{API}?year=2025').get_json()['trips']) == 1
    assert client.get(f'{API}?year=abc').status_code == 400


def test_ship_search(client, monkeypatch):
    _login(client, monkeypatch)
    client.post(API, json=_payload(), headers=_headers(client))
    results = client.get('/admin/api/fishing/ships?q=가나').get_json()['ships']
    assert results[0]['name'] == '가나다호'


def test_page_renders_for_logged_in_admin(client, monkeypatch):
    _login(client, monkeypatch)
    html = client.get('/admin/fishing/trips').get_data(as_text=True)
    assert '출조 기록' in html
    assert 'id="trip-app"' in html


# ---- 로그인 유지 ----

def test_login_without_remember_uses_browser_session_cookie(client, monkeypatch):
    rv = _login(client, monkeypatch)
    cookie = rv.headers.get('Set-Cookie', '')
    assert 'session=' in cookie
    assert 'Expires=' not in cookie


def test_login_with_remember_sets_30_day_cookie(client, monkeypatch):
    rv = _login(client, monkeypatch, remember=True)
    cookie = rv.headers.get('Set-Cookie', '')
    assert 'Expires=' in cookie


def test_logout_clears_admin_session(client, monkeypatch):
    _login(client, monkeypatch, remember=True)
    client.post('/admin/logout', data={'csrf_token': _csrf(client)})
    assert client.get(API).status_code == 403
