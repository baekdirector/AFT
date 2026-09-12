# -*- coding: utf-8 -*-
"""관리자 콘솔 "알림 등록" 탭 - 기기(구독자)별로 감시를 묶어 보여주고,
관리자가 개별/그룹/전체 단위로 해제할 수 있는 기능을 검증한다.
접속 이력 탭 자체(test_admin_visits.py)는 로직을 안 건드렸으므로 여기서
다시 검증하지 않는다."""
import re

from db import db


def _csrf_token(client, path):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html)
    assert m, f'{path} 에서 csrf_token 을 찾지 못함'
    return m.group(1)


def _login(client, monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'correct-horse')
    client.post('/admin', data={
        'csrf_token': _csrf_token(client, '/admin'),
        'username': 'admin', 'password': 'correct-horse',
    })


def _seed_watch(app, ip='1.2.3.4', device_type='mobile', user_agent='UA',
                boat_name='테스트선단', ship_name='테스트호', target_date='2026-12-25'):
    with app.app_context():
        from models import Boat, Subscriber, Watch
        boat = Boat.query.filter_by(name=boat_name).one_or_none()
        if boat is None:
            boat = Boat(name=boat_name, url=f'https://example.com/{boat_name}',
                       city='인천', port='연안부두')
            db.session.add(boat)
            db.session.commit()
        sub = Subscriber(endpoint=f'https://push.example/{ip}-{ship_name}-{target_date}',
                         p256dh='p', auth='a', ip=ip, device_type=device_type,
                         user_agent=user_agent)
        db.session.add(sub)
        db.session.commit()
        watch = Watch(subscriber_id=sub.id, boat_id=boat.id, ship_name=ship_name,
                      target_date=target_date, active=True)
        db.session.add(watch)
        db.session.commit()
        return sub.id, watch.id


# ---- services.watch_service.admin_list_devices ----

def test_admin_list_devices_groups_by_subscriber_not_ip(app):
    """같은 IP를 쓰는 서로 다른 두 구독자(기기)는 서로 다른 카드로 묶여야
    한다 - 공유기 아래 다른 사람이 같은 IP를 쓸 수 있어서, IP로 묶으면
    남의 감시가 내 카드에 섞여 보이는 문제가 생긴다."""
    sub1_id, w1_id = _seed_watch(app, ip='9.9.9.9', ship_name='배1')
    sub2_id, w2_id = _seed_watch(app, ip='9.9.9.9', ship_name='배2')

    with app.app_context():
        from services.watch_service import admin_list_devices
        devices = admin_list_devices()

    assert len(devices) == 2
    ids = {d['subscriber_id'] for d in devices}
    assert ids == {sub1_id, sub2_id}


def test_admin_list_devices_only_includes_active_watches(app):
    sub_id, watch_id = _seed_watch(app, ship_name='활성배')
    with app.app_context():
        from models import Watch
        from services.watch_service import admin_list_devices
        # 두 번째 감시는 이미 꺼진 상태로 추가 - 화면에 안 나와야 한다
        from models import Boat, Subscriber
        sub = Subscriber.query.get(sub_id)
        boat = Boat.query.filter_by(name='테스트선단').first()
        inactive = Watch(subscriber_id=sub_id, boat_id=boat.id, ship_name='꺼진배',
                         target_date='2026-12-25', active=False)
        db.session.add(inactive)
        db.session.commit()

        devices = admin_list_devices()
        assert len(devices) == 1
        names = [w['ship_name'] for w in devices[0]['watches']]
        assert names == ['활성배']


def test_admin_list_devices_empty_when_no_active_watches(app):
    with app.app_context():
        from services.watch_service import admin_list_devices
        assert admin_list_devices() == []


# ---- services.watch_service.admin_release_watches ----

def test_admin_release_watches_deactivates_only_given_ids(app):
    _sub_id, keep_id = _seed_watch(app, ship_name='유지배', target_date='2026-12-25')
    _sub_id2, drop_id = _seed_watch(app, ship_name='해제배', target_date='2026-12-26')

    with app.app_context():
        from models import Watch
        from services.watch_service import admin_release_watches
        released = admin_release_watches([drop_id])
        assert released == 1
        assert Watch.query.get(drop_id).active is False
        assert Watch.query.get(keep_id).active is True


def test_admin_release_watches_with_empty_list_does_nothing(app):
    with app.app_context():
        from services.watch_service import admin_release_watches
        assert admin_release_watches([]) == 0


def test_admin_release_watches_ignores_already_inactive_ids(app):
    _sub_id, watch_id = _seed_watch(app, ship_name='이미꺼짐')
    with app.app_context():
        from models import Watch
        from services.watch_service import admin_release_watches
        admin_release_watches([watch_id])  # 첫 해제
        released_again = admin_release_watches([watch_id])  # 두 번째는 셀 게 없어야 함
        assert released_again == 0


# ---- POST /admin/watches/release ----

def test_release_route_requires_admin_login(client):
    rv = client.post('/admin/watches/release', json={'watch_ids': [1]})
    assert rv.status_code == 403


def test_release_route_requires_csrf_token(client, app, monkeypatch):
    _login(client, monkeypatch)
    _sub_id, watch_id = _seed_watch(app, ship_name='CSRF테스트배')

    rv = client.post('/admin/watches/release', json={'watch_ids': [watch_id]})
    assert rv.status_code == 400

    with app.app_context():
        from models import Watch
        assert Watch.query.get(watch_id).active is True  # 안 지워졌어야 함


def test_release_route_deactivates_watch_and_returns_count(client, app, monkeypatch):
    _login(client, monkeypatch)
    _sub_id, watch_id = _seed_watch(app, ship_name='정상해제배')

    csrf = _csrf_token(client, '/admin')
    rv = client.post('/admin/watches/release', json={'watch_ids': [watch_id]},
                     headers={'X-CSRFToken': csrf})
    assert rv.status_code == 200
    assert rv.get_json() == {'released': 1}

    with app.app_context():
        from models import Watch
        assert Watch.query.get(watch_id).active is False


def test_release_route_rejects_non_integer_watch_ids(client, app, monkeypatch):
    _login(client, monkeypatch)
    csrf = _csrf_token(client, '/admin')
    rv = client.post('/admin/watches/release', json={'watch_ids': ['not-an-int']},
                     headers={'X-CSRFToken': csrf})
    assert rv.status_code == 400


# ---- GET /admin 인증 후 화면에 기기/감시가 반영되는지 ----

def test_admin_page_renders_device_watch_summary(client, app, monkeypatch):
    _login(client, monkeypatch)
    _seed_watch(app, ip='5.5.5.5', device_type='pc', ship_name='요약테스트배')

    rv = client.get('/admin')
    html = rv.get_data(as_text=True)
    assert '알림 등록' in html
    # devices|tojson 은 한글을 \uXXXX 로 이스케이프하므로 이스케이프된
    # 형태로 확인한다(원문 그대로는 안 보임 - Jinja tojson 의 정상 동작).
    import json
    assert json.dumps('요약테스트배').strip('"') in html
