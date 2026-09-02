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
    # 실측(2026-09, Render): 배당 지연이 약 6.6초이고 이 작업은 CPU 가 아니라
    # IO 대기가 지배적이라 스레드 수에 거의 선형으로 개선된다.
    # 71척 기준 대략 71*6.6/N 초. N=4 -> 117초(잘림), N=16 -> 29초, N=24 -> 20초.
    # gunicorn --timeout 을 함께 올리지 않으면 N 을 키워도 잘린다(둘 다 필요).
    # 문제가 생기면 환경변수로 즉시 되돌릴 수 있게 해 둔다.
    try:
        app.config['STATUS_MAX_WORKERS'] = max(1, int(os.environ.get('STATUS_MAX_WORKERS', 24)))
    except (TypeError, ValueError):
        app.config['STATUS_MAX_WORKERS'] = 24

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
