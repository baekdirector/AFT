from flask import Flask
import webbrowser
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from db import db

def create_app(test_config=None):
    app = Flask(__name__, static_folder='../img', static_url_path='/img')
    os.makedirs(app.instance_path, exist_ok=True)

    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)

    sqlite_path = os.path.join(app.instance_path, 'boats.db').replace('\\', '/')
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url or f'sqlite:///{sqlite_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change_this_in_production')
    app.config['DEBUG_LOGGING_ENABLED'] = False
    # /api/status 의 배별 동시 조회 스레드 수.
    #
    # 라이브 실측(2026-09, Render 무료 인스턴스 0.1 CPU / 71척):
    #     동시요청   워커24    워커4
    #       1척       6.9s      -
    #       8척      22.5s    10.6s
    #      24척      67.8s      -
    #      71척     122.7s     105s
    # 처리량이 동시성 8 이상에서 약 0.35척/초로 포화되고, 워커 4 일 때의
    # 0.68~0.75척/초보다 오히려 나쁘다. IO 대기가 아니라 0.1 CPU 위에서의
    # 파싱 CPU/GIL 경합이 병목이라, 스레드를 늘리면 손해다. 그래서 4 를 유지한다.
    #
    # 잘림(71척 중 19척만 오던 증상)의 실제 원인은 동시성이 아니라 gunicorn
    # 기본 --timeout 30 이었다. 그건 Procfile / Render Start Command 에서 해결했다.
    #
    # 근본 해결은 이 값을 키우는 게 아니라 Phase B(스냅샷) + D(스케줄러)로
    # 요청 경로에서 라이브 스크래핑을 없애는 것이다. 이건 그때까지의 가교다.
    # 튜닝은 재배포 없이 환경변수로 한다.
    try:
        app.config['STATUS_MAX_WORKERS'] = max(1, int(os.environ.get('STATUS_MAX_WORKERS', 4)))
    except (TypeError, ValueError):
        app.config['STATUS_MAX_WORKERS'] = 4

    if test_config is not None:
        app.config.from_mapping(test_config)

    db.init_app(app)

    from routes.views import views
    app.register_blueprint(views, url_prefix='')

    import models

    with app.app_context():
        db.create_all()
        from db import initialize_shared_boats
        initialize_shared_boats()

    return app

if __name__ == '__main__':
    app = create_app()
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        webbrowser.open('http://127.0.0.1:5000')
    app.run(host='127.0.0.1', port=5000, debug=True)
