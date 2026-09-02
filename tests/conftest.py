"""
Pytest 설정 및 공유 fixture
"""
import pytest
import os
import sys
import tempfile
from pathlib import Path

# 프로젝트 src 디렉토리를 Python path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / 'src'
sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def app():
    """테스트용 Flask 앱 인스턴스 생성"""
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['TESTING'] = 'true'
    
    # 임시 DB 사용
    db_fd, db_path = tempfile.mkstemp()
    
    from src.app import create_app
    app = create_app({
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'TESTING': True,
    })
    
    with app.app_context():
        # NOTE: 반드시 'db'로 import 한다. 'src.db'로 import 하면
        # src/app.py 의 'from db import db' 와 서로 다른 모듈 객체가 되어
        # SQLAlchemy 인스턴스가 2개로 갈리고 create_all() 이 RuntimeError 를 낸다.
        from db import db
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        # Windows 에서는 엔진이 sqlite 파일 핸들을 잡고 있으면 unlink 가 WinError 32 로 실패한다.
        db.engine.dispose()

    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def client(app):
    """Flask 테스트 클라이언트"""
    return app.test_client()


@pytest.fixture
def runner(app):
    """CLI runner"""
    return app.test_cli_runner()
