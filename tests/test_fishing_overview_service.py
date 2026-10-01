"""개요 대시보드 서비스 (5단계 spec §2). 값은 전부 지어낸 것."""
from datetime import date

TODAY = date(2026, 6, 15)


def _ship(name='가나다호', **kw):
    from db import db
    from models import FishingShip
    ship = FishingShip(name=name, **kw)
    db.session.add(ship)
    db.session.commit()
    return ship


def _trip(ship, d, status='done', **kw):
    from db import db
    from models import FishingTrip
    trip = FishingTrip(ship=ship, trip_date=date.fromisoformat(d), status=status,
                       species=kw.pop('species', []), tags=kw.pop('tags', []),
                       catches=kw.pop('catches', []), **kw)
    db.session.add(trip)
    db.session.commit()
    return trip


def _gear(d, price, category='기타', shop='가나낚시', item='품목'):
    from db import db
    from models import GearPurchase
    db.session.add(GearPurchase(purchase_date=date.fromisoformat(d), shop=shop, item=item, category=category, price=price))
    db.session.commit()


def _c(who, species, count):
    return {'who': who, 'species': species, 'count': count}


# ---- 지금 챙길 것 ----

def test_todo_upcoming_needs_result_unpaid(app):
    from services.fishing_log.overview_service import build_overview
    s = _ship(region='여수')
    _trip(s, '2026-06-01', status='planned')                 # 지난 예정 - 결과 입력 필요
    _trip(s, '2026-05-20', status='planned')
    _trip(s, '2026-06-15', status='planned', cost=100000, prepaid=True)
    _trip(s, '2026-07-01', status='planned', cost=200000)
    _trip(s, '2026-08-01', status='planned')                 # 선비 미입력 - 합계 0으로
    _trip(s, '2026-09-01', status='planned', cost=50000)
    _trip(s, '2026-06-20', status='cancelled')
    todo = build_overview(2026, TODAY)['todo']
    assert [(u['date'], u['d_day']) for u in todo['upcoming']] == [('2026-06-15', 0), ('2026-07-01', 16), ('2026-08-01', 47)]
    assert todo['upcoming'][0]['ship'] == '가나다호' and todo['upcoming'][0]['prepaid'] is True
    assert todo['upcoming_total'] == 4
    assert todo['needs_result'] == {'count': 2, 'oldest': '2026-05-20'}
    assert todo['unpaid'] == {'count': 3, 'amount': 250000}


def test_todo_is_independent_of_year(app):
    from services.fishing_log.overview_service import build_overview
    _trip(_ship(), '2026-07-01', status='planned')
    assert build_overview(2024, TODAY)['todo']['upcoming_total'] == 1


# ---- 연간 결산 ----

def test_spending_counts_and_highlights(app):
    from services.fishing_log.overview_service import build_overview
    a = _ship('A호', region='여수', port='돌산항')
    b = _ship('B호', region='군산')
    _trip(a, '2026-03-02', cost=100000, rating='again', species=['문어', '갑오징어'],
          catches=[_c('나', '문어', 30), _c('나', '갑오징어', 2)])
    _trip(a, '2026-04-02', cost=100000, species=['문어'], catches=[_c('나', '문어', 5)])
    _trip(b, '2026-05-02', cost=None, species=['쭈꾸미'], catches=[_c('나', '쭈꾸미', 20), _c('마눌', '쭈꾸미', 90)])
    _trip(b, '2026-05-09', status='cancelled', cost=999)
    _trip(b, '2026-07-01', status='planned', cost=888, prepaid=True)
    _trip(b, '2025-10-01', cost=777)
    _gear('2026-03-05', 30000, '에기', shop='가나')
    _gear('2026-03-05', 10000, '에기', shop='가나')
    _gear('2026-03-06', 60000, '릴', shop='다라')
    _gear('2025-12-01', 5000)
    o = build_overview(2026, TODAY)
    assert (o['trip_spent'], o['gear_spent'], o['total']) == (200000, 100000, 300000)
    assert o['trips'] == {'done': 3, 'cancelled': 1}
    assert o['gear'] == {'items': 3, 'orders': 2}
    assert o['top_ship'] == {'id': a.id, 'name': 'A호', 'count': 2, 'region': '여수', 'port': '돌산항'}
    assert o['best_catch'] == {'label': '문어 30 · 갑오징어 2', 'date': '2026-03-02', 'ship': 'A호'}
    assert o['species'] == [{'name': '문어', 'count': 2}, {'name': '갑오징어', 'count': 1}, {'name': '쭈꾸미', 'count': 1}]
    assert o['categories'] == [{'name': '릴', 'amount': 60000, 'pct': 60}, {'name': '에기', 'amount': 40000, 'pct': 40}]
    assert [(s['name'], s['count'], s['best'], s['last_rating']) for s in o['ships']] == [
        ('A호', 2, '문어 30 · 갑오징어 2', 'again'), ('B호', 1, '쭈꾸미 20', None)]
    assert o['years'] == [2026, 2025]
    march = o['flow'][2]
    assert march == {'key': 3, 'trip': 100000, 'gear': 100000, 'trips': 1}
    assert len(o['flow']) == 12


def test_flow_note_needs_half_of_spending(app):
    from services.fishing_log.overview_service import build_overview
    s = _ship()
    _trip(s, '2026-09-05', cost=300000)
    _trip(s, '2026-10-05', cost=300000)
    _trip(s, '2026-11-05', cost=150000)
    _gear('2026-02-01', 250000)
    note = build_overview(2026, TODAY)['flow_note']
    assert note == '9~11월에 출조 3회 · 지출의 75%가 몰렸어요'
    _gear('2026-05-01', 600000)            # 9~11월이 50% 미만으로(75만/160만)
    assert build_overview(2026, TODAY)['flow_note'] is None
    assert build_overview(2024, TODAY)['flow_note'] is None


def test_all_period_flow_by_year(app):
    from services.fishing_log.overview_service import build_overview
    s = _ship()
    _trip(s, '2024-05-01', cost=100000)
    _trip(s, '2025-05-01', cost=300000)
    _gear('2025-06-01', 50000)
    o = build_overview(None, TODAY)
    assert [f['key'] for f in o['flow']] == [2024, 2025, 2026]
    assert o['flow'][1] == {'key': 2025, 'trip': 300000, 'gear': 50000, 'trips': 1}
    assert o['flow_note'] == '2025년에 가장 많이 썼어요 (350,000원)'
    assert o['total'] == 450000


def test_empty_year(app):
    from services.fishing_log.overview_service import build_overview
    o = build_overview(2026, TODAY)
    assert (o['total'], o['top_ship'], o['best_catch'], o['species'], o['categories'], o['ships']) == (0, None, None, [], [], [])
    assert o['todo'] == {'upcoming': [], 'upcoming_total': 0, 'needs_result': {'count': 0, 'oldest': None},
                         'unpaid': {'count': 0, 'amount': 0}}
    assert o['years'] == [2026]
