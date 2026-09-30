"""선사 노트 서비스 (4단계 spec §2~§4). 값은 전부 지어낸 것."""
from datetime import date

import pytest

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


def _boat(name='가나다호', url='https://example.com/a'):
    from db import db
    from models import Boat
    boat = Boat(name=name, url=url, city='가시', port='가항')
    db.session.add(boat)
    db.session.commit()
    return boat


def _c(who, species, count):
    return {'who': who, 'species': species, 'count': count}


# ---- 요약(목록 한 줄) ----

def test_summary_counts_skip_cancelled_and_past_planned(app):
    from services.fishing_log.ship_service import ship_summary
    ship = _ship()
    _trip(ship, '2026-05-01', rating='again')
    _trip(ship, '2026-05-10', rating='maybe')
    _trip(ship, '2026-05-20', status='cancelled', rating='never')
    _trip(ship, '2026-06-01', status='planned')      # 지난 예정 - 예정 수에서 빠짐
    _trip(ship, '2026-07-03', status='planned')
    _trip(ship, '2026-06-20', status='planned')
    s = ship_summary(ship, TODAY)
    assert (s['done_count'], s['planned_count']) == (2, 2)
    assert s['next_planned'] == '2026-06-20'
    assert s['last_trip'] == '2026-05-10'
    assert s['last_rating'] == 'maybe'
    assert (s['tag'], s['tone']) == ('2회 · 예정', 'memo')


@pytest.mark.parametrize('trips, tag, tone', [
    ([('2026-05-01', 'done', 'again')], '1회', 'good'),
    ([('2026-05-01', 'done', 'again'), ('2026-05-09', 'done', 'never')], '2회', 'bad'),
    ([('2026-05-01', 'done', 'never'), ('2026-05-09', 'done', None)], '2회', 'bad'),
    ([('2026-10-17', 'planned', None)], '예정 10/17', 'plan'),
    ([('2026-05-01', 'cancelled', None)], '기록 없음', 'memo'),
    ([], '기록 없음', 'memo'),
])
def test_summary_tag_and_tone(app, trips, tag, tone):
    from services.fishing_log.ship_service import ship_summary
    ship = _ship()
    for d, st, r in trips:
        _trip(ship, d, status=st, rating=r)
    s = ship_summary(ship, TODAY)
    assert (s['tag'], s['tone']) == (tag, tone)


# ---- 상세 ----

def test_detail_money_catch_trend_ratings_tags(app):
    from services.fishing_log.ship_service import ship_detail
    ship = _ship()
    _trip(ship, '2025-10-02', cost=100000, rating='again', tags=['전투낚시', '너무 멀다'],
          catches=[_c('나', '문어', 34), _c('나', '갑오징어', 3)])
    _trip(ship, '2025-10-05', cost=200000, rating='again', tags=['전투낚시'],
          catches=[_c('나', '문어', 17), _c('마눌', '문어', 10)])
    _trip(ship, '2025-11-01', cost=200000, rating='maybe', catches=[_c('마눌', '문어', 3)])
    _trip(ship, '2025-11-08', status='cancelled', cost=999, catches=[_c('나', '문어', 99)])
    _trip(ship, '2026-10-31', status='planned', cost=200000, prepaid=True)
    _trip(ship, '2026-11-07', status='planned', cost=50000)
    d = ship_detail(ship, TODAY)
    assert d['spent'] == 500000
    assert d['prepaid_planned'] == 200000
    assert d['my_catch'] == [{'species': '문어', 'avg': 17}, {'species': '갑오징어', 'avg': 1}]
    assert d['main_species'] == '문어'
    assert d['trend'] == [{'date': '2025-10-02', 'count': 34}, {'date': '2025-10-05', 'count': 17},
                          {'date': '2025-11-01', 'count': 0},
                          {'date': '2026-10-31', 'planned': True}, {'date': '2026-11-07', 'planned': True}]
    assert d['ratings'] == {'again': 2, 'maybe': 1, 'never': 0}
    assert d['tags'] == ['전투낚시', '너무 멀다']
    assert [v['date'] for v in d['visits']] == ['2026-11-07', '2026-10-31', '2025-11-08', '2025-11-01',
                                                '2025-10-05', '2025-10-02']
    assert d['visits'][2]['status'] == 'cancelled'
    assert d['visits'][4]['catch'] == '나 문어 17 · 마눌 문어 10'


def test_catch_text_rules(app):
    from services.fishing_log.ship_service import catch_text
    assert catch_text([_c('나', '문어', 6), _c('나', '갑오징어', 2)], 'done') == '문어 6, 갑오징어 2'
    assert catch_text([_c('나', '문어', 0)], 'done') == '꽝'
    assert catch_text([_c('나', '문어', 0), _c('마눌', '문어', 3)], 'done') == '나 꽝 · 마눌 문어 3'
    assert catch_text([], 'done') == '조과 없음'
    assert catch_text([], 'planned') is None


