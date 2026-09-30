"""기존 낚시 기록 엑셀을 DB 초기값으로 옮기기 위한 순수 변환.

DB·Flask 를 모른다(파싱/IO 분리 원칙). 엑셀은 초기값 설정에 한 번만 쓰고
앱에 업로드 기능은 두지 않는다 - docs/superpowers/specs/
2026-09-30-fishing-log-data-model-design.md §3.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime

SHOP_ALIASES = {
    '테무': 'Temu',
    'temu': 'Temu',
    'aliexpress': 'AliExpress',
    '에프마켓인천': '에프마켓인천',
}
CATEGORY_ALIASES = {'줄': '라인', '낚시대': '로드'}
DEFAULT_CATEGORY = '기타'

SPECIES_ALIASES = {
    '쭈꾸미': '쭈꾸미', '주꾸미': '쭈꾸미', '쭈구미': '쭈꾸미', '쭈': '쭈꾸미',
    '갑오징어': '갑오징어', '갑': '갑오징어',
    '문어': '문어', '문': '문어',
    '우럭': '우럭', '광어': '광어', '농어': '농어', '놀래미': '놀래미', '낙지': '낙지',
}
PEOPLE = ('나', '마눌', '와이프', '엄마')

_SPECIES_PATTERN = '|'.join(sorted(SPECIES_ALIASES, key=len, reverse=True))
# 어종 뒤 숫자. 숫자 바로 뒤가 %·kg·호·시면 조과가 아니다("쭈70%", "2kg").
_CATCH_RE = re.compile(rf'({_SPECIES_PATTERN})\s*(\d+)(?!\d)(?!\s*(?:%|kg|호|시))')
_PERSON_RE = re.compile(r'(?<![가-힣])(' + '|'.join(PEOPLE) + r')(?![가-힣])')
_COLON_NAME_RE = re.compile(r'([가-힣A-Za-z]+)\s*:')


def _text(value):
    """셀 값을 앞뒤 공백 없는 문자열로. 비었으면 None. 12.0 같은 정수형
    실수는 '12'로."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def to_int(value):
    """금액 칸 → 원 단위 int. 숫자가 아닌 글("11만원")은 None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    text = _text(value)
    if text and re.fullmatch(r'[\d,]+', text):
        return int(text.replace(',', ''))
    return None


def normalize_shop(value):
    text = _text(value)
    if text is None:
        return None
    key = re.sub(r'\s+', '', text).lower()
    return SHOP_ALIASES.get(key, text)


def normalize_category(value):
    text = _text(value)
    if text is None:
        return DEFAULT_CATEGORY
    return CATEGORY_ALIASES.get(text, text)


def ship_match_key(name):
    """선사 이름 비교용 키: 공백 제거, 소문자, 끝의 '호' 제거."""
    key = re.sub(r'\s+', '', name or '').lower()
    if len(key) > 1 and key.endswith('호'):
        key = key[:-1]
    return key


def extract_ship_name(content):
    """출조 '내용' 칸에서 선사명을 뽑는다. ' - '나 '(' 앞부분을 보고, 그 안에
    '호'로 끝나는 단어가 있으면 그 단어를 쓴다. 나머지 글은 메모로 돌려준다
    (추출이 틀리면 스크립트의 --ship-map 으로 바로잡는다)."""
    text = content.strip()
    head = re.split(r'\s+-\s+|\(', text, maxsplit=1)[0].strip()
    # '호' 한 글자 단어("가나다 호")는 선사명이 아니다 - 두 글자 이상만 본다.
    ho_words = [w for w in head.split() if len(w) > 1 and w.endswith('호')]
    name = ho_words[0] if ho_words else (head or text)
    rest = text.replace(name, '', 1).strip(' -')
    rest = re.sub(r'\s{2,}', ' ', rest).strip()
    return name, (rest or None)


def parse_catches(text):
    """조과 문장에서 (사람, 어종, 마릿수)를 뽑는다. 단순한 형태만 인식하고,
    인식에 쓰이지 않은 숫자가 원문에 남아 있으면 두 번째 값을 True 로 돌려
    호출자가 경고하게 한다(틀린 숫자를 넣느니 비워 둔다)."""
    text = _text(text)
    if text is None:
        return [], False
    catches = []
    who = '나'
    pos = 0
    leftovers = []
    for match in _CATCH_RE.finditer(text):
        gap = text[pos:match.start()]
        named = _COLON_NAME_RE.findall(gap)
        people = _PERSON_RE.findall(gap)
        if named:
            who = named[-1]
        elif people:
            who = people[-1]
        catches.append({'who': who, 'species': SPECIES_ALIASES[match.group(1)],
                        'count': int(match.group(2))})
        leftovers.append(gap)
        pos = match.end()
    leftovers.append(text[pos:])
    return catches, bool(re.search(r'\d', ''.join(leftovers)))


YEAR_HEADER = ['일자', '함께', '항구', '지역', '내용', '어종', '품목', '비고', '가격', '조과']
TRIP_KINDS = {'선비', '배'}
CANCEL_WORDS = ('취소', '최소')  # '최소'는 실제 엑셀에 있던 오타
SHIPS_SHEET = '낚시배'
IGNORED_SHEETS = {'지도'}
_TRAVEL_RE = re.compile(r'\d+시간(\s*\d+분)?|\d+분')


@dataclass
class SeedIssue:
    sheet: str
    row: int
    reason: str
    text: str = ''


@dataclass
class ShipSeed:
    name: str
    region: str | None = None
    port: str | None = None
    travel_time: str | None = None
    memo: str | None = None


@dataclass
class TripSeed:
    trip_date: date
    status: str
    ship_name: str
    cost: int | None
    companions: str | None
    species: list
    catches: list
    catch_raw: str | None
    memo: str | None
    source_text: str


@dataclass
class PurchaseSeed:
    purchase_date: date
    shop: str | None
    item: str
    category: str
    price: int | None


@dataclass
class GearItemSeed:
    name: str
    memo: str


@dataclass
class SeedResult:
    ships: list = field(default_factory=list)
    trips: list = field(default_factory=list)
    purchases: list = field(default_factory=list)
    gear_items: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def _to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _join(*parts):
    kept = [p for p in parts if p]
    return '\n'.join(kept) or None


def _split_species(value):
    text = _text(value)
    if text is None:
        return []
    return [s.strip() for s in re.split(r'[,/]', text) if s.strip()]


def _parse_year_sheet(ws, today, ship_map, result, trip_ship_hints):
    sheet = ws.title
    rows = list(ws.iter_rows(values_only=True))
    header = [_text(c) for c in (list(rows[0])[:10] if rows else [])]
    if header != YEAR_HEADER:
        result.warnings.append(SeedIssue(sheet, 1, '헤더가 예상과 달라 시트를 건너뜀', ' '.join(filter(None, header))))
        return

    last_date = None
    for row_no, raw in enumerate(rows[1:], start=2):
        cells = list(raw)[:10]
        cells += [None] * (10 - len(cells))
        if all(_text(c) is None for c in cells):
            continue
        d_cell, who, port, region, content, species, kind, note, price, catch = cells
        content, kind, note = _text(content), _text(kind), _text(note)

        if _text(d_cell) == '합계' or (content is None and kind is None):
            result.skipped.append(SeedIssue(sheet, row_no, '합계 또는 금액만 있는 줄', _text(price) or ''))
            continue

        row_date = _to_date(d_cell)
        if row_date is None:
            if _text(d_cell) is not None:
                result.warnings.append(SeedIssue(sheet, row_no, '일자를 날짜로 읽지 못함 - 건너뜀', _text(d_cell)))
                continue
            if last_date is None:
                result.warnings.append(SeedIssue(sheet, row_no, '이어받을 일자가 없음 - 건너뜀', content or ''))
                continue
            row_date = last_date
        else:
            last_date = row_date

        if kind in TRIP_KINDS:
            status = 'planned' if row_date > today else 'done'
        elif kind is None and note and any(w in note for w in CANCEL_WORDS):
            status = 'cancelled'
        elif kind is None and _text(who):
            # 품목 칸만 비운 출조 줄(실제 엑셀에 있음) - 장비 구매 줄은 '함께'를
            # 채우지 않으므로 함께가 있으면 출조로 본다.
            status = 'planned' if row_date > today else 'done'
        else:
            status = None

        if status is None:
            if kind is None:
                result.warnings.append(SeedIssue(sheet, row_no, '품목 칸이 비어 기타로 분류', content))
            result.purchases.append(PurchaseSeed(
                purchase_date=row_date, shop=normalize_shop(note), item=content,
                category=normalize_category(kind), price=to_int(price)))
            continue

        if content is None:
            result.warnings.append(SeedIssue(sheet, row_no, '출조인데 내용(선사) 칸이 비어 건너뜀'))
            continue
        if ship_map and content in ship_map:
            # 보정표로 선사명만 정하고, 원문(출항 시각 등)은 메모에 그대로 남긴다
            ship_name, rest = ship_map[content], content
        else:
            ship_name, rest = extract_ship_name(content)
        catch_raw = _text(catch)
        catches, leftover_digits = parse_catches(catch_raw)
        if leftover_digits:
            result.warnings.append(SeedIssue(sheet, row_no, '조과 문장에 인식 못 한 숫자가 있음 - 원문만 보관', catch_raw))
        result.trips.append(TripSeed(
            trip_date=row_date, status=status, ship_name=ship_name, cost=to_int(price),
            companions=_text(who), species=_split_species(species), catches=catches,
            catch_raw=catch_raw, memo=_join(rest, note), source_text=content))
        trip_ship_hints.setdefault(ship_match_key(ship_name), ShipSeed(
            name=ship_name, region=_text(region), port=_text(port)))


def _parse_ships_sheet(ws, result, ships):
    region = port = None
    for row_no, raw in enumerate(ws.iter_rows(values_only=True), start=1):
        cells = [_text(c) for c in raw]
        if not any(cells):
            continue
        cells += [None] * (4 - len(cells))
        if cells[0]:
            region, port = cells[0], cells[2]
        elif cells[2]:
            port = cells[2]
        name = cells[3]
        if not name:
            result.warnings.append(SeedIssue(ws.title, row_no, '선사명(3열)이 비어 건너뜀', ' '.join(filter(None, cells))))
            continue
        travel_time = None
        memos = []
        for value in cells[4:]:
            if not value:
                continue
            if travel_time is None and _TRAVEL_RE.fullmatch(value):
                travel_time = value
            else:
                memos.append(value)
        key = ship_match_key(name)
        memo = ' '.join(memos) or None
        if key in ships:
            ship = ships[key]
            ship.memo = _join(ship.memo, memo)
            ship.travel_time = ship.travel_time or travel_time
        else:
            ships[key] = ShipSeed(name=name, region=region, port=port,
                                  travel_time=travel_time, memo=memo)


def _parse_gear_sheet(ws, result):
    lines = []
    for raw in ws.iter_rows(values_only=True):
        values = [v for v in (_text(c) for c in raw) if v]
        if values:
            lines.append(' '.join(values))
    if lines:
        result.gear_items.append(GearItemSeed(name=ws.title.strip(), memo='\n'.join(lines)))


def parse_workbook(wb, today, ship_map=None):
    """워크북 전체를 SeedResult 로 바꾼다. 줄 단위로 격리 - 해석 못 한 줄은
    warnings/skipped 에 남기고 계속한다."""
    result = SeedResult()
    sheet_ships = {}
    trip_ship_hints = {}
    for ws in wb.worksheets:
        title = ws.title.strip()
        if re.fullmatch(r'\d{4}', title):
            _parse_year_sheet(ws, today, ship_map, result, trip_ship_hints)
        elif title == SHIPS_SHEET:
            _parse_ships_sheet(ws, result, sheet_ships)
        elif title in IGNORED_SHEETS:
            continue
        else:
            _parse_gear_sheet(ws, result)

    for key, hint in trip_ship_hints.items():
        if key in sheet_ships:
            ship = sheet_ships[key]
            ship.region = ship.region or hint.region
            ship.port = ship.port or hint.port
        else:
            sheet_ships[key] = hint
    for trip in result.trips:
        trip.ship_name = sheet_ships[ship_match_key(trip.ship_name)].name
    result.ships = list(sheet_ships.values())
    return result
