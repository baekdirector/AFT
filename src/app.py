from flask import Flask, render_template
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

    # Neon 은 유휴 커넥션을 서버 쪽에서 먼저 끊는다(자동 절전/유휴 타임아웃).
    # SQLAlchemy 커넥션 풀은 그 사실을 모른 채 죽은 커넥션을 재사용하려다 500 을
    # 낸다. 실측(2026-09): 오래 방치된 뒤의 첫 GET /status 가 그렇게 죽었다.
    # pool_pre_ping 이 커넥션을 쓰기 전에 가벼운 핑으로 살아있는지 확인하고,
    # 죽었으면 조용히 재연결한다. pool_recycle 은 Neon 이 끊기 전에 앱이 먼저
    # 갱신하게 한다. test_config 가 최종 URI 를 바꿀 수 있으므로, 이 판단은
    # test_config 반영 이후 실제 설정된 URI 를 보고 한다(env var 만 보면 테스트가
    # SQLALCHEMY_DATABASE_URI 를 직접 주는 경우를 놓친다).
    final_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if final_uri.startswith('postgres'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_pre_ping': True,
            'pool_recycle': 280,
        }

    db.init_app(app)

    from routes.views import views
    app.register_blueprint(views, url_prefix='')

    from routes.watch_views import watch_views
    app.register_blueprint(watch_views, url_prefix='')

    import models

    @app.errorhandler(500)
    def _friendly_500(exc):
        # 원인 불문 전부 여기로 온다. 알림 링크를 눌렀을 때 Render 의 기본
        # 오류 페이지(설명 없는 영문 텍스트)만 보이는 것보다, 다시 시도하라는
        # 안내와 조회 화면으로 가는 버튼을 주는 편이 낫다. 실제 원인은 로그에
        # 남기되 사용자에게는 스택트레이스를 보여주지 않는다.
        app.logger.error('처리되지 않은 오류: %s', exc, exc_info=exc)
        try:
            return render_template('error500.html'), 500
        except Exception:
            # 템플릿 렌더링 자체가 실패하는 최악의 경우를 위한 마지막 방어선
            return '일시적인 오류입니다. 잠시 후 다시 시도해주세요.', 500

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
