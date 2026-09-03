"""
바다낚시지수 API 클라이언트 테스트 (Phase E).

네트워크를 타지 않는다. fetch_page 를 목으로 대체한다.
파싱은 실제 응답 fixture 로, 나머지(거리 매칭·범위 밖 처리·캐시)는
합성 데이터로 검증한다.
"""
import io
from pathlib import Path

import pytest

from services.tide import khoa_fishing as kf

FIXTURE = (Path(__file__).parent / 'fixtures' / 'khoa_fishing'
          / 'boat_page1_20260904.xml')


@pytest.fixture(autouse=True)
def _clear_cache():
    kf.clear_cache()
    yield
    kf.clear_cache()


# --- 파싱 (실제 fixture) -----------------------------------------------------

def test_parse_real_response():
    xml_text = io.open(FIXTURE, encoding='utf-8').read()

    forecasts = kf.parse(xml_text)

    assert len(forecasts) == 100, '실측 당시 100개(numOfRows)였다'
    first = forecasts[0]
    assert first.position == '가거도'
    assert first.lat == pytest.approx(34.07308)
    assert first.date == '2026-09-04'
    assert first.noon == '오전'
    assert first.fish == '감성돔'
    assert first.tide_period == '소조기'
    assert first.total_index == '매우나쁨'
    assert (first.wave_min, first.wave_max) == (1.1, 1.2)


def test_parse_is_deterministic():
    xml_text = io.open(FIXTURE, encoding='utf-8').read()
    assert kf.parse(xml_text) == kf.parse(xml_text)


def test_parse_raises_on_error_result_code():
    """INVALID_REQUEST_PARAMETER_ERROR 등 실제로 겪은 오류 응답 형태."""
    xml_text = ('<response><header><resultCode>10</resultCode>'
                '<resultMsg>INVALID_REQUEST_PARAMETER_ERROR</resultMsg>'
                '</header></response>')
    with pytest.raises(kf.ApiError, match='INVALID_REQUEST_PARAMETER_ERROR'):
        kf.parse(xml_text)


def test_parse_missing_numeric_field_does_not_crash():
    """필드 하나가 비어 있어도(관측 결측 등) 파싱이 죽으면 안 된다."""
    xml_text = ('<response><header><resultCode>00</resultCode>'
                '<resultMsg>NORMAL_SERVICE</resultMsg></header>'
                '<body><items><item>'
                '<seafsPstnNm>테스트항</seafsPstnNm><lat>35.0</lat><lot>126.0</lot>'
                '<predcYmd>2026-09-04</predcYmd><predcNoonSeCd>오전</predcNoonSeCd>'
                '<seafsTgfshNm>테스트어종</seafsTgfshNm><tdlvHrCn>대조기</tdlvHrCn>'
                '<minWvhgt></minWvhgt><maxWvhgt>1.0</maxWvhgt>'
                '<minWtem>20</minWtem><maxWtem>21</maxWtem>'
                '<minArtmp>20</minArtmp><maxArtmp>21</maxArtmp>'
                '<minCrsp>0.1</minCrsp><maxCrsp>0.2</maxCrsp>'
                '<minWspd>1</minWspd><maxWspd>2</maxWspd>'
                '<totalIndex>보통</totalIndex>'
                '</item></items></body></response>')
    forecasts = kf.parse(xml_text)
    assert forecasts[0].wave_min == 0.0


# --- 거리 매칭 ---------------------------------------------------------------

def make_forecast(position, lat, lon, date='2026-09-04', **overrides):
    fields = dict(
        position=position, lat=lat, lon=lon, date=date, noon='오전',
        fish='감성돔', tide_period='소조기',
        wave_min=1.0, wave_max=1.2, water_temp_min=20.0, water_temp_max=21.0,
        air_temp_min=20.0, air_temp_max=21.0, current_min=0.1, current_max=0.2,
        wind_min=1.0, wind_max=2.0, total_index='보통',
    )
    fields.update(overrides)
    return kf.FishingForecast(**fields)


def test_nearest_position_picks_closest():
    forecasts = [
        make_forecast('먼항', 33.0, 124.0),
        make_forecast('가까운항', 37.0, 126.6),
        make_forecast('먼항2', 35.5, 129.0),
    ]
    # 인천 남항 근처 좌표
    name, dist_km = kf.nearest_position(forecasts, 37.47, 126.62)

    assert name == '가까운항'
    assert dist_km < 100


def test_nearest_position_empty_list_returns_none():
    assert kf.nearest_position([], 37.0, 126.0) is None


def test_haversine_zero_distance_for_same_point():
    assert kf._haversine_km(37.0, 126.0, 37.0, 126.0) == pytest.approx(0.0, abs=1e-6)


