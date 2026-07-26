from bs4 import BeautifulSoup, Comment
from threading import Lock
from time import time
from typing import Dict, List
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import requests
import re
import datetime
import json

# 어종 키워드 (필요시 확장)
FISH_KEYWORDS = [
    '주꾸미', '쭈꾸미', '문어', '갑오징어', '우럭', '광어', '낙지', '백조기', '민어',
    '삼치', '쭈갑', '참돔', '갈치', '다운샷', '생미끼', '돌문어', '피문어', '외수질',
    '광어다운샷','한치'
]

# 유효한 배 이름 예외 목록 ("~호"가 없어도 배로 인정)
VALID_SHIP_NAMES = [
    '팀만수', '힐링피싱', '라온피싱', '레드헌터', '레드히어로', '레드썬', '레드퀸', '골드피싱'
]

REQUEST_TIMEOUT_SECONDS = 3
_CACHE_TTL_SECONDS = 300
_CACHE = {}
_CACHE_LOCK = Lock()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _get_cached_result(cache_key: tuple) -> Dict | None:
    now = time()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if not cached:
            return None
        if cached["expires_at"] <= now:
            _CACHE.pop(cache_key, None)
            return None
        return cached["result"]


def _store_cached_result(cache_key: tuple, result: Dict) -> Dict:
    with _CACHE_LOCK:
        _CACHE[cache_key] = {
            "result": result,
            "expires_at": time() + _CACHE_TTL_SECONDS,
        }
    return result


def _norm(text: str) -> str:
    """간단 정규화: 공백/특수문자 제거하여 키워드 포함 여부를 관대하게 검사"""
    if not text:
        return ''
    # \u00a0 등 non-breaking space 포함 다양한 공백/구분자 제거
    return re.sub(r"[\s\u00a0/&(),·\-]+", "", str(text))

def _extract_known_fish(text: str) -> str | None:
    if not text:
        return None

    normalized_text = _norm(text)
    found = []
    for keyword in FISH_KEYWORDS:
        if _norm(keyword) in normalized_text and keyword not in found:
            found.append(keyword)
    return ', '.join(found) if found else None

def _sanitize_fish_text(text: str) -> str | None:
    if not text:
        return None

    cleaned = str(text).strip()
    cleaned = re.sub(r'[\u200b\u200c\u200d\ufeff]+', '', cleaned).strip()
    cleaned = re.sub(r'(낚시\s*종류|낚시종류|어종)\s*[:：-]?\s*', '', cleaned, flags=re.I).strip()
    cleaned = re.sub(r'^[★☆◆■▶▷\[\(<\s]+', '', cleaned).strip()
    cleaned = re.sub(r'[★☆◆■▶▷\]\)>\s]+$', '', cleaned).strip()

    for sep in ['[', ' 탐사', ' 출조', ' 이벤트', ' 예약', ' 조황']:
        if sep in cleaned:
            cleaned = cleaned.split(sep)[0].strip()

    if not cleaned:
        return None

    cleaned = cleaned.strip()
    if not cleaned:
        return None

    return _extract_known_fish(cleaned) or cleaned

def _clean_notice_fish_text(text: str) -> str | None:
    if not text:
        return None

    cleaned = str(text).strip()
    cleaned = re.sub(r'[\u200b\u200c\u200d\ufeff]+', '', cleaned).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'^[\-–—★☆◆■▶▷\[\(<\s]+', '', cleaned).strip()
    cleaned = re.sub(r'[\-–—★☆◆■▶▷\]\)>\s]+$', '', cleaned).strip()
    cleaned = re.sub(r'(낚시\s*종류|낚시종류|어종)\s*[:：-]?\s*', '', cleaned, flags=re.I).strip()

    if not cleaned:
        return None

    if _extract_known_fish(cleaned):
        return cleaned
    return None

def _extract_fish_from_notice_area(node) -> str | None:
    """
    선박 행 안에 중첩된 공지 테이블에서 어종 문구를 추출한다.
    일부 사이트는 별도 공지 tr이 아니라 선박의 안내 td 안에 <img alt="공지">를 넣는다.
    """
    if not node or not getattr(node, 'select', None):
        return None

    notice_imgs = node.find_all('img', alt='공지')
    for img in notice_imgs:
        notice_row = img.find_parent('tr')
        if not notice_row:
            continue
        notice_tds = notice_row.find_all('td')
        text_nodes = notice_tds[1:] if len(notice_tds) > 1 else [notice_row]
        for text_node in text_nodes:
            text = text_node.get_text("\n", strip=True)
            for line in text.splitlines():
                fish = _clean_notice_fish_text(line)
                if fish:
                    return fish

    return None

