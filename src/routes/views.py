import io
import openpyxl
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, Response
from flask import send_from_directory
from forms import BoatRegistrationForm, StatusCheckForm, BoatEditForm
from db import add_boat_instance, get_all_boats, delete_boat, get_boat_by_id, update_boat
from services.reservation_checker import check_single_boat
from forms import REGION_CHOICES
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

views = Blueprint('views', __name__, template_folder='templates')

@views.route('/')
def index():
    boats = get_all_boats()
    # Boat 객체들을 딕셔너리로 변환하여 JSON 직렬화 가능하게 만듭니다
    boats_dict = [boat.to_dict() for boat in boats]

    # 홈 모달 등록 폼에서 CSRF 를 사용하기 위해 폼 인스턴스를 전달
    form = BoatRegistrationForm()

    return render_template(
        'index.html',
        boats=boats,
        boats_json=boats_dict,
        form=form,
        city_port_map=city_port_mapping
    )

@views.route('/download_excel')
def download_excel():
    boats = get_all_boats()
    
    # Create a new workbook and select the active worksheet
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Registered Boats"
    
    # Add header row (비고 포함)
    headers = ["No", "지역", "항구", "등록된 배", "URL", "비고"]
    ws.append(headers)
    
    # Add data rows
    for i, boat in enumerate(boats, start=1):
        row = [i, boat.city, boat.port, boat.name, boat.url, (boat.note or '')]
        ws.append(row)
        
    # Create a virtual file to save the workbook
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    # Create a response
    return Response(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment;filename=boat_list.xlsx"}
    )

city_port_mapping = {
    '인천': ['남항(인천항)', '연안부두', '영흥항'],
    '안산': ['오이도항'],
    '화성': ['전곡항'],
    '평택': ['평택항'],
    '당진': ['장고항'],
    '서산': ['삼길포항'],
    '태안': ['마검포항', '모항항', '영목항', '신진도항'],
    '보령': ['오천항', '구매항', '대천항', '무창포항', '남당항', '홍원항'],
    '군산': ['비응항', '야미도항'],
    '격포': ['격포항'],
    '여수': ['돌산항', '국동항', '소호항', '신추항', '종포항'],
    '고흥': ['녹동방파제']
}

def _compute_region_counts(boats):
    region_sets = {}
    for boat in boats:
        city = getattr(boat, 'city', None) or ''
        registered_name = getattr(boat, 'name', None) or getattr(boat, 'registered_name', None) or ''
        if not city:
            continue
        region_sets.setdefault(city, set()).add(registered_name or '')
    region_counts = {region: len(names) for region, names in region_sets.items()}
    return region_counts, sum(region_counts.values())


def _get_region_boats(boats):
    region_boats = {}
    for boat in boats:
        city = getattr(boat, 'city', None) or ''
        if not city:
            continue
        region_boats.setdefault(city, []).append({
            'id': boat.id,
            'name': boat.name,
        })
    for city in region_boats:
        region_boats[city].sort(key=lambda x: x['name'])
    return region_boats

@views.route('/register', methods=['GET', 'POST'])
def register():
    form = BoatRegistrationForm()
    if request.method == 'POST':
        city = request.form.get('city')
        if city in city_port_mapping:
            form.port.choices = [(port, port) for port in city_port_mapping[city]]
    
    if form.validate_on_submit():
        try:
            add_boat_instance(form.name.data, form.url.data, form.city.data, form.port.data, form.note.data)
            flash('배가 등록되었습니다.', 'success')
            return redirect(url_for('views.index'))
        except Exception as e:
            flash(f'등록 중 오류: {e}', 'danger')
    return render_template('register.html', form=form)

@views.route('/edit/<int:boat_id>', methods=['GET', 'POST'])
def edit_boat(boat_id):
    boat = get_boat_by_id(boat_id)
    if not boat:
        flash('해당 배를 찾을 수 없습니다.', 'danger')
        return redirect(url_for('views.index'))

    form = BoatEditForm(obj=boat)
    if request.method == 'POST':
        city = request.form.get('city')
        if city in city_port_mapping:
            form.port.choices = [(port, port) for port in city_port_mapping[city]]

        if form.validate_on_submit():
            try:
                update_boat(boat_id, form.name.data, form.url.data, form.city.data, form.port.data, form.note.data)
                flash('배 정보가 수정되었습니다.', 'success')
                return redirect(url_for('views.index'))
            except Exception as e:
                flash(f'수정 중 오류: {e}', 'danger')
    else:
        # GET 요청 시, 현재 도시의 항구 목록을 설정
        if boat.city in city_port_mapping:
            form.port.choices = [(port, port) for port in city_port_mapping[boat.city]]

    return render_template('edit_boat.html', form=form, boat_id=boat_id)