# --- for_port: 범위 안/밖 ----------------------------------------------------

def test_for_port_within_range(monkeypatch):
    forecasts = [
        make_forecast('모항항', 36.78, 126.13, date='2026-09-04', noon='오전',
                      total_index='좋음'),
        make_forecast('모항항', 36.78, 126.13, date='2026-09-04', noon='오후',
                      total_index='매우좋음'),
    ]
    monkeypatch.setattr(kf, 'fetch_all', lambda gubun=kf.GUBUN_BOAT: forecasts)

    result = kf.for_port(36.7759, 126.1328, '2026-09-04')

    assert result['available'] is True
    assert result['position'] == '모항항'
    assert len(result['entries']) == 2
    assert {e['noon'] for e in result['entries']} == {'오전', '오후'}


def test_for_port_beyond_forecast_horizon_is_not_an_error(monkeypatch):
    """실측: 이 API 는 오늘부터 +5일만 예보한다. AFT 예약 날짜는 보통
    몇 주 뒤라 대부분 범위 밖이다. 범위 밖은 예외가 아니라 '없음' 이어야 한다."""
    forecasts = [make_forecast('모항항', 36.78, 126.13, date='2026-09-04')]
    monkeypatch.setattr(kf, 'fetch_all', lambda gubun=kf.GUBUN_BOAT: forecasts)

    result = kf.for_port(36.7759, 126.1328, '2026-10-03')

    assert result['available'] is False
    assert result['reason'] == 'forecast_range_exceeded'
    assert result['position'] == '모항항', '범위 밖이어도 가장 가까운 지점은 알려준다'
    assert '2026-09-04' in result['available_dates']


def test_for_port_no_data_at_all(monkeypatch):
    monkeypatch.setattr(kf, 'fetch_all', lambda gubun=kf.GUBUN_BOAT: [])
    result = kf.for_port(36.0, 126.0, '2026-09-04')
    assert result == {'available': False, 'reason': 'no_data'}


# --- fetch_all: 페이지네이션 + 캐시 (네트워크 목) --------------------------------

def test_fetch_all_stops_when_page_is_short(monkeypatch):
    """100건 미만이 오면 마지막 페이지라는 뜻이다. 계속 넘기면 안 된다."""
    pages = {
        1: _xml_page(100),
        2: _xml_page(37),
    }
    calls = []

    def fake_fetch_page(page_no, num_rows=100, gubun=kf.GUBUN_BOAT):
        calls.append(page_no)
        return pages[page_no]

    monkeypatch.setattr(kf, 'fetch_page', fake_fetch_page)

    result = kf.fetch_all()

    assert calls == [1, 2]
    assert len(result) == 137


def test_fetch_all_is_cached_within_ttl(monkeypatch):
    calls = []

    def fake_fetch_page(page_no, num_rows=100, gubun=kf.GUBUN_BOAT):
        calls.append(page_no)
        return _xml_page(1)

    monkeypatch.setattr(kf, 'fetch_page', fake_fetch_page)

    kf.fetch_all()
    kf.fetch_all()

    assert len(calls) == 1, '캐시가 있으면 두 번째 호출은 네트워크를 타면 안 된다'


def test_fetch_page_without_api_key_raises(monkeypatch):
    monkeypatch.delenv(kf.ENV_KEY, raising=False)
    with pytest.raises(RuntimeError, match=kf.ENV_KEY):
        kf.fetch_page(page_no=1)


def _xml_page(n: int) -> str:
    items = ''.join(
        f'<item><seafsPstnNm>지점{i}</seafsPstnNm><lat>35.0</lat><lot>126.0</lot>'
        f'<predcYmd>2026-09-04</predcYmd><predcNoonSeCd>오전</predcNoonSeCd>'
        f'<seafsTgfshNm>어종</seafsTgfshNm><tdlvHrCn>소조기</tdlvHrCn>'
        f'<minWvhgt>1</minWvhgt><maxWvhgt>1</maxWvhgt>'
        f'<minWtem>20</minWtem><maxWtem>20</maxWtem>'
        f'<minArtmp>20</minArtmp><maxArtmp>20</maxArtmp>'
        f'<minCrsp>0.1</minCrsp><maxCrsp>0.1</maxCrsp>'
        f'<minWspd>1</minWspd><maxWspd>1</maxWspd>'
        f'<totalIndex>보통</totalIndex></item>'
        for i in range(n)
    )
    return (f'<response><header><resultCode>00</resultCode>'
           f'<resultMsg>NORMAL_SERVICE</resultMsg></header>'
           f'<body><items>{items}</items></body></response>')
