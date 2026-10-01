"""선사 노트(선사별 통계) - docs/superpowers/specs/2026-10-01-fishing-log-ships-design.md §2~§4.

새 테이블 없이 FishingTrip 을 선사별로 모아 계산한다. 계산은 today 를 인자로 받아
테스트에서 날짜를 고정할 수 있게 했다.
"""
from collections import Counter

from db import db
from models import Boat, FishingShip, FishingTrip
from services.fishing_log.excel_seed import ship_match_key

ME = '나'
TREND_DONE_LIMIT = 8
TAG_LIMIT = 12
MY_CATCH_LIMIT = 2

# 입력칸 이름 → (최대 길이, 화면 라벨)
_TEXT_FIELDS = {
    'region': (50, '지역'),
    'port': (100, '항구'),
    'fleet': (100, '선단'),
    'travel_time': (50, '이동 시간'),
    'memo': (2000, '메모'),
}


class ShipValidationError(ValueError):
    """입력 검증 실패. field 는 화면이 강조할 입력칸 이름."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


class ShipNotFound(LookupError):
    pass


# ---- 계산 도우미 ----

def _split(trips, today):
    done = sorted((t for t in trips if t.status == 'done'), key=lambda t: (t.trip_date, t.id))
    planned = sorted((t for t in trips if t.status == 'planned' and t.trip_date >= today),
                     key=lambda t: (t.trip_date, t.id))
    return done, planned


def _last_rating(done):
    for trip in reversed(done):
        if trip.rating:
            return trip.rating
    return None


def _tag(done, planned):
    if done:
        return f'{len(done)}회' + (' · 예정' if planned else '')
    if planned:
        d = planned[0].trip_date
        return f'예정 {d.month}/{d.day}'
    return '기록 없음'


def _tone(done, planned, last_rating):
    if last_rating == 'again':
        return 'good'
    if last_rating == 'never':
        return 'bad'
    if not done and planned:
        return 'plan'
    return 'memo'


def _number(value):
    value = round(value, 1)
    return int(value) if value == int(value) else value


def catch_text(catches, status):
    """탄 기록 한 줄의 조과 요약. '나'만 있으면 이름을 생략하고, 마릿수가 전부 0인 사람은 꽝."""
    if not catches:
        return '조과 없음' if status == 'done' else None
    groups = {}
    for c in catches:
        groups.setdefault(c.get('who'), []).append(c)
    show_who = len(groups) > 1 or ME not in groups
    parts = []
    for who, items in groups.items():
        caught = [c for c in items if (c.get('count') or 0) > 0]
        body = ', '.join(f"{c['species']} {c['count']}" for c in caught) if caught else '꽝'
        parts.append(f'{who} {body}' if show_who else body)
    return ' · '.join(parts)


def _trips_of(ship):
    return FishingTrip.query.filter_by(ship_id=ship.id).all()


# ---- 요약 · 상세 ----

def _season(done):
    """탄 달을 '9~11월', '4·10~11월'처럼 묶는다. 연도는 무시(어느 철에 가는 배인지)."""
    months = sorted({t.trip_date.month for t in done})
    if not months:
        return None
    runs, start, prev = [], months[0], months[0]
    for m in months[1:] + [None]:
        if m is not None and m == prev + 1:
            prev = m
            continue
        runs.append(str(start) if start == prev else f'{start}~{prev}')
        if m is not None:
            start = prev = m
    return '·'.join(runs) + '월'


def best_catch(done, with_ship=False):
    """'나'의 한 번 출조 조과 합계가 가장 컸던 날(동률이면 최근). 그날 상위 2개 어종.

    done 은 날짜 오름차순이어야 한다(동률 시 뒤의 것 = 최근이 이긴다). 개요 대시보드도 쓴다.
    """
    best = None
    for trip in done:
        mine = Counter()
        for c in trip.catches or []:
            if c.get('who') == ME and c.get('species') and (c.get('count') or 0) > 0:
                mine[c['species']] += c['count']
        total = sum(mine.values())
        if total and (best is None or total >= best[0]):
            best = (total, trip, mine)
    if best is None:
        return None
    label = ' · '.join(f'{sp} {n}' for sp, n in best[2].most_common(MY_CATCH_LIMIT))
    result = {'label': label, 'date': best[1].trip_date.isoformat()}
    if with_ship:
        result['ship'] = best[1].ship.name
    return result


def ship_summary(ship, today, trips=None):
    trips = _trips_of(ship) if trips is None else trips
    done, planned = _split(trips, today)
    last_rating = _last_rating(done)
    return {
        'id': ship.id, 'name': ship.name, 'region': ship.region, 'port': ship.port, 'fleet': ship.fleet,
        'travel_time': ship.travel_time, 'memo': ship.memo, 'boat_id': ship.boat_id,
        'done_count': len(done), 'planned_count': len(planned),
        'next_planned': planned[0].trip_date.isoformat() if planned else None,
        'last_trip': done[-1].trip_date.isoformat() if done else None,
        'last_rating': last_rating,
        'tag': _tag(done, planned), 'tone': _tone(done, planned, last_rating),
        'spent': sum(t.cost or 0 for t in done),
        'season': _season(done),
        'best_catch': best_catch(done),
    }


def ship_detail(ship, today):
    trips = _trips_of(ship)
    done, planned = _split(trips, today)
    result = ship_summary(ship, today, trips)

    totals = Counter()
    for trip in done:
        for c in trip.catches or []:
            if c.get('who') == ME and c.get('species'):
                totals[c['species']] += c.get('count') or 0
    ranked = [(sp, n) for sp, n in totals.most_common() if n > 0][:MY_CATCH_LIMIT]
    main = ranked[0][0] if ranked else None

    def my_count(trip):
        return sum(c.get('count') or 0 for c in trip.catches or [] if c.get('who') == ME and c.get('species') == main)

    trend = []
    if main:
        trend = [{'date': t.trip_date.isoformat(), 'count': my_count(t)} for t in done[-TREND_DONE_LIMIT:]]
        trend += [{'date': t.trip_date.isoformat(), 'planned': True} for t in planned]

    ratings = Counter(t.rating for t in done if t.rating)
    tags = Counter(tag for t in done + planned for tag in t.tags or [])
    boat = db.session.get(Boat, ship.boat_id) if ship.boat_id else None
    visits = sorted(trips, key=lambda t: (t.trip_date, t.id), reverse=True)

    result.update({
        'prepaid_planned': sum(t.cost or 0 for t in planned if t.prepaid),
        'my_catch': [{'species': sp, 'avg': _number(n / len(done))} for sp, n in ranked],
        'main_species': main,
        'trend': trend,
        'ratings': {r: ratings.get(r, 0) for r in ('again', 'maybe', 'never')},
        'tags': [t for t, _ in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))][:TAG_LIMIT],
        'visits': [{
            'id': t.id, 'date': t.trip_date.isoformat(), 'status': t.status,
            'companions': t.companions, 'cost': t.cost, 'prepaid': bool(t.prepaid), 'rating': t.rating,
            'catch': catch_text(t.catches or [], t.status), 'memo': t.memo or t.catch_raw,
        } for t in visits],
        'boat': {'id': boat.id, 'name': boat.name, 'url': boat.url} if boat else None,
    })
    return result


# ---- 목록 ----

def list_ship_notes(today, year=None):
    """다녀온 배 중심(4단계 spec §3, 사용자 결정으로 수정). year=None 이면 전체 기간.

    - ships: 그 기간에 완료 출조가 1회 이상인 배, 이용 횟수 순(동률은 최근 출조, 이름)
    - planned: 완료 기록 없이 다가오는 예정만 있는 배(가까운 날짜 순)
    - 출조 기록이 전혀 없는 선사는 보여주지 않는다(데이터는 그대로 둔다).
    """
    trips = FishingTrip.query.all()
    years = sorted({t.trip_date.year for t in trips if t.status != 'cancelled'} | {today.year}, reverse=True)
    if year is not None:
        trips = [t for t in trips if t.trip_date.year == year]
    by_ship = {}
    for trip in trips:
        by_ship.setdefault(trip.ship_id, []).append(trip)
    ships = FishingShip.query.filter(FishingShip.id.in_(list(by_ship))).all() if by_ship else []
    summaries = [ship_summary(s, today, by_ship[s.id]) for s in ships]

    visited = sorted((s for s in summaries if s['done_count']),
                     key=lambda s: (-s['done_count'], _desc(s['last_trip']), s['name']))
    planned = sorted((s for s in summaries if not s['done_count'] and s['planned_count']),
                     key=lambda s: (s['next_planned'], s['name']))

    done_trips = [t for t in trips if t.status == 'done']
    costed = [t.cost for t in done_trips if t.cost is not None]
    top = visited[0] if visited else None
    all_ships = FishingShip.query.all()
    return {
        'ships': visited,
        'planned': planned,
        'summary': {
            'ship_count': len(visited),
            'trip_count': len(done_trips),
            'spent': sum(costed),
            'avg_cost': round(sum(costed) / len(costed)) if costed else None,
            'top_ship': {'id': top['id'], 'name': top['name'], 'done_count': top['done_count'],
                         'region': top['region'], 'port': top['port']} if top else None,
        },
        'years': years,
        'regions': [r for r, _ in Counter(s.region for s in all_ships if s.region).most_common()],
        'boats': [{'id': b.id, 'name': b.name, 'port': b.port} for b in Boat.query.order_by(Boat.name).all()],
    }


def _desc(text):
    """문자열 내림차순 정렬용 키."""
    return tuple(-ord(ch) for ch in text)


# ---- 수정 ----

def get_ship(ship_id):
    return db.session.get(FishingShip, ship_id)


def _clean(ship, data):
    name = str(data.get('name') or '').strip()
    if not name:
        raise ShipValidationError('name', '선사명을 입력해 주세요.')
    if len(name) > 100:
        raise ShipValidationError('name', '선사명은 100자 이하로 입력해 주세요.')
    key = ship_match_key(name)
    if any(other.id != ship.id and ship_match_key(other.name) == key for other in FishingShip.query.all()):
        raise ShipValidationError('name', '같은 이름의 선사가 이미 있습니다.')
    cleaned = {'name': name}
    for field, (limit, label) in _TEXT_FIELDS.items():
        text = str(data.get(field) or '').strip()
        if len(text) > limit:
            raise ShipValidationError(field, f'{label}은(는) {limit}자 이하로 입력해 주세요.')
        cleaned[field] = text or None
    boat_id = data.get('boat_id') or None
    if boat_id is not None:
        try:
            boat_id = int(boat_id)
        except (TypeError, ValueError):
            raise ShipValidationError('boat_id', 'AFT 배 연결 값이 올바르지 않습니다.') from None
        if db.session.get(Boat, boat_id) is None:
            raise ShipValidationError('boat_id', 'AFT 배 목록에 없는 배입니다.')
    cleaned['boat_id'] = boat_id
    return cleaned


def update_ship(ship_id, data, today):
    ship = get_ship(ship_id)
    if ship is None:
        raise ShipNotFound(ship_id)
    for field, value in _clean(ship, data).items():
        setattr(ship, field, value)
    db.session.commit()
    return ship_detail(ship, today)
