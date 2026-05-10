from flask import Flask
import webbrowser
import os

from db import db

def create_app():
    app = Flask(__name__, static_folder='../img', static_url_path='/img')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///boats.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'change_this_in_production'
    app.config['DEBUG_LOGGING_ENABLED'] = False

    db.init_app(app)

    from routes.views import views
    app.register_blueprint(views, url_prefix='')

    import models

    with app.app_context():
        db.create_all()

    return app

if __name__ == '__main__':
    app = create_app()
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        webbrowser.open('http://127.0.0.1:5000')
    app.run(host='127.0.0.1', port=5000, debug=True)
