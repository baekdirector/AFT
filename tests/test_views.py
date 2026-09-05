"""
일반 라우트 테스트.
"""
from datetime import datetime
from unittest.mock import patch

from routes.views import KST


def _at_kst_hour(hour):
    """routes.views.datetime.now(KST) 가 이 시각을 돌려주게 하는 patch 컨텍스트."""
    fixed = datetime(2026, 9, 5, hour, 0, tzinfo=KST)
    p = patch('routes.views.datetime')
    mock_datetime = p.start()
    mock_datetime.now.return_value = fixed
    return p


def test_healthz_ok_during_active_hours(client):
    """Uptime 모니터링(예: UptimeRobot) 핑이 5분마다 치는 엔드포인트다.

    인증도 없고 DB 도 안 건드려야 한다 - 부하 없이 '떠있다'만 확인하는 용도다.
    06:00~24:00 KST 활동시간대엔 200 이어야 실제로 Render 를 깨운다.
    """
    p = _at_kst_hour(12)
    try:
        rv = client.get('/healthz')
        assert rv.status_code == 200
        assert rv.get_data(as_text=True) == 'ok'
    finally:
        p.stop()


def test_healthz_returns_503_during_sleep_window(client):
    """00:00~06:00 KST 새벽엔 일부러 503을 줘서 찔러도 안 깨우게 한다.

    Render 무료 티어의 월 750 instance-hour 한도를 넘기지 않기 위해서다 -
    24시간 내내 깨우면 31일짜리 달엔 한도를 넘겨 그 달 서비스가 통째로
    정지될 위험이 있다.
    """
    p = _at_kst_hour(2)
    try:
        rv = client.get('/healthz')
        assert rv.status_code == 503
    finally:
        p.stop()
