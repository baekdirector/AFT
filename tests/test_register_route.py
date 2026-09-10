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
        'admin_key': 'aft-kbss',
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
        'admin_key': 'aft-kbss',
    })

    rv = client.get('/')
    assert rv.status_code == 200
    assert '새로생긴항구' in rv.get_data(as_text=True)


def test_register_same_name_different_url_succeeds(client, app):
    """이름이 같아도 예약 URL이 다르면(실제로 다른 배) 등록이 성공해야 한다 -
    실측: "빅보스호"가 여수/화성 두 곳에 서로 다른 배로 존재해 name 단독
    유니크 제약(boats_name_key) 때문에 등록이 거절되던 버그. (register.html의
    인라인 <script>엔 실행되지 않는 정적 JS 에러 문구가 그대로 섞여 있어
    본문에서 '오류' 문자열을 찾는 건 못 믿는다 - 성공 시 /register 에 남지
    않고 홈으로 리다이렉트되는지, 그리고 실제 DB 상태로 확인한다.)"""
    client.post('/register', data={
        'csrf_token': _csrf_token(client, '/register'),
        'name': '동명이배호', 'url': 'https://example-a.sunsang24.com/ship/schedule_fleet',
        'city': '화성', 'port': '전곡항', 'note': '', 'admin_key': 'aft-kbss',
    })

    rv = client.post('/register', data={
        'csrf_token': _csrf_token(client, '/register'),
        'name': '동명이배호', 'url': 'https://example-b.sunsang24.com/ship/schedule_fleet',
        'city': '여수', 'port': '종포항', 'note': '', 'admin_key': 'aft-kbss',
    }, follow_redirects=True)

    assert rv.status_code == 200
    assert rv.request.path == '/'
    with app.app_context():
        from models import Boat
        matches = Boat.query.filter_by(name='동명이배호').all()
        assert len(matches) == 2


def test_register_same_url_twice_shows_friendly_message_not_raw_sql(client, app):
    """완전히 같은 URL로 두 번 등록하면(이름이 같든 다르든) 기존
    _find_duplicate_url_boat 사전 체크가 막는다 - 이 체크가 항상 DB INSERT보다
    먼저 실행되므로 실제로 raw SQL 예외까지 내려가는 경로는 IntegrityError를
    못 만나지만, 그래도 원본 SQL 문구가 새는 일이 없는지는 항상 보장돼야 한다
    (실측: name 단독 유니크 시절엔 이 사전 체크를 통과한 뒤 psycopg2 예외
    전문이 그대로 노출됐었다 - 지금은 애초에 여기서 막힌다)."""
    payload = {
        'name': '중복테스트호', 'url': 'https://example.com/dup',
        'city': '인천', 'port': '남항(인천항)', 'note': '', 'admin_key': 'aft-kbss',
    }
    client.post('/register', data=dict(payload, csrf_token=_csrf_token(client, '/register')))

    rv = client.post('/register', data=dict(payload, csrf_token=_csrf_token(client, '/register')),
                      follow_redirects=True)

    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert '이미 등록된 예약 URL입니다' in body
    assert 'psycopg2' not in body
    assert 'INSERT INTO' not in body


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
        'admin_key': 'aft-kbss',
    }, follow_redirects=True)

    assert rv.status_code == 200
    with app.app_context():
        from models import Boat
        boat = Boat.query.get(boat_id)
        assert boat.port == '다른새항구'
