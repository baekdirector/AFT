# -*- coding: utf-8 -*-
"""/admin 접속 이력 페이지 - 로그인 게이트, 방문 기록 훅(허용목록), 보관
기간 정리, IP 위치 조회 캐시를 검증한다."""
import re
from datetime import datetime, timedelta

from db import db


def _csrf_token(client, path):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html)
    assert m, f'{path} 에서 csrf_token 을 찾지 못함'
    return m.group(1)


# ---- device_type ----

def test_device_type_detects_mobile_tablet_pc():
    from services.visit_logger import device_type

    mobile_ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15'
    tablet_ua = 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15'
    pc_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0'

    assert device_type(mobile_ua) == 'mobile'
    assert device_type(tablet_ua) == 'tablet'
    assert device_type(pc_ua) == 'pc'
    assert device_type(None) == 'unknown'
    assert device_type('') == 'unknown'


# ---- log_visit allowlist (before_request 훅을 통해 통합 테스트) ----

def test_visit_hook_logs_tracked_pages_but_not_api_or_healthz(client, app):
    client.get('/')
    client.get('/healthz')
    client.get('/api/status/cached?date=2026-09-11')

    with app.app_context():
        from models import VisitLog
        paths = [row.path for row in VisitLog.query.all()]
        assert '/' in paths
        assert '/healthz' not in paths
        assert not any(p.startswith('/api/') for p in paths)


def test_visit_hook_does_not_log_admin_page_itself(client, app):
    client.get('/admin')

    with app.app_context():
        from models import VisitLog
        assert VisitLog.query.filter_by(path='/admin').count() == 0


# ---- 보관 기간 정리 ----

def test_purge_old_visit_logs_removes_only_expired_rows(app):
    from models import VisitLog
    from services.snapshot_repository import purge_old_visit_logs

    with app.app_context():
        old = VisitLog(path='/', method='GET', ip='1.2.3.4', device_type='pc',
                        visited_at=datetime.utcnow() - timedelta(days=91))
        fresh = VisitLog(path='/', method='GET', ip='1.2.3.4', device_type='pc',
                          visited_at=datetime.utcnow() - timedelta(days=1))
        db.session.add_all([old, fresh])
        db.session.commit()

        deleted = purge_old_visit_logs()

        assert deleted == 1
        remaining = VisitLog.query.all()
        assert len(remaining) == 1 and remaining[0].id == fresh.id


# ---- 로그인/로그아웃 플로우 ----

def test_admin_login_rejected_without_password_env(client, monkeypatch):
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    rv = client.post('/admin', data={
        'csrf_token': _csrf_token(client, '/admin'),
        'username': 'admin', 'password': 'whatever',
    }, follow_redirects=True)
    assert '관리자 로그인' in rv.get_data(as_text=True)
    assert '접속 이력' not in rv.get_data(as_text=True)


def test_admin_login_wrong_password_rejected(client, monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'correct-horse')
    rv = client.post('/admin', data={
        'csrf_token': _csrf_token(client, '/admin'),
        'username': 'admin', 'password': 'wrong',
    }, follow_redirects=True)
    assert '올바르지 않습니다' in rv.get_data(as_text=True)


def test_admin_login_success_then_logout(client, monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'correct-horse')

    rv = client.post('/admin', data={
        'csrf_token': _csrf_token(client, '/admin'),
        'username': 'admin', 'password': 'correct-horse',
    }, follow_redirects=True)
    assert '접속 이력' in rv.get_data(as_text=True)

    with client.session_transaction() as sess:
        assert sess.get('admin_authed') is True

    rv2 = client.post('/admin/logout', follow_redirects=True)
    assert '관리자 로그인' in rv2.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert not sess.get('admin_authed')


# ---- IP 위치 조회 ----

def test_resolve_missing_marks_private_ip_without_calling_api(app, monkeypatch):
    from models import IpLocation
    from services import ip_location

    def _boom(*a, **kw):
        raise AssertionError('사설 IP는 외부 API를 호출하면 안 된다')

    monkeypatch.setattr(ip_location.requests, 'post', _boom)

    with app.app_context():
        ip_location.resolve_missing(['127.0.0.1', '192.168.0.5'])
        rows = {row.ip: row for row in IpLocation.query.all()}
        assert rows['127.0.0.1'].is_private is True
        assert rows['192.168.0.5'].is_private is True


