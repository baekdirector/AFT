# -*- coding: utf-8 -*-
"""/admin 이력 표용 방문 기록. before_request 훅에서 호출된다.

허용목록(TRACKED_ENDPOINTS)에 든 "사람이 실제로 보는 화면" 라우트만
기록한다 - /api/*, /healthz, 정적 파일까지 잡으면 /status 가 자체 폴링하는
API 호출까지 "접속"으로 쌓여 표가 노이즈로 가득 찬다. 기록 실패가 실제
요청을 절대 막으면 안 되므로(실패 격리) 호출부에서 전부 try/except 로
감싼다.
"""
import re

from flask import current_app, request

from db import db
from models import VisitLog

TRACKED_ENDPOINTS = {
    'views.index',
    'views.status',
    'views.watches',
    'views.weather',
    'views.map_page',
    'views.register',
    'views.edit_boat',
}

_TABLET_RE = re.compile(r'iPad|Tablet|Nexus 7|Nexus 9|Nexus 10|KFAPWI', re.IGNORECASE)
_MOBILE_RE = re.compile(r'Mobi|Android|iPhone|iPod|BlackBerry|Windows Phone', re.IGNORECASE)


def _client_ip() -> str | None:
    """Render는 프록시 뒤에 있어서 request.remote_addr 만으로는 프록시 IP만
    보인다. X-Forwarded-For 의 첫 값(원 클라이언트)을 우선 쓴다."""
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        first = forwarded.split(',')[0].strip()
        if first:
            return first
    return request.remote_addr


def device_type(user_agent: str | None) -> str:
    """완벽한 기기 판별이 목적이 아니라 표에서 PC/모바일/태블릿을 구분할
    실용적 수준이면 충분하다."""
    if not user_agent:
        return 'unknown'
    if _TABLET_RE.search(user_agent):
        return 'tablet'
    if _MOBILE_RE.search(user_agent):
        return 'mobile'
    return 'pc'


def log_visit() -> None:
    if request.endpoint not in TRACKED_ENDPOINTS or request.method != 'GET':
        return
    try:
        ua = (request.headers.get('User-Agent') or '')[:500]
        db.session.add(VisitLog(
            path=request.path,
            method=request.method,
            ip=_client_ip(),
            device_type=device_type(ua),
            user_agent=ua,
        ))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception('방문 기록 저장 실패')
