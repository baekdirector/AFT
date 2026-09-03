"""
캐시 읽기 API 테스트 (Phase F2).

/api/status/cached 는 라이브 스크래핑을 하지 않는다. 저장된 스냅샷만 읽는다.
화면을 열자마자 채워 넣을 값이라 빠르고 조용해야 한다.
"""
import json

import pytest

from db import add_boat_instance, db
from models import Boat
from services.snapshot import Observation
from services.snapshot_repository import apply_observations

DATE = '2026-10-03'


@pytest.fixture
def seeded(app):
    with app.app_context():
        Boat.query.delete()
        db.session.commit()
        incheon = add_boat_instance(name='인천배', url='https://a.example/x',
                                    city='인천', port='남항(인천항)', note='', is_shared=False)
        yeosu = add_boat_instance(name='여수배', url='https://b.example/x',
                                  city='여수', port='국동항', note='', is_shared=False)
        add_boat_instance(name='조회안된배', url='https://c.example/x',
                          city='인천', port='남항(인천항)', note='', is_shared=False)

        apply_observations(incheon.id, DATE, [
            Observation(boat_id=incheon.id, target_date=DATE, ship_name='1호',
                        status='open', available=3, display_status='남은자리 3명',
                        fish='광어', source_url='https://a.example/x'),
            Observation(boat_id=incheon.id, target_date=DATE, ship_name='2호',
                        status='full', available=0, display_status='예약마감'),
        ])
        apply_observations(yeosu.id, DATE, [
            Observation(boat_id=yeosu.id, target_date=DATE, ship_name='3호',
                        status='full', available=0, display_status='예약마감'),
        ])
        yield {'incheon': incheon.id, 'yeosu': yeosu.id}


def get(client, **params):
    resp = client.get('/api/status/cached', query_string=params)
    return resp, resp.get_json()


def test_returns_cached_rows(client, seeded):
    resp, body = get(client, date=DATE)

    assert resp.status_code == 200
    assert body['date'] == DATE
    assert len(body['rows']) == 3
    assert body['boat_count'] == 2, '스냅샷이 있는 배만 센다'
    assert body['total_boats'] == 3, '등록된 배 전체 수도 알려준다'


def test_rows_carry_everything_the_table_needs(client, seeded):
    _, body = get(client, date=DATE)
    row = next(r for r in body['rows'] if r['ship_name'] == '1호')

    assert row['registered_name'] == '인천배'
    assert row['city'] == '인천' and row['port'] == '남항(인천항)'
    assert row['status'] == 'open' and row['available'] == 3
    assert row['display_status'] == '남은자리 3명'
    assert row['fish'] == '광어'
    assert row['source_url'] == 'https://a.example/x'
    assert row['checked_at'], '언제 확인된 값인지 반드시 알려준다'


def test_freshness_is_reported(client, seeded):
    """신선도를 숨기면 사용자가 낡은 값을 최신으로 착각한다."""
    _, body = get(client, date=DATE)
    assert body['checked_at'] is not None


def test_unknown_date_returns_empty_not_error(client, seeded):
    resp, body = get(client, date='2030-01-01')

    assert resp.status_code == 200
    assert body['rows'] == [] and body['checked_at'] is None


def test_missing_date_is_rejected(client, seeded):
    resp, _ = get(client)
    assert resp.status_code == 400


def test_bad_date_format_is_rejected(client, seeded):
    resp, _ = get(client, date='2026/10/03')
    assert resp.status_code == 400


# --- 필터 ------------------------------------------------------------------

def test_region_filter(client, seeded):
    _, body = get(client, date=DATE, regions='인천')

    assert {r['city'] for r in body['rows']} == {'인천'}
    assert len(body['rows']) == 2


def test_all_regions_is_not_a_filter(client, seeded):
    _, body = get(client, date=DATE, regions='전체')
    assert len(body['rows']) == 3


def test_boat_filter(client, seeded):
    _, body = get(client, date=DATE, boats='여수배')

    assert len(body['rows']) == 1
    assert body['rows'][0]['ship_name'] == '3호'


# --- 견고성 ----------------------------------------------------------------

def test_snapshot_of_deleted_boat_is_skipped(app, client, seeded):
    """배를 지웠는데 스냅샷이 남아도 화면이 깨지면 안 된다."""
    with app.app_context():
        from models import Snapshot
        # 존재하지 않는 배의 스냅샷을 직접 심는다
        db.session.add(Snapshot(boat_id=99999, target_date=DATE,
                                ship_name='유령호', status='open'))
        db.session.commit()

    resp, body = get(client, date=DATE)

    assert resp.status_code == 200
    assert not any(r['ship_name'] == '유령호' for r in body['rows'])


def test_does_not_scrape(client, seeded, monkeypatch):
    """이 경로는 절대 네트워크를 타면 안 된다. 그게 존재 이유다."""
    import routes.views as views

    def explode(*a, **kw):
        raise AssertionError('캐시 조회가 스크래핑을 했다')

    monkeypatch.setattr(views, 'check_single_boat', explode)
    resp, _ = get(client, date=DATE)
    assert resp.status_code == 200