def test_resolve_missing_caches_successful_batch_lookup(app, monkeypatch):
    from models import IpLocation
    from services import ip_location

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            # ip-api.com은 lang=ko를 지원하지 않아 실제로도 영문으로 온다
            # (국내 IP도 city="Seoul" 처럼 영문) - 한글화는 format_location()이
            # 표시 시점에 따로 한다.
            return [{'status': 'success', 'query': '8.8.8.8', 'city': 'Seoul',
                      'regionName': 'Seoul', 'country': 'South Korea'}]

    monkeypatch.setattr(ip_location.requests, 'post', lambda *a, **kw: _FakeResp())

    with app.app_context():
        ip_location.resolve_missing(['8.8.8.8'])
        row = IpLocation.query.get('8.8.8.8')
        assert row is not None
        assert row.city == 'Seoul'
        assert row.is_private is False

        # 이미 캐시된 IP는 다시 호출하지 않는다(재호출 시 예외를 던지게 해서 검증).
        monkeypatch.setattr(ip_location.requests, 'post',
                             lambda *a, **kw: (_ for _ in ()).throw(AssertionError('재조회하면 안 됨')))
        ip_location.resolve_missing(['8.8.8.8'])


def test_resolve_missing_survives_api_failure(app, monkeypatch):
    from models import IpLocation
    from services import ip_location

    def _raise(*a, **kw):
        raise RuntimeError('network down')

    monkeypatch.setattr(ip_location.requests, 'post', _raise)

    with app.app_context():
        ip_location.resolve_missing(['8.8.8.8'])  # 예외 없이 통과해야 함
        assert IpLocation.query.get('8.8.8.8') is None


# ---- 위치 한글 표시 ----

def test_format_location_translates_korean_city_and_region():
    from models import IpLocation
    from services.ip_location import format_location

    loc = IpLocation(ip='1.1.1.1', city='Suwon', region='Gyeonggi-do',
                     country='South Korea', is_private=False)
    assert format_location(loc) == '수원 (경기도)'


def test_format_location_leaves_foreign_locations_in_english():
    from models import IpLocation
    from services.ip_location import format_location

    loc = IpLocation(ip='34.83.150.217', city='The Dalles', region='Oregon',
                     country='United States', is_private=False)
    assert format_location(loc) == 'The Dalles (Oregon)'


def test_format_location_handles_missing_private_and_unresolved():
    from models import IpLocation
    from services.ip_location import format_location

    assert format_location(None) == '-'
    assert format_location(IpLocation(ip='127.0.0.1', is_private=True)) == '로컬'
    assert format_location(IpLocation(ip='9.9.9.9', is_private=False, city=None)) == '확인 실패'


# ---- 한국시간(KST) 변환 표시 ----

def test_admin_table_shows_full_datetime_in_kst_not_utc(client, app, monkeypatch):
    """UTC로 저장된 visited_at이 화면에는 KST(UTC+9)로, "YYYY-MM-DD HH:MM:SS"
    형태로 보여야 한다. 예: UTC 9/10 19:30 -> KST 9/11 04:30 (날짜까지 넘어감)."""
    from models import VisitLog

    with app.app_context():
        db.session.add(VisitLog(path='/', method='GET', ip='127.0.0.1', device_type='pc',
                                visited_at=datetime(2026, 9, 10, 19, 30, 0)))
        db.session.commit()

    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'correct-horse')
    client.post('/admin', data={
        'csrf_token': _csrf_token(client, '/admin'),
        'username': 'admin', 'password': 'correct-horse',
    })

    html = client.get('/admin').get_data(as_text=True)
    assert '2026-09-11 04:30:00' in html, 'UTC 19:30 은 KST(UTC+9)로 다음날 04:30 이어야 한다'
    assert '2026-09-10 19:30' not in html, 'UTC 그대로 보이면 안 된다'


# ---- 보관 기간(1주일) ----

def test_visit_log_retention_is_seven_days():
    from services.snapshot_repository import VISIT_LOG_RETENTION_DAYS
    assert VISIT_LOG_RETENTION_DAYS == 7


def test_purge_old_visit_logs_boundary_at_seven_days(app):
    from models import VisitLog
    from services.snapshot_repository import purge_old_visit_logs

    with app.app_context():
        just_over = VisitLog(path='/', method='GET', ip='1.2.3.4', device_type='pc',
                             visited_at=datetime.utcnow() - timedelta(days=8))
        just_under = VisitLog(path='/', method='GET', ip='1.2.3.4', device_type='pc',
                              visited_at=datetime.utcnow() - timedelta(days=6))
        db.session.add_all([just_over, just_under])
        db.session.commit()

        deleted = purge_old_visit_logs()

        assert deleted == 1
        remaining = VisitLog.query.all()
        assert len(remaining) == 1 and remaining[0].id == just_under.id
