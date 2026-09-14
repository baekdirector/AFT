import os

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

db = SQLAlchemy()


def ensure_boat_shared_column():
    if not db.engine:
        return

    inspector = inspect(db.engine)
    columns = {column['name'] for column in inspector.get_columns('boats')}
    if 'is_shared' in columns:
        return

    db.session.execute(text('ALTER TABLE boats ADD COLUMN is_shared BOOLEAN'))
    db.session.commit()


def ensure_boat_name_unique_constraint():
    """boats.name 단독 유니크 제약을 name+url 복합 제약으로 옮긴다.

    이 프로젝트엔 Alembic 같은 정식 마이그레이션 도구가 없어(create_all()이
    새 테이블만 만들고 기존 테이블의 제약은 안 바꾼다) ensure_boat_shared_column()
    과 같은 패턴으로 시작할 때마다 직접 점검한다. name 단독 유니크는 실제로
    다른 두 배가 우연히 같은 이름("빅보스호")을 쓰는 경우를 막아버렸다 -
    운영 DB(Postgres)에서만 의미가 있고, SQLite(로컬/테스트)는 매번 새로
    create_all() 되므로 모델 정의(__table_args__)가 곧바로 적용돼 손댈 게 없다.
    """
    if not db.engine or db.engine.dialect.name != 'postgresql':
        return

    inspector = inspect(db.engine)
    if 'boats' not in inspector.get_table_names():
        return

    constraints = inspector.get_unique_constraints('boats')
    has_name_only = any(set(c['column_names']) == {'name'} for c in constraints)
    has_name_url = any(set(c['column_names']) == {'name', 'url'} for c in constraints)

    # gunicorn이 워커 2개를 fork해서 각자 앱 시작 시 이 함수를 독립적으로
    # 부른다 - 거의 동시에 같은 ALTER를 두 번 시도할 수 있다. 목표 상태(복합
    # 제약만 존재)에 도달하는 게 중요하지 "내가 직접 바꿨는지"가 아니므로,
    # 다른 워커가 먼저 끝내서 대상이 이미 없어졌거나/이미 있어도 조용히
    # 넘어간다 - 그 외의 진짜 오류만 다시 던진다.
    if has_name_only:
        name_only = next(c for c in constraints if set(c['column_names']) == {'name'})
        try:
            db.session.execute(text(f'ALTER TABLE boats DROP CONSTRAINT "{name_only["name"]}"'))
            db.session.commit()
        except Exception:
            db.session.rollback()
            still_there = any(
                set(c['column_names']) == {'name'}
                for c in inspect(db.engine).get_unique_constraints('boats')
            )
            if still_there:
                raise  # 다른 워커의 경쟁이 아니라 진짜 실패

    if not has_name_url:
        try:
            db.session.execute(text(
                'ALTER TABLE boats ADD CONSTRAINT uq_boats_name_url UNIQUE (name, url)'
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            still_missing = not any(
                set(c['column_names']) == {'name', 'url'}
                for c in inspect(db.engine).get_unique_constraints('boats')
            )
            if still_missing:
                raise  # 다른 워커의 경쟁이 아니라 진짜 실패


def _load_shared_boats_from_excel():
    from openpyxl import load_workbook

    excel_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'boat_list.xlsx'))
    if not os.path.exists(excel_path):
        return []

    try:
        workbook = load_workbook(excel_path, data_only=True)
    except Exception:
        return []

    worksheet = workbook.active
    boats = []
    for row in worksheet.iter_rows(min_row=2, values_only=True):
        if not row or len(row) < 5:
            continue

        city = row[1]
        port = row[2]
        name = row[3]
        url = row[4]
        note = row[5] if len(row) > 5 else None

        if isinstance(city, str):
            city = city.strip()
        if isinstance(port, str):
            port = port.strip()
        if isinstance(name, str):
            name = name.strip()
        if isinstance(url, str):
            url = url.strip()
        if isinstance(note, str):
            note = note.strip()

        if not name or not url:
            continue

        boats.append({
            'name': name,
            'url': url,
            'city': city or '',
            'port': port or '',
            'note': note or '초기 공용 데이터',
        })

    return boats


def _get_app_setting(key: str):
    from models import AppSetting
    setting = AppSetting.query.get(key)
    return setting.value if setting else None


def _set_app_setting(key: str, value: str):
    from models import AppSetting
    setting = AppSetting.query.get(key)
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=key, value=value)
        db.session.add(setting)
    db.session.commit()


def initialize_ports():
    """`Port` 표(models.Port)를 config.CITY_PORT_MAPPING × PORT_COORDINATES로
    1회만 채운다(initialize_shared_boats()와 같은 AppSetting 플래그 패턴).
    이 정적 dict는 이제 "초기 시드 데이터"로만 쓰이고, 시딩이 끝나면 앱의
    모든 조회는 이 표를 거친다(PortDataService 참고) - 이후 항구 추가·수정·
    삭제는 관리자 콘솔에서 코드 배포 없이 이 표에 직접 한다.

    예전에 쓰던 PortCoordinate 표(정적 dict에 없는 새 항구의 좌표만 담던
    오버레이 표)에 남은 행이 있으면 같이 옮겨 담는다 - 지역을 모르니
    region=''으로 들어가고, 관리자가 나중에 채워 넣으면 된다."""
    from models import Port
    from config import CITY_PORT_MAPPING, PORT_COORDINATES

    if _get_app_setting('ports_initialized') == 'true':
        return

    for region, port_names in CITY_PORT_MAPPING.items():
        for name in port_names:
            coords = PORT_COORDINATES.get(name)
            if not coords:
                continue
            if Port.query.filter_by(name=name).first():
                continue
            db.session.add(Port(region=region, name=name, lat=coords['lat'], lon=coords['lon']))

    inspector = inspect(db.engine)
    if 'port_coordinates' in inspector.get_table_names():
        legacy_rows = db.session.execute(text('SELECT port, lat, lon FROM port_coordinates')).fetchall()
        for row in legacy_rows:
            if Port.query.filter_by(name=row.port).first():
                continue
            db.session.add(Port(region='', name=row.port, lat=row.lat, lon=row.lon))

    db.session.commit()
    _set_app_setting('ports_initialized', 'true')


