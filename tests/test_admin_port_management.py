# -*- coding: utf-8 -*-
"""관리자 콘솔 "항구 정보" 탭 + 그 밑을 받치는 `Port` DB 모델/시딩을 검증한다.

예전엔 항구(지역별 목록 + 위경도)가 config.CITY_PORT_MAPPING/PORT_COORDINATES
정적 dict에 박혀 있어, 항구 하나를 추가/삭제/수정하려면 코드를 고치고
배포해야 했다(2026-09-14, "돌산나루터" 삭제 요청 때 실제로 겪음 -
constants.py + register.html + edit_boat.html 세 곳을 손으로 고쳐야 했다).
이제 `models.Port` 표가 유일한 출처이고, 앱 시작 시 그 정적 dict를 1회만
옮겨 담는다(db.initialize_ports). 관리자 콘솔이 그 표를 코드 배포 없이
직접 CRUD 한다."""
import json
import re

from db import db


def _csrf_token(client, path):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html)
    assert m, f'{path} 에서 csrf_token 을 찾지 못함'
    return m.group(1)


def _login(client, monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'correct-horse')
    client.post('/admin', data={
        'csrf_token': _csrf_token(client, '/admin'),
        'username': 'admin', 'password': 'correct-horse',
    })


# ---- 시딩 (db.initialize_ports) ----

def test_initialize_ports_seeds_from_static_config(app):
    with app.app_context():
        from models import Port
        from config import CITY_PORT_MAPPING, PORT_COORDINATES

        total_seed_ports = sum(len(v) for v in CITY_PORT_MAPPING.values())
        assert Port.query.count() == total_seed_ports

        row = Port.query.filter_by(name='남항(인천항)').one()
        assert row.region == '인천'
        assert row.lat == PORT_COORDINATES['남항(인천항)']['lat']
        assert row.lon == PORT_COORDINATES['남항(인천항)']['lon']


def test_initialize_ports_runs_only_once(app):
    with app.app_context():
        from models import Port
        from db import initialize_ports

        before = Port.query.count()
        # 이미 시딩된 뒤(앱 생성 시 1회 실행됨) 다시 불러도 중복 추가되지 않는다
        initialize_ports()
        assert Port.query.count() == before


def test_port_data_service_reflects_db_not_static_dict(app):
    """PortDataService가 Port 표를 읽는지 - 시딩 이후 정적 dict를 직접
    고쳐도 반영되지 않고(이미 DB로 옮겨졌으므로), DB에 새 행을 추가하면
    바로 반영돼야 한다."""
    with app.app_context():
        from models import Port
        from services.weather_tide_service import PortDataService

        db.session.add(Port(region='테스트지역', name='테스트항구', lat=36.0, lon=127.0))
        db.session.commit()

        mapping = PortDataService.get_city_port_mapping()
        coords = PortDataService.get_port_coordinates()
        assert '테스트항구' in mapping.get('테스트지역', [])
        assert coords['테스트항구'] == {'lat': 36.0, 'lon': 127.0}


# ---- delete_ports: 사용 중인 항구는 건너뛴다 ----

def test_delete_ports_skips_ports_with_registered_boats(app):
    with app.app_context():
        from models import Port, Boat
        from db import delete_ports

        # boat_list.xlsx로 시딩된 실제 항구(비응항 등)는 이미 배가 여러 척
        # 있을 수 있어 "사용 중 0척"을 전제로 삼을 수 없다 - 격리된 테스트
        # 전용 항구를 새로 만든다.
        port = Port(region='테스트', name='테스트항구A', lat=36.0, lon=127.0)
        db.session.add(port)
        db.session.commit()
        db.session.add(Boat(name='군산테스트호', url='https://example.com/gunsan', city='군산', port='테스트항구A'))
        db.session.commit()

        result = delete_ports([port.id])

        assert result['deleted'] == []
        assert result['skipped'][0]['name'] == '테스트항구A'
        assert result['skipped'][0]['ship_count'] == 1
        assert Port.query.get(port.id) is not None  # 안 지워졌어야 함


def test_delete_ports_removes_unused_port(app):
    with app.app_context():
        from models import Port
        from db import delete_ports

        port = Port(region='테스트', name='테스트항구B', lat=36.0, lon=127.0)
        db.session.add(port)
        db.session.commit()

        result = delete_ports([port.id])

        assert result['deleted'] == [{'id': port.id, 'name': '테스트항구B'}]
        assert result['skipped'] == []
        assert Port.query.get(port.id) is None


# ---- HTTP: POST /admin/ports (추가) ----

def test_create_port_route_requires_admin_login(client):
    rv = client.post('/admin/ports', json={'region': '테스트', 'name': '새항구', 'lat': 36, 'lon': 127})
    assert rv.status_code == 403


