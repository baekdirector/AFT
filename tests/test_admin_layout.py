"""admin 공통 레이아웃(LNB)과 기존 /admin 의 해시 탭 (2단계 spec §2.1, §2.2)."""
from tests.test_fishing_views import _login


def test_admin_login_page_has_no_shell_but_has_remember(client):
    html = client.get('/admin').get_data(as_text=True)
    assert 'id="adm-lnb"' not in html
    assert '로그인 유지' in html


def test_admin_page_uses_shared_layout_with_lnb(client, monkeypatch):
    _login(client, monkeypatch)
    html = client.get('/admin/service').get_data(as_text=True)
    assert 'id="adm-lnb"' in html
    for label in ('서비스 관리', '항구 정보', '접속 이력', '알림 등록', '내 낚시 기록', '개요', '출조 기록', '장비 구매', '선사 노트'):
        assert label in html
    assert 'href="/admin/service#ports"' in html and 'href="/admin/service#watch"' in html
    for href in ('/admin/fishing', '/admin/fishing/trips', '/admin/fishing/gear', '/admin/fishing/ships'):
        assert f'href="{href}"' in html
    # 기존 탭 콘텐츠는 그대로 있다
    assert 'id="tab-ports"' in html and 'id="tab-access"' in html and 'id="tab-watch"' in html
    assert 'activateTab(location.hash.slice(1))' in html


def test_trips_page_marks_its_menu_active(client, monkeypatch):
    _login(client, monkeypatch)
    html = client.get('/admin/fishing/trips').get_data(as_text=True)
    assert 'class="active" aria-current="page">' in html.replace('\n', '') or 'aria-current="page"' in html
    assert html.count('aria-current="page"') == 1


def test_admin_when_logged_in_lands_on_trips(client, monkeypatch):
    _login(client, monkeypatch)
    rv = client.get('/admin')
    assert rv.status_code == 302 and rv.headers['Location'].endswith('/admin/fishing/trips')


def test_admin_service_requires_login(client):
    rv = client.get('/admin/service')
    assert rv.status_code == 302 and rv.headers['Location'].endswith('/admin')


def test_lnb_lists_fishing_log_above_service_management(client, monkeypatch):
    _login(client, monkeypatch)
    html = client.get('/admin/service').get_data(as_text=True)
    assert html.index('내 낚시 기록</div>') < html.index('서비스 관리</div>')