@views.route('/status', methods=['GET'])
def status():
    form = StatusCheckForm()
    # 쿼리에서 값 읽어 폼에 주입 (조회 후에도 값 유지)
    y_arg = request.args.get("year")
    m_arg = request.args.get("month")
    d_arg = request.args.get("day")
    if y_arg: form.year.data = int(y_arg)
    if m_arg: form.month.data = int(m_arg)
    if d_arg: form.day.data = int(d_arg)

    # 지역 목록 및 선택값
    region_names = [label for value, label in REGION_CHOICES if value]
    selected_regions = request.args.getlist("regions") or ['전체']
    selected_boats = request.args.getlist("boats")

    # --- added: compute region_counts immediately so status page shows counts on load ---
    registered_boats = get_all_boats()
    region_counts, total_registered = _compute_region_counts(registered_boats)
    region_boats = _get_region_boats(registered_boats)
    # --- end added ---

    # 날짜 미입력 시 조회하지 않고 화면만 렌더링
    if not (y_arg and m_arg and d_arg):
        return render_template(
            "status.html",
            form=form,
            entries=[],
            year=y_arg or "",
            month=m_arg or "",
            day=d_arg or "",
            region_names=region_names,
            selected_regions=selected_regions,
            selected_boats=selected_boats,
            region_counts=region_counts,        # now populated
            total_registered=total_registered,  # now populated
            region_boats=region_boats,
        )

    # 날짜 파싱
    try:
        year, month, day = int(y_arg), int(m_arg), int(d_arg)
    except Exception:
        flash("연/월/일을 올바르게 입력하세요.", "warning")
        return render_template(
            "status.html",
            form=form,
            entries=[],
            year=y_arg or "",
            month=m_arg or "",
            day=d_arg or "",
            region_names=region_names,
            selected_regions=selected_regions,
            selected_boats=selected_boats,
            region_counts={},           # { changed code }
            total_registered=0,         # { changed code }
            region_boats=region_boats,
        )

    # 지역 필터링(OR). '전체'만 선택 시 전체 조회
    registered_boats = get_all_boats()

    # { changed code } : 선택된 지역에 따라 쿼리 대상 목록 생성
    filter_targets = [r for r in selected_regions if r != '전체']
    boats_to_query = [b for b in registered_boats if b.city in filter_targets] if filter_targets else registered_boats

    # 선택된 배가 있으면 해당 배만 조회
    if selected_boats:
        selected_boat_set = set(selected_boats)
        boats_to_query = [b for b in boats_to_query if b.name in selected_boat_set]

    # DEBUG: get_all_boats() 반환값 검사 — 터미널에 출력
    if current_app.config['DEBUG_LOGGING_ENABLED']:
        print("DEBUG: get_all_boats() returned", len(registered_boats), "boats")
        for i, b in enumerate(registered_boats, start=1):
            try:
                info = {
                    'repr': repr(b),
                    'type': type(b).__name__,
                    'id': getattr(b, 'id', None),
                    'name': getattr(b, 'name', None),
                    'registered_name': getattr(b, 'registered_name', None),
                    'city': getattr(b, 'city', None),
                    'port': getattr(b, 'port', None),
                    'url': getattr(b, 'url', None),
                }
            except Exception as exc:
                info = {'error': str(exc), 'repr': repr(b)}
            print(f"DEBUG boat[{i}]:", info)

    # 조회 실행 - 병렬 처리로 속도 개선
    results = []
    
    # Flask application context를 스레드에서 사용하기 위해 미리 저장
    debug_enabled = current_app.config.get('DEBUG_LOGGING_ENABLED', False)
    
    # 병렬 처리 함수 정의
    def process_boat(boat):
        boat_name = getattr(boat, "name", None) or getattr(boat, "registered_name", "unknown")
        boat_url = getattr(boat, "url", "")
        try:
            check = check_single_boat(boat_url, year, month, day, debug_enabled=debug_enabled)
            check_source = check.get("source_url") or boat_url or ""
            
            boat_results = []
            for e in check.get("entries", []):
                full_url = (e.get("used_url") or e.get("source_url") or e.get("url") or check_source or boat_url) or ""
                url_path = e.get("used_url_path") or e.get("url_path") or full_url
                boat_results.append({
                     "registered_name": boat_name,
                     "city": getattr(boat, "city", ""),
                     "port": getattr(boat, "port", ""),
                     "ship_name": e.get("ship_name"),
                     "status": e.get("status"),
                     "available": e.get("available"),
                     "display_status": e.get("display_status"),
                     "raw_status_text": e.get("raw_status_text"),
                     "url": full_url,
                     "url_path": url_path,
                     "fish": e.get("fish"),
                     "row_html": e.get("row_html"),
                     "tide": check.get("tide"),
                })
            return boat_results
        except Exception as e:
            if debug_enabled:
                import traceback
                print(f"Error processing boat {boat_name}: {e}")
                print(traceback.format_exc())
            return []
    
    # ThreadPoolExecutor로 병렬 처리 (동시 요청 수를 줄여 리소스 부담과 타임아웃 리스크를 낮춤)
    max_workers = min(6, len(boats_to_query)) if boats_to_query else 1
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_boat = {executor.submit(process_boat, boat): boat for boat in boats_to_query}
        for future in as_completed(future_to_boat):
            try:
                boat_results = future.result()
                results.extend(boat_results)
            except Exception as e:
                if debug_enabled:
                    import traceback
                    print(f"Error getting future result: {e}")
                    print(traceback.format_exc())

    # { changed code } : 등록된 배 목록(registered_boats)에서 지역별 등록 수 계산
    region_counts, total_registered = _compute_region_counts(registered_boats)

    # 예약가능 상태 배를 먼저 보여주도록 정렬
    results_sorted = sorted(results, key=lambda x: x.get('status') != 'open')
    # 템플릿에는 실제 보여줄 결과 리스트(results)를 전달
    return render_template('status.html',
                           form=form,
                           entries=results_sorted,
                           region_names=region_names,
                           selected_regions=selected_regions,
                           selected_boats=selected_boats,
                           year=year,
                           month=month,
                           day=day,
                           region_counts=region_counts,
                           total_registered=total_registered,
                           region_boats=region_boats)

