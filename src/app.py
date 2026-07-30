from flask import Flask
import webbrowser
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from db import db

def create_app():
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
