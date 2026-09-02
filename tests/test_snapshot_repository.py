"""
Snapshot 저장소 계층 테스트 (Phase B).

DB 는 타지만 네트워크는 타지 않는다.
"""
import pytest

from db import add_boat_instance, db
from models import Snapshot
from services.snapshot import SEAT_OPEN, Observation
from services.snapshot_repository import (
    apply_observations,
    load_for_dates,
    load_observations,
)

DATE = '2026-09-05'


@pytest.fixture
def boat(app):
    with app.app_context():
        b = add_boat_instance(name='레드헌터', url='https://redhunter.example/x',
                              city='인천', port='남항(인천항)', note='', is_shared=False)
        yield b.id


def o(status, available=None, ship='레드헌터(22인승)', boat_id=None, **kw):
    return Observation(boat_id=boat_id, target_date=DATE, ship_name=ship,
                       status=status, available=available, **kw)


def test_first_apply_stores_rows_and_reports_no_transition(app, boat):
    with app.app_context():
        transitions = apply_observations(boat, DATE, [o('full', 0, boat_id=boat)])

        assert transitions == [], '첫 관측은 비교 대상이 없으므로 알리지 않는다'
        rows = Snapshot.query.all()
        assert len(rows) == 1
        assert (rows[0].status, rows[0].available) == ('full', 0)


def test_second_apply_detects_seat_open_and_overwrites_row(app, boat):
    with app.app_context():
        apply_observations(boat, DATE, [o('full', 0, boat_id=boat)])

        transitions = apply_observations(boat, DATE, [o('open', 4, boat_id=boat)])

        assert len(transitions) == 1
        assert transitions[0].kind == SEAT_OPEN
        rows = Snapshot.query.all()
        assert len(rows) == 1, '이력이 아니라 최신 상태 1행만 유지한다'
        assert (rows[0].status, rows[0].available) == ('open', 4)


def test_unknown_does_not_overwrite_known_state(app, boat):
    """수집이 한 번 실패했다고 마지막으로 알던 상태를 지우면 안 된다."""
    with app.app_context():
        apply_observations(boat, DATE, [o('open', 4, boat_id=boat)])
        before = Snapshot.query.one().checked_at

        transitions = apply_observations(boat, DATE, [o('unknown', boat_id=boat)])

        row = Snapshot.query.one()
        assert transitions == []
        assert (row.status, row.available) == ('open', 4), '멀쩡한 기록이 살아있어야 한다'
        assert row.checked_at >= before, '확인 시각은 갱신한다'


def test_recovery_after_failed_collection_compares_against_last_known(app, boat):
    """실패 -> 복구 시, 실패 이전의 실제 상태와 비교돼 전환이 잡힌다."""
    with app.app_context():
        apply_observations(boat, DATE, [o('full', 0, boat_id=boat)])
        apply_observations(boat, DATE, [o('unknown', boat_id=boat)])   # 수집 실패

        transitions = apply_observations(boat, DATE, [o('open', 3, boat_id=boat)])

        assert len(transitions) == 1 and transitions[0].kind == SEAT_OPEN


def test_multiple_ships_from_one_boat_are_separate_rows(app, boat):
    """선단 페이지 한 장에 여러 척이 실린다. 배 하나에 행 하나가 아니다."""
    with app.app_context():
        apply_observations(boat, DATE, [
            o('full', 0, ship='1호', boat_id=boat),
            o('full', 0, ship='2호', boat_id=boat),
            o('full', 0, ship='3호', boat_id=boat),
        ])
        transitions = apply_observations(boat, DATE, [
            o('full', 0, ship='1호', boat_id=boat),
            o('open', 2, ship='2호', boat_id=boat),
            o('full', 0, ship='3호', boat_id=boat),
        ])

        assert Snapshot.query.count() == 3
        assert [t.ship_name for t in transitions] == ['2호']


def test_dates_are_kept_separate(app, boat):
    with app.app_context():
        apply_observations(boat, DATE, [o('full', 0, boat_id=boat)])
        apply_observations(boat, '2026-09-06', [
            Observation(boat_id=boat, target_date='2026-09-06',
                        ship_name='레드헌터(22인승)', status='open', available=5)])

        assert Snapshot.query.count() == 2
        assert len(load_observations(boat, DATE)) == 1
        assert len(load_for_dates([DATE, '2026-09-06'])) == 2


def test_load_for_dates_is_ordered_and_handles_empty(app, boat):
    with app.app_context():
        assert load_for_dates([]) == []
        apply_observations(boat, DATE, [
            o('open', 1, ship='나호', boat_id=boat),
            o('open', 1, ship='가호', boat_id=boat),
        ])
        rows = load_for_dates([DATE])
        assert [r.ship_name for r in rows] == ['가호', '나호']


def test_deleting_boat_removes_its_snapshots(app, boat):
    """배를 지우면 스냅샷도 따라 지워진다 (고아 행 방지)."""
    with app.app_context():
        from models import Boat
        apply_observations(boat, DATE, [o('open', 1, boat_id=boat)])
        assert Snapshot.query.count() == 1

        db.session.delete(Boat.query.get(boat))
        db.session.commit()

        assert Snapshot.query.count() == 0
