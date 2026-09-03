"""
스케줄러 파이프라인 테스트 (Phase D).

네트워크를 타지 않는다. check_single_boat 를 목으로 대체한다.
수집 -> 스냅샷 -> 전환 -> 발송이 한 줄로 이어지는지, 그리고 한 척이 터져도
나머지가 계속되는지를 본다.
"""
import sys
from pathlib import Path

import pytest

SCHEDULER_DIR = Path(__file__).resolve().parents[1] / 'src'
if str(SCHEDULER_DIR) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_DIR))

from db import add_boat_instance
from models import Notification, Snapshot, Watch
from scheduler import run_scrape
from services.notify import webpush
from services.watch_service import add_watch, upsert_subscriber

DATE = '2026-12-05'      # 넉넉히 미래. 지난 날짜 정리에 걸리면 안 된다.


def entry(ship, status, available=None):
    return {'ship_name': ship, 'status': status, 'available': available,
            'display_status': f'{status} {available if available is not None else ""}'.strip(),
            'fish': '광어', 'source_url': 'https://example.com/x'}


@pytest.fixture
def scene(app, monkeypatch):
    """배 2척, 각각 감시 1건씩 걸어둔 상태."""
    monkeypatch.setattr(run_scrape, 'create_app', lambda: app)
    with app.app_context():
        boats = [
            add_boat_instance(name=f'배{i}호', url=f'https://b{i}.example/x',
                              city='인천', port='남항(인천항)', note='', is_shared=False)
            for i in range(2)
        ]
        sub = upsert_subscriber('https://push.example/aaa', 'k', 'a', '나')
        add_watch(sub, boats[0].id, '1호', DATE)
        add_watch(sub, boats[1].id, '2호', DATE)
        yield app, [b.id for b in boats]


def patch_fetch(monkeypatch, responses):
    """boat.url -> check_single_boat 반환값 매핑."""
    def fake(boat_url, year, month, day, debug_enabled=False, known_ship_name=None):
        return responses.get(boat_url, {'entries': []})

    monkeypatch.setattr('services.reservation_checker.check_single_boat', fake)
    return fake


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(webpush, 'send',
                        lambda info, payload, timeout=10: (calls.append(payload), (webpush.SENT, ''))[1])
    return calls


# --- 파이프라인 -------------------------------------------------------------

def test_first_run_stores_snapshots_without_notifying(scene, monkeypatch, sent):
    """첫 수집은 비교 대상이 없으므로 저장만 하고 알리지 않는다."""
    app, boat_ids = scene
    patch_fetch(monkeypatch, {
        'https://b0.example/x': {'entries': [entry('1호', 'full', 0)]},
        'https://b1.example/x': {'entries': [entry('2호', 'full', 0)]},
    })

    summary = run_scrape.run(delay=0)

    assert summary['targets'] == 2 and summary['collected'] == 2
    assert summary['sent'] == 0
    with app.app_context():
        assert Snapshot.query.count() == 2
    assert sent == []


def test_second_run_detects_change_and_notifies(scene, monkeypatch, sent):
    """만석이던 배에 자리가 나면 알림이 나간다. 이 서비스의 목적이다."""
    app, boat_ids = scene
    patch_fetch(monkeypatch, {
        'https://b0.example/x': {'entries': [entry('1호', 'full', 0)]},
        'https://b1.example/x': {'entries': [entry('2호', 'full', 0)]},
    })
    run_scrape.run(delay=0)

    patch_fetch(monkeypatch, {
        'https://b0.example/x': {'entries': [entry('1호', 'open', 3)]},
        'https://b1.example/x': {'entries': [entry('2호', 'full', 0)]},
    })
    summary = run_scrape.run(delay=0)

    assert summary['transitions'] == 1 and summary['sent'] == 1
    assert len(sent) == 1
    assert '자리 났습니다' in sent[0]['title']
    with app.app_context():
        assert Notification.query.filter_by(result=webpush.SENT).count() == 1


