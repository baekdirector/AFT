"""
배 등록/삭제 확인 문자(admin_key) 게이트 테스트.

URL만 알면 누구나 배 목록을 지우거나 등록할 수 있는 구조라(로그인 없음),
등록/삭제 요청에 정해진 확인 문자(BOAT_ADMIN_KEY)가 같이 와야만 처리되게
막았다(사용자 결정). 강한 보안이 아니라 실수/장난을 막는 최소한의 마찰이다.
"""
import re

from routes.views import BOAT_ADMIN_KEY


def _csrf_token(client, path):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html)
    assert m, f'{path} 에서 csrf_token 을 찾지 못함'
    return m.group(1)


def test_register_without_admin_key_is_rejected(client, app):
    rv = client.post('/register', data={
        'csrf_token': _csrf_token(client, '/register'),
        'name': '무단등록호',
        'url': 'https://example.com/ship',
        'city': '인천',
        'port': '남항(인천항)',
        'note': '',
    }, follow_redirects=True)

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        assert Boat.query.filter_by(name='무단등록호').one_or_none() is None


def test_register_with_wrong_admin_key_is_rejected(client, app):
    rv = client.post('/register', data={
        'csrf_token': _csrf_token(client, '/register'),
        'name': '틀린키등록호',
        'url': 'https://example.com/ship',
        'city': '인천',
        'port': '남항(인천항)',
        'note': '',
        'admin_key': 'not-the-key',
    }, follow_redirects=True)

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        assert Boat.query.filter_by(name='틀린키등록호').one_or_none() is None


def test_register_with_correct_admin_key_succeeds(client, app):
    rv = client.post('/register', data={
        'csrf_token': _csrf_token(client, '/register'),
        'name': '정상키등록호',
        'url': 'https://example.com/ship',
        'city': '인천',
        'port': '남항(인천항)',
        'note': '',
        'admin_key': BOAT_ADMIN_KEY,
    }, follow_redirects=True)

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        assert Boat.query.filter_by(name='정상키등록호').one_or_none() is not None


def test_delete_boats_without_admin_key_leaves_boat_intact(client, app):
    from db import add_boat_instance
    with app.app_context():
        boat = add_boat_instance(name='삭제대상호', url='https://example.com/x',
                                 city='인천', port='남항(인천항)', note='', is_shared=False)
        boat_id = boat.id

    rv = client.post('/delete_boats', data={'delete_ids': [str(boat_id)]},
                     follow_redirects=True)

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        assert Boat.query.get(boat_id) is not None


def test_delete_boats_with_correct_admin_key_removes_boat(client, app):
    from db import add_boat_instance
    with app.app_context():
        boat = add_boat_instance(name='정상삭제호', url='https://example.com/x',
                                 city='인천', port='남항(인천항)', note='', is_shared=False)
        boat_id = boat.id

    rv = client.post('/delete_boats', data={
        'delete_ids': [str(boat_id)],
        'admin_key': BOAT_ADMIN_KEY,
    }, follow_redirects=True)

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        assert Boat.query.get(boat_id) is None


def test_single_delete_without_admin_key_leaves_boat_intact(client, app):
    from db import add_boat_instance
    with app.app_context():
        boat = add_boat_instance(name='단건삭제대상호', url='https://example.com/x',
                                 city='인천', port='남항(인천항)', note='', is_shared=False)
        boat_id = boat.id

    rv = client.post(f'/delete/{boat_id}', follow_redirects=True)

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        assert Boat.query.get(boat_id) is not None


def test_api_add_ship_without_admin_key_is_rejected(client, app):
    rv = client.post('/api/ships', json={
        'region': '인천', 'port': '남항(인천항)',
        'registrationNumber': 'API무단등록호', 'url': 'https://example.com/api-ship',
    })

    assert rv.status_code == 403
    with app.app_context():
        from models import Boat
        assert Boat.query.filter_by(name='API무단등록호').one_or_none() is None


def test_api_add_ship_with_correct_admin_key_succeeds(client, app):
    rv = client.post('/api/ships', json={
        'region': '인천', 'port': '남항(인천항)',
        'registrationNumber': 'API정상등록호', 'url': 'https://example.com/api-ship2',
        'admin_key': BOAT_ADMIN_KEY,
    })

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        assert Boat.query.filter_by(name='API정상등록호').one_or_none() is not None
