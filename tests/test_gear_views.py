"""장비 구매 화면·API (3단계 spec §6)."""
from tests.test_fishing_views import _csrf, _login

API = '/admin/api/fishing/gear'


def _order(**over):
    base = {'original': None, 'date': '2026-05-02', 'shop': '가나낚시',
            'items': [{'item': '테스트 에기', 'category': '에기', 'price': '12,000'}]}
    base.update(over)
    return base


def test_page_and_api_require_login(client):
    rv = client.get('/admin/fishing/gear')
    assert rv.status_code == 302 and rv.headers['Location'].endswith('/admin')
    assert client.get(API).status_code == 403
    assert client.post(API + '/orders', json=_order()).status_code == 403
    assert client.get(API + '/cleanup').status_code == 403
    assert client.get(API + '/items').status_code == 403


def test_writes_require_csrf(client, monkeypatch):
    _login(client, monkeypatch)
    assert client.post(API + '/orders', json=_order()).status_code == 400
    assert client.post(API + '/items', json={'name': '릴'}).status_code == 400


def test_order_round_trip_and_delete(client, monkeypatch):
    _login(client, monkeypatch)
    h = {'X-CSRFToken': _csrf(client)}
    rv = client.post(API + '/orders', json=_order(), headers=h)
    assert rv.status_code == 200
    order = rv.get_json()['order']
    assert order['total'] == 12000

    listed = client.get(API + '?year=2026').get_json()
    assert [o['shop'] for o in listed['orders']] == ['가나낚시']
    assert listed['summary']['total'] == 12000

    rv = client.post(API + '/orders', json=_order(original={'date': '2026-05-02', 'shop': '가나낚시'}, shop='나다낚시',
                                                  items=[{'id': order['items'][0]['id'], 'item': '수정', 'price': 1}]), headers=h)
    assert rv.get_json()['order']['shop'] == '나다낚시'

    rv = client.delete(API + '/orders', json={'date': '2026-05-02', 'shop': '나다낚시'}, headers=h)
    assert rv.get_json()['deleted'] == 1
    assert client.get(API + '?year=2026').get_json()['orders'] == []


def test_validation_error_and_bad_year(client, monkeypatch):
    _login(client, monkeypatch)
    rv = client.post(API + '/orders', json=_order(items=[]), headers={'X-CSRFToken': _csrf(client)})
    assert rv.status_code == 400 and rv.get_json()['field'] == 'items'
    assert client.get(API + '?year=abc').status_code == 400


def test_cleanup_and_gear_items_api(client, monkeypatch):
    _login(client, monkeypatch)
    h = {'X-CSRFToken': _csrf(client)}
    client.post(API + '/orders', json=_order(items=[{'item': '스냅도래', 'category': '기타', 'price': 1}]), headers=h)
    sug = client.get(API + '/cleanup').get_json()['suggestions']
    assert sug[0]['to'] == '도래'
    rv = client.post(API + '/cleanup', json={'categories': [{'id': sug[0]['id'], 'category': '도래'}]}, headers=h)
    assert rv.get_json()['changed'] == 1

    rv = client.post(API + '/items', json={'name': '테스트 릴', 'kind': '릴'}, headers=h)
    assert rv.status_code == 201
    gid = rv.get_json()['item']['id']
    assert client.get(f'{API}/items/{gid}').get_json()['item']['name'] == '테스트 릴'
    assert client.put(f'{API}/items/{gid}', json={'name': ''}, headers=h).status_code == 400
    assert client.delete(f'{API}/items/{gid}', headers=h).status_code == 200
    assert client.get(f'{API}/items/{gid}').status_code == 404


def test_page_renders(client, monkeypatch):
    _login(client, monkeypatch)
    html = client.get('/admin/fishing/gear').get_data(as_text=True)
    assert 'id="gear-app"' in html
    assert 'aria-current="page"' in html