# API endpoint: JSON으로 파싱결과 반환 (클라이언트가 fetch로 호출)
@views.route('/api/status', methods=['POST'])
def api_status():
    data = request.get_json() or request.form
    try:
        year = int(data.get('year'))
        month = int(data.get('month'))
        day = int(data.get('day'))
    except Exception:
        return jsonify({"error": "invalid date"}), 400

    boats = get_all_boats()
    out = []
    for b in boats:
        info = check_single_boat(b.url, year, month, day, debug_enabled=current_app.config['DEBUG_LOGGING_ENABLED'])
        entries_out = []
        source_url = info.get("source_url") or b.url
        for entry in info.get("entries", []):
            # API 응답에서도 동일한 우선순위와 전체 URL 텍스트 전달
            full_url = (entry.get("used_url") or entry.get("source_url") or entry.get("url") or source_url or "") or ""
            url_path = entry.get("used_url_path") or entry.get("url_path") or full_url
            entries_out.append({
                "ship_name": entry.get("ship_name"),
                "status": entry.get("status"),
                "available": entry.get("available"),
                "raw_status_text": entry.get("raw_status_text"),
                "row_html": entry.get("row_html"),
                "source_url": full_url,
                "url_path": url_path,
                "fish": entry.get("fish")
            })
        if not entries_out:
            entries_out.append({
                "ship_name": None,
                "status": "unknown",
                "available": None,
                "raw_status_text": "",
                "row_html": "",
                "source_url": source_url
            })

        out.append({
            "registered_name": b.name,
            "city": b.city,
            "port": b.port,
            "query_date": f"{int(year):04d}-{int(month):02d}-{int(day):02d}",
            "date_id": info.get("date_id"),
            "tide": info.get("tide"),   # 추가: 물때 정보
            "entries": entries_out
        })
    return jsonify(out)

@views.route('/weather')
def weather():
    """날씨 정보 조회 페이지"""
    # map_page에서 사용하는 것과 동일한 데이터 사용
    return render_template('weather.html', 
                         city_port_mapping=get_city_port_mapping(),
                         port_coordinates=get_port_coordinates(),
                         bada_port_ids=get_bada_port_ids())

def get_port_coordinates():
    """항구 좌표 정보를 반환"""
    return {
        '남항(인천항)': {'lat': 37.47, 'lon': 126.62},
        '연안부두': {'lat': 37.4416, 'lon': 126.6110},
        '영흥항': {'lat': 37.25455083861362, 'lon': 126.49825493353622},
        '오이도항': {'lat': 37.326444939596996, 'lon': 126.65458586308483},
        '전곡항': {'lat': 37.18786766510414, 'lon': 126.65235743282231},
        '평택항': {'lat': 36.96158755929977, 'lon': 126.84006775074936},
        '장고항': {'lat': 37.03122635505709, 'lon': 126.55981703596025},
        '삼길포항': {'lat': 37.00415509197122, 'lon': 126.45292068915825},
        '마검포항': {'lat': 36.61943531903122, 'lon': 126.2875526892295},
        '모항항': {'lat': 36.7759, 'lon': 126.1328},
        '영목항': {'lat': 36.3999, 'lon': 126.4277},
        '신진도항': {'lat': 36.6833, 'lon': 126.1500},
        '오천항': {'lat': 36.4383319, 'lon': 126.5201303},
        '구매항': {'lat': 36.424732, 'lon': 126.432133},
        '대천항': {'lat': 36.3333, 'lon': 126.5167},
        '무창포항': {'lat': 36.2436, 'lon': 126.5469},
        '남당항': {'lat': 36.5390947, 'lon': 126.4689945},
        '홍원항': {'lat': 36.1583, 'lon': 126.5028},
        '비응항': {'lat': 35.93826493213535, 'lon': 126.53099554693064},
        '야미도항': {'lat': 35.8407672, 'lon': 126.488760},
        '격포항': {'lat': 35.6225668, 'lon': 126.4694321},
        '돌산항': {'lat': 34.61326519186631, 'lon': 127.7224984379492},
        '국동항': {'lat': 34.72949367130133, 'lon': 127.7253480879476},
        '소호항': {'lat': 34.746193195297266, 'lon': 127.6561636346259},
        '신추항': {'lat': 34.7308212588099, 'lon': 127.754781729328},
        '종포항': {'lat': 34.73738965299665, 'lon': 127.74701532311137},
        '녹동방파제': {'lat': 34.52298050694286, 'lon': 127.14353349262528},
    }

def get_city_port_mapping():
    """지역별 항구 매핑 정보를 반환"""
    return {
        '인천': ['남항(인천항)', '연안부두', '영흥항'],
        '안산': ['오이도항'],
        '화성': ['전곡항'],
        '평택': ['평택항'],
        '당진': ['장고항'],
        '서산': ['삼길포항'],
        '태안': ['마검포항', '모항항', '영목항', '신진도항'],
        '보령': ['오천항', '구매항', '대천항', '무창포항', '남당항', '홍원항'],
        '군산': ['비응항', '야미도항'],
        '격포': ['격포항'],
        '여수': ['돌산항', '국동항', '소호항', '신추항', '종포항'],
        '고흥': ['녹동방파제']
    }

def get_bada_port_ids():
    """바다타임 포트 ID 매핑 반환 (항구명 -> ID)"""
    return {
        '남항(인천항)': 158,
        '연안부두': 158,
        '영흥항': 151,
        '오이도항': 380,
        '전곡항': 618,
        '평택항': 149,
        '장고항': 370,
        '삼길포항': 144,
        '마검포항': 1400,
        '모항항': 134,
        '영목항': 354,
        '신진도항': 965,
        '오천항': 355,
        '구매항': 1385,
        '대천항': 126,
        '무창포항': 236,
        '남당항': 356,
        '홍원항': 523,
        '비응항': 118,
        '야미도항': 348,
        '격포항': 430,
        '돌산항': 270,
        '국동항': 271,
        '소호항': 826,
        '신추항': 885,
        '종포항': 886,
        '녹동방파제': 443,
    }


