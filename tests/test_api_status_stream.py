"""
/api/status NDJSON 스트림의 계약 테스트 (Phase A0).

실측 배경: 71척 조회가 gunicorn 기본 timeout 30초를 넘겨 워커가 강제 종료되면서
스트림이 19척에서 잘렸다. 프론트는 잘린 것과 다 끝난 것을 구분할 수 없었다.
그래서 'end' 마커를 도입했고, 이 테스트가 그 계약을 고정한다.

네트워크는 타지 않는다. check_single_boat 을 목으로 대체한다.
"""
import json

import pytest

from db import add_boat_instance


def _seed(app, count):
    """boats 테이블을 비우고 count 척을 넣는다.

    create_app() 이 boat_list.xlsx 로 공용 배를 시드하므로, 지우지 않으면
    조회 대상 수가 달라져 총계 단언이 무의미해진다.
    """
    from db import db
    from models import Boat

    with app.app_context():
        Boat.query.delete()
        db.session.commit()
        for i in range(count):
            add_boat_instance(
                name=f'테스트{i:02d}호',
                url=f'https://boat{i:02d}.sunsang24.com/ship/schedule_fleet/202609',
                city='인천', port='남항(인천항)', note='', is_shared=False,
            )


def _fake_check(monkeypatch, side_effect=None):
    """check_single_boat 을 라우트가 import 한 이름 자리에서 갈아끼운다."""
    import routes.views as views

    def fake(boat_url, year, month, day, debug_enabled=False, known_ship_name=None):
        if side_effect:
            side_effect(known_ship_name)
        return {
            'source_url': boat_url,
            'tide': '7물',
            'entries': [{
                'ship_name': known_ship_name, 'status': 'open', 'available': 5,
                'raw_status_text': '남은자리 5명', 'display_status': '남은자리 5명',
                'used_url': boat_url, 'fish': '광어',
            }],
        }

    monkeypatch.setattr(views, 'check_single_boat', fake)


def _post(client, **extra):
    data = {'year': '2026', 'month': '9', 'day': '5'}
    data.update(extra)
    resp = client.post('/api/status', data=data)
    assert resp.status_code == 200
    lines = [json.loads(ln) for ln in resp.get_data(as_text=True).splitlines() if ln.strip()]
    return lines


def test_stream_emits_start_every_boat_and_end(app, client, monkeypatch):
    """71척이 잘림 없이 완주하고, start/본문/end 가 모두 나온다."""
    _seed(app, 71)
    _fake_check(monkeypatch)

    lines = _post(client)

    assert lines[0] == {'type': 'start', 'total': 71}
    end = lines[-1]
    assert end['type'] == 'end', "종료 마커가 없으면 프론트가 잘림을 감지할 수 없다"
    assert end['completed'] == 71
    assert end['missing'] == []
    # start + 71척 + end
    assert len(lines) == 73
    assert len([l for l in lines if l.get('registered_name')]) == 71


def test_boat_failure_is_isolated_and_still_reported(app, client, monkeypatch):
    """배 한 척이 터져도 전체가 멈추지 않고, 그 배도 결과 줄로 나온다 (fail-soft)."""
    _seed(app, 5)

    def blow_up(name):
        if name == '테스트02호':
            raise RuntimeError('boom')

    _fake_check(monkeypatch, side_effect=blow_up)

    lines = _post(client)
    end = lines[-1]

    assert end['type'] == 'end'
    assert end['completed'] == 5, "실패한 배도 결과 줄을 내보내야 한다"
    assert end['missing'] == []

    failed = [l for l in lines if l.get('registered_name') == '테스트02호']
    assert len(failed) == 1
    assert failed[0]['entries'][0]['status'] == 'unknown'
    assert '조회 오류' in failed[0]['entries'][0]['raw_status_text']


def test_boats_filter_allows_partial_requery(app, client, monkeypatch):
    """재조회 버튼이 쓰는 경로: boats 필터로 일부만 조회할 수 있다."""
    _seed(app, 10)
    _fake_check(monkeypatch)

    lines = _post(client, boats=['테스트03호', '테스트07호'])

    assert lines[0]['total'] == 2
    assert lines[-1]['type'] == 'end'
    assert lines[-1]['completed'] == 2
    names = sorted(l['registered_name'] for l in lines if l.get('registered_name'))
    assert names == ['테스트03호', '테스트07호']


def test_max_workers_config_is_respected(app, client, monkeypatch):
    """STATUS_MAX_WORKERS 설정이 실제 풀 크기로 전달된다 (환경변수 롤백 경로)."""
    _seed(app, 8)
    _fake_check(monkeypatch)

    import routes.views as views
    seen = {}
    real_pool = views.ThreadPoolExecutor

    class SpyPool(real_pool):
        def __init__(self, max_workers=None, **kw):
            seen['max_workers'] = max_workers
            super().__init__(max_workers=max_workers, **kw)

    monkeypatch.setattr(views, 'ThreadPoolExecutor', SpyPool)
    app.config['STATUS_MAX_WORKERS'] = 12

    _post(client)

    # 배가 8척뿐이므로 8로 클램프된다
    assert seen['max_workers'] == 8

    seen.clear()
    _seed(app, 40)
    app.config['STATUS_MAX_WORKERS'] = 12
    _post(client)
    assert seen['max_workers'] == 12
