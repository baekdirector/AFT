"""admin "내 낚시 기록" - 출조 기록 화면과 JSON API.

docs/superpowers/specs/2026-09-30-fishing-log-trips-design.md §2.4. views.py 가
이미 커서 따로 뺐다. 로그인은 기존 admin 세션(admin_authed)을 그대로 쓰고,
쓰기 요청은 기존 admin 액션과 같은 방식(X-CSRFToken 헤더)으로 막는다.
"""
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from services.fishing_log import trip_service
from services.fishing_log.trip_service import TripValidationError

fishing_views = Blueprint('fishing_views', __name__)


def _read_guard():
    if not session.get('admin_authed'):
        return jsonify({'error': '로그인이 필요합니다.'}), 403
    return None


def _write_guard():
    guard = _read_guard()
    if guard:
        return guard
    from flask_wtf.csrf import validate_csrf
    from wtforms.validators import ValidationError
    try:
        validate_csrf(request.headers.get('X-CSRFToken', ''))
    except ValidationError:
        return jsonify({'error': 'CSRF 토큰이 올바르지 않습니다. 새로고침 후 다시 시도해주세요.'}), 400
    return None


def _no_store(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def _validation_error(exc):
    return jsonify({'error': str(exc), 'field': exc.field}), 400


@fishing_views.route('/admin/fishing/trips')
def trips_page():
    if not session.get('admin_authed'):
        return redirect(url_for('views.admin_page'))
    from forms import AdminLoginForm
    return render_template('fishing_trips.html', active_menu='fishing_trips', form=AdminLoginForm())


@fishing_views.route('/admin/api/fishing/trips', methods=['GET'])
def list_trips_api():
    guard = _read_guard()
    if guard:
        return guard
    raw_year = request.args.get('year')
    today = trip_service.kst_today()
    if raw_year in (None, ''):
        year = today.year
    elif raw_year == 'all':
        year = None
    elif raw_year.isdigit():
        year = int(raw_year)
    else:
        return jsonify({'error': '연도가 올바르지 않습니다.', 'field': 'year'}), 400
    return _no_store(jsonify(trip_service.list_trips(year, today)))


@fishing_views.route('/admin/api/fishing/trips', methods=['POST'])
def create_trip_api():
    guard = _write_guard()
    if guard:
        return guard
    try:
        trip = trip_service.create_trip(request.get_json(silent=True) or {})
    except TripValidationError as exc:
        return _validation_error(exc)
    return jsonify({'trip': trip_service.serialize_trip(trip, trip_service.kst_today())}), 201


@fishing_views.route('/admin/api/fishing/trips/<int:trip_id>', methods=['GET'])
def get_trip_api(trip_id):
    guard = _read_guard()
    if guard:
        return guard
    trip = trip_service.get_trip(trip_id)
    if trip is None:
        return jsonify({'error': '출조 기록을 찾을 수 없습니다.'}), 404
    return _no_store(jsonify({'trip': trip_service.serialize_trip(trip, trip_service.kst_today())}))


@fishing_views.route('/admin/api/fishing/trips/<int:trip_id>', methods=['PUT'])
def update_trip_api(trip_id):
    guard = _write_guard()
    if guard:
        return guard
    trip = trip_service.get_trip(trip_id)
    if trip is None:
        return jsonify({'error': '출조 기록을 찾을 수 없습니다.'}), 404
    try:
        trip_service.update_trip(trip, request.get_json(silent=True) or {})
    except TripValidationError as exc:
        return _validation_error(exc)
    return jsonify({'trip': trip_service.serialize_trip(trip, trip_service.kst_today())})


@fishing_views.route('/admin/api/fishing/trips/<int:trip_id>', methods=['DELETE'])
def delete_trip_api(trip_id):
    guard = _write_guard()
    if guard:
        return guard
    trip = trip_service.get_trip(trip_id)
    if trip is None:
        return jsonify({'error': '출조 기록을 찾을 수 없습니다.'}), 404
    trip_service.delete_trip(trip)
    return jsonify({'deleted': trip_id})


@fishing_views.route('/admin/api/fishing/ships', methods=['GET'])
def search_ships_api():
    guard = _read_guard()
    if guard:
        return guard
    return _no_store(jsonify({'ships': trip_service.search_ships(request.args.get('q', ''))}))


# ---------------------------------------------------------------------------
# 선사 노트 - docs/superpowers/specs/2026-10-01-fishing-log-ships-design.md
# ---------------------------------------------------------------------------

@fishing_views.route('/admin/fishing/ships')
def ships_page():
    if not session.get('admin_authed'):
        return redirect(url_for('views.admin_page'))
    from forms import AdminLoginForm
    return render_template('fishing_ships.html', active_menu='fishing_ships', form=AdminLoginForm())


@fishing_views.route('/admin/api/fishing/ships/notes', methods=['GET'])
def ship_notes_api():
    guard = _read_guard()
    if guard:
        return guard
    from services.fishing_log import ship_service
    return _no_store(jsonify(ship_service.list_ship_notes(trip_service.kst_today())))


@fishing_views.route('/admin/api/fishing/ships/<int:ship_id>', methods=['GET'])
def ship_detail_api(ship_id):
    guard = _read_guard()
    if guard:
        return guard
    from services.fishing_log import ship_service
    ship = ship_service.get_ship(ship_id)
    if ship is None:
        return jsonify({'error': '선사를 찾을 수 없습니다.'}), 404
    return _no_store(jsonify({'ship': ship_service.ship_detail(ship, trip_service.kst_today())}))


@fishing_views.route('/admin/api/fishing/ships/<int:ship_id>', methods=['PUT'])
def update_ship_api(ship_id):
    guard = _write_guard()
    if guard:
        return guard
    from services.fishing_log import ship_service
    try:
        ship = ship_service.update_ship(ship_id, request.get_json(silent=True) or {}, trip_service.kst_today())
    except ship_service.ShipValidationError as exc:
        return _validation_error(exc)
    except ship_service.ShipNotFound:
        return jsonify({'error': '선사를 찾을 수 없습니다.'}), 404
    return jsonify({'ship': ship})


# ---------------------------------------------------------------------------
# 장비 구매 - docs/superpowers/specs/2026-10-01-fishing-log-gear-design.md
# ---------------------------------------------------------------------------

def _gear_error(exc):
    return jsonify({'error': str(exc), 'field': exc.field}), 400


def _year_arg(today):
    raw = request.args.get('year')
    if raw in (None, ''):
        return today.year, None
    if raw == 'all':
        return None, None
    if raw.isdigit():
        return int(raw), None
    return None, (jsonify({'error': '연도가 올바르지 않습니다.', 'field': 'year'}), 400)


@fishing_views.route('/admin/fishing/gear')
def gear_page():
    if not session.get('admin_authed'):
        return redirect(url_for('views.admin_page'))
    from forms import AdminLoginForm
    return render_template('gear.html', active_menu='fishing_gear', form=AdminLoginForm())


@fishing_views.route('/admin/api/fishing/gear', methods=['GET'])
def list_gear_api():
    guard = _read_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    today = trip_service.kst_today()
    year, error = _year_arg(today)
    if error:
        return error
    return _no_store(jsonify(gear_service.list_gear(year, today)))


@fishing_views.route('/admin/api/fishing/gear/orders', methods=['POST'])
def save_gear_order_api():
    guard = _write_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    try:
        order = gear_service.save_order(request.get_json(silent=True) or {})
    except gear_service.GearValidationError as exc:
        return _gear_error(exc)
    return jsonify({'order': order})


@fishing_views.route('/admin/api/fishing/gear/orders', methods=['DELETE'])
def delete_gear_order_api():
    guard = _write_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    data = request.get_json(silent=True) or {}
    try:
        deleted = gear_service.delete_order(data.get('date'), data.get('shop'))
    except gear_service.GearValidationError as exc:
        return _gear_error(exc)
    return jsonify({'deleted': deleted})


@fishing_views.route('/admin/api/fishing/gear/cleanup', methods=['GET'])
def gear_cleanup_api():
    guard = _read_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    return _no_store(jsonify({'suggestions': gear_service.cleanup_suggestions()}))


@fishing_views.route('/admin/api/fishing/gear/cleanup', methods=['POST'])
def apply_gear_cleanup_api():
    guard = _write_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    try:
        changed = gear_service.apply_cleanup(request.get_json(silent=True) or {})
    except gear_service.GearValidationError as exc:
        return _gear_error(exc)
    return jsonify({'changed': changed})


@fishing_views.route('/admin/api/fishing/gear/items', methods=['GET'])
def list_gear_items_api():
    guard = _read_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    return _no_store(jsonify({'items': gear_service.gear_items_summary()}))


@fishing_views.route('/admin/api/fishing/gear/items', methods=['POST'])
def create_gear_item_api():
    guard = _write_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    try:
        item = gear_service.save_gear_item(None, request.get_json(silent=True) or {})
    except gear_service.GearValidationError as exc:
        return _gear_error(exc)
    return jsonify({'item': item}), 201


@fishing_views.route('/admin/api/fishing/gear/items/<int:gear_id>', methods=['GET'])
def get_gear_item_api(gear_id):
    guard = _read_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    gear = gear_service.get_gear_item(gear_id)
    if gear is None:
        return jsonify({'error': '장비를 찾을 수 없습니다.'}), 404
    return _no_store(jsonify({'item': gear_service.gear_item_dict(gear)}))


@fishing_views.route('/admin/api/fishing/gear/items/<int:gear_id>', methods=['PUT'])
def update_gear_item_api(gear_id):
    guard = _write_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    try:
        item = gear_service.save_gear_item(gear_id, request.get_json(silent=True) or {})
    except gear_service.GearValidationError as exc:
        return _gear_error(exc)
    except gear_service.GearNotFound:
        return jsonify({'error': '장비를 찾을 수 없습니다.'}), 404
    return jsonify({'item': item})


@fishing_views.route('/admin/api/fishing/gear/items/<int:gear_id>', methods=['DELETE'])
def delete_gear_item_api(gear_id):
    guard = _write_guard()
    if guard:
        return guard
    from services.fishing_log import gear_service
    try:
        gear_service.delete_gear_item(gear_id)
    except gear_service.GearNotFound:
        return jsonify({'error': '장비를 찾을 수 없습니다.'}), 404
    return jsonify({'deleted': gear_id})
