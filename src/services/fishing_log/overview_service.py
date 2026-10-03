"""개요 대시보드 - docs/superpowers/specs/2026-10-01-fishing-log-overview-design.md §2.

"지금 챙길 것"(오늘 기준)과 "연간 결산"(연도 또는 전체 기간)을 한 번에 계산한다.
새 테이블 없이 FishingTrip·GearPurchase 를 모은다. today 는 테스트 고정용 인자.
"""
from collections import Counter

from models import FishingTrip, GearPurchase
from services.fishing_log.ship_service import best_catch

UPCOMING_LIMIT = 3
SPECIES_LIMIT = 6
CATEGORY_LIMIT = 4
SHIP_LIMIT = 5
NOTE_MIN_SHARE = 0.5


def _todo(trips, today):
    planned = sorted((t for t in trips if t.status == 'planned'), key=lambda t: (t.trip_date, t.id))
    future = [t for t in planned if t.trip_date >= today]
    past = [t for t in planned if t.trip_date < today]
    unpaid = [t for t in future if not t.prepaid]
    return {
        'upcoming': [{
            'id': t.id, 'date': t.trip_date.isoformat(), 'd_day': (t.trip_date - today).days,
            'ship': t.ship.name, 'region': t.ship.region, 'port': t.ship.port, 'cost': t.cost, 'prepaid': bool(t.prepaid),
            'companions': t.companions,
        } for t in future[:UPCOMING_LIMIT]],
        'upcoming_total': len(future),
        'needs_result': {'count': len(past), 'oldest': past[0].trip_date.isoformat() if past else None},
        'unpaid': {'count': len(unpaid), 'amount': sum(t.cost or 0 for t in unpaid)},
    }


def _in(year, d):
    return year is None or d.year == year


def _won(n):
    return f'{n:,}'


def _flow(year, done, gear, years):
    if year is None:
        keys = sorted(years)
        key_of = (lambda d: d.year)
    else:
        keys = list(range(1, 13))
        key_of = (lambda d: d.month)
    rows = {k: {'key': k, 'trip': 0, 'gear': 0, 'trips': 0} for k in keys}
    for t in done:
        row = rows.setdefault(key_of(t.trip_date), {'key': key_of(t.trip_date), 'trip': 0, 'gear': 0, 'trips': 0})
        row['trip'] += t.cost or 0
        row['trips'] += 1
    for g in gear:
        row = rows.setdefault(key_of(g.purchase_date), {'key': key_of(g.purchase_date), 'trip': 0, 'gear': 0, 'trips': 0})
        row['gear'] += g.price or 0
    return [rows[k] for k in sorted(rows)]


def _flow_note(year, flow):
    total = sum(r['trip'] + r['gear'] for r in flow)
    if not total:
        return None
    if year is None:
        top = max(flow, key=lambda r: (r['trip'] + r['gear'], r['key']))
        return f"{top['key']}년에 가장 많이 썼어요 ({_won(top['trip'] + top['gear'])}원)"
    best = None
    for start in range(0, 10):
        window = flow[start:start + 3]
        spent = sum(r['trip'] + r['gear'] for r in window)
        if best is None or spent > best[0]:
            best = (spent, window)
    spent, window = best
    if spent / total < NOTE_MIN_SHARE:
        return None
    trips = sum(r['trips'] for r in window)
    return f"{window[0]['key']}~{window[-1]['key']}월에 출조 {trips}회 · 지출의 {round(spent / total * 100)}%가 몰렸어요"


def _ship_rank(done):
    by_ship = {}
    for t in done:
        by_ship.setdefault(t.ship_id, []).append(t)
    ranked = sorted(by_ship.values(), key=lambda ts: (-len(ts), -ts[-1].trip_date.toordinal(), ts[0].ship.name))
    result = []
    for ts in ranked:
        ship = ts[0].ship
        rated = [t.rating for t in ts if t.rating]
        best = best_catch(ts)
        result.append({'id': ship.id, 'name': ship.name, 'count': len(ts), 'region': ship.region, 'port': ship.port,
                       'best': best['label'] if best else None, 'last_rating': rated[-1] if rated else None})
    return result


def build_overview(year, today):
    """year=None 이면 전체 기간."""
    trips = FishingTrip.query.all()
    gear_all = GearPurchase.query.all()
    years = sorted({t.trip_date.year for t in trips if t.status != 'cancelled'}
                   | {g.purchase_date.year for g in gear_all} | {today.year}, reverse=True)

    scoped = [t for t in trips if _in(year, t.trip_date)]
    done = sorted((t for t in scoped if t.status == 'done'), key=lambda t: (t.trip_date, t.id))
    gear = [g for g in gear_all if _in(year, g.purchase_date)]
    trip_spent = sum(t.cost or 0 for t in done)
    gear_spent = sum(g.price or 0 for g in gear)

    flow = _flow(year, done, gear, years)
    ships = _ship_rank(done)
    species = Counter(sp for t in done for sp in (t.species or []))
    cats = Counter()
    for g in gear:
        cats[g.category or '기타'] += g.price or 0
    top = ships[0] if ships else None

    return {
        'year': year,
        'todo': _todo(trips, today),
        'total': trip_spent + gear_spent,
        'trip_spent': trip_spent,
        'gear_spent': gear_spent,
        'trips': {'done': len(done), 'cancelled': sum(1 for t in scoped if t.status == 'cancelled')},
        'gear': {'items': len(gear), 'orders': len({(g.purchase_date, g.shop) for g in gear})},
        'top_ship': {k: top[k] for k in ('id', 'name', 'count', 'region', 'port')} if top else None,
        'best_catch': best_catch(done, with_ship=True),
        'flow': flow,
        'flow_note': _flow_note(year, flow),
        'species': [{'name': n, 'count': c} for n, c in sorted(species.items(), key=lambda kv: (-kv[1], kv[0]))][:SPECIES_LIMIT],
        'categories': [{'name': n, 'amount': a, 'pct': round(a / gear_spent * 100) if gear_spent else 0}
                       for n, a in sorted(cats.items(), key=lambda kv: (-kv[1], kv[0])) if a > 0][:CATEGORY_LIMIT],
        'ships': ships[:SHIP_LIMIT],
        'years': years,
    }
