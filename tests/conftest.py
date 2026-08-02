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
        from src.db import db
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
    
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    """Flask 테스트 클라이언트"""
    return app.test_client()


@pytest.fixture
def runner(app):
    """CLI runner"""
    return app.test_cli_runner()
