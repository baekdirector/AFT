"""출조 기록 서비스 (2단계 spec §3). 값은 전부 지어낸 것."""
from datetime import date

import pytest

TODAY = date(2026, 6, 15)


def _data(**over):
    base = {'trip_date': '2026-05-02', 'status': 'done', 'ship_name': '가나다호',
            'ship_region': '가시', 'ship_port': '가항'}
    base.update(over)
    return base


def _ship(name='가나다호', **kw):
    from db import db
    from models import FishingShip
    ship = FishingShip(name=name, **kw)
    db.session.add(ship)
    db.session.commit()
    return ship


# ---- 검증 ----

@pytest.mark.parametrize('over, field', [
    ({'trip_date': ''}, 'trip_date'),
    ({'trip_date': '2026/05/02'}, 'trip_date'),
    ({'status': 'maybe'}, 'status'),
    ({'ship_name': '   '}, 'ship_name'),
    ({'ship_name': '가' * 101}, 'ship_name'),
    ({'cost': '-1'}, 'cost'),
    ({'cost': '11만원'}, 'cost'),
    ({'rating': 'good'}, 'rating'),
    ({'companions': '가' * 101}, 'companions'),
    ({'species': ['가' * 21]}, 'species'),
    ({'tags': [f'태그{i}' for i in range(21)]}, 'tags'),
    ({'catches': [{'who': '나', 'species': '문어', 'count': 10000}]}, 'catches'),
    ({'catches': [{'who': '나', 'species': '문어', 'count': 'x'}]}, 'catches'),
    ({'memo': '가' * 2001}, 'memo'),
    ({'boat_id': 999}, 'boat_id'),
])
def test_invalid_input_names_the_field(app, over, field):
    from services.fishing_log.trip_service import TripValidationError, create_trip
    with pytest.raises(TripValidationError) as exc:
        create_trip(_data(**over))
    assert exc.value.field == field


def test_create_normalizes_values(app):
    from services.fishing_log.trip_service import create_trip
    trip = create_trip(_data(
        cost='100,000', companions=' 솔로 ', rating='again', memo='  좋음 ',
        species=['쭈꾸미', ' 쭈꾸미', '', '갑오징어'], tags=['신조선배', '신조선배'],
        catches=[{'who': '나', 'species': '쭈꾸미', 'count': '12'},
                 {'who': '', 'species': '문어', 'count': 3},
                 {'who': '마눌', 'species': '문어', 'count': 0}]))
    assert trip.trip_date == date(2026, 5, 2)
    assert trip.cost == 100000
    assert trip.companions == '솔로'
    assert trip.memo == '좋음'
    assert trip.species == ['쭈꾸미', '갑오징어']
    assert trip.tags == ['신조선배']
    assert trip.catches == [{'who': '나', 'species': '쭈꾸미', 'count': 12},
                            {'who': '마눌', 'species': '문어', 'count': 0}]
    assert trip.rating == 'again'


def test_blank_optional_values_become_none(app):
    from services.fishing_log.trip_service import create_trip
    trip = create_trip(_data(cost='', companions='', rating='', memo=''))
    assert (trip.cost, trip.companions, trip.rating, trip.memo) == (None, None, None, None)


# ---- 선사 맞추기 · 생성 ----

def test_existing_ship_matched_ignoring_spaces_and_ho(app):
    from services.fishing_log.trip_service import create_trip
    ship = _ship('가나다호', region='원래시', port='원래항')
    trip = create_trip(_data(ship_name=' 가나 다 ', ship_region='딴시', ship_port='딴항'))
    assert trip.ship_id == ship.id
    assert (ship.region, ship.port) == ('원래시', '원래항')


def test_new_ship_created_with_region_and_port(app):
    from models import FishingShip
    from services.fishing_log.trip_service import create_trip
    trip = create_trip(_data(ship_name='새배호', ship_region='나시', ship_port='나항'))
    assert trip.ship.name == '새배호'
    assert (trip.ship.region, trip.ship.port) == ('나시', '나항')
    assert FishingShip.query.count() == 1


def test_new_ship_from_aft_boat_links_and_fills_location(app):
    from db import db
    from models import Boat
    from services.fishing_log.trip_service import create_trip
    boat = Boat(name='보트호', url='https://example.com/b', city='다시', port='다항')
    db.session.add(boat)
    db.session.commit()
    trip = create_trip(_data(ship_name='보트호', ship_region='', ship_port='', boat_id=boat.id))
    assert trip.ship.boat_id == boat.id
    assert (trip.ship.region, trip.ship.port) == ('다시', '다항')


def test_changing_ship_keeps_previous_ship(app):
    from models import FishingShip
    from services.fishing_log.trip_service import create_trip, update_trip
    trip = create_trip(_data(ship_name='첫배호'))
    update_trip(trip, _data(ship_name='둘째배호'))
    assert trip.ship.name == '둘째배호'
    assert {s.name for s in FishingShip.query.all()} == {'첫배호', '둘째배호'}


