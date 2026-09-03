"""
수집 트리거 엔드포인트 테스트 (Phase D 보강).

이 엔드포인트는 외부 사이트로 요청을 내보낸다. 공개되면 남용될 수 있으므로
인증을 특히 촘촘히 본다.
"""
import pytest

from db import add_boat_instance, db
from models import Boat, Snapshot
from services.watch_service import add_watch, upsert_subscriber

DATE = '2026-12-05'
TOKEN = 'test-scrape-token-abc123'


@pytest.fixture
def watched(app, monkeypatch):
    monkeypatch.setenv('SCRAPE_TOKEN', TOKEN)
    with app.app_context():
        Boat.query.delete()
        db.session.commit()
        boat = add_boat_instance(name='감시배', url='https://b.example/x',
                                 city='인천', port='남항(인천항)', note='', is_shared=False)
        sub = upsert_subscriber('https://push.example/aaa', 'k', 'a')
        add_watch(sub, boat.id, '1호', DATE)
        yield boat.id


def fake_fetch(monkeypatch, entries):
    monkeypatch.setattr(
        'services.reservation_checker.check_single_boat',
        lambda *a, **kw: {'entries': entries})


def entry(ship, status, available=None):
    return {'ship_name': ship, 'status': status, 'available': available,
            'display_status': status, 'fish': '광어', 'source_url': 'https://x/y'}


# --- 인증 ------------------------------------------------------------------

def test_missing_token_config_disables_the_endpoint(app, client, monkeypatch):
    """토큰이 설정 안 됐으면 열어두지 않는다. 열어두면 누구나 스크래핑을
    시킬 수 있고, 그 부하는 원본 사이트가 받는다."""
    monkeypatch.delenv('SCRAPE_TOKEN', raising=False)

    resp = client.post('/api/scrape/run')

    assert resp.status_code == 503
    assert 'SCRAPE_TOKEN' in resp.get_json()['error']


def test_wrong_token_is_rejected(client, watched):
    resp = client.post('/api/scrape/run', headers={'X-Scrape-Token': 'nope'})
    assert resp.status_code == 403


def test_no_token_header_is_rejected(client, watched):
    resp = client.post('/api/scrape/run')
    assert resp.status_code == 403


def test_get_is_not_allowed(client, watched):
    """부작용이 있는 동작이므로 GET 으로 열어두지 않는다."""
    assert client.get('/api/scrape/run').status_code == 405


# --- 동작 ------------------------------------------------------------------

def test_valid_token_runs_the_pipeline(app, client, watched, monkeypatch):
    fake_fetch(monkeypatch, [entry('1호', 'full', 0)])

    resp = client.post('/api/scrape/run', headers={'X-Scrape-Token': TOKEN})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['targets'] == 1 and body['collected'] == 1
    assert body['failed'] == 0
    assert 'elapsed_seconds' in body
    with app.app_context():
        assert Snapshot.query.count() == 1


def test_dry_run_writes_nothing(app, client, watched, monkeypatch):
    fake_fetch(monkeypatch, [entry('1호', 'open', 3)])

    resp = client.post('/api/scrape/run?dry_run=true',
                       headers={'X-Scrape-Token': TOKEN})

    assert resp.get_json()['dry_run'] is True
    with app.app_context():
        assert Snapshot.query.count() == 0


def test_collection_failure_is_reported_not_hidden(app, client, watched, monkeypatch):
    """실패를 성공으로 세면 알림이 안 와도 원인을 알 수 없다."""
    monkeypatch.setattr(
        'services.reservation_checker.check_single_boat',
        lambda *a, **kw: {'entries': [], 'error': 'http_error:connect timeout'})

    body = client.post('/api/scrape/run',
                       headers={'X-Scrape-Token': TOKEN}).get_json()

    assert body['collected'] == 0 and body['failed'] == 1


def test_pipeline_exception_returns_500_not_a_silent_success(app, client, watched, monkeypatch):
    monkeypatch.setattr('scheduler.run_scrape.run_pipeline',
                        lambda **kw: (_ for _ in ()).throw(RuntimeError('터짐')))

    resp = client.post('/api/scrape/run', headers={'X-Scrape-Token': TOKEN})

    assert resp.status_code == 500
    assert 'RuntimeError' in resp.get_json()['error']