@views.route('/api/weather', methods=['GET'])
def api_weather():
    """기상청 API를 호출하여 날씨 정보를 가져오는 API"""
    import requests
    from datetime import datetime
    
    port = request.args.get('port')
    date_str = request.args.get('date')  # YYYY-MM-DD
    
    if not port or not date_str:
        return jsonify({'error': '항구와 날짜를 입력해주세요.'}), 400
    
    # port_coordinates에서 좌표 가져오기
    port_coords = get_port_coordinates()
    if port not in port_coords:
        return jsonify({'error': f'{port}의 좌표 정보를 찾을 수 없습니다.'}), 404
    
    lat = port_coords[port]['lat']
    lon = port_coords[port]['lon']
    
    try:
        # 위경도를 기상청 격자 좌표로 변환
        grid = convert_to_grid(lat, lon)
        
        # 날짜 파싱
        target_date = datetime.strptime(date_str, '%Y-%m-%d')
        base_date = target_date.strftime('%Y%m%d')
        
        # 기상청 단기예보 API 호출
        # 공공데이터포털(https://www.data.go.kr/)에서 '기상청_단기예보' 검색하여 API 키 발급
        service_key = current_app.config.get('KMA_API_KEY', 'd7734746c9c841d53b70df3ffbda3e56422c50e5af2a345ab650bfb24d78b0c9')
        
        # API 키가 설정되지 않은 경우 항구별 샘플 데이터 사용
        use_sample = (service_key == 'd7734746c9c841d53b70df3ffbda3e56422c50e5af2a345ab650bfb24d78b0c9')
        
        if use_sample:
            # 항구별로 다른 샘플 데이터 반환
            weather_data = generate_sample_weather_data(port, lat, lon)
            return jsonify({
                'lat': lat,
                'lon': lon,
                'nx': grid['nx'],
                'ny': grid['ny'],
                'data': weather_data,
                'note': '샘플 데이터입니다. 실제 데이터를 보려면 기상청 API 키를 설정해주세요.'
            })
        
        # 실제 API 호출
        url = 'http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst'
        params = {
            'serviceKey': service_key,
            'pageNo': '1',
            'numOfRows': '1000',
            'dataType': 'JSON',
            'base_date': base_date,
            'base_time': '0500',
            'nx': grid['nx'],
            'ny': grid['ny']
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            # API 호출 실패 시 샘플 데이터로 대체
            current_app.logger.warning(f"KMA API call failed with status {response.status_code}")
            weather_data = generate_sample_weather_data(port, lat, lon)
            return jsonify({
                'lat': lat,
                'lon': lon,
                'nx': grid['nx'],
                'ny': grid['ny'],
                'data': weather_data,
                'note': 'API 호출 실패로 샘플 데이터를 표시합니다.'
            })
        
        result = response.json()
        
        # API 응답 처리
        weather_data = process_kma_weather_data(result, base_date)
        
        if not weather_data:
            # 데이터가 없는 경우 샘플 데이터로 대체
            weather_data = generate_sample_weather_data(port, lat, lon)
            return jsonify({
                'lat': lat,
                'lon': lon,
                'nx': grid['nx'],
                'ny': grid['ny'],
                'data': weather_data,
                'note': '해당 날짜의 실제 데이터가 없어 샘플 데이터를 표시합니다.'
            })
        
        return jsonify({
            'lat': lat,
            'lon': lon,
            'nx': grid['nx'],
            'ny': grid['ny'],
            'data': weather_data
        })
        
    except Exception as e:
        current_app.logger.error(f"Weather API error: {e}")
        # 에러 발생 시에도 샘플 데이터 제공
        try:
            weather_data = generate_sample_weather_data(port, lat, lon)
            return jsonify({
                'lat': lat,
                'lon': lon,
                'nx': grid['nx'] if 'grid' in locals() else 0,
                'ny': grid['ny'] if 'grid' in locals() else 0,
                'data': weather_data,
                'error': f'에러가 발생하여 샘플 데이터를 표시합니다: {str(e)}'
            })
        except:
            return jsonify({'error': f'날씨 정보를 가져올 수 없습니다: {str(e)}'}), 500

def convert_to_grid(lat, lon):
    """위경도를 기상청 격자 좌표로 변환"""
    import math
    
    RE = 6371.00877  # 지구 반경(km)
    GRID = 5.0  # 격자 간격(km)
    SLAT1 = 30.0  # 표준위도1
    SLAT2 = 60.0  # 표준위도2
    OLON = 126.0  # 기준점 경도
    OLAT = 38.0  # 기준점 위도
    XO = 43  # 기준점 X좌표
    YO = 136  # 기준점 Y좌표

    DEGRAD = math.pi / 180.0
    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD
    olat = OLAT * DEGRAD

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = math.pow(sf, sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / math.pow(ro, sn)

    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = re * sf / math.pow(ra, sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    nx = int(ra * math.sin(theta) + XO + 0.5)
    ny = int(ro - ra * math.cos(theta) + YO + 0.5)

    return {'nx': nx, 'ny': ny}

def process_kma_weather_data(result, base_date):
    """기상청 API 응답 데이터 처리"""
    if not result.get('response', {}).get('body', {}).get('items', {}).get('item'):
        return []
    
    items = result['response']['body']['items']['item']
    time_data = {}
    
    # 시간대별로 데이터 그룹화
    for item in items:
        fcst_date = item['fcstDate']
        fcst_time = item['fcstTime']
        category = item['category']
        value = item['fcstValue']
        
        if fcst_date == base_date:
            time_key = f"{fcst_time[:2]}시"
            if time_key not in time_data:
                time_data[time_key] = {}
            time_data[time_key][category] = value
    
    # 시간대별 데이터를 배열로 변환
    weather_array = []
    for time in sorted(time_data.keys()):
        data = time_data[time]
        
        # 풍향 변환
        wind_dir_deg = float(data.get('VEC', 0))
        direction = get_wind_direction(wind_dir_deg)
        
        # 날씨 아이콘 결정
        sky = data.get('SKY', '1')
        pty = data.get('PTY', '0')
        weather = get_weather_icon(sky, pty)
        
        weather_array.append({
            'time': time,
            'direction': direction,
            'windSpeed': float(data.get('WSD', 0)),
            'maxWindSpeed': float(data.get('WSD', 0)) * 1.5,
            'weather': weather,
            'temp': float(data.get('TMP', 0)),
            'waveHeight': 0.6,  # 기본값
            'wavePeriod': 7.0   # 기본값
        })
    
    return weather_array

def get_wind_direction(deg):
    """풍향 각도를 방위로 변환"""
    dirs = ['북', '북북동', '북동', '동북동', '동', '동남동', '남동', '남남동',
            '남', '남남서', '남서', '서남서', '서', '서북서', '북서', '북북서']
    idx = int((deg + 22.5 * 0.5) / 22.5) % 16
    return dirs[idx]

def get_weather_icon(sky, pty):
    """하늘 상태와 강수 형태로 날씨 아이콘 결정"""
    if pty == '1' or pty == '4':
        return '🌧️'  # 비
    if pty == '2':
        return '🌨️'  # 비/눈
    if pty == '3':
        return '❄️'  # 눈
    if sky == '1':
        return '☀️'  # 맑음
    if sky == '3':
        return '⛅'  # 구름많음
    if sky == '4':
        return '☁️'  # 흐림
    return '🌤️'

def generate_sample_weather_data(port_name, lat, lon):
    """항구별로 다른 샘플 날씨 데이터 생성"""
    import random
    
    # 항구 이름을 시드로 사용하여 일관된 랜덤 값 생성
    seed = hash(port_name) % 10000
    random.seed(seed)
    
    times = ['00시', '03시', '06시', '09시', '12시', '15시', '18시', '21시']
    
    # 위도에 따라 기온 범위 조정 (남쪽이 더 따뜻함)
    base_temp = 15 + (37.5 - lat) * 0.5  # 위도가 낮을수록 기온 높음
    
    # 경도와 위도로 풍향 경향 결정
    wind_direction_base = int((lon - 126) * 10 + (lat - 35) * 5) % 360
    
    data = []
    for i, time in enumerate(times):
        # 시간대별 기온 변화
        hour = int(time.replace('시', ''))
        temp_variation = -3 if hour < 6 else (5 if 12 <= hour < 15 else 0)
        temp = round(base_temp + temp_variation + random.uniform(-2, 2), 1)
        
        # 풍향 (항구별로 다르게)
        wind_deg = (wind_direction_base + random.randint(-30, 30)) % 360
        direction = get_wind_direction(wind_deg)
        
        # 풍속 (연안 지역 특성)
        wind_speed = round(random.uniform(1.5, 6.0), 1)
        max_wind_speed = round(wind_speed * random.uniform(1.3, 1.8), 1)
        
        # 날씨 (일부 랜덤)
        weather_options = ['☀️', '🌤️', '⛅', '☁️']
        if random.random() < 0.15:  # 15% 확률로 비
            weather_options = ['🌧️', '🌦️']
        weather = random.choice(weather_options)
        
        # 파고 (풍속과 연관)
        wave_height = round(wind_speed * 0.15 + random.uniform(0.3, 0.8), 1)
        wave_period = round(random.uniform(4.0, 9.0), 1)
        
        data.append({
            'time': time,
            'direction': direction,
            'windSpeed': wind_speed,
            'maxWindSpeed': max_wind_speed,
            'weather': weather,
            'temp': int(temp),
            'waveHeight': wave_height,
            'wavePeriod': wave_period
        })
    
    return data

# ---------------- Tide (Badatime) Integration -----------------
@views.route('/api/tide')
def api_tide():
    """바다타임 특정 항구 번호(port_id)의 주간(week_container) 정보를 파싱하여 시간대별 데이터 반환.
    요청: /api/tide?port_id=118
    반환 필드: time, wind_dir, wind_speed, weather, temperature, wave_info
    바다타임 페이지에 풍향/풍속/날씨/기온/파고가 모두 없을 수 있으므로 가용한 정보만 구성하고 나머지는 추정/빈값 처리.
    """
    import requests
    from bs4 import BeautifulSoup
    port_id = request.args.get('port_id', type=int)
    if not port_id:
        return jsonify({'error': 'port_id 파라미터가 필요합니다.'}), 400

    # 날짜는 /{port_id}/tide/YYYY-MM-DD 형태의 경로로 전달됨
    date_str = request.args.get('date')  # YYYY-MM-DD
    base_url = f"https://www.badatime.com/{port_id}/tide"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36'
    }
    try:
        # 날짜가 있으면 경로 세그먼트로 전달: /{port}/tide/YYYY-MM-DD
        used_url = f"{base_url}/{date_str}" if date_str else base_url
        resp = requests.get(used_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return jsonify({'error': f'페이지 응답 오류: {resp.status_code}'}), 502
    except Exception as e:
        return jsonify({'error': f'요청 실패: {e}'}), 500

    soup = BeautifulSoup(resp.text, 'html.parser')
    week_container = soup.select_one('.week_container')
    if not week_container:
        return jsonify({'error': 'week_container(class)를 찾을 수 없습니다.'}), 500

    table = week_container.select_one('table.week_table')
    if not table:
        return jsonify({'error': 'week_table을 찾을 수 없습니다.'}), 500

    import re
    rows = table.select('tbody > tr')
    if not rows or len(rows) < 5:
        return jsonify({'error': '예상보다 적은 행. 구조 변경 가능성.'}), 500

    # 1행: 날짜 + 시간 헤더들
    time_cells = rows[0].find_all('td')[1:]  # 첫번째는 날짜
    times = []
    for c in time_cells:
        t = c.get_text(strip=True).replace('현재','').strip()
        # Normalize '07시' -> '07시'
        times.append(t)

    count = len(times)

    def extract_icon_row(tr):
        icons = []
        for td in tr.find_all('td')[1:]:
            img = td.find('img')
            icons.append(img['src'] if img else '')
        return icons

    def extract_text_cells(tr):
        return [td.get_text(strip=True) for td in tr.find_all('td')[1:]]

    # 행 식별: 두번째 행 아이콘, 세번째 행 날씨텍스트(맑음), 네번째 기온(첫셀 '기온'), 다섯번째 풍향(첫셀 '풍향'), 여섯번째 풍속, 일곱번째 파고, 여덟번째 습도, 아홉번째 강수량
    icon_urls      = extract_icon_row(rows[1])
    weather_texts  = extract_text_cells(rows[2])
    temp_values    = extract_text_cells(rows[3]) if '기온' in rows[3].find('td').get_text() else ['']*count
    wind_dir_cells = rows[4].find_all('td')[1:]
    wind_dirs = []
    wind_dir_icons = []
    for td in wind_dir_cells:
        img = td.find('img')
        wind_dir_icons.append(img['src'] if img else '')
        # span 또는 텍스트
        txt = td.get_text(strip=True)
        wind_dirs.append(txt)
    wind_speeds    = extract_text_cells(rows[5]) if '풍속' in rows[5].find('td').get_text() else ['']*count
    wave_heights   = extract_text_cells(rows[6]) if '파고' in rows[6].find('td').get_text() else ['']*count
    humidities     = extract_text_cells(rows[7]) if len(rows) > 7 and '습도' in rows[7].find('td').get_text() else ['']*count
    precipitations = extract_text_cells(rows[8]) if len(rows) > 8 and '강수' in rows[8].find('td').get_text() else ['']*count

    data_out = []
    for i in range(count):
        data_out.append({
            'time': times[i],
            'weather_icon_url': icon_urls[i] if i < len(icon_urls) else '',
            'weather_text': weather_texts[i] if i < len(weather_texts) else '',
            'temperature': temp_values[i] if i < len(temp_values) else '',
            'wind_dir': wind_dirs[i] if i < len(wind_dirs) else '',
            'wind_dir_icon_url': wind_dir_icons[i] if i < len(wind_dir_icons) else '',
            'wind_speed': wind_speeds[i] if i < len(wind_speeds) else '',
            'wave_height': wave_heights[i] if i < len(wave_heights) else '',
            'humidity': humidities[i] if i < len(humidities) else '',
            'precipitation': precipitations[i] if i < len(precipitations) else ''
        })

    return jsonify({'port_id': port_id, 'source_url': used_url if date_str else base_url, 'data': data_out, 'date': date_str})

# New: Parse Badatime graph page and return only summary table + chart script
@views.route('/api/tide_graph', methods=['GET'])
def api_tide_graph():
    """Badatime 그래프 페이지(/{port_id}/graph/{date})에서 요약 테이블(pc_txt_view)과
    차트 컨테이너(#chartdiv) 및 해당 스크립트만 추출해서 반환.
    응답: { success, pc_html, chart_html, script, source_url }
    """
    import requests
    from bs4 import BeautifulSoup

    port_id = request.args.get('port_id', type=int)
    date_str = request.args.get('date', default='')  # YYYY-MM-DD
    if not port_id or not date_str:
        return jsonify({'success': False, 'message': 'port_id와 date가 필요합니다.'}), 400

    source_url = f"https://www.badatime.com/{port_id}/graph/{date_str}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36'
    }
    try:
        resp = requests.get(source_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return jsonify({'success': False, 'message': f'페이지 응답 오류: {resp.status_code}'}), 502
    except Exception as e:
        return jsonify({'success': False, 'message': f'요청 실패: {e}'}), 500

    soup = BeautifulSoup(resp.text, 'html.parser')

    # PC 요약 테이블
    pc_view = soup.select_one('div.pc_txt_view')
    pc_html = pc_view.decode() if pc_view else ''

    # 모바일 요약 테이블
    mo_view = soup.select_one('div.mo_txt_view')
    mo_html = mo_view.decode() if mo_view else ''

    # 차트 컨테이너와 스크립트(바로 뒤에 오는 inline script)
    chart_div = soup.select_one('#chartdiv')
    chart_html = ''
    script_text = ''
    if chart_div:
        # chart div 자체는 보통 빈 div. height 스타일을 보장하기 위해 기본 높이 부여
        # 원본 div를 복사하고 style 추가
        chart_div_copy = BeautifulSoup(str(chart_div), 'html.parser')
        chart_root = chart_div_copy.select_one('#chartdiv')
        if chart_root:
            # 기본 높이 적용 (없을 경우)
            style_val = chart_root.get('style', '')
            if 'height:' not in style_val:
                style_val = (style_val + '; height: 460px;').strip('; ')
                chart_root['style'] = style_val
        chart_html = str(chart_div_copy)

        # 차트 설정 스크립트: chartdiv 다음 <script> 추출
        next_script = chart_div.find_next('script')
        if next_script and next_script.string:
            script_text = next_script.string
        else:
            # 일부 페이지는 script 내에 주석/공백 포함 -> 전체 텍스트 사용
            script_text = next_script.get_text("\n") if next_script else ''

        # 안전을 위해 외부 참조가 상대경로일 경우 절대경로로 고치기(이미지/아이콘 등)
        def absolutize_urls(html_text: str) -> str:
            # badatime.com 이미지를 절대경로로 변경
            html_text = re.sub(r'(["\'])(\/\/(?:images|img)\.badatime\.com[^"\']*)(["\'])', r"https:\1\2\3", html_text)
            # /img/icon/ 경로를 로컬 static 경로로 변경 - 더 포괄적인 정규식 사용
            html_text = re.sub(r'(["\'])\/img\/icon\/(sunrise|sunset)\.svg(["\'])', r'\1/img/\2.svg\3', html_text)
            return html_text
        
        def absolutize_script_urls(script_text: str) -> str:
            # 스크립트 내의 이미지 경로도 변경
            script_text = re.sub(r'(["\'])\/img\/icon\/(sunrise|sunset)\.svg(["\'])', r'\1/img/\2.svg\3', script_text)
            return script_text

        pc_html = absolutize_urls(pc_html)
        mo_html = absolutize_urls(mo_html)
        chart_html = absolutize_urls(chart_html)
        if script_text:
            script_text = absolutize_script_urls(script_text)

    return jsonify({
        'success': True,
        'pc_html': pc_html,
        'mo_html': mo_html,
        'chart_html': chart_html,
        'script': script_text,
        'source_url': source_url,
    })

@views.route('/map')
def map_page():
    """지도 페이지 - 항구별 등록된 배 표시"""
    port_coordinates = get_port_coordinates()
    city_port_mapping = get_city_port_mapping()

    boats = get_all_boats()
    boat_counts = {}
    port_boat_names = {}
    for boat in boats:
        port = boat.port
        if port not in port_boat_names:
            port_boat_names[port] = []
        port_boat_names[port].append(boat.name)

    for boat in boats:
        port = boat.port
        if port in boat_counts:
            boat_counts[port] += 1
        else:
            boat_counts[port] = 1

    total_boats = len(boats)

    return render_template(
        'map.html',
        city_port_mapping=city_port_mapping,
        port_coordinates=port_coordinates,
        boat_counts=boat_counts,
        port_boat_names=port_boat_names,
        total_boats=total_boats
    )

# 추가: 배 삭제 라우트 (POST)
@views.route('/delete/<int:boat_id>', methods=['POST'], endpoint='delete_boat')
def delete_boat_route(boat_id):
    try:
        delete_boat(boat_id)
        flash('배가 삭제되었습니다.', 'success')
    except Exception as e:
        flash(f'삭제 중 오류: {e}', 'danger')
    return redirect(url_for('views.index'))

# New route: handle deletion of selected boats
@views.route('/delete_boats', methods=['POST'])
def delete_boats():
    ids = request.form.getlist('delete_ids')
    if not ids:
        flash('삭제할 배를 선택하세요.', 'warning')
        return redirect(url_for('views.index'))
    deleted = 0
    for bid in ids:
        try:
            # delete_boat 함수가 id를 받는다고 가정
            delete_boat(int(bid))
            deleted += 1
        except Exception as e:
            # continue on error, but notify
            print(f"delete_boat error for id={bid}: {e}")
    flash(f'{deleted}개의 배가 삭제되었습니다.', 'success')
    return redirect(url_for('views.index'))

@views.route('/upload_excel', methods=['POST'])
def upload_excel():
    from models import Boat
    from db import db

    if 'excel_file' not in request.files:
        return jsonify({'success': False, 'message': '파일이 없습니다.'}), 400
    
    file = request.files['excel_file']
    if file.filename == '':
        return jsonify({'success': False, 'message': '파일을 선택해주세요.'}), 400

    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        try:
            workbook = openpyxl.load_workbook(file)
            sheet = workbook.active

            # Map existing boats by name for updates
            existing_by_name = {b.name: b for b in Boat.query.all()}
            
            new_boats_count = 0
            updated_boats_count = 0
            # Iterate over rows, skipping the header (row 1)
            for row in sheet.iter_rows(min_row=2, values_only=True):
                # Column order from download_excel: No, 지역, 항구, 등록된 배, URL, 비고
                # We ignore 'No' (index 0)
                if len(row) < 5:
                    continue # Skip malformed rows

                city = row[1]
                port = row[2]
                name = row[3]
                url = row[4]
                note = row[5] if len(row) > 5 else None

                # Basic validation
                if not all([city, port, name, url]):
                    current_app.logger.warning(f"Skipping row due to missing data: {row}")
                    continue

                existing = existing_by_name.get(name)
                if not existing:
                    new_boat = Boat(name=name, url=url, city=city, port=port, note=note)
                    db.session.add(new_boat)
                    existing_by_name[name] = new_boat  # track to avoid duplicates
                    new_boats_count += 1
                else:
                    # Update existing boat fields (including 비고)
                    changed = False
                    if existing.city != city and city:
                        existing.city = city; changed = True
                    if existing.port != port and port:
                        existing.port = port; changed = True
                    if existing.url != url and url:
                        existing.url = url; changed = True
                    # note can be empty string; update even if '' provided
                    if note is not None and existing.note != note:
                        existing.note = note; changed = True
                    if changed:
                        updated_boats_count += 1
            
            db.session.commit()
            
            if new_boats_count > 0 or updated_boats_count > 0:
                message = f'성공: 신규 {new_boats_count}척, 업데이트 {updated_boats_count}척 처리했습니다.'
            else:
                message = '변경 사항이 없습니다. 모든 배가 이미 최신입니다.'

            return jsonify({'success': True, 'message': message})

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Excel upload failed: {e}")
            return jsonify({'success': False, 'message': f'파일 처리 중 오류가 발생했습니다: {e}'}), 500

    return jsonify({'success': False, 'message': '엑셀 파일(.xlsx, .xls)만 업로드할 수 있습니다.'}), 400

# API 엔드포인트: 선박 목록 JSON으로 반환
@views.route('/api/ships', methods=['GET'])
def api_ships():
    """선박 목록을 JSON 형태로 반환하는 API 엔드포인트"""
    try:
        boats = get_all_boats()
        ships_data = []
        
        for boat in boats:
            ship = {
                'id': boat.id,
                'region': boat.city,  # 지역
                'port': boat.port,    # 항구
                'registration_number': boat.name,  # 등록번호 (현재는 name을 사용)
                'name': boat.name,    # 선박 이름
                'url': boat.url       # 상세 URL
            }
            ships_data.append(ship)
        
        return jsonify(ships_data)
    
    except Exception as e:
        current_app.logger.error(f"API ships error: {e}")
        return jsonify({'error': '선박 목록을 가져오는 중 오류가 발생했습니다.'}), 500

# API 엔드포인트: 새 선박 등록
@views.route('/api/ships', methods=['POST'])
def api_add_ship():
    """새 선박을 등록하는 API 엔드포인트"""
    try:
        data = request.get_json()
        
        # 필수 필드 검증
        required_fields = ['region', 'port', 'registrationNumber', 'url']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} 필드가 필요합니다.'}), 400
        
        # 선박 등록
        add_boat_instance(
            name=data.get('registrationNumber'),  # 등록번호를 name으로 사용
            url=data.get('url'),
            city=data.get('region'),
            port=data.get('port')
        )
        
        return jsonify({'success': True, 'message': '선박이 성공적으로 등록되었습니다.'})
        
    except Exception as e:
        current_app.logger.error(f"API add ship error: {e}")
        return jsonify({'error': '선박 등록 중 오류가 발생했습니다.'}), 500

@views.route('/sea-temp-test')
@views.route('/sea-temp-test/<int:port_id>')
def sea_temp_test(port_id=None):
    """Badatime 바다 수온 지도 임베드 테스트 페이지
    - 경로: /sea-temp-test 또는 /sea-temp-test/<port_id>
    - 쿼리스트링으로도 지정 가능: /sea-temp-test?port_id=118
    """
    # 우선순위: path param > query param
    q_port_id = request.args.get('port_id', type=int)
    pid = port_id or q_port_id or 118
    # 항구명-포트ID 매핑 전달하여 선택 편의 제공
    return render_template(
        'sea_temp_test.html',
        current_port_id=pid,
        bada_port_ids=get_bada_port_ids(),
    )

@views.route('/api/sea_temp')
def api_sea_temp():
    """바다타임에서 수온 정보를 가져와서 자체 Kakao Maps API로 재구성"""
    import requests
    from bs4 import BeautifulSoup
    import re
    import json
    
    port_id = request.args.get('port_id', type=int, default=443)
    url = f"https://www.badatime.com/{port_id}/sea-temp"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # main.content 영역 찾기
        content = soup.select_one('main.content')
        
        if not content:
            return jsonify({'error': 'main.content 영역을 찾을 수 없습니다.'}), 404
        
        # 지도 스크립트에서 마커 데이터 추출
        map_markers = []
        center_coords = {'lat': 34.5049, 'lng': 127.1228}  # 기본값
        
        for script in soup.find_all('script'):
            if script.string and 'mapOption' in script.string:
                script_text = script.string
                
                # 중심 좌표 추출
                center_match = re.search(r'center:\s*new\s+daum\.maps\.LatLng\(([^,]+),\s*([^)]+)\)', script_text)
                if center_match:
                    center_coords = {
                        'lat': float(center_match.group(1)),
                        'lng': float(center_match.group(2))
                    }
                
                # 마커 데이터 추출 (위도, 경도, 라벨, 온도)
                # customOverlay content 추출
                overlay_pattern = r"var content = '(.+?)';\s*var position = new daum\.maps\.LatLng\(([^,]+),\s*([^)]+)\);"
                for match in re.finditer(overlay_pattern, script_text, re.DOTALL):
                    content_html = match.group(1)
                    lat = float(match.group(2))
                    lng = float(match.group(3))
                    
                    # HTML에서 지역명과 온도 추출
                    name_match = re.search(r'font-weight:600[^>]*>([^<]+?)\s*<span', content_html)
                    temp_match = re.search(r'font-size:15px[^>]*>([^<]+)</span>', content_html)
                    time_match = re.search(r'font-size:12px[^>]*>([^<]+)</div>', content_html)
                    
                    if name_match and temp_match:
                        map_markers.append({
                            'name': name_match.group(1).strip(),
                            'temp': temp_match.group(1).strip(),
                            'time': time_match.group(1).strip() if time_match else '',
                            'lat': lat,
                            'lng': lng
                        })
        
        # 이미지 경로를 절대 경로로 변환
        for img in content.find_all('img'):
            src = img.get('src', '')
            if src.startswith('//'):
                img['src'] = 'https:' + src
            elif src.startswith('/'):
                img['src'] = 'https://www.badatime.com' + src
        
        # 링크 경로를 절대 경로로 변환
        for link in content.find_all('a'):
            href = link.get('href', '')
            if href.startswith('/') and not href.startswith('//'):
                link['href'] = 'https://www.badatime.com' + href
                link['target'] = '_blank'
        
        # 지도 관련 스크립트 제거 (우리가 직접 구현)
        for script in content.find_all('script'):
            if 'kakao' in str(script) or 'daum.maps' in str(script) or 'mapContainer' in str(script):
                script.decompose()
        
        # 지도 div는 유지하되 내용 비우기
        map_div = content.find('div', id='map')
        if map_div:
            map_div.clear()
            map_div['style'] = 'width:100%; height:500px;'
        
        # Highcharts 스크립트 추출 (그래프용)
        highcharts_scripts = []
        for script in content.find_all('script'):
            if script.string and 'Highcharts.chart' in script.string:
                highcharts_scripts.append(script.string)
                script.decompose()  # 원본 제거
        
        # content HTML 추출
        content_html = str(content)
        
        return jsonify({
            'success': True,
            'html': content_html,
            'map_data': {
                'center': center_coords,
                'markers': map_markers,
                'zoom': 8
            },
            'highcharts_scripts': highcharts_scripts,
            'source_url': url
        })
        
    except requests.RequestException as e:
        return jsonify({'error': f'요청 중 오류 발생: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'파싱 중 오류 발생: {str(e)}'}), 500

@views.route('/manifest.json')
def pwa_manifest():
    """Serve the PWA manifest (root scope)."""
    return send_from_directory(current_app.root_path, 'manifest.json', mimetype='application/manifest+json')

@views.route('/service-worker.js')
def pwa_service_worker():
    """Serve the service worker at root for widest scope."""
    return send_from_directory(current_app.root_path, 'service-worker.js', mimetype='application/javascript')

@views.route('/offline')
def offline_page():
    """Offline fallback page served when navigation fails in PWA."""
    return render_template('offline.html')

