"""선사 노트의 자유 입력 지역·항구를 날씨 화면의 지역/항구(Port 표)에 맞춘다.

선사 노트의 항구는 직접 입력한 텍스트라 날씨 쪽 이름과 자주 다르다(영흥도 ↔
영흥항, 남항 ↔ 남항(인천항), 돌산나루터 ↔ 돌산항). 순수 함수라 DB 없이 테스트한다.
"""
import re

_SUFFIXES = ('나루터', '방파제', '부두', '항', '도')


def _stem(name: str) -> str:
    base = re.sub(r'\(.*?\)', '', name or '').replace(' ', '')
    for suf in _SUFFIXES:
        if base.endswith(suf) and len(base) > len(suf):
            return base[: -len(suf)]
    return base


def _find_port(port: str, candidates: list[str]) -> str | None:
    """후보 항구 중 가장 알맞은 것: 이름 일치 → 어간 일치 → 어간 포함(2글자 이상)."""
    if port in candidates:
        return port
    stem = _stem(port)
    for c in candidates:
        if _stem(c) == stem:
            return c
    if len(stem) >= 2:
        for c in candidates:
            if stem in c.replace(' ', ''):
                return c
    return None


def resolve_weather_target(region: str | None, port: str | None,
                           city_ports: dict[str, list[str]]) -> dict:
    """{'city': 지역|None, 'port': 항구|None}. 항구를 못 찾으면 지역만(지역도 모르면 둘 다 None)."""
    region = (region or '').strip()
    port = (port or '').strip()
    city = region if region in city_ports else None

    if port:
        if city:
            found = _find_port(port, city_ports[city])
            if found:
                return {'city': city, 'port': found}
        # 지역이 비었거나(선사 노트의 '오천' 등 Port 표에 없는 지역명) 그 지역에서 못 찾음 -> 전체에서 찾는다.
        for other, ports in city_ports.items():
            if other == city:
                continue
            found = _find_port(port, ports)
            if found:
                return {'city': other, 'port': found}
    return {'city': city, 'port': None}
