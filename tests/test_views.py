"""
일반 라우트 테스트.
"""


def test_healthz_returns_ok_without_auth_or_db(client):
    """GitHub Actions keep-alive 핑이 매 10분마다 치는 엔드포인트다.

    인증도 없고 DB 도 안 건드려야 한다 - 부하 없이 '떠있다'만 확인하는 용도다.
    """
    rv = client.get('/healthz')

    assert rv.status_code == 200
    assert rv.get_data(as_text=True) == 'ok'
