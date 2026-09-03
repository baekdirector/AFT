"""
전역 500 처리 + Postgres 커넥션 풀 옵션 테스트.

배경: 알림을 늦게 확인해 Render/Neon 이 둘 다 잠들어 있는 사이, 첫 요청이 죽은
DB 커넥션을 재사용하며 500 이 났다. 그때 사용자가 본 것은 Render 의 기본 오류
페이지(설명 없는 영문 텍스트)뿐이었다. 다시 시도하라는 안내조차 없었다.
"""
from src.app import create_app


def test_unhandled_exception_renders_friendly_page():
    """예외가 나도 스택트레이스가 아니라 안내 페이지가 나가야 한다.

    TESTING=True 는 Flask 테스트 클라이언트가 예외를 그대로 다시 던지게 만들어
    errorhandler 를 건너뛴다(디버깅 편의 기능). 실제 운영 환경(Render)의
    동작을 보려면 꺼야 한다.
    """
    app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'TESTING': False})

    @app.route('/__boom')
    def _boom():
        raise RuntimeError('강제 오류')

    resp = app.test_client().get('/__boom')

    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert '일시적인 오류' in body
    assert '다시 시도' in body
    assert 'RuntimeError' not in body, '사용자에게 스택트레이스를 보여주면 안 된다'


def test_postgres_gets_pool_pre_ping_to_survive_cold_connections(monkeypatch):
    """Neon 은 유휴 커넥션을 서버 쪽에서 먼저 끊는다. pool_pre_ping 없이는
    죽은 커넥션을 재사용하려다 500 이 난다.

    create_app() 은 끝에서 db.create_all() 로 실제 연결을 시도하므로, 존재하지
    않는 postgres 호스트를 주면 그 연결 시도 자체가 예외를 낸다. 여기서
    확인하려는 것은 연결 성공 여부가 아니라 엔진 옵션이 설정되는지이므로,
    그 두 호출을 비활성화해 연결 시도 자체를 막는다.
    """
    import db as db_module
    monkeypatch.setattr(db_module.db, 'create_all', lambda: None)
    monkeypatch.setattr(db_module, 'initialize_shared_boats', lambda: None)

    app = create_app({
        'SQLALCHEMY_DATABASE_URI': 'postgresql://user:pass@host/db',
        'TESTING': False,
    })

    options = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})
    assert options.get('pool_pre_ping') is True
    assert options.get('pool_recycle')


def test_sqlite_does_not_need_pool_pre_ping():
    """SQLite 는 파일이라 이 문제와 무관하다. 굳이 켤 이유가 없다.

    Flask-SQLAlchemy 가 항상 기본값(빈 dict)을 채워두므로 키 자체는 있다.
    우리가 pool_pre_ping 을 강제로 켜지 않았는지만 본다.
    """
    app = create_app({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'TESTING': False})
    options = app.config.get('SQLALCHEMY_ENGINE_OPTIONS') or {}
    assert 'pool_pre_ping' not in options
