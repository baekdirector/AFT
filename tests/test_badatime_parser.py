"""
Badatime 파서 테스트
"""
import io
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

GRAPH_FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'badatime'


def create_mock_tide_table_html():
    """목 HTML 테이블 생성"""
    html = """
    <table class="week_table">
        <tbody>
            <tr>
                <td>날짜</td>
                <td>00시</td>
                <td>03시</td>
                <td>06시</td>
            </tr>
            <tr>
                <td>아이콘</td>
                <td><img src="/icon1.png"/></td>
                <td><img src="/icon2.png"/></td>
                <td><img src="/icon3.png"/></td>
            </tr>
            <tr>
                <td>날씨</td>
                <td>맑음</td>
                <td>구름많음</td>
                <td>흐림</td>
            </tr>
            <tr>
                <td>기온</td>
                <td>15℃</td>
                <td>18℃</td>
                <td>12℃</td>
            </tr>
            <tr>
                <td>풍향</td>
                <td><img src="/wind1.png"/>북</td>
                <td><img src="/wind2.png"/>남</td>
                <td><img src="/wind3.png"/>동</td>
            </tr>
            <tr>
                <td>풍속</td>
                <td>3m/s</td>
                <td>5m/s</td>
                <td>2m/s</td>
            </tr>
            <tr>
                <td>파고</td>
                <td>0.5m</td>
                <td>1.0m</td>
                <td>0.8m</td>
            </tr>
            <tr>
                <td>습도</td>
                <td>60%</td>
                <td>70%</td>
                <td>65%</td>
            </tr>
            <tr>
                <td>강수</td>
                <td>0mm</td>
                <td>0mm</td>
                <td>1mm</td>
            </tr>
        </tbody>
    </table>
    """
    return html


def test_tide_table_parser_extract_times():
    """시간 추출 테스트"""
    from services.badatime_parser import TideTableParser
    
    html = create_mock_tide_table_html()
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    
    parser = TideTableParser(table)
    times = parser.extract_times()
    
    assert len(times) == 3
    assert '00시' in times
    assert '03시' in times
    assert '06시' in times


def test_tide_table_parser_extract_weather_data():
    """날씨 데이터 추출 테스트"""
    from services.badatime_parser import TideTableParser
    
    html = create_mock_tide_table_html()
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    
    parser = TideTableParser(table)
    weather_data = parser.extract_weather_data()
    
    assert 'weather' in weather_data
    assert 'temp' in weather_data
    assert 'wind_dir' in weather_data
    assert 'wind_speed' in weather_data
    assert 'wave_height' in weather_data
    
    assert len(weather_data['weather']) == 3
    assert weather_data['temp'][0] == '15℃'


@pytest.mark.xfail(
    reason="목 HTML 이 '아이콘' 행과 '날씨' 행을 분리해두었지만 실제 badatime 구조가 "
           "그런지 확인되지 않았다. 파서와 목 중 어느 쪽이 틀렸는지는 실제 응답 fixture "
           "(tests/fixtures/badatime/) 확보 후 Phase E 에서 판정한다. "
           "하네스 규칙상 fixture 없이 파싱 코드를 고치지 않는다.",
    strict=True,
)
def test_tide_table_parser_extract_weather_icons():
    """날씨 아이콘 추출 테스트"""
    from services.badatime_parser import TideTableParser
    
    html = create_mock_tide_table_html()
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    
    parser = TideTableParser(table)
    icons = parser.extract_weather_icons()
    
    assert len(icons) == 3
    assert '/icon1.png' in icons[0]
    assert '/icon2.png' in icons[1]


def test_tide_table_parser_extract_wind_direction_icons():
    """풍향 아이콘 추출 테스트"""
    from services.badatime_parser import TideTableParser
    
    html = create_mock_tide_table_html()
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    
    parser = TideTableParser(table)
    icons = parser.extract_wind_direction_icons()
    
    assert len(icons) == 3
    assert '/wind1.png' in icons[0]
    assert '/wind2.png' in icons[1]


def test_tide_table_parser_parse_full():
    """전체 파싱 테스트"""
    from services.badatime_parser import TideTableParser
    
    html = create_mock_tide_table_html()
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    
    parser = TideTableParser(table)
    result = parser.parse()
    
    assert result is not None
    assert len(result) == 3
    
    first_entry = result[0]
    assert first_entry['time'] == '00시'
    assert first_entry['weather_text'] == '맑음'
    assert first_entry['temperature'] == '15℃'
    assert first_entry['wind_dir'] == '북'
    assert first_entry['wind_speed'] == '3m/s'
    assert first_entry['wave_height'] == '0.5m'


def test_tide_table_parser_graceful_empty_table():
    """빈 테이블 처리 테스트"""
    from services.badatime_parser import TideTableParser
    
    html = '<table class="week_table"><tbody></tbody></table>'
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table')
    
    parser = TideTableParser(table)
    result = parser.parse()

    # 빈 테이블은 None 또는 빈 리스트 반환
    assert result is None or result == []


# --- GraphPageParser: 실제 /{port_id}/graph/{date} 페이지 fixture 기반 -------
# 사용자 요청: iframe으로 바다타임 그래프를 그대로 띄우면 LNB를 못 지우고
# 패널 크기도 못 바꾼다(cross-origin) - 원시 데이터만 파싱해 자체 위젯을
# 그리기로 했다. 위 TideTableParser 테스트들과 달리 손으로 만든 mock이 아니라
# 실제로 받은 응답(tests/fixtures/badatime/)을 그대로 쓴다(CLAUDE.md 규칙 1).

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
