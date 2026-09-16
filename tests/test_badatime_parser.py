"""
Badatime 파서 테스트
"""
import io
import json
from pathlib import Path

import pytest

GRAPH_FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'badatime'


# --- GraphPageParser: 실제 /{port_id}/graph/{date} 페이지 fixture 기반 -------
# 사용자 요청: iframe으로 바다타임 그래프를 그대로 띄우면 LNB를 못 지우고
# 패널 크기도 못 바꾼다(cross-origin) - 원시 데이터만 파싱해 자체 위젯을
# 그리기로 했다. 손으로 만든 mock이 아니라 실제로 받은 응답
# (tests/fixtures/badatime/)을 그대로 쓴다(CLAUDE.md 규칙 1).

def _load_graph_fixture(name):
    html = io.open(GRAPH_FIXTURE_ROOT / f'{name}.html', encoding='utf-8').read()
    expected = json.loads(io.open(GRAPH_FIXTURE_ROOT / f'{name}.expected.json', encoding='utf-8').read())
    return html, expected


GRAPH_FIXTURES = ['인천_158_graph_20260919', '소호항_826_graph_20260919']


@pytest.mark.parametrize('name', GRAPH_FIXTURES)
def test_graph_page_parser_matches_golden(name):
    """서해(인천)·남해(소호항) 두 지역 실측 fixture가 골든과 일치해야 한다."""
    from services.badatime_parser import GraphPageParser

    html, expected = _load_graph_fixture(name)
    result = GraphPageParser(html).parse()
    assert result == expected


def test_graph_page_parser_hourly_rows_have_icons_and_wind():
    """시간대별 행에 날씨 아이콘·풍향 아이콘이 절대경로로, 풍속/파고가 채워져
    있어야 한다 - 이게 바다타임 iframe을 대체하는 화면의 핵심 데이터다."""
    from services.badatime_parser import GraphPageParser

    html, _ = _load_graph_fixture('인천_158_graph_20260919')
    hourly = GraphPageParser(html).parse_hourly()

    assert len(hourly) >= 8
    for row in hourly:
        assert row['time'].endswith('시')
        assert row['weather_icon_url'].startswith('https://www.badatime.com/')
        assert row['wind_dir_icon_url'].startswith('https://www.badatime.com/')
        assert row['wind_speed']
        assert row['wave_height']


def test_graph_page_parser_tide_events_count_varies_by_day():
    """간조/만조 개수는 그날 조석 주기에 따라 3~4건으로 바뀐다 - 하드코딩하면
    안 된다는 걸 명시적으로 고정한다."""
    from services.badatime_parser import GraphPageParser

    html, _ = _load_graph_fixture('인천_158_graph_20260919')
    events = GraphPageParser(html).parse_tide_events()

    assert len(events) in (3, 4)
    assert all(e['type'] in ('low', 'high') for e in events)
    assert all('\n' in e['label'] for e in events)  # cm·증감 줄바꿈이 살아있는지


def test_graph_page_parser_sun_moon_times():
    from services.badatime_parser import GraphPageParser

    html, _ = _load_graph_fixture('소호항_826_graph_20260919')
    sun_moon = GraphPageParser(html).parse_sun_moon()

    assert sun_moon == {
        'sunrise': '06:15', 'sunset': '18:31',
        'moonrise': '14:04', 'moonset': '23:31',
    }


def test_graph_page_parser_flow_percent_and_tide_label():
    from services.badatime_parser import GraphPageParser

    html, _ = _load_graph_fixture('소호항_826_graph_20260919')
    parser = GraphPageParser(html)

    assert parser.parse_flow_percent() == 3
    assert parser.parse_tide_label() == '1물'


def test_graph_page_parser_survives_missing_script_gracefully():
    """간조/만조·일출몰 정보가 담긴 스크립트가 아예 없어도(사이트 개편 등)
    예외 없이 빈 값으로 돌아와야 한다(실패 격리, CLAUDE.md 4번 원칙)."""
    from services.badatime_parser import GraphPageParser

    result = GraphPageParser('<html><body>내용 없음</body></html>').parse()
    assert result == {
        'hourly': [], 'tide_events': [],
        'sun_moon': {'sunrise': None, 'sunset': None, 'moonrise': None, 'moonset': None},
        'flow_percent': None, 'tide_label': None,
    }


def test_graph_page_parser_tide_events_include_mins_level_delta():
    """카드 행 렌더링·조위 곡선 보간(status.html/weather.html 새 위젯) 양쪽에
    필요한 구조화 필드 - label 문자열 파싱에 의존하지 않고 바로 쓸 수 있어야
    한다."""
    from services.badatime_parser import GraphPageParser

    html, _ = _load_graph_fixture('인천_158_graph_20260919')
    events = GraphPageParser(html).parse_tide_events()

    assert events[0] == {
        'time': '03:12', 'label': '간조 03:12\n(339) ▼-380', 'type': 'low',
        'mins': 192, 'level': 339, 'delta': -380,
    }
    assert events[1]['delta'] == 292  # 만조는 양수(▲+292)


