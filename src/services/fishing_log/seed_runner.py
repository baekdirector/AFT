"""엑셀 이관 결과(SeedResult)를 DB에 넣고, 넣기 전 미리보기 보고서를 만든다.

새 테이블 4개가 모두 비어 있을 때만 한 트랜잭션으로 넣는다 - 이관은 한 번뿐이라
다시 실행해도 중복되지 않게 막고, 중간에 실패하면 전부 롤백해 빈 상태로 되돌린다.
"""
from collections import Counter

from db import db
from models import Boat, FishingShip, FishingTrip, GearItem, GearPurchase

FISHING_MODELS = (FishingShip, FishingTrip, GearItem, GearPurchase)


class SeedRefused(Exception):
    """이미 낚시 기록 데이터가 있어 이관을 거부함."""


def tables_are_empty():
    return all(model.query.count() == 0 for model in FISHING_MODELS)


def _unique_boat_ids():
    """이름이 하나뿐인 Boat 만 자동 연결 대상. 같은 이름의 배가 여러 지역에
    등록된 경우(실제로 있음)는 어느 쪽인지 알 수 없으므로 연결하지 않는다."""
    boats = Boat.query.all()
    counts = Counter(b.name for b in boats)
    return {b.name: b.id for b in boats if counts[b.name] == 1}


def _add_ships(result):
    boat_ids = _unique_boat_ids()
    ships = {}
    for seed in result.ships:
        ship = FishingShip(name=seed.name, region=seed.region, port=seed.port,
                           travel_time=seed.travel_time, memo=seed.memo,
                           boat_id=boat_ids.get(seed.name))
        db.session.add(ship)
        ships[seed.name] = ship
    return ships


def _add_trips(result, ships):
    for seed in result.trips:
        db.session.add(FishingTrip(
            trip_date=seed.trip_date, status=seed.status, ship=ships[seed.ship_name],
            cost=seed.cost, companions=seed.companions, species=seed.species,
            tags=[], catches=seed.catches, catch_raw=seed.catch_raw, memo=seed.memo))


def _add_gear_items(result):
    for seed in result.gear_items:
        db.session.add(GearItem(name=seed.name, memo=seed.memo))


def _add_purchases(result):
    for seed in result.purchases:
        db.session.add(GearPurchase(
            purchase_date=seed.purchase_date, shop=seed.shop, item=seed.item,
            category=seed.category, price=seed.price))


def commit_seed(result):
    if not tables_are_empty():
        raise SeedRefused('낚시 기록 테이블에 이미 데이터가 있어 이관하지 않습니다.')
    try:
        ships = _add_ships(result)
        _add_trips(result, ships)
        _add_gear_items(result)
        _add_purchases(result)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {'ships': len(result.ships), 'trips': len(result.trips),
            'purchases': len(result.purchases), 'gear_items': len(result.gear_items)}


def format_report(result):
    status = Counter(t.status for t in result.trips)
    lines = [
        '=== 낚시 기록 이관 미리보기 ===',
        f'선사 {len(result.ships)}',
        f"출조 {len(result.trips)} (완료 {status['done']} · 예정 {status['planned']} · 취소 {status['cancelled']})",
        f'장비 구매 {len(result.purchases)}',
        f'장비 노트 {len(result.gear_items)}',
        '',
        '--- 출조 원문 → 선사명 (틀린 줄은 --ship-map 으로 보정) ---',
    ]
    for trip in result.trips:
        catches = ', '.join(f"{c['who']} {c['species']} {c['count']}" for c in trip.catches) or '-'
        lines.append(f'{trip.trip_date} [{trip.status}] {trip.source_text} → {trip.ship_name} | 조과: {catches}')
    lines += ['', f'--- 경고 {len(result.warnings)} ---']
    lines += [f'[{w.sheet} {w.row}행] {w.reason}: {w.text}' for w in result.warnings]
    lines += ['', f'--- 제외 {len(result.skipped)} ---']
    lines += [f'[{s.sheet} {s.row}행] {s.reason}: {s.text}' for s in result.skipped]
    return '\n'.join(lines)
