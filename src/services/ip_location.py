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
                json=[{'query': ip, 'fields': 'status,city,regionName,country,query'} for ip in chunk],
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
                ))
            else:
                db.session.add(IpLocation(ip=ip, is_private=False))

    db.session.commit()
