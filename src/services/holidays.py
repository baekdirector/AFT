"""대한민국 공휴일(양력) 계산 - 순수 함수, 외부 API 의존 없음.

korean_lunar_calendar(이미 mulddae.py가 물때 계산에 쓰는 의존성)로 설날/추석/
부처님오신날 같은 음력 기반 공휴일을 양력으로 환산하고, "관공서의 공휴일에
관한 규정"(2023.06.05 개정)의 대체공휴일 규칙을 그대로 적용한다. 연도가
바뀌어도 코드/하드코딩 수정 없이 항상 정확한 날짜를 낸다 - mulddae.py와 같은
원칙(결정론적 계산 > 매년 손으로 채워 넣는 표).

**설날/추석 연휴는 일요일 겹침만 대체공휴일 대상이다(토요일은 제외)** -
어린이날·부처님오신날·성탄절·삼일절·광복절·개천절·한글날(모두 이 규정
제3조 제2항, 2021/2023 개정으로 확대된 쪽)은 토·일요일 모두 겹치면
대체공휴일이 붙지만, 설날/추석 3일 연휴(제3조 제1항, 원래부터 있던 규칙)는
그 연휴가 "일요일"과 겹칠 때만 대상이다(실측: 2026년 추석은 9/24(목)~
9/26(토)로 토요일만 걸쳐서 9/28에 대체공휴일이 없다 - 여러 언론 보도로
확인, 반대로 2025년 추석은 10/5(일)~10/7(화)로 일요일이 껴 있어 10/8에
대체공휴일이 실제로 있었다). 이 둘을 구분 안 하고 요일 겹침을 전부
"주말"로 뭉뚱그리면(과거 실수) 토요일만 걸친 해에 없는 대체공휴일을
만들어낸다.

알려진 한계: 대체공휴일 규정은 위 요일 겹침뿐 아니라 "다른 공휴일과 겹칠
때"도 대상으로 삼는데, 이 함수는 요일 겹침만 구현했다(날짜 자체가 겹치는
경우는 안 봄). 이런 겹침은 드물게 발생한다(예: 2028년 추석과 개천절이 같은
날) - 그런 해엔 이 함수가 대체공휴일을 놓칠 수 있으니 정부 발표를 직접
확인해야 한다. 같은 날짜에 공휴일이 두 개 겹치면 이름은 '·'로 합쳐서
보여준다(위 2028년 사례처럼 놓치지 않고 알아볼 수 있게).
"""
from __future__ import annotations
import datetime
from typing import Dict, List, Optional

from korean_lunar_calendar import KoreanLunarCalendar

# (월, 일, 이름, 대체공휴일 대상 여부) - 신정·현충일은 규정상 대체공휴일이 없다.
_FIXED = [
    (1, 1, '신정', False),
    (3, 1, '삼일절', True),
    (5, 5, '어린이날', True),
    (6, 6, '현충일', False),
    (8, 15, '광복절', True),
    (10, 3, '개천절', True),
    (10, 9, '한글날', True),
    (12, 25, '성탄절', True),
]


def _lunar_to_solar(year: int, month: int, day: int) -> datetime.date:
    cal = KoreanLunarCalendar()
    cal.setLunarDate(year, month, day, False)
    return datetime.date(cal.solarYear, cal.solarMonth, cal.solarDay)


def _is_weekend(d: datetime.date) -> bool:
    return d.weekday() >= 5  # 5=토, 6=일


def _is_sunday(d: datetime.date) -> bool:
    return d.weekday() == 6


def _next_free_day(start: datetime.date, taken: set) -> datetime.date:
    cand = start
    while _is_weekend(cand) or cand in taken:
        cand += datetime.timedelta(days=1)
    return cand


def kr_holidays_for_year(year: int) -> Dict[str, str]:
    """그 해 대한민국 공휴일을 {ISO 날짜: 이름} 으로 돌려준다."""
    entries: Dict[datetime.date, List[str]] = {}

    def add(d: datetime.date, label: str) -> None:
        labels = entries.setdefault(d, [])
        if label not in labels:
            labels.append(label)

    seollal = _lunar_to_solar(year, 1, 1)
    seollal_span = [seollal - datetime.timedelta(days=1), seollal, seollal + datetime.timedelta(days=1)]
    for d, label in zip(seollal_span, ['설날 연휴', '설날', '설날 연휴']):
        add(d, label)

    chuseok = _lunar_to_solar(year, 8, 15)
    chuseok_span = [chuseok - datetime.timedelta(days=1), chuseok, chuseok + datetime.timedelta(days=1)]
    for d, label in zip(chuseok_span, ['추석 연휴', '추석', '추석 연휴']):
        add(d, label)

    buddha = _lunar_to_solar(year, 4, 8)
    add(buddha, '부처님오신날')

    for month, day, label, _eligible in _FIXED:
        add(datetime.date(year, month, day), label)

    taken = set(entries.keys())

    for span, name in ((seollal_span, '설날'), (chuseok_span, '추석')):
        # 설날/추석 연휴는 "일요일"과 겹칠 때만 대체공휴일 대상이다(토요일은
        # 대상이 아님 - 위 모듈 docstring 참고). 대체일 자체를 찾을 때는
        # 당연히 토·일 모두 건너뛴다(_next_free_day 가 _is_weekend 를 씀).
        if any(_is_sunday(d) for d in span):
            sub = _next_free_day(span[-1] + datetime.timedelta(days=1), taken)
            add(sub, f'대체공휴일({name})')
            taken.add(sub)

    if _is_weekend(buddha):
        sub = _next_free_day(buddha + datetime.timedelta(days=1), taken)
        add(sub, '대체공휴일(부처님오신날)')
        taken.add(sub)

    for month, day, label, eligible in _FIXED:
        if not eligible:
            continue
        d = datetime.date(year, month, day)
        if _is_weekend(d):
            sub = _next_free_day(d + datetime.timedelta(days=1), taken)
            add(sub, f'대체공휴일({label})')
            taken.add(sub)

    return {d.isoformat(): '·'.join(labels) for d, labels in sorted(entries.items())}


def kr_holidays_for_years(years) -> Dict[str, str]:
    """여러 해를 한 dict로 합친다 - 달력이 연도 경계를 넘나들 때 통째로 넘기기 위함."""
    merged: Dict[str, str] = {}
    for y in years:
        merged.update(kr_holidays_for_year(y))
    return merged


def kr_holidays_around(today: Optional[datetime.date] = None, before: int = 1, after: int = 4) -> Dict[str, str]:
    """오늘 기준 (today.year - before) ~ (today.year + after) 범위를 묶어서 돌려준다.
    예약현황 달력이 보여줄 법한 근미래 몇 년치를 매 요청마다 새로 계산해 두면
    연도가 바뀌어도 별도 유지보수 없이 항상 최신 범위를 커버한다."""
    year = (today or datetime.date.today()).year
    return kr_holidays_for_years(range(year - before, year + after + 1))