def test_unchanged_state_sends_nothing(scene, monkeypatch, sent):
    """상태가 그대로면 매 시간 돌아도 조용하다."""
    app, _ = scene
    responses = {
        'https://b0.example/x': {'entries': [entry('1호', 'full', 0)]},
        'https://b1.example/x': {'entries': [entry('2호', 'full', 0)]},
    }
    patch_fetch(monkeypatch, responses)

    run_scrape.run(delay=0)
    summary = run_scrape.run(delay=0)

    assert summary['sent'] == 0 and sent == []


# --- 실패 격리 --------------------------------------------------------------

def test_fetch_error_is_counted_as_failure_not_success(scene, monkeypatch, sent):
    """조회 실패를 '수집 성공, 변화 없음' 으로 세면 안 된다.

    실측(2026-09, Actions): 6척 중 5척이 연결 실패인데 로그에는
    collected=6, failed=0 으로 찍혔다. 실패를 성공으로 세면 무엇이 망가졌는지
    아무도 모르고, 알림이 안 와도 원인을 찾을 수 없다.
    """
    app, _ = scene
    patch_fetch(monkeypatch, {
        'https://b0.example/x': {'entries': [], 'error': 'http_error:connect timeout'},
        'https://b1.example/x': {'entries': [entry('2호', 'full', 0)]},
    })

    summary = run_scrape.run(delay=0)

    assert summary['collected'] == 1
    assert summary['failed'] == 1


def test_fetch_error_does_not_wipe_last_known_state(scene, monkeypatch, sent):
    """조회 실패는 '상태가 사라졌다'가 아니다. 기존 스냅샷을 지우면 안 된다."""
    app, _ = scene
    patch_fetch(monkeypatch, {
        'https://b0.example/x': {'entries': [entry('1호', 'open', 5)]},
        'https://b1.example/x': {'entries': [entry('2호', 'full', 0)]},
    })
    run_scrape.run(delay=0)

    patch_fetch(monkeypatch, {
        'https://b0.example/x': {'entries': [], 'error': 'http_status:403'},
        'https://b1.example/x': {'entries': [entry('2호', 'full', 0)]},
    })
    summary = run_scrape.run(delay=0)

    assert summary['sent'] == 0, '조회 실패로 가짜 알림이 나가면 안 된다'
    with app.app_context():
        row = Snapshot.query.filter_by(ship_name='1호').one()
        assert (row.status, row.available) == ('open', 5), '마지막으로 알던 상태가 남아야 한다'


def test_one_boat_raising_does_not_stop_the_rest(scene, monkeypatch, sent):
    app, _ = scene
    import scheduler.run_scrape as rs
    original = rs.collect_one

    def flaky(boat, target_date, dry_run):
        if boat.name == '배0호':
            raise RuntimeError('터짐')
        return original(boat, target_date, dry_run)

    monkeypatch.setattr(rs, 'collect_one', flaky)
    patch_fetch(monkeypatch, {
        'https://b1.example/x': {'entries': [entry('2호', 'full', 0)]},
    })

    summary = run_scrape.run(delay=0)

    assert summary['failed'] == 1 and summary['collected'] == 1
    with app.app_context():
        assert Snapshot.query.count() == 1


# --- 대상 선정 --------------------------------------------------------------

def test_only_watched_targets_are_collected(app, monkeypatch, sent):
    """감시 안 걸린 배는 수집하지 않는다. 이게 수집량을 작게 유지하는 핵심이다."""
    monkeypatch.setattr(run_scrape, 'create_app', lambda: app)
    fetched = []

    with app.app_context():
        watched_boat = add_boat_instance(name='감시배', url='https://watched.example/x',
                                         city='인천', port='남항(인천항)', note='', is_shared=False)
        add_boat_instance(name='안보는배', url='https://ignored.example/x',
                          city='인천', port='남항(인천항)', note='', is_shared=False)
        sub = upsert_subscriber('https://push.example/aaa', 'k', 'a')
        add_watch(sub, watched_boat.id, '1호', DATE)

    def fake(boat_url, year, month, day, debug_enabled=False, known_ship_name=None):
        fetched.append(boat_url)
        return {'entries': [entry('1호', 'full', 0)]}

    monkeypatch.setattr('services.reservation_checker.check_single_boat', fake)
    run_scrape.run(delay=0)

    assert fetched == ['https://watched.example/x']


