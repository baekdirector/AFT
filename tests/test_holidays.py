"""공휴일 계산(src/services/holidays.py) 검증 - 실제로 알려진 날짜와 대조한다."""
from services.holidays import kr_holidays_for_year, kr_holidays_for_years, kr_holidays_around


def test_2026_chuseok_and_substitute_matches_known_dates():
    holidays = kr_holidays_for_year(2026)
    assert holidays['2026-09-24'] == '추석 연휴'
    assert holidays['2026-09-25'] == '추석'
    assert holidays['2026-09-26'] == '추석 연휴'
    assert holidays['2026-10-03'] == '개천절'
    assert holidays['2026-10-05'] == '대체공휴일(개천절)'


def test_fixed_date_holidays_present_every_year():
    for year in (2025, 2027, 2030):
        holidays = kr_holidays_for_year(year)
        assert holidays[f'{year}-01-01'] == '신정'
        assert holidays[f'{year}-06-06'] == '현충일'
        assert holidays[f'{year}-12-25'] == '성탄절'


def test_sinjeong_and_hyeonchung_have_no_substitute():
    # 신정/현충일은 대체공휴일 대상이 아니다 - 토/일요일에 걸려도 생기면 안 된다.
    for year in range(2025, 2031):
        holidays = kr_holidays_for_year(year)
        for d, label in holidays.items():
            assert '대체공휴일(신정)' != label
            assert '대체공휴일(현충일)' != label


def test_lunar_new_year_and_chuseok_are_three_day_spans():
    holidays = kr_holidays_for_year(2025)
    assert holidays['2025-01-28'] == '설날 연휴'
    assert holidays['2025-01-29'] == '설날'
    assert holidays['2025-01-30'] == '설날 연휴'


def test_kr_holidays_for_years_merges_multiple_years():
    merged = kr_holidays_for_years([2025, 2026])
    assert '2025-01-01' in merged
    assert '2026-09-25' in merged


def test_kr_holidays_around_covers_requested_window():
    import datetime
    merged = kr_holidays_around(datetime.date(2026, 9, 10), before=1, after=2)
    assert '2025-01-01' in merged
    assert '2028-01-01' in merged
    assert '2029-01-01' not in merged
