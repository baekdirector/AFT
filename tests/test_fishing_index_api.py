"""
GET /api/fishing_index 테스트 (Phase E).

이 API 는 오늘부터 +5일만 예보한다. 대부분의 예약 조회 날짜는 그 밖이므로,
'범위 밖'을 200 + available=false 로 조용히 알려주는 것이 핵심 계약이다.
"""
import pytest

from services.tide import khoa_fishing as kf


@pytest.fixture(autouse=True)
def _clear_cache():
    kf.clear_cache()
    yield
    kf.clear_cache()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(kf.ENV_KEY, 'test-key')


def test_missing_params_returns_400(client, configured):
    assert client.get('/api/fishing_index').status_code == 400
    assert client.get('/api/fishing_index?port=남항(인천항)').status_code == 400


def test_unknown_port_returns_404(client, configured):
    resp = client.get('/api/fishing_index?port=없는항&date=2026-09-04')
    assert resp.status_code == 404


def test_missing_api_key_returns_503_not_a_crash(client, monkeypatch):
    monkeypatch.delenv(kf.ENV_KEY, raising=False)
    resp = client.get('/api/fishing_index?port=남항(인천항)&date=2026-09-04')
    assert resp.status_code == 503


def test_within_range_returns_data(client, configured, monkeypatch):
    forecast = kf.FishingForecast(
        position='연안부두', lat=37.4416, lon=126.6110, date='2026-09-04',
        noon='오전', fish='감성돔', tide_period='소조기',
        wave_min=1.0, wave_max=1.2, water_temp_min=20.0, water_temp_max=21.0,
        air_temp_min=20.0, air_temp_max=21.0, current_min=0.1, current_max=0.2,
        wind_min=1.0, wind_max=2.0, total_index='좋음',
    )
    monkeypatch.setattr(kf, 'fetch_all', lambda gubun=kf.GUBUN_BOAT: [forecast])

    resp = client.get('/api/fishing_index?port=남항(인천항)&date=2026-09-04')

    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['available'] is True
    assert data['entries'][0]['total_index'] == '좋음'


def test_beyond_horizon_is_200_not_error(client, configured, monkeypatch):
    """이게 이 엔드포인트의 핵심 계약이다. 몇 주 뒤 예약 날짜를 조회했다고
    프론트에 500/404 를 던지면 안 된다 - 정상적으로 없는 것이다."""
    forecast = kf.FishingForecast(
        position='연안부두', lat=37.4416, lon=126.6110, date='2026-09-04',
        noon='오전', fish='감성돔', tide_period='소조기',
        wave_min=1.0, wave_max=1.2, water_temp_min=20.0, water_temp_max=21.0,
        air_temp_min=20.0, air_temp_max=21.0, current_min=0.1, current_max=0.2,
        wind_min=1.0, wind_max=2.0, total_index='좋음',
    )
    monkeypatch.setattr(kf, 'fetch_all', lambda gubun=kf.GUBUN_BOAT: [forecast])

    resp = client.get('/api/fishing_index?port=남항(인천항)&date=2026-10-03')

    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['available'] is False
    assert data['reason'] == 'forecast_range_exceeded'


def test_upstream_failure_is_502_not_a_crash(client, configured, monkeypatch):
    def boom(gubun=kf.GUBUN_BOAT):
        raise RuntimeError('네트워크 실패')
    monkeypatch.setattr(kf, 'fetch_all', boom)

    resp = client.get('/api/fishing_index?port=남항(인천항)&date=2026-09-04')

    assert resp.status_code == 502