def test_create_port_route_adds_port_and_is_visible_on_register_page(client, monkeypatch):
    _login(client, monkeypatch)
    csrf = _csrf_token(client, '/admin')

    rv = client.post('/admin/ports', json={'region': '테스트지역', 'name': '새로운항구', 'lat': 36.5, 'lon': 127.5},
                     headers={'X-CSRFToken': csrf})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body['name'] == '새로운항구'
    assert body['ship_count'] == 0

    # 코드 배포 없이 등록 화면 선택지에도 바로 반영돼야 한다(오늘 겪은 문제의
    # 핵심 검증 포인트). tojson이 유니코드를 \uXXXX로 이스케이프하므로 원문
    # 부분문자열 검사 대신 실제로 JSON을 파싱해서 확인한다(브라우저가 하는
    # 것과 동일).
    register_html = client.get('/register').get_data(as_text=True)
    m = re.search(r'const cityPortMapping = (.+?);', register_html)
    assert m, 'register.html에서 cityPortMapping을 찾지 못함'
    mapping = json.loads(m.group(1))
    assert '새로운항구' in mapping.get('테스트지역', [])


def test_create_port_route_rejects_invalid_coordinates(client, monkeypatch):
    _login(client, monkeypatch)
    csrf = _csrf_token(client, '/admin')

    rv = client.post('/admin/ports', json={'region': '테스트', 'name': '이상한항구', 'lat': 10, 'lon': 127},
                     headers={'X-CSRFToken': csrf})
    assert rv.status_code == 400


def test_create_port_route_rejects_duplicate_name(client, monkeypatch):
    _login(client, monkeypatch)
    csrf = _csrf_token(client, '/admin')

    rv = client.post('/admin/ports', json={'region': '인천', 'name': '남항(인천항)', 'lat': 37.47, 'lon': 126.62},
                     headers={'X-CSRFToken': csrf})
    assert rv.status_code == 409


# ---- HTTP: POST /admin/ports/<id> (수정) ----

def test_update_port_route_saves_new_values(client, app, monkeypatch):
    _login(client, monkeypatch)
    with app.app_context():
        from models import Port
        port_id = Port.query.filter_by(name='격포항').one().id

    csrf = _csrf_token(client, '/admin')
    rv = client.post(f'/admin/ports/{port_id}', json={'name': '격포항(수정)', 'lat': 35.7, 'lon': 126.5},
                     headers={'X-CSRFToken': csrf})
    assert rv.status_code == 200

    with app.app_context():
        from models import Port
        row = Port.query.get(port_id)
        assert row.name == '격포항(수정)'
        assert row.lat == 35.7


# ---- HTTP: POST /admin/ports/delete (삭제, 개별/일괄 공용) ----

def test_delete_ports_route_reports_skipped_in_use_ports(client, app, monkeypatch):
    _login(client, monkeypatch)
    with app.app_context():
        from models import Port, Boat
        port = Port.query.filter_by(name='야미도항').one()
        db.session.add(Boat(name='야미도테스트호', url='https://example.com/yamido', city='군산', port='야미도항'))
        db.session.commit()
        port_id = port.id

    csrf = _csrf_token(client, '/admin')
    rv = client.post('/admin/ports/delete', json={'port_ids': [port_id]}, headers={'X-CSRFToken': csrf})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body['deleted'] == []
    assert body['skipped'][0]['name'] == '야미도항'


def test_dashboard_data_route_requires_admin_login(client):
    """관리자 콘솔의 실제 데이터(/admin/dashboard_data)는 /admin 뼈대와
    분리돼 있다(로그인 후 화면 이동이 느리다는 지적을 받아 무거운 계산을
    여기로 옮겼다) - 이 라우트도 세션 인증 없인 막혀야 한다."""
    rv = client.get('/admin/dashboard_data')
    assert rv.status_code == 403


def test_admin_page_shell_renders_without_touching_port_or_boat_data(client, monkeypatch):
    """/admin(로그인 후)은 이제 탭 뼈대만 내려주고 항구/배 데이터를 전혀
    조회하지 않는다 - 실제 데이터는 /admin/dashboard_data 가 따로 담당한다.
    뼈대 자체가 빠르다는 것을 "항구 정보 관련 숫자가 아직 없다"로 간접
    확인한다(항구가 31개 시딩돼 있어도 뼈대엔 그 개수가 안 박혀 있어야
    한다 - 있었다면 여전히 서버가 그 시점에 Port 표를 읽었다는 뜻)."""
    _login(client, monkeypatch)
    shell_html = client.get('/admin').get_data(as_text=True)
    assert '항구 정보' in shell_html
    assert 'id="ports-tab-count">…<' in shell_html  # 서버가 채운 숫자가 아니라 로딩 placeholder


def test_admin_page_lists_ports_with_ship_counts(client, app, monkeypatch):
    _login(client, monkeypatch)
    with app.app_context():
        from models import Boat
        db.session.add(Boat(name='인천테스트호', url='https://example.com/incheon', city='인천', port='연안부두'))
        db.session.commit()

    shell_html = client.get('/admin').get_data(as_text=True)
    assert '항구 정보' in shell_html  # 뼈대는 즉시 뜬다(탭 이름은 데이터 없이도 보임)

    rv = client.get('/admin/dashboard_data')
    body = rv.get_json()
    assert rv.status_code == 200
    ports_by_name = {p['name']: p for p in body['data']['ports']}
    assert '연안부두' in ports_by_name
    assert ports_by_name['연안부두']['ship_count'] == 1
