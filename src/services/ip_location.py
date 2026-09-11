# -*- coding: utf-8 -*-
"""/admin 표에 표시할 IP -> 도시/지역 조회. 무료 배치 API(ip-api.com, 키
불필요, 분당 45회 한도)를 쓴다 - AFT는 무료 호스팅 전용 원칙이라 유료
지오로케이션 서비스는 쓰지 않는다.

방문 시점이 아니라 관리자가 /admin 을 열 때 지연 조회 + 캐시한다. 매
페이지뷰마다 외부 API를 부르면 실제 방문자의 로딩이 그만큼 느려지기
때문이다(방문 기록 자체는 services.visit_logger 가 동기 호출 없이 즉시
저장한다).
"""
import ipaddress

import requests
from flask import current_app

from db import db
from models import IpLocation

BATCH_URL = 'http://ip-api.com/batch'
BATCH_SIZE = 100  # ip-api.com 무료 배치 한 요청당 최대 IP 수

#: ip-api.com 무료 API 는 lang 파라미터로 en/de/es/pt-BR/fr/ja/zh-CN/ru 만
#: 지원하고 한국어(ko)는 없다(공식 문서 확인). 그래서 국내(South Korea) IP만
#: 시/도·주요 시 이름을 직접 번역해서 보여준다 - GeoIP 응답에 나오는 영문
#: 표기 변형을 최대한 커버하되, 여기 없는 값은 원문(영문) 그대로 보여준다
#: (완벽한 번역이 아니라 실용적 수준의 가독성이 목적).
KOREA_REGION_KO = {
    'Seoul': '서울특별시', 'Busan': '부산광역시', 'Daegu': '대구광역시',
    'Incheon': '인천광역시', 'Gwangju': '광주광역시', 'Daejeon': '대전광역시',
    'Ulsan': '울산광역시', 'Sejong': '세종특별자치시', 'Sejong-si': '세종특별자치시',
    'Gyeonggi-do': '경기도', 'Gyeonggi': '경기도',
    'Gangwon-do': '강원특별자치도', 'Gangwon': '강원특별자치도', 'Gangwon State': '강원특별자치도',
    'Chungcheongbuk-do': '충청북도', 'North Chungcheong': '충청북도',
    'Chungcheongnam-do': '충청남도', 'South Chungcheong': '충청남도',
    'Jeollabuk-do': '전북특별자치도', 'North Jeolla': '전북특별자치도', 'Jeonbuk': '전북특별자치도',
    'Jeollanam-do': '전라남도', 'South Jeolla': '전라남도',
    'Gyeongsangbuk-do': '경상북도', 'North Gyeongsang': '경상북도',
    'Gyeongsangnam-do': '경상남도', 'South Gyeongsang': '경상남도',
    'Jeju-do': '제주특별자치도', 'Jeju': '제주특별자치도',
}

