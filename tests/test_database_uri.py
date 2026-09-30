"""DATABASE_URL 정규화 - SQLAlchemy 2.1부터 'postgresql://' 기본 드라이버가
psycopg(3)로 바뀌어 운영(psycopg2만 설치)에서 앱이 뜨지 못했다. 드라이버를 명시한다."""
from src.app import _database_uri


def test_postgres_scheme_gets_explicit_psycopg2_driver():
    assert _database_uri('postgres://u:p@h/db', '/x/boats.db') == 'postgresql+psycopg2://u:p@h/db'
    assert _database_uri('postgresql://u:p@h/db?sslmode=require', '/x/boats.db') == \
        'postgresql+psycopg2://u:p@h/db?sslmode=require'


def test_explicit_driver_is_kept():
    assert _database_uri('postgresql+psycopg2://u:p@h/db', '/x') == 'postgresql+psycopg2://u:p@h/db'


def test_missing_url_falls_back_to_sqlite():
    assert _database_uri(None, 'C:/repo/instance/boats.db') == 'sqlite:///C:/repo/instance/boats.db'
    assert _database_uri('', '/x/boats.db') == 'sqlite:////x/boats.db'
