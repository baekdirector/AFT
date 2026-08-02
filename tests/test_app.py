import pytest
from src.app import create_app
from db import db as _db
from db import initialize_shared_boats
from models import Boat

@pytest.fixture
def app(tmp_path):
    app = create_app({
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'TESTING': True,
    })
    with app.app_context():
        _db.drop_all()
        _db.create_all()
    yield app

@pytest.fixture
def client(app):
    return app.test_client()

def test_index(client):
    rv = client.get('/')
    assert rv.status_code == 200


def test_existing_boats_are_treated_as_initial_shared_data(app):
    with app.app_context():
        boat = Boat(name='팀만수호', url='https://example.com', city='인천', port='남항(인천항)', note='seed', is_shared=None)
        _db.session.add(boat)
        _db.session.commit()

        initialize_shared_boats()

        refreshed = Boat.query.get(boat.id)
        assert refreshed.is_shared is True


def test_initialize_shared_boats_seed_default_data_when_db_is_empty(app):
    with app.app_context():
        _db.session.query(Boat).delete()
        _db.session.commit()

        initialize_shared_boats()

        boats = Boat.query.order_by(Boat.id).all()
        assert len(boats) >= 1
        assert all(boat.is_shared is True for boat in boats)


def test_initialize_shared_boats_runs_only_once(app):
    with app.app_context():
        _db.session.query(Boat).delete()
        _db.session.commit()

        initialize_shared_boats()
        first_count = Boat.query.count()

        initialize_shared_boats()
        second_count = Boat.query.count()

        assert first_count == second_count

# To run the application, use the following commands:
# cd C:\Workspace\python_ship\fishing-boat-reservation-app
# python -m venv .venv
# .\.venv\Scripts\Activate.ps1
# python -m pip install --upgrade pip
# python -m pip install -r requirements.txt
# cd src
# python app.py
# Then open a browser and go to: http://127.0.0.1:5000