def _extract_fish_from_special_marker(text: str) -> str | None:
    """
    특수문자(★/◆/☆)로 감싼 어종 전체를 추출
    예: "★봄 쭈꾸미 ★[8만원]" → "봄 쭈꾸미"
    예: "◆봄 왕쭈꾸미 전문 출조 ◆[8만원]" → "봄 왕쭈꾸미 전문 출조"
    """
    if not text:
        return None
    
    # ★...★ / ◆...◆ / ☆...☆ 패턴 추출 (탐욕적이지 않게)
    pattern = r'(★|◆|☆)\s*([^★◆☆\[]*?)\s*(★|◆|☆)'
    match = re.search(pattern, text)
    
    if not match:
        return None
    
    fish = match.group(2).strip()
    
    # "[" 이후는 제거 (가격 정보)
    if '[' in fish:
        fish = fish.split('[')[0].strip()
    
    # " 탐사[" 패턴 제거
    if ' 탐사[' in fish:
        fish = fish.split(' 탐사[')[0].strip()
    
    return fish if fish else None

def _clean_ship_name(name: str) -> str:
    """배 이름에서 불필요한 문구 제거"""
    if not name:
        return name
    # "예약하기"/"대기하기" 문구 제거
    name = name.replace('예약하기', '').replace('대기하기', '').strip()
    # 선상24 선단 페이지는 "레드헌터(22인승)"처럼 정원 표기가 붙어 내려온다.
    name = re.sub(r'\(\s*\d+\s*인승\s*\)', '', name).strip()
    return name

def _is_valid_ship_name(name: str, extra_valid_names: set | None = None) -> bool:
    """배 이름이 유효한지 검증: '호'를 포함하거나 예외 목록에 있거나, 실제 등록된 배 이름이면 인정"""
    if not name:
        return False
    name = _clean_ship_name(name)
    # "~호"를 포함하면 배로 인정
    if '호' in name:
        return True
    # 예외 목록에 있으면 배로 인정
    if name in VALID_SHIP_NAMES:
        return True
    # 실제 DB에 등록된 배 이름이면 인정 (신규 등록 배가 필터에 걸리지 않도록)
    if extra_valid_names and name in extra_valid_names:
        return True

def build_query_url(base_url: str, year: int, month: int, day: int) -> str:
    """
    URL 패턴에 따라 적절한 쿼리 파라미터를 구성합니다.
    sunsang24.com 도메인(또는 기존에 schedule_fleet이 포함된 경우)은
    /ship/schedule_fleet/YYYYMM 형태로 처리합니다.
    그 외 도메인은 기존처럼 쿼리 파라미터를 추가합니다.
    """
    parsed = urlparse(base_url)
    path = parsed.path or ""
    netloc = (parsed.netloc or "").lower()
    query = parse_qs(parsed.query or "")

    # sunsang24 도메인 또는 기존 schedule_fleet 경로는 schedule_fleet 처리
    if 'sunsang24.com' in netloc or 'schedule_fleet' in path:
        scheme = parsed.scheme or "https"
        new_path = f"/ship/schedule_fleet/{year:04d}{month:02d}"
        return urlunparse((scheme, parsed.netloc, new_path, "", "", ""))

    # 일반 게시판 패턴 (예: index.php?mid=bk) — 기존 쿼리 유지 후 날짜 파라미터 추가
    query.update({
        'year': [f"{year:04d}"],
        'month': [f"{month:02d}"],
        'day': [f"{day:02d}"],
        'mode': ['list'],
        'won': ['1'],
        'PA_N_UID': ['0'],
        'sel': ['day']
    })
    query_string = urlencode({k: v[0] for k, v in query.items()})
    scheme = parsed.scheme or "https"
    return urlunparse((scheme, parsed.netloc, parsed.path, "", query_string, ""))

def _headers_for(url: str, alt: bool = False) -> dict:
    p = urlparse(url)
    scheme = p.scheme or "https"
    referer = f"{scheme}://{p.netloc}/"
    if not alt:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    else:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
    }

def _weekday_kor(year: int, month: int, day: int) -> str:
    return "월화수목금토일"[datetime.date(year, month, day).weekday()]

