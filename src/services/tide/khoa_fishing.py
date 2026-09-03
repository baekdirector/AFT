"""
KHOA(국립해양조사원) 바다낚시지수 조회 API. Phase E.

공공데이터포털 dataset 15142486, End Point:
  https://apis.data.go.kr/1192136/fcstFishingv2/GetFcstFishingApiServicev2

실측(2026-09)으로 확인한 사실 (문서에 없어서 직접 호출해서 알아낸 것들):
  - resultType=json 을 줘도 항상 XML 로 온다. JSON 은 지원하지 않는다.
  - 필수 파라미터는 gubun(값: '선상' 또는 '갯바위') 하나뿐이다. 날짜 파라미터가
    없다 - date/searchDate/predcYmd/baseDate 를 줘도 조용히 무시되고 오늘 기준
    응답만 온다.
  - **예보 범위가 오늘부터 +5일뿐이다.** AFT 사용자가 조회하는 예약 날짜는
    보통 몇 주 뒤라 대부분 이 범위 밖이다. 그래서 이 API는 원래 계획한
    "예약 날짜에 맞는 조석"을 대체하지 못한다. 근시일(치)에만 낚시지수를
    보여주는 보조 정보로 취급한다. 범위 밖이면 오류가 아니라 '예보 없음'
    으로 조용히 처리한다(PLAN.md 의 NOT_OPEN 류와 같은 취급).
  - numOfRows 상한이 있다(1000 은 INVALID_REQUEST_PARAMETER_ERROR, 100 은 됨).
  - 한 페이지가 지점×어종×오전/오후 조합이라 한 지점의 하루 전체를 보려면
    여러 페이지를 넘겨봐야 한다. 페이지 수가 얼마나 되는지도 문서에 없어서
    직접 넘겨보며 확인했다(totalCount=1400, 100개씩 14페이지, 날짜 6일치).

fixture: tests/fixtures/khoa_fishing/boat_page1_20260904.xml (실제 응답 원본)
"""
from __future__ import annotations

import math
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

API_URL = 'https://apis.data.go.kr/1192136/fcstFishingv2/GetFcstFishingApiServicev2'
ENV_KEY = 'KHOA_FISHING_API_KEY'

# 선상낚시만 쓴다. AFT 는 선상 예약 조회 서비스이지 갯바위가 아니다.
GUBUN_BOAT = '선상'

_CONNECT_TIMEOUT = float(os.environ.get('KHOA_FISHING_CONNECT_TIMEOUT', 5))
_READ_TIMEOUT = float(os.environ.get('KHOA_FISHING_READ_TIMEOUT', 10))

# 데이터가 대략 하루 단위로 갱신되므로 매 요청마다 14페이지를 다시 긁을
# 이유가 없다. 서버 프로세스 하나가 살아있는 동안 이 캐시를 공유한다.
_CACHE_TTL_SECONDS = 3600
_cache: dict[str, tuple[float, list['FishingForecast']]] = {}


class ApiError(Exception):
    """API 가 명시적으로 오류를 돌려줬다(resultCode != '00')."""


@dataclass(frozen=True)
class FishingForecast:
    position: str          # seafsPstnNm - 지점명
    lat: float
    lon: float
    date: str               # 'YYYY-MM-DD'
    noon: str                # '오전' | '오후'
    fish: str                # seafsTgfshNm - 대상어종
    tide_period: str         # tdlvHrCn - '소조기'/'대조기' 등. N물 숫자는 아니다.
    wave_min: float
    wave_max: float
    water_temp_min: float
    water_temp_max: float
    air_temp_min: float
    air_temp_max: float
    current_min: float
    current_max: float
    wind_min: float
    wind_max: float
    total_index: str         # '매우나쁨'~'매우좋음' 5단계


def _text(item: ET.Element, tag: str) -> str:
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else ''


def _num(item: ET.Element, tag: str) -> float:
    raw = _text(item, tag)
    try:
        return float(raw)
    except ValueError:
        return 0.0


def parse(xml_text: str) -> list[FishingForecast]:
    """API 응답 XML 하나를 파싱한다. 순수 함수 - 네트워크 없음.

    resultCode 가 정상이 아니면 ApiError 를 던진다. 상위 호출자가 판단할
    문제(잘못된 파라미터 등)와 정상적으로 항목이 0건인 경우를 구분해야 한다.
    """
    root = ET.fromstring(xml_text)
    result_code = _text(root, './/resultCode')
    if result_code != '00':
        result_msg = _text(root, './/resultMsg')
        raise ApiError(f'{result_code}: {result_msg}')

    forecasts = []
    for item in root.iter('item'):
        forecasts.append(FishingForecast(
            position=_text(item, 'seafsPstnNm'),
            lat=_num(item, 'lat'),
            lon=_num(item, 'lot'),
            date=_text(item, 'predcYmd'),
            noon=_text(item, 'predcNoonSeCd'),
            fish=_text(item, 'seafsTgfshNm'),
            tide_period=_text(item, 'tdlvHrCn'),
            wave_min=_num(item, 'minWvhgt'), wave_max=_num(item, 'maxWvhgt'),
            water_temp_min=_num(item, 'minWtem'), water_temp_max=_num(item, 'maxWtem'),
            air_temp_min=_num(item, 'minArtmp'), air_temp_max=_num(item, 'maxArtmp'),
            current_min=_num(item, 'minCrsp'), current_max=_num(item, 'maxCrsp'),
            wind_min=_num(item, 'minWspd'), wind_max=_num(item, 'maxWspd'),
            total_index=_text(item, 'totalIndex'),
        ))
    return forecasts


def fetch_page(page_no: int, num_rows: int = 100, gubun: str = GUBUN_BOAT) -> str:
    """페이지 하나를 가져온다. 네트워크 I/O 는 여기만 담당한다."""
    api_key = os.environ.get(ENV_KEY)
    if not api_key:
        raise RuntimeError(f'{ENV_KEY} 환경변수가 설정되지 않았다.')

    resp = requests.get(API_URL, params={
        'serviceKey': api_key,
        'pageNo': page_no,
        'numOfRows': num_rows,
        'gubun': gubun,
    }, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
    resp.raise_for_status()
    return resp.text


def fetch_all(gubun: str = GUBUN_BOAT, max_pages: int = 20) -> list[FishingForecast]:
    """전체 예보(오늘~+5일, 전 지점)를 긁어 캐시한다.

    페이지당 최대 100건이고 전체가 약 1,400건(14페이지)이라, 매 요청마다
    새로 긁으면 외부 API 를 14번 왕복해야 한다. 데이터가 하루 단위로
    갱신되므로 프로세스 내 캐시로 충분하다.
    """
    now = time.monotonic()
    cached = _cache.get(gubun)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    all_forecasts: list[FishingForecast] = []
    page = 1
    while page <= max_pages:
        xml_text = fetch_page(page_no=page, gubun=gubun)
        batch = parse(xml_text)
        if not batch:
            break
        all_forecasts.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    _cache[gubun] = (now, all_forecasts)
    return all_forecasts


def clear_cache() -> None:
    _cache.clear()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 사이의 대권거리(km). 지구를 구로 근사한다 - 항구 간 거리
    비교에는 그 정도 오차가 문제되지 않는다."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def nearest_position(forecasts: list[FishingForecast],
                     lat: float, lon: float) -> tuple[str, float] | None:
    """이 항구에서 가장 가까운 예보 지점명과 거리(km)를 돌려준다.

    이 API 의 지점은 AFT 항구 목록과 이름이 다를 수 있다(예: '가거도').
    이름 매칭 대신 좌표로 가장 가까운 지점을 고른다.
    """
    if not forecasts:
        return None
    seen: dict[str, tuple[float, float]] = {}
    for f in forecasts:
        seen.setdefault(f.position, (f.lat, f.lon))

    best_name, best_dist = None, float('inf')
    for name, (flat, flon) in seen.items():
        dist = _haversine_km(lat, lon, flat, flon)
        if dist < best_dist:
            best_name, best_dist = name, dist
    return (best_name, best_dist) if best_name else None


def for_port(port_lat: float, port_lon: float, target_date: str,
            gubun: str = GUBUN_BOAT) -> dict:
    """항구 좌표 + 날짜로 낚시지수 예보를 조회한다.

    돌려주는 dict 는 항상 'available' 키를 가진다. 날짜가 예보 범위(오늘~+5일)
    밖이면 available=False 로, 예외를 던지지 않고 '없음' 을 알려준다.
    (PLAN.md 의 NOT_OPEN 처리와 같은 태도 - 없는 게 정상일 수 있다.)
    """
    forecasts = fetch_all(gubun=gubun)
    if not forecasts:
        return {'available': False, 'reason': 'no_data'}

    match = nearest_position(forecasts, port_lat, port_lon)
    if match is None:
        return {'available': False, 'reason': 'no_data'}
    position, distance_km = match

    entries = [f for f in forecasts if f.position == position and f.date == target_date]
    if not entries:
        available_dates = sorted({f.date for f in forecasts})
        return {
            'available': False,
            'reason': 'forecast_range_exceeded',
            'position': position,
            'distance_km': round(distance_km, 1),
            'available_dates': available_dates,
        }

    return {
        'available': True,
        'position': position,
        'distance_km': round(distance_km, 1),
        'date': target_date,
        'entries': [
            {
                'noon': e.noon,
                'fish': e.fish,
                'tide_period': e.tide_period,
                'wave_m': [e.wave_min, e.wave_max],
                'water_temp_c': [e.water_temp_min, e.water_temp_max],
                'air_temp_c': [e.air_temp_min, e.air_temp_max],
                'current_kt': [e.current_min, e.current_max],
                'wind_ms': [e.wind_min, e.wind_max],
                'total_index': e.total_index,
            }
            for e in entries
        ],
    }
