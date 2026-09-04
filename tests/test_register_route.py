"""
배 등록/수정 화면의 "항구 직접 입력" 기능 테스트.

항구는 원래 Boat.port 가 자유 텍스트 컬럼이라 DB 제약은 없었지만, 폼이
CITY_PORT_MAPPING 에 있는 값만 select choices 로 강제해서 실제로는 목록에
없는 항구를 등록할 수 없었다. 이 제약을 풀고, 새로 등록된 항구가 다음
등록 화면의 선택지에도 나타나는지를 검증한다.
"""
import re


def _csrf_token(client, path):
    """FlaskForm 은 CSRFProtect 확장 없이도 자체적으로 csrf_token 을 검증하므로,
    폼이 있는 페이지를 먼저 GET 해서 세션에 묶인 토큰을 그대로 재사용해야 한다."""
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html)
    assert m, f'{path} 에서 csrf_token 을 찾지 못함'
    return m.group(1)


def test_register_accepts_port_not_in_city_port_mapping(client, app):
    """지역은 유효하지만 사전 등록되지 않은 항구도 등록이 성공해야 한다."""
    rv = client.post('/register', data={
        'csrf_token': _csrf_token(client, '/register'),
        'name': '테스트호',
        'url': 'https://example.com/ship',
        'city': '인천',
        'port': '새로생긴항구',
        'note': '',
    }, follow_redirects=True)

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        boat = Boat.query.filter_by(name='테스트호').one()
        assert boat.city == '인천'
        assert boat.port == '새로생긴항구'


def test_newly_registered_port_appears_on_home_page_for_future_registrations(client):
    """한 번 등록된 새 항구는 홈 화면의 city_port_map 에도 반영되어야 한다.

    별도 테이블 없이, 다음 등록 화면에서 바로 선택지로 나타나게 하는 방식이다.
    """
    client.post('/register', data={
        'csrf_token': _csrf_token(client, '/register'),
        'name': '테스트호2',
        'url': 'https://example.com/ship2',
        'city': '인천',
        'port': '새로생긴항구',
        'note': '',
    })

    rv = client.get('/')
    assert rv.status_code == 200
    assert '새로생긴항구' in rv.get_data(as_text=True)


def test_edit_also_accepts_port_not_in_city_port_mapping(client, app):
    from db import add_boat_instance
    with app.app_context():
        boat = add_boat_instance(
            name='수정대상호', url='https://example.com/x',
            city='인천', port='남항(인천항)', note='', is_shared=False)
        boat_id = boat.id

    rv = client.post(f'/edit/{boat_id}', data={
        'csrf_token': _csrf_token(client, f'/edit/{boat_id}'),
        'name': '수정대상호',
        'url': 'https://example.com/x',
        'city': '인천',
        'port': '다른새항구',
        'note': '',
    }, follow_redirects=True)

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        boat = Boat.query.get(boat_id)
        assert boat.port == '다른새항구'