def test_avg_rounds_to_one_decimal(app):
    from services.fishing_log.ship_service import ship_detail
    ship = _ship()
    _trip(ship, '2025-10-02', catches=[_c('나', '문어', 10)])
    _trip(ship, '2025-10-03', catches=[_c('나', '문어', 5)])
    _trip(ship, '2025-10-04', catches=[_c('나', '문어', 0)])
    assert ship_detail(ship, TODAY)['my_catch'] == [{'species': '문어', 'avg': 5}]
    _trip(ship, '2025-10-05')
    assert ship_detail(ship, TODAY)['my_catch'] == [{'species': '문어', 'avg': 3.8}]


def test_trend_keeps_last_eight_done(app):
    from services.fishing_log.ship_service import ship_detail
    ship = _ship()
    for day in range(1, 11):
        _trip(ship, f'2025-10-{day:02d}', catches=[_c('나', '문어', day)])
    trend = ship_detail(ship, TODAY)['trend']
    assert [t['count'] for t in trend] == [3, 4, 5, 6, 7, 8, 9, 10]


def test_detail_of_ship_without_trips_and_boat_link(app):
    from services.fishing_log.ship_service import ship_detail
    boat = _boat()
    ship = _ship(memo='멘구추천', boat_id=boat.id)
    d = ship_detail(ship, TODAY)
    assert (d['spent'], d['my_catch'], d['main_species'], d['trend'], d['visits']) == (0, [], None, [], [])
    assert d['boat'] == {'id': boat.id, 'name': '가나다호', 'url': 'https://example.com/a'}
    assert d['memo'] == '멘구추천' and d['tag'] == '기록 없음'


# ---- 목록 ----

def test_list_groups_by_region_and_sorts(app):
    from services.fishing_log.ship_service import list_ship_notes
    a = _ship('A호', region='여수')
    b = _ship('B호', region='여수')
    c = _ship('C호', region='여수')
    d = _ship('D호', region='군산')
    e = _ship('E호')
    for day in ('01', '02'):
        _trip(a, f'2026-05-{day}')
    _trip(b, '2026-05-09')
    _trip(d, '2026-05-01')
    _trip(d, '2026-05-02')
    _trip(d, '2026-05-03')
    _trip(e, '2026-05-01')
    data = list_ship_notes(TODAY)
    assert [(g['region'], [s['name'] for s in g['ships']]) for g in data['groups']] == [
        ('군산', ['D호']), ('여수', ['A호', 'B호', 'C호']), (None, ['E호'])]
    assert data['regions'] == ['여수', '군산']
    assert c.id in [s['id'] for s in data['groups'][1]['ships']]


def test_list_includes_boats_for_link_dropdown(app):
    from services.fishing_log.ship_service import list_ship_notes
    _boat('ㅎ테스트호', 'https://example.com/n')
    _boat('ㄱ테스트호', 'https://example.com/g')
    names = [b['name'] for b in list_ship_notes(TODAY)['boats']]
    assert names == sorted(names)
    assert names.index('ㄱ테스트호') < names.index('ㅎ테스트호')


# ---- 수정 ----

def test_update_ship_saves_fields(app):
    from services.fishing_log.ship_service import update_ship
    boat = _boat()
    ship = _ship()
    result = update_ship(ship.id, {'name': ' 가나다2호 ', 'region': '여수', 'port': '돌산항', 'fleet': '레드',
                                   'travel_time': '50분', 'memo': '메모', 'boat_id': boat.id}, TODAY)
    assert (result['name'], result['region'], result['port'], result['fleet'], result['travel_time'],
            result['memo'], result['boat_id']) == ('가나다2호', '여수', '돌산항', '레드', '50분', '메모', boat.id)
    result = update_ship(ship.id, {'name': '가나다2호', 'region': '', 'boat_id': None}, TODAY)
    assert result['region'] is None and result['boat_id'] is None


@pytest.mark.parametrize('body, field', [
    ({'name': ''}, 'name'),
    ({'name': '가' * 101}, 'name'),
    ({'name': '다른호'}, 'name'),
    ({'name': '가나다호', 'region': '가' * 51}, 'region'),
    ({'name': '가나다호', 'memo': '가' * 2001}, 'memo'),
    ({'name': '가나다호', 'boat_id': 999}, 'boat_id'),
    ({'name': '가나다호', 'boat_id': 'x'}, 'boat_id'),
])
def test_update_ship_validation(app, body, field):
    from services.fishing_log.ship_service import ShipValidationError, update_ship
    ship = _ship()
    _ship('다른호')
    with pytest.raises(ShipValidationError) as exc:
        update_ship(ship.id, body, TODAY)
    assert exc.value.field == field


def test_update_missing_ship(app):
    from services.fishing_log.ship_service import ShipNotFound, update_ship
    with pytest.raises(ShipNotFound):
        update_ship(999, {'name': 'x'}, TODAY)
