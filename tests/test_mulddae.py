"""
물때(N물) 계산 테스트.

여기 골든 값은 추정이 아니라 바다타임 실제 페이지를 raw HTML로 직접 긁어
확보한 것이다(인천 158번/여수 국동항 271번, 2026-09 조회) - 하네스 우선
원칙(PLAN.md §4b.2: "매핑은 알려진 값으로 검증한 lookup table로 확정한다").
2026-08-27 값은 PLAN.md에 이미 기록돼 있던 실측치와 교차검증한 것이다.
"""
from datetime import date

import pytest

from services.tide.mulddae import get_mulddae


@pytest.mark.parametrize('solar, city, expected', [
    # 서해(인천) - 바다타임 158번 raw HTML 직접 확인
    (date(2026, 9, 5), '인천', '무시'),
    (date(2026, 9, 6), '인천', '1물'),
    (date(2026, 9, 10), '인천', '5물'),
    (date(2026, 9, 11), '인천', '7물'),   # 음력 7월이 29일까지라 6물이 스킵됨
    (date(2026, 9, 12), '인천', '8물'),
    (date(2026, 9, 17), '인천', '13물'),
    (date(2026, 9, 18), '인천', '조금'),
    (date(2026, 9, 19), '인천', '무시'),
    # 남해(여수) - 바다타임 271번(국동항) raw HTML 직접 확인
    (date(2026, 9, 5), '여수', '1물'),
    (date(2026, 9, 10), '여수', '6물'),
    (date(2026, 9, 11), '여수', '8물'),   # 남해는 '무시' 없이 바로 8물(7물 스킵)
    (date(2026, 9, 17), '여수', '14물'),
    (date(2026, 9, 18), '여수', '조금'),
    (date(2026, 9, 19), '여수', '1물'),
    # PLAN.md §4b.2에 이미 기록돼 있던 실측치와 교차검증
    (date(2026, 8, 27), '인천', '6물'),
    (date(2026, 8, 27), '여수', '7물'),
])
def test_get_mulddae_matches_verified_reference(solar, city, expected):
    assert get_mulddae(solar, city) == expected


def test_west_and_south_share_the_same_jogeum_day():
    """조금은 물리적으로 같은 저조기라 라벨 규칙만 다를 뿐 같은 날이어야 한다."""
    assert get_mulddae(date(2026, 9, 18), '인천') == '조금'
    assert get_mulddae(date(2026, 9, 18), '여수') == '조금'


def test_unregistered_city_returns_none_not_a_guess():
    assert get_mulddae(date(2026, 9, 5), '서울') is None


def test_other_west_and_south_cities_use_the_right_table():
    """지역 분류가 인천/여수 두 도시만이 아니라 CITY_PORT_MAPPING 12개 전부에 적용되는지."""
    assert get_mulddae(date(2026, 9, 5), '태안') == get_mulddae(date(2026, 9, 5), '인천')
    assert get_mulddae(date(2026, 9, 5), '고흥') == get_mulddae(date(2026, 9, 5), '여수')