def test_graph_page_parser_hourly_precipitation_empty_when_no_rain():
    """비가 안 오는 날은 badatime 마크업 자체가 비어있다 - 0mm를 지어내지
    않고 빈 문자열로 정직하게 둔다."""
    from services.badatime_parser import GraphPageParser

    html, _ = _load_graph_fixture('인천_158_graph_20260919')
    hourly = GraphPageParser(html).parse_hourly()
    assert all(h['precipitation'] == '' for h in hourly)


def test_graph_page_parser_hourly_precipitation_populated_when_raining():
    from services.badatime_parser import GraphPageParser

    html, _ = _load_graph_fixture('소호항_826_graph_20260919')
    hourly = GraphPageParser(html).parse_hourly()
    rainy = [h for h in hourly if h['precipitation']]
    assert rainy, '이 fixture에는 강수 있는 시간대가 있어야 검증이 성립한다'
    assert rainy[0]['precipitation'] == '2.1 mm'


# --- DailyPageParser: 실제 /{port_id}/daily 페이지 fixture 기반 -----------
# 사용자 제보: "https://www.badatime.com/380/daily 를 보면 이미 한달치
# 정보가 있다" - 실측해보니 오늘부터 30일 롤링 윈도우로 물때/만조/간조/
# 일출몰/월출몰/날씨아이콘이 한 페이지에 다 있었다(그래프 페이지를 30번
# 부를 필요가 없었다).

def _load_daily_fixture():
    html = io.open(GRAPH_FIXTURE_ROOT / '오이도항_380_daily_20260914.html', encoding='utf-8').read()
    expected = json.loads(io.open(GRAPH_FIXTURE_ROOT / '오이도항_380_daily_20260914.expected.json', encoding='utf-8').read())
    return html, expected


def test_daily_page_parser_matches_golden():
    from services.badatime_parser import DailyPageParser

    html, expected = _load_daily_fixture()
    assert DailyPageParser(html).parse() == expected


def test_daily_page_parser_covers_30_day_rolling_window_not_calendar_month():
    """달력 월(1~30/31일)이 아니라 요청 시점 기준 앞으로 30일이다 - 그래서
    응답이 두 개 캘린더 월(9월/10월)에 걸쳐 있다. 날짜 순서가 항상 오름차순
    연속이어야 한다(하루도 안 빠지고, 역순도 없이)."""
    from datetime import date, timedelta
    from services.badatime_parser import DailyPageParser

    html, _ = _load_daily_fixture()
    days = DailyPageParser(html).parse()

    assert len(days) == 30
    dates = [date.fromisoformat(d['date']) for d in days]
    assert dates[0] == date(2026, 9, 14)
    assert dates[-1] == date(2026, 10, 13)
    assert dates == [dates[0] + timedelta(days=i) for i in range(30)]


def test_daily_page_parser_sunday_weekday_not_blank():
    """일요일 셀은 badatime이 <font color="#FF0000">일</font>로 감싸서 괄호와
    글자가 다른 텍스트 노드로 쪼개진다(get_text(' ', strip=True)가 그 사이에
    공백을 넣음) - 정규식이 이 공백을 허용하지 않으면 요일이 빈 문자열로
    사라진다(실측 fixture로 발견한 버그, 2026-09-20 등 4개 일요일 행 전부에서
    재현됨). 요일이 절대 빈 문자열이면 안 된다."""
    from services.badatime_parser import DailyPageParser

    html, _ = _load_daily_fixture()
    days = DailyPageParser(html).parse()

    sundays = [d for d in days if d['date'] in ('2026-09-20', '2026-09-27', '2026-10-04', '2026-10-11')]
    assert len(sundays) == 4
    for d in sundays:
        assert d['weekday'] == '일', d['date']


def test_daily_page_parser_row_has_up_to_two_tide_events_each_kind():
    from services.badatime_parser import DailyPageParser

    html, _ = _load_daily_fixture()
    day = DailyPageParser(html).parse()[0]

    kinds = [e['type'] for e in day['tide_events']]
    assert kinds.count('high') <= 2 and kinds.count('low') <= 2
    assert kinds.count('high') + kinds.count('low') == len(day['tide_events'])
    # 시간순 정렬돼 있어야 카드/곡선에서 바로 쓸 수 있다
    mins = [e['mins'] for e in day['tide_events']]
    assert mins == sorted(mins)


def test_daily_page_parser_survives_missing_rows_gracefully():
    """day-row 자체가 없으면(사이트 개편 등) 예외 없이 빈 리스트를 돌려줘야
    한다(실패 격리)."""
    from services.badatime_parser import DailyPageParser

    assert DailyPageParser('<html><body>내용 없음</body></html>').parse() == []
