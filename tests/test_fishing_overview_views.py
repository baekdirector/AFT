"""개요 대시보드 화면·API (5단계 spec §3)."""
from tests.test_fishing_views import _login

API = '/admin/api/fishing/overview'


def test_page_and_api_require_login(client):
    rv = client.get('/admin/fishing')
    assert rv.status_code == 302 and rv.headers['Location'].endswith('/admin')
    assert client.get(API).status_code == 403


def test_api_year_arg(client, monkeypatch):
    _login(client, monkeypatch)
    data = client.get(API).get_json()
    assert isinstance(data['year'], int) and data['todo']['upcoming'] == []
    assert client.get(API + '?year=all').get_json()['year'] is None
    assert client.get(API + '?year=2025').get_json()['year'] == 2025
    rv = client.get(API + '?year=abc')
    assert rv.status_code == 400 and rv.get_json()['field'] == 'year'


def test_page_renders_with_active_menu(client, monkeypatch):
    _login(client, monkeypatch)
    html = client.get('/admin/fishing').get_data(as_text=True)
    assert 'id="overview-app"' in html
    assert html.count('aria-current="page"') == 1
