"""admin 공통 레이아웃(LNB)과 기존 /admin 의 해시 탭 (2단계 spec §2.1, §2.2)."""
from tests.test_fishing_views import _login


def test_admin_login_page_has_no_shell_but_has_remember(client):
    html = client.get('/admin').get_data(as_text=True)
    assert 'id="adm-lnb"' not in html
    assert '로그인 유지' in html


def test_admin_page_uses_shared_layout_with_lnb(client, monkeypatch):
    _login(client, monkeypatch)
    html = client.get('/admin').get_data(as_text=True)
    assert 'id="adm-lnb"' in html
    for label in ('서비스 관리', '항구 정보', '접속 이력', '알림 등록', '내 낚시 기록', '출조 기록', '준비 중'):
        assert label in html
    assert 'href="/admin#ports"' in html and 'href="/admin#watch"' in html
    assert 'href="/admin/fishing/trips"' in html
    # 기존 탭 콘텐츠는 그대로 있다
    assert 'id="tab-ports"' in html and 'id="tab-access"' in html and 'id="tab-watch"' in html
    assert 'activateTab(location.hash.slice(1))' in html


def test_trips_page_marks_its_menu_active(client, monkeypatch):
    _login(client, monkeypatch)
    html = client.get('/admin/fishing/trips').get_data(as_text=True)
    assert 'class="active" aria-current="page">' in html.replace('\n', '') or 'aria-current="page"' in html
    assert html.count('aria-current="page"') == 1