def create_port(region: str, name: str, lat: float, lon: float):
    from models import Port
    port = Port(region=region, name=name, lat=lat, lon=lon)
    db.session.add(port)
    try:
        db.session.commit()
        return port
    except Exception:
        db.session.rollback()
        raise


def update_port(port_id: int, name: str, lat: float, lon: float):
    from models import Port
    port = Port.query.get(port_id)
    if not port:
        raise ValueError('항구를 찾을 수 없습니다.')
    port.name = name
    port.lat = lat
    port.lon = lon
    try:
        db.session.commit()
        return port
    except Exception:
        db.session.rollback()
        raise


def delete_ports(port_ids):
    """체크된 항구를 지운다. 그 항구를 쓰는 배가 하나라도 있으면(사용자 결정 -
    배 데이터는 절대 안 건드린다) 그 항구는 건너뛰고 skipped에 담아 돌려준다."""
    from models import Port, Boat
    deleted, skipped = [], []
    for port_id in port_ids:
        port = Port.query.get(port_id)
        if not port:
            continue
        ship_count = Boat.query.filter_by(port=port.name).count()
        if ship_count > 0:
            skipped.append({'id': port.id, 'name': port.name, 'ship_count': ship_count})
            continue
        deleted.append({'id': port.id, 'name': port.name})
        db.session.delete(port)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {'deleted': deleted, 'skipped': skipped}


def initialize_shared_boats():
    from models import Boat

    ensure_boat_shared_column()
    ensure_boat_name_unique_constraint()

    if _get_app_setting('shared_boats_initialized') == 'true':
        return

    shared_boats = _load_shared_boats_from_excel()
    if not shared_boats:
        shared_boats = [
            {
                'name': '팀만수',
                'url': 'https://teammansu.kr/index.php?mid=bk',
                'city': '인천',
                'port': '남항(인천항)',
                'note': '초기 공용 데이터',
            },
            {
                'name': '레드헌터',
                'url': 'https://redhunter.sunsang24.com/ship/schedule_fleet',
                'city': '인천',
                'port': '연안부두',
                'note': '초기 공용 데이터',
            },
            {
                'name': '힐링피싱',
                'url': 'https://hl.sunsang24.com/ship/schedule_fleet/202607',
                'city': '안산',
                'port': '오이도항',
                'note': '초기 공용 데이터',
            },
        ]

    for boat_data in shared_boats:
        existing_boat = Boat.query.filter_by(name=boat_data['name']).first()
        if existing_boat:
            existing_boat.url = boat_data['url']
            existing_boat.city = boat_data['city']
            existing_boat.port = boat_data['port']
            existing_boat.note = boat_data['note']
            existing_boat.is_shared = True
            continue

        boat = Boat(
            name=boat_data['name'],
            url=boat_data['url'],
            city=boat_data['city'],
            port=boat_data['port'],
            note=boat_data['note'],
            is_shared=True,
        )
        db.session.add(boat)

    db.session.commit()
    _set_app_setting('shared_boats_initialized', 'true')


def add_boat_instance(name: str, url: str, city: str, port: str, note: str = None, is_shared: bool = True):
    from models import Boat
    boat = Boat(name=name, url=url, city=city, port=port, note=note, is_shared=is_shared)
    db.session.add(boat)
    try:
        db.session.commit()
        return boat
    except Exception:
        db.session.rollback()
        raise

def get_all_boats():
    from models import Boat
    return Boat.query.order_by(Boat.id).all()

def get_boat_by_id(boat_id: int):
    from models import Boat
    return Boat.query.get(boat_id)

# 추가: 배 삭제 함수
def delete_boat(boat_id: int):
    from models import Boat
    boat = Boat.query.get(boat_id)
    if not boat:
        raise ValueError("등록된 배를 찾을 수 없습니다.")
    db.session.delete(boat)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

def update_boat(boat_id: int, name: str, url: str, city: str, port: str, note: str = None):
    from models import Boat
    boat = Boat.query.get(boat_id)
    if not boat:
        raise ValueError("등록된 배를 찾을 수 없습니다.")
    boat.name = name
    boat.url = url
    boat.city = city
    boat.port = port
    boat.note = note
    try:
        db.session.commit()
        return boat
    except Exception:
        db.session.rollback()
        raise

def upsert_port_coordinate(port: str, lat, lon, city: str = None):
    """배 등록/수정 화면에서 목록에 없는 항구를 직접 입력하며 위경도까지
    선택 입력했을 때만 호출된다. 이미 `Port` 표에 있는 항구(관리자가 큐레이션
    했거나 앞서 등록된 값)는 조용히 무시한다 - 사용자 오타가 그 값을
    덮어쓰지 않게 하기 위함. 새 항구면 `city`(배 등록 폼의 지역 선택값)를
    region으로 그대로 써서 Port 표에 만든다 - 그래야 관리자 콘솔 "항구 정보"
    탭에도 바로 나타난다."""
    from models import Port
    if lat is None or lon is None:
        return
    if Port.query.filter_by(name=port).first():
        return
    db.session.add(Port(region=city or '', name=port, lat=lat, lon=lon))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise