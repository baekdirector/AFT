import pytest
from services.weather_port_match import resolve_weather_target

CP = {
    '인천': ['남항(인천항)', '연안부두', '영흥항'],
    '보령': ['구매항', '대천항', '무창포항테스트', '오천항'],
    '여수': ['돌산항', '종포항'],
    '군산': ['비응항'],
}


@pytest.mark.parametrize('region,port,city,found', [
    ('인천', '연안부두', '인천', '연안부두'),      # 이름 일치
    ('인천', '영흥도', '인천', '영흥항'),          # 어간 일치
    ('인천', '남항', '인천', '남항(인천항)'),      # 괄호 이름
    ('여수', '돌산나루터', '여수', '돌산항'),
    ('보령', '무창포항', '보령', '무창포항테스트'),  # 포함
    ('오천', '오천항', '보령', '오천항'),          # 지역명이 Port 표에 없음 -> 전체에서
    ('군산', '비응항', '군산', '비응항'),
])
def test_port_is_resolved(region, port, city, found):
    assert resolve_weather_target(region, port, CP) == {'city': city, 'port': found}


def test_one_letter_typo_is_tolerated_within_the_region():
    assert resolve_weather_target('인천', '연안부드', CP) == {'city': '인천', 'port': '연안부두'}


def test_unmatched_port_falls_back_to_region_only():
    assert resolve_weather_target('인천', '엉뚱한곳', CP) == {'city': '인천', 'port': None}
    # 오타 허용은 같은 지역 안에서만 - 다른 지역의 비슷한 이름으로 새지 않는다
    assert resolve_weather_target('여수', '연안부드', CP) == {'city': '여수', 'port': None}


def test_empty_input():
    assert resolve_weather_target(None, None, CP) == {'city': None, 'port': None}
    assert resolve_weather_target('없는지역', '모르는항', CP) == {'city': None, 'port': None}


def test_weather_page_data_prefill_only_when_requested(client):
    base = client.get('/api/weather_page_data').get_json()['data']
    assert 'prefill' not in base
    got = client.get('/api/weather_page_data?region=인천&port=영흥도').get_json()['data']
    assert got['prefill']['city'] == '인천' and got['prefill']['port'] in got['city_port_mapping']['인천']