def test_update_does_not_touch_catch_raw(app):
    from db import db
    from services.fishing_log.trip_service import create_trip, update_trip
    trip = create_trip(_data())
    trip.catch_raw = '엑셀 원문'
    db.session.commit()
    update_trip(trip, _data(catch_raw='바꾸기 시도', memo='수정'))
    assert trip.catch_raw == '엑셀 원문'
    assert trip.memo == '수정'


def test_delete_trip(app):
    from models import FishingShip, FishingTrip
    from services.fishing_log.trip_service import create_trip, delete_trip
    trip = create_trip(_data())
    delete_trip(trip)
    assert FishingTrip.query.count() == 0
    assert FishingShip.query.count() == 1


# ---- 목록 ----

def _seed_year():
    from services.fishing_log.trip_service import create_trip
    create_trip(_data(trip_date='2026-07-01', status='planned', ship_name='칠월호', cost=100))
    create_trip(_data(trip_date='2026-06-20', status='planned', ship_name='유월호', cost=200))
    create_trip(_data(trip_date='2026-06-01', status='planned', ship_name='지난예정호'))
    create_trip(_data(trip_date='2026-05-02', status='done', ship_name='오월호', cost=300,
                      companions='솔로', species=['문어'], tags=['신조선배']))
    create_trip(_data(trip_date='2026-05-10', status='done', ship_name='오월둘호', companions='솔로'))
    create_trip(_data(trip_date='2026-04-05', status='cancelled', ship_name='취소호', cost=999))
    create_trip(_data(trip_date='2025-10-02', status='done', ship_name='작년호'))


def test_list_year_sorting_and_flags(app):
    from services.fishing_log.trip_service import list_trips
    _seed_year()
    result = list_trips(2026, TODAY)
    by_name = {t['ship']['name']: t for t in result['trips']}
    assert by_name['유월호']['d_day'] == 5
    assert by_name['유월호']['needs_result'] is False
    assert by_name['지난예정호']['needs_result'] is True
    assert by_name['지난예정호']['d_day'] is None
    assert by_name['오월호']['d_day'] is None
    assert '작년호' not in by_name


def test_list_planned_first_ascending_then_rest_descending(app):
    from services.fishing_log.trip_service import list_trips
    _seed_year()
    names = [t['ship']['name'] for t in list_trips(2026, TODAY)['trips']]
    assert names == ['지난예정호', '유월호', '칠월호', '오월둘호', '오월호', '취소호']


def test_list_summary_years_and_suggestions(app):
    from services.fishing_log.trip_service import list_trips
    _seed_year()
    result = list_trips(2026, TODAY)
    assert result['summary'] == {'planned': 3, 'done': 2, 'cancelled': 1, 'cost_total': 600}
    assert result['years'] == [2026, 2025]
    assert result['suggestions']['companions'][0] == '솔로'
    assert result['suggestions']['species'][:1] == ['문어']
    assert '쭈꾸미' in result['suggestions']['species']
    assert result['suggestions']['tags'][0] == '신조선배'


def test_list_all_years(app):
    from services.fishing_log.trip_service import list_trips
    _seed_year()
    assert len(list_trips(None, TODAY)['trips']) == 7


def test_list_years_include_current_year_when_empty(app):
    from services.fishing_log.trip_service import list_trips
    assert list_trips(2026, TODAY)['years'] == [2026]


# ---- 선사 자동완성 ----

def test_search_ships_combines_ships_and_unlinked_boats(app):
    from db import db
    from models import Boat
    from services.fishing_log.trip_service import create_trip, search_ships
    linked = Boat(name='연결된보트', url='https://example.com/l', city='가시', port='가항')
    free = Boat(name='가나 보트', url='https://example.com/f', city='나시', port='나항')
    db.session.add_all([linked, free])
    db.session.commit()
    create_trip(_data(ship_name='가나다호'))
    create_trip(_data(ship_name='가나다호'))
    create_trip(_data(ship_name='연결된보트', boat_id=linked.id))

    results = search_ships('가나')
    assert results[0] == {'kind': 'ship', 'id': results[0]['id'], 'name': '가나다호',
                          'region': '가시', 'port': '가항', 'trip_count': 2, 'boat_id': None}
    assert {'kind': 'boat', 'boat_id': free.id, 'name': '가나 보트',
            'region': '나시', 'port': '나항'} in results
    assert all(r['name'] != '연결된보트' or r['kind'] == 'ship' for r in search_ships('연결'))


def test_search_ships_limit_and_empty_query(app):
    from services.fishing_log.trip_service import create_trip, search_ships
    for i in range(12):
        create_trip(_data(ship_name=f'배{i:02d}호'))
    create_trip(_data(ship_name='배00호'))
    results = search_ships('')
    assert len(results) == 10
    assert results[0]['name'] == '배00호'
