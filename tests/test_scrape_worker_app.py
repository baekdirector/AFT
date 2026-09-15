"""
스크래핑 워커(worker/app.py) 테스트.

이 서비스는 DB도, 감시/알림 로직도 모른다 - 배 한 척을 긁어서 결과
dict를 그대로 돌려주는 게 전부다. 실제 fetch+parse는
_check_single_boat_locally()가 하므로 여기서는 목으로 대체하고,
이 얇은 Flask 레이어(인증 토큰, 요청 파싱)만 검증한다.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

# 리포 루트에 이미 app.py(create_app()만 만들고 .run()은 안 부르는 그
# 파일 - CLAUDE.md에 적힌 알려진 함정)가 있어서, 이름을 'app'으로 그냥
# import 하면 sys.modules 캐시 상태에 따라 엉뚱한 파일을 가져올 위험이
# 있다. 경로로 직접 로드해 그 위험을 아예 없앤다.
_spec = importlib.util.spec_from_file_location('scrape_worker_app', ROOT / 'worker' / 'app.py')
worker_app_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker_app_module)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(worker_app_module, 'WORKER_TOKEN', None)
    worker_app_module.app.config['TESTING'] = True
    return worker_app_module.app.test_client()


def test_check_calls_local_checker_and_returns_its_result(client, monkeypatch):
    seen = {}

    def fake_local(boat_url, year, month, day, debug_enabled=False, known_ship_name=None):
        seen.update(boat_url=boat_url, year=year, month=month, day=day,
                    debug_enabled=debug_enabled, known_ship_name=known_ship_name)
        return {'entries': [{'ship_name': known_ship_name, 'status': 'open', 'available': 5}]}

    monkeypatch.setattr(worker_app_module, '_check_single_boat_locally', fake_local)

    resp = client.post('/check', json={
        'boat_url': 'https://boat.example/x', 'year': 2026, 'month': 11, 'day': 3,
        'known_ship_name': '테스트호',
    })

    assert resp.status_code == 200
    assert resp.get_json()['entries'][0]['ship_name'] == '테스트호'
    assert seen == {'boat_url': 'https://boat.example/x', 'year': 2026, 'month': 11,
                    'day': 3, 'debug_enabled': False, 'known_ship_name': '테스트호'}


def test_check_rejects_missing_fields(client):
    resp = client.post('/check', json={'boat_url': 'https://boat.example/x'})
    assert resp.status_code == 400


def test_healthz_ok(client):
    resp = client.get('/healthz')
    assert resp.status_code == 200


# --- 토큰 인증 --------------------------------------------------------------

def test_check_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr(worker_app_module, 'WORKER_TOKEN', 'secret-token')
    monkeypatch.setattr(worker_app_module, '_check_single_boat_locally',
                        lambda *a, **kw: {'entries': []})
    worker_app_module.app.config['TESTING'] = True
    client = worker_app_module.app.test_client()

    payload = {'boat_url': 'https://boat.example/x', 'year': 2026, 'month': 11, 'day': 3}

    no_token = client.post('/check', json=payload)
    assert no_token.status_code == 403

    wrong_token = client.post('/check', json=payload, headers={'X-Worker-Token': 'wrong'})
    assert wrong_token.status_code == 403

    right_token = client.post('/check', json=payload, headers={'X-Worker-Token': 'secret-token'})
    assert right_token.status_code == 200