KOREA_CITY_KO = {
    'Seoul': '서울', 'Busan': '부산', 'Daegu': '대구', 'Incheon': '인천',
    'Gwangju': '광주', 'Daejeon': '대전', 'Ulsan': '울산', 'Sejong': '세종',
    'Suwon': '수원', 'Seongnam': '성남', 'Yongin': '용인', 'Goyang': '고양',
    'Bucheon': '부천', 'Ansan': '안산', 'Anyang': '안양', 'Namyangju': '남양주',
    'Hwaseong': '화성', 'Pyeongtaek': '평택', 'Uijeongbu': '의정부', 'Siheung': '시흥',
    'Paju': '파주', 'Gimpo': '김포', 'Gwangmyeong': '광명', 'Gunpo': '군포',
    'Icheon': '이천', 'Osan': '오산', 'Guri': '구리', 'Anseong': '안성',
    'Pocheon': '포천', 'Uiwang': '의왕', 'Hanam': '하남', 'Yangju': '양주',
    'Dongducheon': '동두천', 'Gwacheon': '과천', 'Yeoju': '여주',
    'Cheongju': '청주', 'Chungju': '충주', 'Cheonan': '천안', 'Asan': '아산',
    'Seosan': '서산', 'Dangjin': '당진', 'Taean': '태안', 'Boryeong': '보령',
    'Gongju': '공주', 'Nonsan': '논산',
    'Jeonju': '전주', 'Iksan': '익산', 'Gunsan': '군산', 'Jeongeup': '정읍',
    'Namwon': '남원', 'Buan': '부안', 'Gimje': '김제',
    'Mokpo': '목포', 'Yeosu': '여수', 'Suncheon': '순천', 'Gwangyang': '광양',
    'Naju': '나주', 'Goheung': '고흥',
    'Pohang': '포항', 'Gyeongju': '경주', 'Gumi': '구미', 'Andong': '안동',
    'Gimcheon': '김천', 'Changwon': '창원', 'Jinju': '진주', 'Gimhae': '김해',
    'Yangsan': '양산', 'Geoje': '거제', 'Tongyeong': '통영', 'Sacheon': '사천',
    'Chuncheon': '춘천', 'Wonju': '원주', 'Gangneung': '강릉', 'Donghae': '동해',
    'Sokcho': '속초', 'Jeju': '제주', 'Seogwipo': '서귀포',
}


def format_location(loc: 'IpLocation | None') -> str:
    """/admin 표에 쓸 위치 문자열. 국내(South Korea) IP는 한글로 번역해서
    보여주고, 그 밖의 나라는 GeoIP가 돌려준 영문 그대로 보여준다(모든
    나라의 모든 도시를 번역할 수는 없다 - 방문자 대부분이 국내라는 이
    프로젝트 성격상 국내만 한글화해도 실용적으로 충분하다)."""
    if loc is None:
        return '-'
    if loc.is_private:
        return '로컬'
    if not loc.city:
        return '확인 실패'
    if loc.country == 'South Korea':
        city = KOREA_CITY_KO.get(loc.city, loc.city)
        region = KOREA_REGION_KO.get(loc.region, loc.region) if loc.region else None
        if region and region != city:
            return f'{city} ({region})'
        return city
    return f'{loc.city} ({loc.region})' if loc.region and loc.region != loc.city else loc.city


def is_private_ip(ip: str | None) -> bool:
    if not ip:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback


def resolve_missing(ips: list[str]) -> None:
    """주어진 IP 목록 중 IpLocation 캐시에 없는 것만 조회해서 채운다.
    외부 API 실패는 통째로 삼킨다(실패 격리) - 실패해도 /admin 페이지
    자체는 "위치 확인 실패" 표시로 정상 렌더된다."""
    unique_ips = sorted({ip for ip in ips if ip})
    if not unique_ips:
        return

    known = {row.ip for row in IpLocation.query.filter(IpLocation.ip.in_(unique_ips)).all()}
    missing = [ip for ip in unique_ips if ip not in known]
    if not missing:
        return

    for ip in missing:
        if is_private_ip(ip):
            db.session.add(IpLocation(ip=ip, is_private=True))
    to_lookup = [ip for ip in missing if not is_private_ip(ip)]

    for start in range(0, len(to_lookup), BATCH_SIZE):
        chunk = to_lookup[start:start + BATCH_SIZE]
        try:
            resp = requests.post(
                BATCH_URL,
                json=[{'query': ip, 'fields': 'status,city,regionName,country,hosting,query'} for ip in chunk],
                timeout=8,
            )
            resp.raise_for_status()
            results = resp.json()
        except Exception:
            current_app.logger.exception('IP 위치 조회 실패(%d건)', len(chunk))
            continue

        for item in results:
            ip = item.get('query')
            if not ip:
                continue
            if item.get('status') == 'success':
                db.session.add(IpLocation(
                    ip=ip, city=item.get('city'), region=item.get('regionName'),
                    country=item.get('country'), is_private=False,
                    is_hosting=bool(item.get('hosting')),
                ))
            else:
                db.session.add(IpLocation(ip=ip, is_private=False))

    db.session.commit()