def test_past_date_watches_are_deactivated(app, monkeypatch, sent):
    """지난 날짜 감시가 슬롯을 계속 먹으면 새 감시를 걸 수 없다."""
    monkeypatch.setattr(run_scrape, 'create_app', lambda: app)
    with app.app_context():
        boat = add_boat_instance(name='배', url='https://b.example/x',
                                 city='인천', port='남항(인천항)', note='', is_shared=False)
        sub = upsert_subscriber('https://push.example/aaa', 'k', 'a')
        add_watch(sub, boat.id, '1호', '2020-01-01')      # 지난 날짜
        add_watch(sub, boat.id, '2호', DATE)              # 미래

    monkeypatch.setattr('services.reservation_checker.check_single_boat',
                        lambda *a, **kw: {'entries': [entry('2호', 'full', 0)]})

    summary = run_scrape.run(delay=0)

    assert summary['expired_watches'] == 1
    assert summary['targets'] == 1, '지난 날짜는 수집 대상에서 빠진다'
    with app.app_context():
        assert Watch.query.filter_by(active=True).count() == 1


def test_main_refuses_to_run_without_database_url(monkeypatch, capsys):
    """DATABASE_URL 없이 돌면 로컬 SQLite 를 보게 되어 감시를 하나도 못 찾고,
    아무 일도 안 한 채 성공한 것처럼 끝난다. CI 에서 초록불인데 알림은 영영
    안 오는 상태가 되므로 크게 실패해야 한다."""
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr('sys.argv', ['run_scrape.py'])

    called = []
    monkeypatch.setattr(run_scrape, 'run', lambda **kw: called.append(kw) or {})

    assert run_scrape.main() == 2
    assert called == [], '수집을 시도조차 하면 안 된다'


def test_allow_local_db_opt_out(app, monkeypatch):
    """개발 중에는 로컬 DB 로 돌려볼 수 있어야 한다."""
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr('sys.argv', ['run_scrape.py', '--allow-local-db'])
    monkeypatch.setattr(run_scrape, 'create_app', lambda: app)

    assert run_scrape.main() == 0


def test_main_fails_when_nothing_could_be_collected(app, monkeypatch):
    """감시가 있는데 하나도 못 긁었으면 실패다. 조용히 넘어가면 매시간
    초록불을 내면서 알림은 오지 않는다."""
    monkeypatch.setenv('DATABASE_URL', 'postgresql://x/y')
    monkeypatch.setattr('sys.argv', ['run_scrape.py'])
    monkeypatch.setattr(run_scrape, 'run',
                        lambda **kw: {'targets': 5, 'collected': 0, 'failed': 5,
                                      'transitions': 0, 'sent': 0, 'expired_watches': 0})

    assert run_scrape.main() == 1


def test_no_targets_is_a_clean_noop(app, monkeypatch):
    monkeypatch.setattr(run_scrape, 'create_app', lambda: app)
    summary = run_scrape.run(delay=0)
    assert summary['targets'] == 0 and summary['collected'] == 0


# --- dry-run ---------------------------------------------------------------

def test_dry_run_writes_nothing(scene, monkeypatch, sent):
    app, _ = scene
    patch_fetch(monkeypatch, {
        'https://b0.example/x': {'entries': [entry('1호', 'open', 3)]},
        'https://b1.example/x': {'entries': [entry('2호', 'full', 0)]},
    })

    run_scrape.run(dry_run=True, delay=0)

    with app.app_context():
        assert Snapshot.query.count() == 0
    assert sent == []
