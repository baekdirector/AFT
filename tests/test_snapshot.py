"""
스냅샷 변화 감지 규칙 테스트 (Phase B).

네트워크도 DB 도 타지 않는다. 순수 함수만 검증한다.
여기서 고정하는 규칙이 곧 알림 품질이다. 느슨하면 가짜 알림이 쏟아지고,
빡빡하면 정작 자리가 났을 때 조용하다.
"""
import pytest

from services.snapshot import (
    SEAT_GONE,
    SEAT_OPEN,
    STATUS_CHANGE,
    Observation,
    compare,
    diff,
    entries_to_observations,
)


def obs(status, available=None, ship='레드헌터', date='2026-09-05', boat_id=1, **kw):
    return Observation(boat_id=boat_id, target_date=date, ship_name=ship,
                       status=status, available=available, **kw)


# --- 알려야 하는 전환 ------------------------------------------------------

def test_full_to_open_is_seat_open():
    """만석이던 배에 자리가 났다. 이 서비스가 존재하는 이유다."""
    t = compare(obs('full', 0), obs('open', 3))
    assert t is not None
    assert t.kind == SEAT_OPEN
    assert (t.previous_available, t.current_available) == (0, 3)


@pytest.mark.parametrize('before', ['full', 'reserved', 'maintenance', 'cancelled'])
def test_any_closed_state_to_open_is_seat_open(before):
    t = compare(obs(before), obs('open', 2))
    assert t is not None and t.kind == SEAT_OPEN


def test_zero_remaining_to_positive_is_seat_open_even_if_status_stays_open():
    """상태 표기는 open 그대로인데 잔여석이 0에서 2로 늘었다.

    자리 숫자가 상태 문구보다 신뢰도가 높다(PLAN.md 4).
    """
    t = compare(obs('open', 0), obs('open', 2))
    assert t is not None and t.kind == SEAT_OPEN


def test_open_to_full_is_seat_gone():
    t = compare(obs('open', 3), obs('full', 0))
    assert t is not None and t.kind == SEAT_GONE


def test_maintenance_to_cancelled_is_status_change():
    """둘 다 자리는 없지만 사유가 바뀌었다. 알릴 값어치는 있다."""
    t = compare(obs('maintenance'), obs('cancelled'))
    assert t is not None and t.kind == STATUS_CHANGE


# --- 알리면 안 되는 것 -----------------------------------------------------

def test_no_change_produces_nothing():
    assert compare(obs('full', 0), obs('full', 0)) is None


def test_seat_count_wiggle_is_not_notified():
    """6명 남았다가 5명 남은 것은 알리지 않는다. 알림 홍수의 주범이다."""
    assert compare(obs('open', 6), obs('open', 5)) is None
    assert compare(obs('open', 5), obs('open', 6)) is None


def test_first_observation_never_notifies():
    """이전 기록이 없는 첫 관측으로 알리면, 감시를 걸자마자
    이미 열려 있던 자리까지 전부 알림이 나간다."""
    assert compare(None, obs('open', 5)) is None


def test_transition_into_unknown_is_ignored():
    """조회/파싱이 실패하면 unknown 이 된다. 이걸 '자리가 사라졌다'로
    알리면 사이트가 잠깐 흔들릴 때마다 가짜 알림이 나간다."""
    assert compare(obs('open', 5), obs('unknown')) is None


def test_transition_out_of_unknown_is_ignored():
    """직전 수집이 실패했었다면, 그 실패를 기준으로 '자리가 났다'고 알리지 않는다."""
    assert compare(obs('unknown'), obs('open', 5)) is None


def test_open_with_zero_seats_is_not_treated_as_open():
    """'남은자리 0명'은 open 표기여도 자리가 없는 것이다."""
    assert compare(obs('full'), obs('open', 0)) is None


# --- 묶음 비교 -------------------------------------------------------------

def test_diff_only_reports_changed_ships():
    before = [obs('full', 0, ship='1호'), obs('open', 2, ship='2호'), obs('full', 0, ship='3호')]
    after = [obs('open', 4, ship='1호'), obs('open', 2, ship='2호'), obs('full', 0, ship='3호')]

    result = diff(before, after)

    assert len(result) == 1
    assert result[0].ship_name == '1호' and result[0].kind == SEAT_OPEN


def test_diff_is_deterministic():
    """같은 입력은 항상 같은 순서로 나와야 한다 (PLAN.md 3b.4)."""
    before = [obs('full', 0, ship=f'{i}호') for i in range(5)]
    after = [obs('open', 1, ship=f'{i}호') for i in range(5)]

    first = diff(before, after)
    second = diff(list(reversed(before)), list(reversed(after)))

    assert [t.ship_name for t in first] == [t.ship_name for t in second]
    assert [t.ship_name for t in first] == sorted(t.ship_name for t in first)


def test_diff_handles_newly_appearing_ship():
    """전에 없던 선박이 목록에 나타나도 첫 관측이므로 알리지 않는다."""
    assert diff([obs('full', 0, ship='1호')],
                [obs('full', 0, ship='1호'), obs('open', 3, ship='새로운호')]) == []


def test_diff_separates_by_date_and_boat():
    """같은 선박명이라도 날짜나 배가 다르면 다른 대상이다."""
    before = [obs('full', 0, date='2026-09-05'), obs('full', 0, date='2026-09-06')]
    after = [obs('open', 1, date='2026-09-05'), obs('full', 0, date='2026-09-06')]

    result = diff(before, after)
    assert len(result) == 1 and result[0].target_date == '2026-09-05'


# --- 중복 방지 키 ----------------------------------------------------------

def test_dedup_key_is_stable_for_same_transition():
    a = compare(obs('full', 0), obs('open', 3))
    b = compare(obs('full', 0), obs('open', 5))
    assert a.dedup_key == b.dedup_key, '잔여석 수가 달라도 같은 전환이면 한 번만 알린다'


def test_dedup_key_differs_after_revert_and_reopen():
    """열림 -> 닫힘 -> 다시 열림 은 다시 알려야 한다 (PLAN.md 6)."""
    opened = compare(obs('full', 0), obs('open', 3))
    gone = compare(obs('open', 3), obs('full', 0))
    assert opened.dedup_key != gone.dedup_key


# --- 기존 파서 출력과의 접합 -----------------------------------------------

def test_entries_to_observations_maps_existing_parser_output():
    """check_single_boat() 이 내놓는 entries 모양을 그대로 받아들인다."""
    entries = [{
        'ship_name': '레드헌터(22인승)', 'status': 'open', 'available': 6,
        'display_status': '남은자리 6명', 'raw_status_text': '남은자리 6명 예약/14명',
        'fish': '문어', 'source_url': 'https://example.com/x',
    }]

    result = entries_to_observations(7, '2026-09-05', entries)

    assert len(result) == 1
    o = result[0]
    assert o.key == (7, '2026-09-05', '레드헌터(22인승)')
    assert o.status == 'open' and o.available == 6 and o.has_seat


def test_entries_to_observations_skips_nameless_entries():
    assert entries_to_observations(1, '2026-09-05', [{'ship_name': '', 'status': 'open'}]) == []


def test_entries_to_observations_tolerates_string_and_missing_available():
    result = entries_to_observations(1, '2026-09-05', [
        {'ship_name': 'A', 'status': 'open', 'available': '4'},
        {'ship_name': 'B', 'status': 'open', 'available': '알수없음'},
        {'ship_name': 'C', 'status': 'full'},
    ])
    assert [o.available for o in result] == [4, None, None]
    # available 이 없으면 status 로 판단한다
    assert [o.has_seat for o in result] == [True, True, False]
