"""출조 기록 조회·저장 - docs/superpowers/specs/2026-09-30-fishing-log-trips-design.md §3.

라우트(fishing_views)는 이 모듈만 부른다. 선사는 이름의 정규화 키(1단계
excel_seed.ship_match_key)로 맞추고, 없으면 저장할 때 새로 만든다.
"""
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from db import db
from models import TRIP_RATINGS, TRIP_STATUSES, Boat, FishingShip, FishingTrip
from services.fishing_log.excel_seed import ship_match_key

KST = timezone(timedelta(hours=9))

DEFAULT_SPECIES = ['쭈꾸미', '갑오징어', '문어', '우럭', '광어', '농어']
POSITIVE_TAGS = ['신조선배', '배 컨디션 좋음', '줄 잘 잡아줌', '사무장 있음', '밥 맛있음']
NEGATIVE_TAGS = ['선장이 낚시함', '준비물 부족', '너무 멀다', '포인트 이동 적음']

MAX_LIST_ITEMS = 20
MAX_ITEM_LEN = 20
MAX_CATCH_COUNT = 9999
SUGGESTION_LIMIT = 10
SHIP_SEARCH_LIMIT = 10


class TripValidationError(ValueError):
    """입력 검증 실패. field 는 화면이 강조할 입력칸 이름."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def kst_today():
    return datetime.now(KST).date()


# ---- 입력 정리 ----

def _clean_text(data, field, limit, label):
    value = data.get(field)
    if value is None:
        return None
    text = str(value).strip()
    if len(text) > limit:
        raise TripValidationError(field, f'{label}은(는) {limit}자 이하로 입력해 주세요.')
    return text or None


def _clean_date(value):
    text = str(value or '').strip()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        raise TripValidationError('trip_date', '날짜를 YYYY-MM-DD 형식으로 입력해 주세요.')
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise TripValidationError('trip_date', '올바른 날짜가 아닙니다.') from None


def _clean_cost(value):
    if value is None or str(value).strip() == '':
        return None
    if isinstance(value, bool):
        raise TripValidationError('cost', '비용은 숫자로 입력해 주세요.')
    if isinstance(value, int):
        number = value
    else:
        text = str(value).strip().replace(',', '')
        if not re.fullmatch(r'\d+', text):
            raise TripValidationError('cost', '비용은 0 이상의 숫자로 입력해 주세요.')
        number = int(text)
    if number < 0:
        raise TripValidationError('cost', '비용은 0 이상의 숫자로 입력해 주세요.')
    return number


def _clean_list(data, field, label):
    values = data.get(field) or []
    if not isinstance(values, list):
        raise TripValidationError(field, f'{label} 형식이 올바르지 않습니다.')
    cleaned = []
    for value in values:
        text = str(value or '').strip()
        if not text or text in cleaned:
            continue
        if len(text) > MAX_ITEM_LEN:
            raise TripValidationError(field, f'{label}은(는) 항목마다 {MAX_ITEM_LEN}자 이하로 입력해 주세요.')
        cleaned.append(text)
    if len(cleaned) > MAX_LIST_ITEMS:
        raise TripValidationError(field, f'{label}은(는) {MAX_LIST_ITEMS}개까지 입력할 수 있습니다.')
    return cleaned


def _clean_catches(values):
    if not isinstance(values or [], list):
        raise TripValidationError('catches', '조과 형식이 올바르지 않습니다.')
    cleaned = []
    for row in values or []:
        if not isinstance(row, dict):
            raise TripValidationError('catches', '조과 형식이 올바르지 않습니다.')
        who = str(row.get('who') or '').strip()
        species = str(row.get('species') or '').strip()
        count = row.get('count')
        if not who or not species or count is None or str(count).strip() == '':
            continue
        if len(who) > MAX_ITEM_LEN or len(species) > MAX_ITEM_LEN:
            raise TripValidationError('catches', f'조과의 이름·어종은 {MAX_ITEM_LEN}자 이하로 입력해 주세요.')
        try:
            number = int(str(count).strip())
        except ValueError:
            raise TripValidationError('catches', '조과 마릿수는 숫자로 입력해 주세요.') from None
        if not 0 <= number <= MAX_CATCH_COUNT:
            raise TripValidationError('catches', f'조과 마릿수는 0~{MAX_CATCH_COUNT} 사이로 입력해 주세요.')
        cleaned.append({'who': who, 'species': species, 'count': number})
    return cleaned


def _clean(data):
    status = data.get('status')
    if status not in TRIP_STATUSES:
        raise TripValidationError('status', '상태를 골라 주세요.')
    ship_name = _clean_text(data, 'ship_name', 100, '선사명')
    if not ship_name:
        raise TripValidationError('ship_name', '선사명을 입력해 주세요.')
    rating = data.get('rating') or None
    if rating is not None and rating not in TRIP_RATINGS:
        raise TripValidationError('rating', '재이용 의사를 다시 골라 주세요.')
    boat_id = data.get('boat_id') or None
    if boat_id is not None:
        try:
            boat_id = int(boat_id)
        except (TypeError, ValueError):
            raise TripValidationError('boat_id', '배 목록 연결 값이 올바르지 않습니다.') from None
        if db.session.get(Boat, boat_id) is None:
            raise TripValidationError('boat_id', '배 목록에 없는 배입니다.')
    return {
        'trip_date': _clean_date(data.get('trip_date')),
        'status': status,
        'ship_name': ship_name,
        'ship_region': _clean_text(data, 'ship_region', 50, '지역'),
        'ship_port': _clean_text(data, 'ship_port', 100, '항구'),
        'boat_id': boat_id,
        'cost': _clean_cost(data.get('cost')),
        'companions': _clean_text(data, 'companions', 100, '동행'),
        'species': _clean_list(data, 'species', '어종'),
        'tags': _clean_list(data, 'tags', '태그'),
        'catches': _clean_catches(data.get('catches')),
        'rating': rating,
        'memo': _clean_text(data, 'memo', 2000, '메모'),
        'prepaid': bool(data.get('prepaid')),
    }


# ---- 선사 ----

def resolve_ship(name, region=None, port=None, boat_id=None):
    """정규화 이름이 같은 선사가 있으면 그것, 없으면 새로 만든다(커밋은 호출자)."""
    key = ship_match_key(name)
    for ship in FishingShip.query.all():
        if ship_match_key(ship.name) == key:
            return ship
    boat = db.session.get(Boat, boat_id) if boat_id else None
    ship = FishingShip(name=name, region=region or (boat.city if boat else None),
                       port=port or (boat.port if boat else None),
                       boat_id=boat.id if boat else None)
    db.session.add(ship)
    return ship


def search_ships(q, limit=SHIP_SEARCH_LIMIT):
    """자동완성: 기존 선사(출조 많은 순) + 아직 어느 선사와도 연결 안 된 AFT 배."""
    needle = re.sub(r'\s+', '', q or '').lower()

    def hit(name):
        return needle in re.sub(r'\s+', '', name).lower()

    counts = Counter(ship_id for (ship_id,) in db.session.query(FishingTrip.ship_id).all())
    ships = [s for s in FishingShip.query.all() if hit(s.name)]
    ships.sort(key=lambda s: (-counts.get(s.id, 0), s.name))
    results = [{'kind': 'ship', 'id': s.id, 'name': s.name, 'region': s.region, 'port': s.port,
                'trip_count': counts.get(s.id, 0), 'boat_id': s.boat_id} for s in ships[:limit]]
    if len(results) < limit:
        linked = {s.boat_id for s in FishingShip.query.filter(FishingShip.boat_id.isnot(None))}
        boats = [b for b in Boat.query.order_by(Boat.name).all() if b.id not in linked and hit(b.name)]
        results += [{'kind': 'boat', 'boat_id': b.id, 'name': b.name, 'region': b.city, 'port': b.port}
                    for b in boats[:limit - len(results)]]
    return results


# ---- 저장 ----

def _apply(trip, cleaned):
    trip.trip_date = cleaned['trip_date']
    trip.status = cleaned['status']
    trip.ship = resolve_ship(cleaned['ship_name'], cleaned['ship_region'],
                             cleaned['ship_port'], cleaned['boat_id'])
    for field in ('cost', 'companions', 'species', 'tags', 'catches', 'rating', 'memo', 'prepaid'):
        setattr(trip, field, cleaned[field])


def create_trip(data):
    cleaned = _clean(data)
    trip = FishingTrip()
    _apply(trip, cleaned)
    db.session.add(trip)
    db.session.commit()
    return trip


def update_trip(trip, data):
    cleaned = _clean(data)
    _apply(trip, cleaned)
    db.session.commit()
    return trip


def delete_trip(trip):
    db.session.delete(trip)
    db.session.commit()


def get_trip(trip_id):
    return db.session.get(FishingTrip, trip_id)


# ---- 조회 ----

def serialize_trip(trip, today):
    planned = trip.status == 'planned'
    ship = trip.ship
    return {
        'id': trip.id,
        'trip_date': trip.trip_date.isoformat(),
        'status': trip.status,
        'ship': {'id': ship.id, 'name': ship.name, 'region': ship.region,
                 'port': ship.port, 'boat_id': ship.boat_id},
        'cost': trip.cost,
        'companions': trip.companions,
        'rating': trip.rating,
        'species': trip.species or [],
        'tags': trip.tags or [],
        'catches': trip.catches or [],
        'catch_raw': trip.catch_raw,
        'memo': trip.memo,
        'prepaid': bool(trip.prepaid),
        'needs_result': planned and trip.trip_date < today,
        'd_day': (trip.trip_date - today).days if planned and trip.trip_date >= today else None,
    }


def _ranked(values, defaults=()):
    """과거에 많이 쓴 값 상위 10개 뒤에 기본값(아직 없는 것만)을 붙인다."""
    ranked = [v for v, _ in Counter(values).most_common(SUGGESTION_LIMIT)]
    return ranked + [v for v in defaults if v not in ranked]


def list_trips(year, today):
    """year=None 이면 전체. 예정(가까운 날짜 먼저) 뒤에 완료·취소(최근 먼저)."""
    query = FishingTrip.query
    if year is not None:
        query = query.filter(FishingTrip.trip_date >= date(year, 1, 1),
                             FishingTrip.trip_date <= date(year, 12, 31))
    trips = query.all()
    planned = sorted((t for t in trips if t.status == 'planned'), key=lambda t: (t.trip_date, t.id))
    others = sorted((t for t in trips if t.status != 'planned'), key=lambda t: (t.trip_date, t.id), reverse=True)

    all_trips = FishingTrip.query.all()
    years = sorted({t.trip_date.year for t in all_trips} | {today.year}, reverse=True)
    status_counts = Counter(t.status for t in trips)
    return {
        'trips': [serialize_trip(t, today) for t in planned + others],
        'years': years,
        'summary': {
            'planned': status_counts['planned'],
            'done': status_counts['done'],
            'cancelled': status_counts['cancelled'],
            'cost_total': sum(t.cost or 0 for t in trips if t.status != 'cancelled'),
        },
        'suggestions': {
            'companions': _ranked([t.companions for t in all_trips if t.companions]),
            'species': _ranked([s for t in all_trips for s in (t.species or [])], DEFAULT_SPECIES),
            'tags': _ranked([s for t in all_trips for s in (t.tags or [])], POSITIVE_TAGS + NEGATIVE_TAGS),
            # 조과 "누구" 선택지 - 항상 '나'가 먼저, 그다음 예전에 조과를 적은 사람들
            'people': ['나'] + [p for p in _ranked([c.get('who') for t in all_trips for c in (t.catches or [])
                                                     if c.get('who')]) if p != '나'],
        },
        'tag_tones': {'positive': POSITIVE_TAGS, 'negative': NEGATIVE_TAGS},
    }
