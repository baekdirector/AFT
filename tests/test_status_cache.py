"""
라이브 조회가 스냅샷 캐시를 채우는지 검증한다 (Phase F1).

배경: 스냅샷은 감시 등록된 5건만 쌓인다. /status 를 DB 읽기로 바꾸면 71척 중
66척이 빈칸이 되어 지금보다 나빠진다. 그런데 /api/status 는 이미 71척을 긁고
있으면서 그 결과를 버리고 있었다. 그걸 저장하면 Actions 분을 한 푼도 더 쓰지
않고 캐시가 채워진다.
"""
import json

import pytest

from db import add_boat_instance, db
from models import Notification, Snapshot
from services.notify import webpush
from services.watch_service import add_watch, upsert_subscriber

DATE = {'year': '2026', 'month': '10', 'day': '3'}
DATE_STR = '2026-10-03'


@pytest.fixture
def boats(app):
    from models import Boat
    with app.app_context():
        Boat.query.delete()
        db.session.commit()
        made = [
            add_boat_instance(name=f'배{i}호', url=f'https://b{i}.example/x',
                              city='인천', port='남항(인천항)', note='', is_shared=False)
            for i in range(3)
        ]
        yield [b.id for b in made]


def fake_check(monkeypatch, by_url):
    import routes.views as views

    def fake(boat_url, year, month, day, debug_enabled=False, known_ship_name=None):
        return by_url.get(boat_url, {'entries': []})

    monkeypatch.setattr(views, 'check_single_boat', fake)


def entry(ship, status, available=None):
    return {'ship_name': ship, 'status': status, 'available': available,
            'display_status': status, 'fish': '광어',
            'source_url': 'https://example.com/x'}


def post(client):
    resp = client.post('/api/status', data=DATE)
    assert resp.status_code == 200
    return [json.loads(l) for l in resp.get_data(as_text=True).splitlines() if l.strip()]


# --- 캐시 채우기 -----------------------------------------------------------

def test_live_query_writes_snapshots(app, client, boats, monkeypatch):
    """조회 한 번이 그 날짜의 캐시를 채운다."""
    fake_check(monkeypatch, {
        'https://b0.example/x': {'entries': [entry('1호', 'full', 0)]},
        'https://b1.example/x': {'entries': [entry('2호', 'open', 4)]},
        'https://b2.example/x': {'entries': [entry('3호', 'maintenance')]},
    })

    post(client)

    with app.app_context():
        rows = Snapshot.query.order_by(Snapshot.ship_name).all()
        assert [(r.ship_name, r.status) for r in rows] == [
            ('1호', 'full'), ('2호', 'open'), ('3호', 'maintenance')]
        assert all(r.target_date == DATE_STR for r in rows)


def test_second_query_updates_not_duplicates(app, client, boats, monkeypatch):
    fake_check(monkeypatch, {'https://b0.example/x': {'entries': [entry('1호', 'full', 0)]}})
    post(client)

    fake_check(monkeypatch, {'https://b0.example/x': {'entries': [entry('1호', 'open', 2)]}})
    post(client)

    with app.app_context():
        rows = Snapshot.query.filter_by(ship_name='1호').all()
        assert len(rows) == 1, '이력이 아니라 최신 상태 1행만 유지한다'
        assert (rows[0].status, rows[0].available) == ('open', 2)


def test_boat_id_is_included_in_stream(app, client, boats, monkeypatch):
    """스냅샷을 쓰려면 어느 배인지 알아야 한다."""
    fake_check(monkeypatch, {'https://b0.example/x': {'entries': [entry('1호', 'full', 0)]}})

    lines = post(client)
    rows = [l for l in lines if l.get('registered_name')]

    assert all('boat_id' in r for r in rows)


# --- 알림 정합성 -----------------------------------------------------------

def test_live_query_notifies_watchers_of_a_change(app, client, boats, monkeypatch):
    """웹 조회가 스냅샷만 갱신하고 알리지 않으면, 스케줄러는 다음에 볼 때
    이미 바뀐 상태라 변화를 못 알아챈다. 감시자는 영영 못 받는다."""
    sent = []
    monkeypatch.setattr(webpush, 'send',
                        lambda i, p, timeout=10: (sent.append(p), (webpush.SENT, ''))[1])

    with app.app_context():
        sub = upsert_subscriber('https://push.example/aaa', 'k', 'a')
        add_watch(sub, boats[0], '1호', DATE_STR)

    fake_check(monkeypatch, {'https://b0.example/x': {'entries': [entry('1호', 'full', 0)]}})
    post(client)
    assert sent == [], '첫 조회는 비교 대상이 없으므로 알리지 않는다'

    fake_check(monkeypatch, {'https://b0.example/x': {'entries': [entry('1호', 'open', 3)]}})
    post(client)

    assert len(sent) == 1 and '자리 났습니다' in sent[0]['title']
    with app.app_context():
        assert Notification.query.filter_by(result=webpush.SENT).count() == 1


def test_unwatched_boat_change_notifies_nobody(app, client, boats, monkeypatch):
    sent = []
    monkeypatch.setattr(webpush, 'send',
                        lambda i, p, timeout=10: (sent.append(p), (webpush.SENT, ''))[1])

    fake_check(monkeypatch, {'https://b0.example/x': {'entries': [entry('1호', 'full', 0)]}})
    post(client)
    fake_check(monkeypatch, {'https://b0.example/x': {'entries': [entry('1호', 'open', 3)]}})
    post(client)

    assert sent == []


# --- 실패 격리 --------------------------------------------------------------

def test_cache_failure_does_not_break_the_query(app, client, boats, monkeypatch):
    """캐시 저장이 실패해도 사용자가 방금 본 조회 결과는 멀쩡해야 한다."""
    import routes.views as views

    fake_check(monkeypatch, {'https://b0.example/x': {'entries': [entry('1호', 'full', 0)]}})
    monkeypatch.setattr('services.snapshot_repository.apply_many',
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('DB 터짐')))

    lines = post(client)

    assert lines[-1]['type'] == 'end' and lines[-1]['completed'] == 3
    assert len([l for l in lines if l.get('registered_name')]) == 3


def test_boats_with_no_entries_are_not_cached(app, client, boats, monkeypatch):
    """조회 실패로 만들어진 unknown 자리표시 행을 캐시에 넣으면 안 된다."""
    fake_check(monkeypatch, {})   # 전부 빈 결과 -> unknown 자리표시가 붙는다

    post(client)

    with app.app_context():
        # unknown 은 신뢰할 수 없는 관측이라 새 행을 만들지 않는다
        assert Snapshot.query.filter(Snapshot.status != 'unknown').count() == 0