def _parse_tide_from_text(text: str) -> str | None:
    m = re.search(r'(\d+)\s*물', text)
    return f"{m.group(1)}물" if m else None

def check_single_boat(boat_url: str, year: int, month: int, day: int, debug_enabled: bool = False, known_ship_name: str | None = None) -> Dict:
    cache_key = (str(boat_url or ""), int(year), int(month), int(day))
    cached_result = _get_cached_result(cache_key)
    if cached_result is not None:
        return cached_result

    final_url = build_query_url(boat_url, year, month, day)

    # 요일/표시 날짜(물때는 응답 후 보강)
    weekday = _weekday_kor(year, month, day)
    display_date = f"{year:04d}-{month:02d}-{day:02d}({weekday})"

    # 1차 시도: 정상 헤더 (짧은 타임아웃으로 빠르게 실패 처리)
    try:
        resp = requests.get(final_url, headers=_headers_for(final_url), timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        result = {"used_url": final_url, "display_date": display_date, "entries": [], "error": f"http_error:{e}"}
        return _store_cached_result(cache_key, result)

    # 403이면 UA/Referer 바꿔 재시도 + http 스킴 폴백
    if resp.status_code == 403:
        try:
            resp = requests.get(final_url, headers=_headers_for(final_url, alt=True), timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException:
            resp = None

        if (resp is None) or (resp.status_code == 403 and final_url.startswith("https://")):
            try:
                http_url = "http://" + final_url[len("https://"):]
                resp = requests.get(http_url, headers=_headers_for(http_url, alt=True), timeout=REQUEST_TIMEOUT_SECONDS)
                final_url = http_url  # 실제 사용 URL 갱신
            except requests.RequestException:
                pass

    # 여전히 200이 아니면 예외를 던지지 않고 빈 결과 반환 (500 방지)
    if resp is None or resp.status_code != 200:
        result = {
            "used_url": final_url,
            "display_date": display_date,
            "entries": [],
            "error": f"http_status:{getattr(resp, 'status_code', 'unknown')}"
        }
        return _store_cached_result(cache_key, result)

    soup = BeautifulSoup(resp.text, "html.parser")

    # 판단 기준: target의 호스트가 sunsang24.com 이거나 path에 schedule_fleet가 있으면 기존 패턴 사용
    parsed_target = urlparse(final_url)
    target_netloc = (parsed_target.netloc or "").lower()
    use_schedule_pattern = ('sunsang24.com' in target_netloc) or ('schedule_fleet' in parsed_target.path)

    if use_schedule_pattern:
        date_id = f"d{year:04d}-{month:02d}-{day:02d}"
        day_block = soup.find(id=date_id) or soup.select_one('.shipsinfo_daywarp.weekday')

        if not day_block:
            # try comment-based search
            for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
                if "날자별 선단 소속 선박 리스트" in str(comment):
                    nxt = comment
                    for _ in range(8):
                        nxt = nxt.next_sibling
                        if not nxt:
                            break
                        if getattr(nxt, 'select', None):
                            found = nxt.select_one(f".shipsinfo_daywarp#{date_id}, .shipsinfo_daywarp.weekday, .shipsinfo_daywarp")
                            if found:
                                day_block = found
                                break

        if not day_block:
            result = {"matched": False, "date_id": date_id, "source_url": final_url, "entries": [], "tide": None}
            return _store_cached_result(cache_key, result)

        # extract tide info from .date_info2
        tide = None
        date_info2_el = day_block.select_one('.date_info2')
        if date_info2_el:
            tide = date_info2_el.get_text(separator=' ', strip=True)

        # 어종 추출: div#fish 또는 .fish 우선, 없으면 '낚시종류' 라벨 주변에서 시도
        fish = None
        fish_el = day_block.select_one('div#fish') or day_block.select_one('.fish') or soup.select_one('div#fish')
        if fish_el:
            fish = _sanitize_fish_text(fish_el.get_text(" ", strip=True))
        else:
            label_text = day_block.find(string=re.compile(r'낚시종류'))
            if label_text:
                parent = label_text.parent
                if parent and parent.name == 'td':
                    sib = parent.find_next_sibling('td')
                    if sib:
                        fish = _sanitize_fish_text(sib.get_text(" ", strip=True))
                else:
                    nxt = label_text.find_next()
                    if nxt and getattr(nxt, 'get_text', None):
                        fish = _sanitize_fish_text(nxt.get_text(" ", strip=True))

        # debug: schedule_fleet 패턴에서 추출된 어종 확인
        if debug_enabled:
            try:
                print(json.dumps({"DEBUG_FISH_SCHEDULE": fish, "date": display_date, "url": final_url}, ensure_ascii=False))
            except Exception:
                print("DEBUG_FISH_SCHEDULE:", fish, display_date, final_url)

        entries = []
        ship_tables = day_block.select('table.ship_unit, table[class*="ship_unit_"], table.ship_unit_ship_no_918, .ships_warp table')
        if not ship_tables:
            ship_tables = [t for t in day_block.find_all('table') if t.select_one('.title') or t.select_one('.ship_info')]

        for t in ship_tables:
            # find title
            title_el = t.select_one('.ship_info .title') or t.select_one('.title')
            ship_name = title_el.get_text(strip=True) if title_el else None

            # ship_info2 status
            status_el = t.select_one('.ship_info2 .shipping_status') or t.select_one('.ship_info2') or None
            status_text = status_el.get_text(separator=' ', strip=True) if status_el else ""
            status_code = status_el.get('data-status_code') if status_el and status_el.has_attr('data-status_code') else None

            # remaining seats
            avail = None
            num_el = t.select_one('span.number.blink_me.n_blue.f_20') or t.select_one('.ship_info2 .number') or t.select_one('.number')
            if num_el:
                mnum = re.search(r'(\d+)', num_el.get_text())
                if mnum:
                    avail = int(mnum.group(1))

            if re.search(r'점검일', status_text):
                status = 'maintenance'
                avail = 0
                display_status = "점검일"
            elif status_code == 'END' or re.search(r'(예약마감|매진|마감)', status_text):
                status = 'full'
                if avail is None:
                    avail = 0
                display_status = "예약마감"
            elif re.search(r'예약\s*완료', status_text):
                status = 'reserved'
                avail = 0
                display_status = "예약완료"
            elif avail is not None and avail > 0:
                status = 'open'
                display_status = f"남은자리 {avail}명"
            else:
                status = 'unknown'
                display_status = status_text or "알 수 없음"

            # --- changed: 배별 어종(fish) 추출 ---
            ship_fish = None
            # 1) 선박 테이블 내부에서 어종 셀렉터 우선 탐색
            ship_fish_el = (
                t.select_one('.ship_info .fish') or
                t.select_one('.ship_info2 .fish') or
                t.select_one('.fish') or
                t.select_one('div.fish') or
                t.select_one('span.fish') or
                t.select_one('.ship_kinds') or
                t.select_one('.ship_kind') or
                t.select_one('.tags') or
                t.select_one('.tag_area')
            )
            if ship_fish_el:
                ship_fish_text = ship_fish_el.get_text(" ", strip=True)
                # 라벨 제거 (낚시종류:, 어종: 등)
                ship_fish = _sanitize_fish_text(ship_fish_text)
            
            # 2) 라벨 기반 탐색 (테이블 내 "낚시종류" 또는 "어종" 라벨)
            if not ship_fish:
                lbl = t.find(string=re.compile(r'(낚시\s*종류|어종)', re.I))
                if lbl:
                    p = getattr(lbl, 'parent', None)
                    if p and getattr(p, 'name', None) == 'td':
                        sib = p.find_next_sibling('td')
                        if sib:
                            txt = sib.get_text(" ", strip=True)
                            ship_fish = _sanitize_fish_text(txt)
                    if not ship_fish:
                        nxt = lbl.find_next()
                        if nxt and getattr(nxt, 'get_text', None):
                            txt = nxt.get_text(" ", strip=True)
                            ship_fish = _sanitize_fish_text(txt)
            
            # 3) 페이지 전체(day_block) 어종을 최종 폴백
            if not ship_fish:
                ship_fish = fish
            # ---------------------------------------
            
            # debug: 파싱된 항목 콘솔 출력
            if debug_enabled:
                try:
                    print(json.dumps({
                        "DEBUG_SCHEDULE_ENTRY": {
                            "ship_name": ship_name,
                            "status": status,
                            "available": avail,
                            "display_status": display_status,
                            "raw_status_text": status_text,
                            "fish": ship_fish,  # 배별 어종
                            "query_date": display_date,
                            "row_html_len": len(str(t))
                        }
                    }, ensure_ascii=False))
                except Exception:
                    print("DEBUG_SCHEDULE_ENTRY:", ship_name, status, avail, display_status, ship_fish)
            
            # 배 이름 정리 (예약하기 등 제거)
            ship_name = _clean_ship_name(ship_name)

            # 유효한 배 이름인지 검증
            if not _is_valid_ship_name(ship_name, {known_ship_name} if known_ship_name else None):
                continue
            
            entries.append({
                "ship_name": ship_name,
                "status": status,
                "available": avail,
                "raw_status_text": status_text,
                "display_status": display_status,
                "row_html": str(t),
                "query_date": display_date,
                "fish": ship_fish  # 배별 어종
            })

        result = {"matched": True, "entries": entries, "date_id": date_id, "source_url": final_url, "tide": tide}
        return _store_cached_result(cache_key, result)

        # 일반 게시판 패턴
    else:
        if debug_enabled:
            print("DEBUG: 일반 게시판 패턴 시작")
        tide = None
        # new-div-YYYYMMDD 컨테이너에서 선박별 행을 추출
        entries = []
        date8 = f"{int(year):04d}{int(month):02d}{int(day):02d}"

        # 대표 컨테이너 찾기
        container = soup.select_one(f"div#new-div-{date8}") or soup.select_one(f"div.new-divs, .new-divs")
        if debug_enabled:
            print(f"DEBUG_CONTAINER: date8={date8}, container_found={container is not None}")
            if container:
                print(f"DEBUG_CONTAINER_ID: {container.get('id', 'no-id')}, class: {container.get('class', [])}")

        # 물때 정보 추출 (jeil-panel tr의 data-str 속성에서)
        if container:
            jeil_panel_tr = container.select_one('tr.jeil-panel')
            if jeil_panel_tr and jeil_panel_tr.has_attr('data-str'):
                data_str = jeil_panel_tr['data-str']
                m = re.search(r'(\d+)\s*물', data_str)
                if m:
                    tide = f"{m.group(1)}물"

        # 일반 게시판에서도 어종 추출 시도
        fish = None
        if container:
            # 1순위: div#fish 또는 .fish 클래스
            fish_el = container.select_one('div#fish') or container.select_one('.fish') or soup.select_one('div#fish')
            if fish_el:
                fish = _sanitize_fish_text(fish_el.get_text(" ", strip=True))
            
            # 2순위: ★어종★ 패턴 추출 (야무진 사이트 패턴)
            if not fish:
                all_text = container.get_text(" ", strip=True)
                # ★...★ 패턴 매칭 (완벽한 매칭, 비탐욕적)
                star_matches = re.findall(r'★\s*([^★]+?)\s*★', all_text)
                if star_matches:
                    # 첫 번째 ★...★ 패턴을 어종으로 간주
                    fish_candidate = star_matches[0].strip()
                    # 불필요한 정보 제거 (금액, 예선 등)
                    # "[" 이후는 제거 (금액 정보)
                    if '[' in fish_candidate:
                        fish_candidate = fish_candidate.split('[')[0].strip()
                    # " 탐사" 이후는 제거
                    if ' 탐사' in fish_candidate:
                        fish_candidate = fish_candidate.split(' 탐사')[0].strip()
                    if fish_candidate:
                        fish = fish_candidate
            
            # 3순위: 낚시종류 이미지 또는 텍스트 라벨
            if not fish:
                # 야무진 사이트: 이미지 아이콘 사용
                label_img = container.find('img', alt='낚시종류')
                if label_img:
                    # 이미지의 부모 td 찾기
                    label_td = label_img.find_parent('td')
                    if label_td:
                        fish_td = label_td.find_next_sibling('td')
                        if fish_td:
                            fish = fish_td.get_text(" ", strip=True)
                else:
                    # 텍스트 라벨로 "낚시종류" 찾기
                    label_tag = container.find(lambda tag: tag.name == 'div' and tag.string and tag.string.strip() == '낚시종류')
                    if label_tag:
                        label_td = label_tag.find_parent('td')
                        if label_td:
                            fish_td = label_td.find_next_sibling('td')
                            if fish_td:
                                fish = fish_td.get_text(" ", strip=True)

        # 컨테이너 내 tr을 우선 사용, 없으면 문서 전체 tr로 폴백
        rows = []
        if container:
            rows = container.select("tr") or []
        if not rows:
            rows = soup.select("tr")
        
        if debug_enabled:
            print(f"DEBUG_ROWS: container_rows={len(container.select('tr') if container else 0)}, total_rows={len(rows)}")
        
        exclude_keywords = {"공지사항", "입금대기", "선박명", "공지", "오늘:"}
        current_fish = fish  # 페이지 레벨 어종으로 시작

        for tr in rows:
            tds = tr.find_all("td")
            if debug_enabled:
                print(f"DEBUG_TR: tds_count={len(tds)}, tr_text='{tr.get_text(strip=True)[:50]}...'")
            if not tds:
                continue

            # --- 공지 행에서 어종 추출 ---
            is_notice = False
            # <img alt="공지">
            img = tds[0].find('img', alt='공지')
            if img:
                is_notice = True
            # <div>공지</div>
            div = tds[0].find('div')
            if div and '공지' in div.get_text(strip=True):
                is_notice = True
            if is_notice and len(tds) >= 2:
                # 공지 행의 어종 정보 추출 (단, 안내문 스타일은 무시)
                notice_area_fish = _extract_fish_from_notice_area(tr)
                if notice_area_fish:
                    current_fish = notice_area_fish
                    continue

                # 1) td 내 모든 텍스트 노드에서 어종 키워드 추출
                all_texts = []
                # 모든 텍스트 노드 수집 (중첩 태그 포함)
                for elem in tds[1].descendants:
                    if elem.name is None:
                        txt = str(elem).strip()
                        if txt:
                            all_texts.append(txt)
                found_fish = []
                for txt in all_texts:
                    extracted = _extract_known_fish(txt)
                    if extracted:
                        for fish_name in extracted.split(', '):
                            if fish_name not in found_fish:
                                found_fish.append(fish_name)
                if found_fish:
                    current_fish = ', '.join(found_fish)
                    continue
                # 2) 전체 텍스트에서 키워드 추출 (백업)
                notice_fish = tds[1].get_text(" ", strip=True)
                notice_fish = notice_fish.replace('\n', ' ').replace('\r', ' ')
                notice_fish = ' '.join(notice_fish.split())
                extracted_notice_fish = _extract_known_fish(notice_fish)
                if extracted_notice_fish:
                    current_fish = extracted_notice_fish
                elif notice_fish and len(notice_fish) <= 20 and not re.match(r'^[0-9a-zA-Z\(\)\[\]#]', notice_fish) and notice_fish.count('.') < 2:
                    current_fish = _sanitize_fish_text(notice_fish)
                continue

            # 어종 정보 행인지 확인 (td가 2개이고 첫번째에 '낚시종류' 포함)
            first_td_text = tds[0].get_text(" ", strip=True)
            if '낚시종류' in first_td_text and len(tds) >= 2:
                current_fish = _sanitize_fish_text(tds[1].get_text(" ", strip=True).strip())
                # 어종 정보 행은 보트가 아니므로 건너뜀
                continue

            # 보트 행이 아니면 건너뜀 (td 갯수 등)
            if len(tds) < 3:
                continue

            # 1번째 td에서 선박명 추출
            ship_name = tds[0].get_text(" ", strip=True)

            if debug_enabled:
                print(f"DEBUG_SHIP_ROW: ship_name='{ship_name}', tds_count={len(tds)}")
                for i, td in enumerate(tds):
                    print(f"  TD[{i}]: '{td.get_text(strip=True)}'")

            # 불필요한 행(헤더/공지 등) 제거
            if not ship_name:
                continue
            lowered = ship_name.replace(" ", "")
            skip = False
            for kw in exclude_keywords:
                if kw in ship_name or kw in lowered:
                    skip = True
                    break
            if skip:
                continue

            # 배별 어종 추출 시도 (TD[1]에서 특수문자 기반)
            ship_fish = None
            if len(tds) >= 2:
                ship_fish = _extract_fish_from_notice_area(tds[1])
                td1_text = tds[1].get_text(strip=True)
                if debug_enabled:
                    print(f"DEBUG_TD1_TEXT: '{td1_text}'")
                if not ship_fish:
                    ship_fish = _extract_fish_from_special_marker(td1_text)
                if debug_enabled:
                    print(f"DEBUG_EXTRACTED_FISH: '{ship_fish}'")
            
            # 배별 어종이 없으면 페이지 레벨 어종 사용
            if not ship_fish:
                ship_fish = current_fish

            # 3번째 td (또는 admin-right div)가 실제 상태/잔여 정보를 가지고 있는 경우 추출
            admin_div = None
            if len(tds) >= 3:
                admin_div = tds[2].select_one('div[id^="admin-right-"]')
            if not admin_div:
                admin_div = tr.select_one('div[id^="admin-right-"]')

            raw_status_text = ""
            available = None
            status_type = "unknown"

            if admin_div:
                img = admin_div.find("img")
                if img and img.has_attr("alt"):
                    raw_status_text = img["alt"].strip()
                else:
                    raw_status_text = admin_div.get_text(" ", strip=True)

                if re.search(r'점검일', raw_status_text):
                    status_type = "maintenance"
                    available = 0
                else:
                    m = re.search(r'남은\s*자리\s*[:：]?\s*(\d+)', raw_status_text) or                             re.search(r'남은자리\s*(\d+)', raw_status_text) or                             re.search(r'(\d+)\s*명', raw_status_text)

                    if m:
                        try:
                            available = int(m.group(1))
                            status_type = "open"
                        except Exception:
                            available = None
                            status_type = "unknown"
                    elif re.search(r'예약완료|예약 완료', raw_status_text):
                        status_type = "reserved"
                        available = 0
                    elif re.search(r'매진|마감|예약마감', raw_status_text):
                        status_type = "full"
                        available = 0
                    else:
                        status_type = "unknown"
            else:
                second_text = tds[1].get_text(" ", strip=True)
                raw_status_text = second_text
                if re.search(r'입금대기', second_text):
                    status_type = "pending"
                elif re.search(r'예약\s*완료', raw_status_text):
                    status_type = "reserved"
                    available = 0
                else:
                    status_type = "unknown"

            display_status = "-"
            if status_type == "maintenance":
                display_status = "점검일"
            elif status_type == "reserved":
                display_status = "예약마감"
            elif status_type == "open" and available is not None:
                display_status = f"남은자리 {available}명"
            elif status_type == "full":
                display_status = "예약마감"
            elif status_type == "pending":
                display_status = "입금대기"
            else:
                display_status = raw_status_text or "알 수 없음"

            # debug: 출력하여 파싱 결과 확인
            if debug_enabled:
                try:
                    print(json.dumps({
                        "DEBUG_BOARD_ENTRY": {
                            "ship_name": ship_name,
                            "status": status_type,
                            "available": available,
                            "display_status": display_status,
                            "raw_status_text": raw_status_text,
                            "fish": ship_fish,
                            "row_html_len": len(str(tr))
                        }
                    }, ensure_ascii=False))
                except Exception:
                    print("DEBUG_BOARD_ENTRY:", ship_name, status_type, available, display_status, ship_fish)

            # 유효한 배 이름인지 검증
            if not _is_valid_ship_name(ship_name, {known_ship_name} if known_ship_name else None):
                continue

            # 배 이름 정리 (예약하기 등 제거)
            ship_name = _clean_ship_name(ship_name)

            entries.append({
                "ship_name": ship_name,
                "status": status_type,
                "available": available,
                "raw_status_text": raw_status_text,
                "display_status": display_status,
                "row_html": str(tr),
                "fish": ship_fish
            })

        # 폴백 2: 위 방식으로 entries가 비면 admin-right 블록을 직접 스캔
        if not entries:
            # 모든 공지 tr을 수집하여 어종 매핑 구축
            notice_fish_map = {}
            all_trs = soup.select('tr')
            for idx, tr_item in enumerate(all_trs):
                tds2 = tr_item.find_all('td')
                if len(tds2) < 2:
                    continue
                left = tds2[0]
                is_notice2 = False
                if left.find('img', alt='공지'):
                    is_notice2 = True
                dv = left.find('div')
                if dv and '공지' in dv.get_text(strip=True):
                    is_notice2 = True
                if is_notice2:
                    notice_area_fish = _extract_fish_from_notice_area(tr_item)
                    if notice_area_fish:
                        for j in range(idx+1, len(all_trs)):
                            notice_fish_map[id(all_trs[j])] = notice_area_fish
                        continue

                    # 오른쪽 td 전체 텍스트에서 키워드
                    texts = []
                    for elem in tds2[1].descendants:
                        if elem.name is None:
                            t = str(elem).strip()
                            if t:
                                texts.append(t)
                    found = []
                    for t in texts:
                        extracted = _extract_known_fish(t)
                        if extracted:
                            for fish_name in extracted.split(', '):
                                if fish_name not in found:
                                    found.append(fish_name)
                    if found:
                        # 이 공지 tr 이후의 모든 tr에 어종 적용 (다음 공지가 나오기 전까지)
                        fish_val = ', '.join(found)
                        for j in range(idx+1, len(all_trs)):
                            notice_fish_map[id(all_trs[j])] = fish_val
            
            def _fish_from_notice_before(node):
                return notice_fish_map.get(id(node), None)

            for adm in soup.select('div[id^="admin-right-"]'):
                tr = adm.find_parent('tr')
                if not tr:
                    continue
                tds3 = tr.find_all('td')
                ship_name = ''
                local_fish = None
                
                # 1) 현재 tr의 첫 td에서 선박명 추출
                if tds3:
                    ship_name = tds3[0].get_text(' ', strip=True)
                if len(tds3) >= 2:
                    local_fish = _extract_fish_from_notice_area(tds3[1])
                # 문서 전체 tr 스캔 (테이블 경계 무시)
                all_trs_to_scan = soup.find_all('tr')
                idx_current = -1
                for i, t_item in enumerate(all_trs_to_scan):
                    if t_item is tr:
                        idx_current = i
                        break
                
                if not local_fish:
                    # 현재 tr 이후의 tr들에서 공지 행 탐색
                    for j in range(idx_current + 1, len(all_trs_to_scan)):
                        prev_tr = all_trs_to_scan[j]
                        prev_tds = prev_tr.find_all('td')
                        if len(prev_tds) >= 2:
                            left = prev_tds[0]
                            is_n = False
                            if left.find('img', alt='공지'):
                                is_n = True
                            dv = left.find('div')
                            if dv and '공지' in dv.get_text(strip=True):
                                is_n = True
                            if is_n:
                                texts = []
                                for elem in prev_tds[1].descendants:
                                    if elem.name is None:
                                        t = str(elem).strip()
                                        if t:
                                            texts.append(t)
                                found = []
                                for t in texts:
                                    nt = _norm(t)
                                    for w in FISH_KEYWORDS:
                                        if _norm(w) in nt and w not in found:
                                            found.append(w)
                                if found:
                                    local_fish = ', '.join(found)
                                    break
                            # 선박명이 없으면 이전 tr에서 선박명도 추출
                            if not ship_name and prev_tds[0]:
                                ship_name = prev_tds[0].get_text(' ', strip=True)

                if not ship_name:
                    continue

                # 상태/잔여 계산
                raw_status_text = ''
                img = adm.find('img')
                if img and img.has_attr('alt'):
                    raw_status_text = img['alt'].strip()
                else:
                    raw_status_text = adm.get_text(' ', strip=True)

                available = None
                status_type = 'unknown'
                if re.search(r'점검일', raw_status_text):
                    status_type = 'maintenance'
                    available = 0
                else:
                    m = re.search(r'남은\s*자리\s*[:：]?\s*(\d+)', raw_status_text) or \
                        re.search(r'남은자리\s*(\d+)', raw_status_text) or \
                        re.search(r'(\d+)\s*명', raw_status_text)
                    if m:
                        try:
                            available = int(m.group(1))
                            status_type = 'open'
                        except Exception:
                            available = None
                            status_type = 'unknown'
                    elif re.search(r'예약완료|예약 완료', raw_status_text):
                        status_type = 'reserved'
                        available = 0
                    elif re.search(r'매진|마감|예약마감', raw_status_text):
                        status_type = 'full'
                        available = 0

                # 배 이름 정리 (예약하기 등 제거)
                ship_name = _clean_ship_name(ship_name)

                # 유효한 배 이름인지 검증
                if not _is_valid_ship_name(ship_name, {known_ship_name} if known_ship_name else None):
                    continue

                fish_local = local_fish or _fish_from_notice_before(tr) or fish or None
                entries.append({
                    'ship_name': ship_name,
                    'status': status_type,
                    'available': available,
                    'raw_status_text': raw_status_text,
                    'display_status': '-',
                    'row_html': str(tr),
                    'fish': fish_local
                })

        # matched True로 반환하되 entries가 비어있을 수 있음
        result = {
            "matched": True,
            "entries": entries,
            "source_url": final_url,
            "raw_html": resp.text[:1000],  # 디버깅용 요약
            "tide": tide
        }
        return _store_cached_result(cache_key, result)

# 예시: 조회 함수에서 지역 필터링 적용
def filter_entries_by_region(entries, selected_regions):
    # selected_regions: ["인천", "안산", ...]
    return [e for e in entries if e.get("city") in selected_regions]
