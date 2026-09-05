"""
음력 날짜 기반 물때(N물) 계산. KHOA 바다낚시지수 API와 무관한 순수 함수다.

왜 API 대신 계산인가: KHOA 바다낚시지수(`khoa_fishing.py`)는 '소조기'/'대조기'
같은 큰 단위만 주고 "6물" 같은 구체 번호는 안 준다. 게다가 오늘부터 +5일만
예보해서, 예약현황에서 조회하는(보통 몇 주 뒤) 날짜 대부분엔 아예 데이터가
없다. 물때는 음력 날짜만 알면 정해지는 결정론적 값이라 API 없이도 어떤
날짜든 계산할 수 있다.

아래 두 표는 추정/기억 공식이 아니라 바다타임 실제 페이지를 raw HTML로 직접
긁어 확보한 값이다(2026-09 조회, 인천 158번/여수 국동항 271번 - 하네스 우선
원칙: PLAN.md §4b.2 "매핑은 알려진 값으로 검증한 lookup table로 확정한다").
지역마다 세는 관례가 다르다:
  - 서해: '조금' 다음날은 하루 쉬고('무시') 그 다음날부터 1물을 센다.
  - 남해: '무시' 없이 '조금' 바로 다음날부터 1물을 센다(그래서 14물까지 감).
둘 다 '조금'은 음력 8일/23일로 같다 - 물리적으로 같은 저조기라 라벨 규칙만
다르다. 이 표는 PLAN.md에 이미 기록돼 있던 실측치("2026-08-27 → 서해 6물/
남해 7물")와도 정확히 일치함을 확인했다(tests/test_mulddae.py).
"""
from __future__ import annotations

from datetime import date

from korean_lunar_calendar import KoreanLunarCalendar

# 음력 일(1~15) -> 물때 라벨. 16~30일은 1~15일과 동일하게 반복된다.
_WEST_TABLE = {
    1: '7물', 2: '8물', 3: '9물', 4: '10물', 5: '11물', 6: '12물', 7: '13물',
    8: '조금', 9: '무시', 10: '1물', 11: '2물', 12: '3물', 13: '4물', 14: '5물',
    15: '6물',
}
_SOUTH_TABLE = {
    1: '8물', 2: '9물', 3: '10물', 4: '11물', 5: '12물', 6: '13물', 7: '14물',
    8: '조금', 9: '1물', 10: '2물', 11: '3물', 12: '4물', 13: '5물', 14: '6물',
    15: '7물',
}

# CITY_PORT_MAPPING의 12개 도시를 서해/남해로 나눈다.
_WEST_CITIES = {
    '인천', '안산', '화성', '평택', '당진', '서산', '태안', '보령', '군산', '격포',
}
_SOUTH_CITIES = {'여수', '고흥'}


def get_mulddae(solar_date: date, city: str) -> str | None:
    """양력 날짜 + 지역(도시명)으로 물때 라벨을 계산한다.

    등록되지 않은 지역이면 조용히 None을 돌려준다 - 배 등록은 항상 이
    12개 도시 중 하나라 실무에서는 일어나지 않지만, 거짓 정보를 지어내는
    것보다는 안전하다.
    """
    if city in _WEST_CITIES:
        table = _WEST_TABLE
    elif city in _SOUTH_CITIES:
        table = _SOUTH_TABLE
    else:
        return None

    calendar = KoreanLunarCalendar()
    calendar.setSolarDate(solar_date.year, solar_date.month, solar_date.day)
    lunar_day = calendar.lunarDay

    position = ((lunar_day - 1) % 15) + 1
    return table[position]
