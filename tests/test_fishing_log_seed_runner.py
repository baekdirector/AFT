"""이관 DB 쓰기 · 미리보기 보고서 (spec §3.1, §4)."""
from datetime import date

import pytest

from services.fishing_log.excel_seed import (
    GearItemSeed, PurchaseSeed, SeedIssue, SeedResult, ShipSeed, TripSeed,
)


def _result():
    return SeedResult(
        ships=[ShipSeed(name='가나다호', region='가시', port='가항', travel_time='50분', memo='메모'),
               ShipSeed(name='라마호')],
        trips=[TripSeed(trip_date=date(2026, 5, 2), status='done', ship_name='가나다호', cost=90000,
                        companions='솔로', species=['쭈꾸미'],
                        catches=[{'who': '나', 'species': '쭈꾸미', 'count': 10}],
                        catch_raw='쭈 10', memo=None, source_text='가나다호'),
               TripSeed(trip_date=date(2026, 7, 1), status='planned', ship_name='라마호', cost=None,
                        companions=None, species=[], catches=[], catch_raw=None, memo=None,
                        source_text='라마호 오전배')],
        purchases=[PurchaseSeed(purchase_date=date(2026, 3, 1), shop='Temu', item='테스트 에기',
                                category='에기', price=12000)],
        gear_items=[GearItemSeed(name='테스트 릴', memo='우핸들')],
        warnings=[SeedIssue('2026', 7, '조과 문장에 인식 못 한 숫자가 있음 - 원문만 보관', '나(12)')],
        skipped=[SeedIssue('2026', 9, '합계 또는 금액만 있는 줄', '12000')],
    )


def test_commit_inserts_all_rows(app):
    from models import FishingShip, FishingTrip, GearItem, GearPurchase
    from services.fishing_log.seed_runner import commit_seed

    counts = commit_seed(_result())

    assert counts == {'ships': 2, 'trips': 2, 'purchases': 1, 'gear_items': 1}
    trip = FishingTrip.query.filter_by(status='done').one()
    assert trip.ship.name == '가나다호'
    assert trip.catches == [{'who': '나', 'species': '쭈꾸미', 'count': 10}]
    assert trip.rating is None
    ship = FishingShip.query.filter_by(name='가나다호').one()
    assert (ship.region, ship.port, ship.travel_time) == ('가시', '가항', '50분')
    assert GearPurchase.query.one().shop == 'Temu'
    assert GearItem.query.one().name == '테스트 릴'


def test_commit_refuses_when_any_table_has_rows(app):
    from db import db
    from models import GearItem
    from services.fishing_log.seed_runner import SeedRefused, commit_seed, tables_are_empty

    db.session.add(GearItem(name='이미 있음'))
    db.session.commit()

    assert tables_are_empty() is False
    with pytest.raises(SeedRefused):
        commit_seed(_result())
    assert GearItem.query.count() == 1


def test_commit_rolls_back_on_error(app, monkeypatch):
    from models import FishingShip
    from services.fishing_log import seed_runner

    def boom(*args, **kwargs):
        raise RuntimeError('중간 실패')
    monkeypatch.setattr(seed_runner, '_add_purchases', boom)

    with pytest.raises(RuntimeError):
        seed_runner.commit_seed(_result())
    assert FishingShip.query.count() == 0
    assert seed_runner.tables_are_empty() is True


def test_boat_link_only_when_name_unique(app):
    from db import db
    from models import Boat, FishingShip
    from services.fishing_log.seed_runner import commit_seed

    db.session.add(Boat(name='가나다호', url='https://example.com/a', city='가시', port='가항'))
    db.session.add(Boat(name='라마호', url='https://example.com/b', city='나시', port='나항'))
    db.session.add(Boat(name='라마호', url='https://example.com/c', city='다시', port='다항'))
    db.session.commit()

    commit_seed(_result())

    linked = FishingShip.query.filter_by(name='가나다호').one()
    assert linked.boat is not None and linked.boat.url == 'https://example.com/a'
    assert FishingShip.query.filter_by(name='라마호').one().boat_id is None


def test_report_lists_counts_ship_mapping_warnings_and_skips():
    from services.fishing_log.seed_runner import format_report

    report = format_report(_result())

    assert '선사 2' in report
    assert '출조 2 (완료 1 · 예정 1 · 취소 0)' in report
    assert '장비 구매 1' in report
    assert '장비 노트 1' in report
    assert '라마호 오전배 → 라마호' in report
    assert '[2026 7행] 조과 문장에 인식 못 한 숫자가 있음' in report
    assert '[2026 9행] 합계 또는 금액만 있는 줄' in report
