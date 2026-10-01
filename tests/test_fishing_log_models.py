"""낚시 기록 모델 (spec §2)."""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError


def _ship(name='가나다호'):
    from models import FishingShip
    return FishingShip(name=name, region='테스트시', port='테스트항')


def test_trip_json_fields_default_to_empty_lists(app):
    from db import db
    from models import FishingTrip
    ship = _ship()
    trip = FishingTrip(trip_date=date(2026, 1, 3), status='done', ship=ship)
    db.session.add(trip)
    db.session.commit()

    saved = FishingTrip.query.one()
    assert saved.species == []
    assert saved.tags == []
    assert saved.catches == []
    assert saved.rating is None
    assert saved.ship.name == '가나다호'
    assert saved.created_at is not None and saved.updated_at is not None


def test_trip_catches_round_trip_as_json(app):
    from db import db
    from models import FishingTrip
    catches = [{'who': '나', 'species': '쭈꾸미', 'count': 12}]
    db.session.add(FishingTrip(trip_date=date(2026, 1, 3), status='done', ship=_ship(),
                               species=['쭈꾸미'], catches=catches))
    db.session.commit()
    assert FishingTrip.query.one().catches == catches


def test_ship_name_is_unique(app):
    from db import db
    db.session.add(_ship('가나다호'))
    db.session.commit()
    db.session.add(_ship('가나다호'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_ship_with_trips_cannot_be_deleted(app):
    from db import db
    from models import FishingTrip
    ship = _ship()
    db.session.add(FishingTrip(trip_date=date(2026, 1, 3), status='done', ship=ship))
    db.session.commit()

    db.session.delete(ship)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_deleting_gear_item_keeps_purchase_and_clears_link(app):
    from db import db
    from models import GearItem, GearPurchase
    gear = GearItem(name='테스트 릴', kind='릴')
    db.session.add(GearPurchase(purchase_date=date(2026, 2, 1), item='테스트 릴 본체',
                                category='릴', price=1000, gear=gear))
    db.session.commit()

    db.session.delete(gear)
    db.session.commit()

    purchase = GearPurchase.query.one()
    assert purchase.gear_id is None
    assert purchase.category == '릴'


def test_purchase_category_defaults_to_etc(app):
    from db import db
    from models import GearPurchase
    db.session.add(GearPurchase(purchase_date=date(2026, 2, 1), item='테스트 소품'))
    db.session.commit()
    assert GearPurchase.query.one().category == '기타'


def test_allowed_value_constants():
    import models
    assert models.TRIP_STATUSES == ('planned', 'done', 'cancelled')
    assert models.TRIP_RATINGS == ('again', 'maybe', 'never')


def test_prepaid_column_is_added_back_when_missing(app):
    """운영 DB 의 fishing_trips 는 prepaid 컬럼 없이 먼저 만들어졌다 - 앱 기동 시
    없으면 ALTER 로 보정한다(기존 _ensure_* 패턴)."""
    from sqlalchemy import inspect, text
    from db import db
    from src.app import _ensure_fishing_trip_prepaid_column
    with db.engine.begin() as conn:
        conn.execute(text('ALTER TABLE fishing_trips DROP COLUMN prepaid'))
    assert 'prepaid' not in {c['name'] for c in inspect(db.engine).get_columns('fishing_trips')}
    _ensure_fishing_trip_prepaid_column(app)
    _ensure_fishing_trip_prepaid_column(app)  # 두 번 불러도 안전
    assert 'prepaid' in {c['name'] for c in inspect(db.engine).get_columns('fishing_trips')}


def test_gear_status_column_is_added_back_when_missing(app):
    """gear_items.status(사용 중/부러짐/분실)도 운영 테이블이 먼저 있어서 ALTER 로 보정한다."""
    from sqlalchemy import inspect, text
    from db import db
    from models import GearItem
    from src.app import _ensure_gear_item_status_column
    db.session.add(GearItem(name='예전 릴'))
    db.session.commit()
    with db.engine.begin() as conn:
        conn.execute(text('ALTER TABLE gear_items DROP COLUMN status'))
    _ensure_gear_item_status_column(app)
    _ensure_gear_item_status_column(app)  # 두 번 불러도 안전
    with db.engine.begin() as conn:
        assert conn.execute(text('SELECT status FROM gear_items')).scalar() == 'active'
