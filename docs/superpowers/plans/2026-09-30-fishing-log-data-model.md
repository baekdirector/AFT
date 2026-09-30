# 낚시 기록 1단계 (데이터 모델 + 초기 이관) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 낚시 기록용 새 테이블 4개와, 기존 엑셀을 한 번만 DB로 옮기는 로컬 이관 스크립트를 만든다.

**Architecture:** 모델은 기존 관례대로 `src/models.py`에 추가하고 `db.create_all()`이 테이블을 만든다. 엑셀 해석은 DB를 모르는 순수 함수(`excel_seed.py`)로, DB 쓰기는 별도 모듈(`seed_runner.py`)로 나누고, `scripts/seed_fishing_log.py`는 인자 처리만 하는 얇은 진입점이다. 라우트·화면은 만들지 않는다.

**Tech Stack:** Python 3, Flask-SQLAlchemy(SQLite 테스트 / Neon Postgres 운영), openpyxl(이미 의존성에 있음), pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-fishing-log-data-model-design.md`

## Global Constraints

- 리포는 public이다. 실제 엑셀, 변환 결과, 동행자 호칭·실제 금액·조과 같은 개인 기록을 커밋하지 않는다. 테스트 엑셀은 테스트 코드 안에서 openpyxl로 만들고 값은 지어낸다.
- 새 라우트 · 템플릿 · API를 추가하지 않는다. 기존 테이블 · 라우트 · 테스트를 바꾸지 않는다.
- 새 파이썬 패키지를 추가하지 않는다(openpyxl은 이미 `src/requirements.txt`에 있다).
- 앱 import는 `from src.app import create_app`(wsgi.py와 같은 경로 → 같은 SQLite 파일). 모듈 내부 import는 기존 관례대로 `from db import db`, `from models import ...`(src가 sys.path에 있음).
- 금액은 원 단위 `int`, 날짜는 `datetime.date`, 시각은 기존 관례대로 `datetime.utcnow`.
- 허용값: 출조 status `planned` / `done` / `cancelled`, rating `again` / `maybe` / `never` / `None`.
- 테스트 실행: 작업 중에는 건드린 테스트 파일만(`python -m pytest tests/<file> -q`). 전체 스위트는 마지막 Task에서 한 번. 이미 알려진 무관한 실패 1건: `tests/test_admin_visits.py::test_admin_table_shows_full_datetime_in_kst_not_utc`.
- 커밋 메시지는 한국어, 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- 가격 칸에 숫자가 아닌 글("11만원", "무료")이 있으면 → 가격은 `None`, 줄은 정상 처리(크래시 없음). Task 2 `test_to_int_*`에서 고정.
- 일자 칸에 날짜형이 아닌 글("2025.10.02")이 있으면 → 그 줄은 경고 후 제외, 다음 줄의 날짜 이어받기는 그 줄의 영향을 받지 않음. Task 3 `test_text_date_is_warned_and_skipped`에서 고정.
- `낚시배` 시트에 같은 이름의 배가 두 지역에 나오면 → 하나로 합쳐져 `--commit`에서 UNIQUE 위반이 나지 않음. Task 3 `test_duplicate_ship_names_are_merged`, Task 4 `test_commit_inserts_all_rows`에서 고정.
- AFT에 같은 이름의 Boat가 둘 이상이면 → 자동 연결하지 않음(`boat_id` None). Task 4 `test_boat_link_only_when_name_unique`에서 고정.
- `--commit` 도중 오류가 나면 → 전부 롤백되어 테이블이 빈 상태로 남아 다시 실행할 수 있음. Task 4 `test_commit_rolls_back_on_error`에서 고정.

---

## File Structure

| 파일 | 역할 |
|---|---|
| `src/models.py` (수정) | `FishingShip`, `FishingTrip`, `GearItem`, `GearPurchase`, 상수 `TRIP_STATUSES`, `TRIP_RATINGS` 추가 |
| `src/services/fishing_log/__init__.py` (생성) | 패키지 표시(빈 파일 + 한 줄 docstring) |
| `src/services/fishing_log/excel_seed.py` (생성) | 엑셀 → `SeedResult` 순수 변환. DB · Flask 모름 |
| `src/services/fishing_log/seed_runner.py` (생성) | 미리보기 보고서 문자열 생성, 빈 테이블 확인, 한 트랜잭션 삽입, Boat 자동 연결 |
| `scripts/seed_fishing_log.py` (생성) | argparse 진입점. 미리보기는 DB 없이, `--commit`만 앱 생성 |
| `tests/test_fishing_log_models.py` (생성) | 모델 테스트 |
| `tests/test_fishing_log_seed.py` (생성) | 파서 테스트 (가짜 엑셀을 코드로 생성) |
| `tests/test_fishing_log_seed_runner.py` (생성) | DB 쓰기 · 보고서 · 스크립트 진입점 테스트 |

---

### Task 1: 모델 4개

**Files:**
- Modify: `src/models.py` (파일 끝에 추가)
- Test: `tests/test_fishing_log_models.py`

**Interfaces:**
- Produces:
  - `models.TRIP_STATUSES = ('planned', 'done', 'cancelled')`, `models.TRIP_RATINGS = ('again', 'maybe', 'never')`
  - `FishingShip(name, region, port, fleet, travel_time, memo, boat_id)` — 테이블 `fishing_ships`, `trips` backref
  - `FishingTrip(trip_date, status, ship / ship_id, cost, companions, rating, species, tags, catches, catch_raw, memo)` — 테이블 `fishing_trips`
  - `GearItem(name, kind, memo)` — 테이블 `gear_items`, `purchases` backref
  - `GearPurchase(purchase_date, shop, item, category, price, memo, gear / gear_id)` — 테이블 `gear_purchases`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_fishing_log_models.py`

```python
"""낚시 기록 모델 (spec §2)."""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError


def _ship(name='가나다호'):
    from models import FishingShip
    return FishingShip(name=name, region='테스트시', port='테스트항')


def test_trip_json_fields_default_to_empty_lists(app):
    from db import db
    from models import FishingTrip
    ship = _ship()
    trip = FishingTrip(trip_date=date(2026, 1, 3), status='done', ship=ship)
    db.session.add(trip)
    db.session.commit()

    saved = FishingTrip.query.one()
    assert saved.species == []
    assert saved.tags == []
    assert saved.catches == []
    assert saved.rating is None
    assert saved.ship.name == '가나다호'
    assert saved.created_at is not None and saved.updated_at is not None


def test_trip_catches_round_trip_as_json(app):
    from db import db
    from models import FishingTrip
    catches = [{'who': '나', 'species': '쭈꾸미', 'count': 12}]
    db.session.add(FishingTrip(trip_date=date(2026, 1, 3), status='done', ship=_ship(),
                               species=['쭈꾸미'], catches=catches))
    db.session.commit()
    assert FishingTrip.query.one().catches == catches


def test_ship_name_is_unique(app):
    from db import db
    db.session.add(_ship('가나다호'))
    db.session.commit()
    db.session.add(_ship('가나다호'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_ship_with_trips_cannot_be_deleted(app):
    from db import db
    from models import FishingTrip
    ship = _ship()
    db.session.add(FishingTrip(trip_date=date(2026, 1, 3), status='done', ship=ship))
    db.session.commit()

    db.session.delete(ship)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_deleting_gear_item_keeps_purchase_and_clears_link(app):
    from db import db
    from models import GearItem, GearPurchase
    gear = GearItem(name='테스트 릴', kind='릴')
    db.session.add(GearPurchase(purchase_date=date(2026, 2, 1), item='테스트 릴 본체',
                                category='릴', price=1000, gear=gear))
    db.session.commit()

    db.session.delete(gear)
    db.session.commit()

    purchase = GearPurchase.query.one()
    assert purchase.gear_id is None
    assert purchase.category == '릴'


def test_purchase_category_defaults_to_etc(app):
    from db import db
    from models import GearPurchase
    db.session.add(GearPurchase(purchase_date=date(2026, 2, 1), item='테스트 소품'))
    db.session.commit()
    assert GearPurchase.query.one().category == '기타'


def test_allowed_value_constants():
    import models
    assert models.TRIP_STATUSES == ('planned', 'done', 'cancelled')
    assert models.TRIP_RATINGS == ('again', 'maybe', 'never')
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_fishing_log_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'FishingTrip'` 등

- [ ] **Step 3: 구현** — `src/models.py` 끝에 추가

```python
# ---------------------------------------------------------------------------
# 낚시 기록 (admin 전용 개인 기록) - docs/superpowers/specs/
# 2026-09-30-fishing-log-data-model-design.md. 새 테이블만 추가하므로
# db.create_all() 이 만든다(ALTER 보정 불필요). 데이터가 작아 통계용
# 테이블은 두지 않고 화면에서 필요할 때 파이썬으로 집계한다.
# ---------------------------------------------------------------------------

TRIP_STATUSES = ('planned', 'done', 'cancelled')
TRIP_RATINGS = ('again', 'maybe', 'never')


class FishingShip(db.Model):
    """선사(선사 노트의 기준). 출조는 항상 선사 하나를 가리킨다 - 선사별
    집계("이 배 몇 번 탔나")의 기준이라 이름을 UNIQUE로 둔다. AFT 배 목록과는
    boat_id 로 선택적으로 연결한다(연결되면 예약현황·빈자리 알림으로 이동)."""
    __tablename__ = 'fishing_ships'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    region = db.Column(db.String(50), nullable=True)
    port = db.Column(db.String(100), nullable=True)
    fleet = db.Column(db.String(100), nullable=True)
    travel_time = db.Column(db.String(50), nullable=True)
    memo = db.Column(db.Text, nullable=True)
    boat_id = db.Column(db.Integer, db.ForeignKey('boats.id', ondelete='SET NULL'),
                        nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    boat = db.relationship('Boat')

    def __repr__(self):
        return f'<FishingShip {self.name}>'


class FishingTrip(db.Model):
    """출조 한 건. 항구·지역은 선사에만 둔다. 어종/태그/조과는 JSON 목록 -
    조과는 [{"who": "나", "species": "쭈꾸미", "count": 12}] 모양이고,
    catch_raw 에는 원문(엑셀 이관 시 조과 문장)을 그대로 보관한다."""
    __tablename__ = 'fishing_trips'

    id = db.Column(db.Integer, primary_key=True)
    trip_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default='done')
    # 출조가 있는 선사는 지울 수 없다 - ORM 이 ship_id 를 NULL 로 바꾸려다
    # NOT NULL 에 걸려 IntegrityError 가 난다(SQLite/Postgres 공통).
    ship_id = db.Column(db.Integer, db.ForeignKey('fishing_ships.id', ondelete='RESTRICT'),
                        nullable=False, index=True)
    cost = db.Column(db.Integer, nullable=True)
    companions = db.Column(db.String(100), nullable=True)
    rating = db.Column(db.String(16), nullable=True)
    species = db.Column(db.JSON, nullable=False, default=list)
    tags = db.Column(db.JSON, nullable=False, default=list)
    catches = db.Column(db.JSON, nullable=False, default=list)
    catch_raw = db.Column(db.Text, nullable=True)
    memo = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    ship = db.relationship('FishingShip', backref=db.backref('trips'))

    def __repr__(self):
        return f'<FishingTrip {self.trip_date} ship={self.ship_id}>'


class GearItem(db.Model):
    """내 장비 노트(예: 릴·로드 한 대에 대한 메모)."""
    __tablename__ = 'gear_items'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(50), nullable=True)
    memo = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<GearItem {self.name}>'


class GearPurchase(db.Model):
    """장비 구매 품목 1개 = 1행. "주문"은 테이블로 두지 않고 같은
    purchase_date + shop 으로 묶어 보여준다. 장비 노트를 지워도 구매 기록은
    남고 gear_id 만 NULL 이 된다."""
    __tablename__ = 'gear_purchases'

    id = db.Column(db.Integer, primary_key=True)
    purchase_date = db.Column(db.Date, nullable=False, index=True)
    shop = db.Column(db.String(100), nullable=True)
    item = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False, default='기타')
    price = db.Column(db.Integer, nullable=True)
    memo = db.Column(db.Text, nullable=True)
    gear_id = db.Column(db.Integer, db.ForeignKey('gear_items.id', ondelete='SET NULL'),
                        nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    gear = db.relationship('GearItem', backref=db.backref('purchases'))

    def __repr__(self):
        return f'<GearPurchase {self.purchase_date} {self.item[:20]}>'
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_fishing_log_models.py tests/test_models.py -q`
Expected: 모두 PASS (기존 `test_models.py`도 그대로 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/models.py tests/test_fishing_log_models.py
git commit -m "낚시 기록 모델 4개 추가 (선사·출조·장비 노트·장비 구매)"
```

---

### Task 2: 엑셀 값 해석 도우미 (순수 함수)

**Files:**
- Create: `src/services/fishing_log/__init__.py`
- Create: `src/services/fishing_log/excel_seed.py` (이 Task에서는 도우미만)
- Test: `tests/test_fishing_log_seed.py`

**Interfaces:**
- Produces (모두 `services.fishing_log.excel_seed`):
  - `to_int(value) -> int | None`
  - `normalize_shop(value: str | None) -> str | None`
  - `normalize_category(value: str | None) -> str` (없으면 `'기타'`)
  - `ship_match_key(name: str) -> str`
  - `extract_ship_name(content: str) -> tuple[str, str | None]` — (선사명, 나머지 글)
  - `parse_catches(text: str | None) -> tuple[list[dict], bool]` — (조과 목록, 인식 못 한 숫자가 남았는지)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_fishing_log_seed.py`

```python
"""엑셀 초기 이관 파서 (spec §3). 실제 엑셀은 커밋하지 않는다 - 값은 전부
지어낸 것이고, 필요한 엑셀은 테스트 안에서 openpyxl로 만든다."""
from services.fishing_log.excel_seed import (
    extract_ship_name, normalize_category, normalize_shop, parse_catches,
    ship_match_key, to_int,
)


def test_to_int_accepts_numbers_and_digit_strings():
    assert to_int(12000) == 12000
    assert to_int(12000.0) == 12000
    assert to_int(1234.6) == 1235
    assert to_int('12,000') == 12000


def test_to_int_returns_none_for_text_and_blanks():
    assert to_int('11만원') is None
    assert to_int('무료') is None
    assert to_int(None) is None
    assert to_int('') is None
    assert to_int(True) is None


def test_normalize_shop_merges_known_spellings():
    assert normalize_shop('테무') == 'Temu'
    assert normalize_shop('temu') == 'Temu'
    assert normalize_shop('aliexpress') == 'AliExpress'
    assert normalize_shop('Aliexpress') == 'AliExpress'
    assert normalize_shop('에프마켓 인천') == '에프마켓인천'
    assert normalize_shop('  가나낚시 ') == '가나낚시'
    assert normalize_shop(None) is None


def test_normalize_category_maps_synonyms_and_blank():
    assert normalize_category('줄') == '라인'
    assert normalize_category('낚시대') == '로드'
    assert normalize_category('에기') == '에기'
    assert normalize_category(None) == '기타'


def test_ship_match_key_ignores_spaces_case_and_trailing_ho():
    assert ship_match_key('가나다호') == ship_match_key(' 가나 다 ')
    assert ship_match_key('ABC호') == ship_match_key('abc')


def test_extract_ship_name_prefers_word_ending_in_ho():
    assert extract_ship_name('가나다호 - (농어, 우럭)') == ('가나다호', '(농어, 우럭)')
    assert extract_ship_name('라마낚시 바사호 문어') == ('바사호', '라마낚시 문어')
    assert extract_ship_name('테스트도 원강호(다른호)') == ('원강호', '테스트도 (다른호)')
    assert extract_ship_name('하늘폭스') == ('하늘폭스', None)
    assert extract_ship_name('가나다 호') == ('가나다 호', None)


def test_parse_catches_simple_forms():
    assert parse_catches('쭈 10, 갑 2') == (
        [{'who': '나', 'species': '쭈꾸미', 'count': 10},
         {'who': '나', 'species': '갑오징어', 'count': 2}], False)
    assert parse_catches('문어3마리') == ([{'who': '나', 'species': '문어', 'count': 3}], False)


def test_parse_catches_tracks_people():
    catches, leftover = parse_catches('마눌 문5, 나 문7')
    assert catches == [{'who': '마눌', 'species': '문어', 'count': 5},
                       {'who': '나', 'species': '문어', 'count': 7}]
    assert leftover is False

    catches, _ = parse_catches('마눌 쭈4,갑1')
    assert [c['who'] for c in catches] == ['마눌', '마눌']

    catches, _ = parse_catches('가: 쭈3, 나: 쭈5')
    assert [(c['who'], c['count']) for c in catches] == [('가', 3), ('나', 5)]


def test_parse_catches_ignores_percent_and_weight_and_flags_leftover_digits():
    catches, leftover = parse_catches('쭈 10, 입질 60~70%')
    assert catches == [{'who': '나', 'species': '쭈꾸미', 'count': 10}]
    assert leftover is True

    catches, leftover = parse_catches('쭈70%')
    assert catches == [] and leftover is True


def test_parse_catches_no_digits_is_not_a_warning():
    assert parse_catches('꽝') == ([], False)
    assert parse_catches('배 깨끗함') == ([], False)
    assert parse_catches(None) == ([], False)


def test_parse_catches_does_not_treat_na_inside_words_as_person():
    catches, _ = parse_catches('나름 괜찮음 쭈 3')
    assert catches == [{'who': '나', 'species': '쭈꾸미', 'count': 3}]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_fishing_log_seed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.fishing_log'`

- [ ] **Step 3: 구현**

`src/services/fishing_log/__init__.py`:

```python
"""admin 낚시 기록 (출조·장비 구매·선사 노트) 서비스."""
```

`src/services/fishing_log/excel_seed.py` (이 Task 범위):

```python
"""기존 낚시 기록 엑셀을 DB 초기값으로 옮기기 위한 순수 변환.

DB·Flask 를 모른다(파싱/IO 분리 원칙). 엑셀은 초기값 설정에 한 번만 쓰고
앱에 업로드 기능은 두지 않는다 - docs/superpowers/specs/
2026-09-30-fishing-log-data-model-design.md §3.
"""
import re

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
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_fishing_log_seed.py -q`
Expected: 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/services/fishing_log/__init__.py src/services/fishing_log/excel_seed.py tests/test_fishing_log_seed.py
git commit -m "낚시 기록 이관: 엑셀 값 해석 도우미(금액·구매처·선사명·조과)"
```

---

### Task 3: 워크북 전체 변환 `parse_workbook`

**Files:**
- Modify: `src/services/fishing_log/excel_seed.py` (dataclass들과 `parse_workbook` 추가)
- Test: `tests/test_fishing_log_seed.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 2의 `to_int`, `normalize_shop`, `normalize_category`, `ship_match_key`, `extract_ship_name`, `parse_catches`, `_text`
- Produces (모두 `services.fishing_log.excel_seed`):
  - `SeedIssue(sheet: str, row: int, reason: str, text: str = '')`
  - `ShipSeed(name: str, region: str | None = None, port: str | None = None, travel_time: str | None = None, memo: str | None = None)`
  - `TripSeed(trip_date: date, status: str, ship_name: str, cost: int | None, companions: str | None, species: list, catches: list, catch_raw: str | None, memo: str | None, source_text: str)`
  - `PurchaseSeed(purchase_date: date, shop: str | None, item: str, category: str, price: int | None)`
  - `GearItemSeed(name: str, memo: str)`
  - `SeedResult(ships, trips, purchases, gear_items, warnings, skipped)` — 모두 list
  - `parse_workbook(wb, today: date, ship_map: dict[str, str] | None = None) -> SeedResult`
  - 상수 `YEAR_HEADER`, `SHIPS_SHEET = '낚시배'`, `IGNORED_SHEETS = {'지도'}`

- [ ] **Step 1: 실패하는 테스트 추가** — `tests/test_fishing_log_seed.py` 끝에

```python
from datetime import date, datetime

from openpyxl import Workbook

from services.fishing_log.excel_seed import YEAR_HEADER, parse_workbook

TODAY = date(2026, 6, 15)


def _book(year_rows=None, ship_rows=None, extra_sheets=None, header=None):
    """가짜 엑셀. year_rows: 2026 시트의 데이터 줄(10칸 리스트)."""
    wb = Workbook()
    ws = wb.active
    ws.title = '2026'
    ws.append(header or YEAR_HEADER)
    for row in year_rows or []:
        ws.append(row)
    if ship_rows is not None:
        ships = wb.create_sheet('낚시배')
        for row in ship_rows:
            ships.append(row)
    for title, rows in (extra_sheets or {}).items():
        sheet = wb.create_sheet(title)
        for row in rows:
            sheet.append(row)
    return wb


def _row(d=None, who=None, port=None, region=None, content=None, species=None,
         kind=None, note=None, price=None, catch=None):
    return [d, who, port, region, content, species, kind, note, price, catch]


def test_trip_row_becomes_done_trip_with_ship():
    wb = _book([_row(datetime(2026, 5, 2), '솔로', '가항', '가시', '가나다호 - (쭈갑)',
                     '쭈꾸미, 갑오징어', '선비', '배 깨끗', 90000, '쭈 10, 갑 2')])
    result = parse_workbook(wb, TODAY)

    assert len(result.trips) == 1
    trip = result.trips[0]
    assert trip.trip_date == date(2026, 5, 2)
    assert trip.status == 'done'
    assert trip.ship_name == '가나다호'
    assert trip.cost == 90000
    assert trip.companions == '솔로'
    assert trip.species == ['쭈꾸미', '갑오징어']
    assert trip.catches == [{'who': '나', 'species': '쭈꾸미', 'count': 10},
                            {'who': '나', 'species': '갑오징어', 'count': 2}]
    assert trip.catch_raw == '쭈 10, 갑 2'
    assert trip.memo == '(쭈갑)\n배 깨끗'
    assert [(s.name, s.region, s.port) for s in result.ships] == [('가나다호', '가시', '가항')]


def test_future_trip_is_planned_and_kind_bae_is_trip():
    wb = _book([_row(datetime(2026, 7, 1), '마눌', '나항', '나시', '라마호', '문어', '배', None, 200000)])
    assert parse_workbook(wb, TODAY).trips[0].status == 'planned'


def test_cancelled_rows_including_typo():
    wb = _book([
        _row(datetime(2026, 4, 5), '솔로', '가항', '가시', '바사호', '우럭', None, '날씨로 취소'),
        _row(datetime(2026, 4, 12), '솔로', '가항', '가시', '아자호', None, None, '최소됨'),
    ])
    trips = parse_workbook(wb, TODAY).trips
    assert [(t.ship_name, t.status) for t in trips] == [('바사호', 'cancelled'), ('아자호', 'cancelled')]


def test_blank_date_carries_previous_date_for_purchases():
    wb = _book([
        _row(datetime(2026, 3, 1), content='테스트 에기 3개', kind='에기', note='테무', price=12000),
        _row(None, content='테스트 봉돌', kind='봉돌', note='테무', price='3,000'),
    ])
    purchases = parse_workbook(wb, TODAY).purchases
    assert [(p.purchase_date, p.item, p.category, p.shop, p.price) for p in purchases] == [
        (date(2026, 3, 1), '테스트 에기 3개', '에기', 'Temu', 12000),
        (date(2026, 3, 1), '테스트 봉돌', '봉돌', 'Temu', 3000),
    ]


def test_total_rows_and_price_only_rows_are_skipped():
    wb = _book([
        _row(datetime(2026, 3, 1), content='테스트 줄', kind='줄', note='가나낚시', price=5000),
        _row('합계', price=5000),
        _row(None, price=5000),
    ])
    result = parse_workbook(wb, TODAY)
    assert [p.category for p in result.purchases] == ['라인']
    assert len(result.skipped) == 2


def test_first_row_without_date_is_warned_and_skipped():
    wb = _book([_row(None, content='테스트 에기', kind='에기', price=1000)])
    result = parse_workbook(wb, TODAY)
    assert result.purchases == []
    assert any('이어받을 일자' in w.reason for w in result.warnings)


def test_text_date_is_warned_and_skipped():
    wb = _book([
        _row(datetime(2026, 3, 1), content='첫 품목', kind='에기', price=1000),
        _row('2026.03.05', content='글자 날짜 품목', kind='에기', price=1000),
        _row(None, content='이어받는 품목', kind='에기', price=1000),
    ])
    result = parse_workbook(wb, TODAY)
    assert [(p.item, p.purchase_date) for p in result.purchases] == [
        ('첫 품목', date(2026, 3, 1)), ('이어받는 품목', date(2026, 3, 1))]
    assert any('날짜로 읽지 못함' in w.reason for w in result.warnings)


def test_row_without_kind_or_cancel_becomes_etc_purchase_with_warning():
    wb = _book([_row(datetime(2026, 3, 1), content='분류 없는 물건', note='가나낚시', price=2000)])
    result = parse_workbook(wb, TODAY)
    assert [(p.item, p.category) for p in result.purchases] == [('분류 없는 물건', '기타')]
    assert any('기타' in w.reason for w in result.warnings)


def test_trip_price_missing_and_unrecognized_catch_warns():
    wb = _book([_row(datetime(2026, 5, 2), '솔로', '가항', '가시', '가나다호', '문어', '선비',
                     None, None, '나(12), 마눌(3)')])
    result = parse_workbook(wb, TODAY)
    trip = result.trips[0]
    assert trip.cost is None
    assert trip.catches == []
    assert trip.catch_raw == '나(12), 마눌(3)'
    assert any('조과' in w.reason for w in result.warnings)


def test_ship_map_overrides_extraction():
    wb = _book([_row(datetime(2026, 5, 2), '솔로', '가항', '가시', '25시 수평선호 (새벽)', '쭈꾸미', '선비')])
    result = parse_workbook(wb, TODAY, ship_map={'25시 수평선호 (새벽)': '25시 수평선호'})
    assert result.trips[0].ship_name == '25시 수평선호'
    assert result.trips[0].memo is None


def test_header_mismatch_skips_sheet():
    wb = _book([_row(datetime(2026, 5, 2), content='x', kind='에기', price=1)],
               header=['날짜', '내용'])
    result = parse_workbook(wb, TODAY)
    assert result.purchases == [] and result.trips == []
    assert any('헤더' in w.reason for w in result.warnings)


def test_ships_sheet_carries_region_port_and_reads_travel_time():
    wb = _book(ship_rows=[
        ['가시', None, '가항', '가나다호', '문어 전문'],
        [None, None, None, '라마호'],
        [None, None, '나항', '바사호', '50분', '추천받음'],
        ['나시', None, None, '아자호', '1시간 7분'],
        ['무시할 줄', None, None, None],
    ])
    result = parse_workbook(wb, TODAY)
    ships = {s.name: s for s in result.ships}
    assert (ships['가나다호'].region, ships['가나다호'].port, ships['가나다호'].memo) == ('가시', '가항', '문어 전문')
    assert (ships['라마호'].region, ships['라마호'].port) == ('가시', '가항')
    assert (ships['바사호'].port, ships['바사호'].travel_time, ships['바사호'].memo) == ('나항', '50분', '추천받음')
    assert (ships['아자호'].region, ships['아자호'].port, ships['아자호'].travel_time) == ('나시', None, '1시간 7분')
    assert any('선사명' in w.reason for w in result.warnings)


def test_duplicate_ship_names_are_merged():
    wb = _book(ship_rows=[
        ['가시', None, '가항', '빅보스호', '메모1'],
        ['나시', None, '나항', '빅보스 호', '메모2'],
    ])
    ships = parse_workbook(wb, TODAY).ships
    assert len(ships) == 1
    assert ships[0].name == '빅보스호'
    assert ships[0].region == '가시'
    assert ships[0].memo == '메모1\n메모2'


def test_trip_ship_matches_sheet_ship_by_normalized_name():
    wb = _book(
        [_row(datetime(2026, 5, 2), '솔로', '딴항', '딴시', '가나다 호', '문어', '선비')],
        ship_rows=[['가시', None, '가항', '가나다호', '메모']],
    )
    result = parse_workbook(wb, TODAY)
    assert [s.name for s in result.ships] == ['가나다호']
    assert result.ships[0].port == '가항'
    assert result.trips[0].ship_name == '가나다호'


def test_gear_sheets_with_content_become_gear_items_and_map_is_ignored():
    wb = _book(extra_sheets={
        '테스트 릴': [['기어비 5.6', '우핸들'], ['합사 1호']],
        '빈 장비': [],
        '지도': [['무시']],
    })
    items = parse_workbook(wb, TODAY).gear_items
    assert [(g.name, g.memo) for g in items] == [('테스트 릴', '기어비 5.6 우핸들\n합사 1호')]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_fishing_log_seed.py -q`
Expected: FAIL — `ImportError: cannot import name 'YEAR_HEADER'`

- [ ] **Step 3: 구현** — `excel_seed.py`의 import 줄을 바꾸고 파일 끝에 추가

import 줄 교체:

```python
import re
from dataclasses import dataclass, field
from datetime import date, datetime
```

파일 끝에 추가:

```python
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
            ship_name, rest = ship_map[content], None
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
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_fishing_log_seed.py -q`
Expected: 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/services/fishing_log/excel_seed.py tests/test_fishing_log_seed.py
git commit -m "낚시 기록 이관: 워크북 전체 변환(연도·낚시배·장비 시트)"
```

---

### Task 4: DB 쓰기 · 미리보기 보고서 `seed_runner`

**Files:**
- Create: `src/services/fishing_log/seed_runner.py`
- Test: `tests/test_fishing_log_seed_runner.py`

**Interfaces:**
- Consumes: Task 1 모델, Task 3 `SeedResult`/`ShipSeed`/`TripSeed`/`PurchaseSeed`/`GearItemSeed`/`SeedIssue`
- Produces (모두 `services.fishing_log.seed_runner`):
  - `class SeedRefused(Exception)`
  - `tables_are_empty() -> bool` (앱 컨텍스트 필요)
  - `commit_seed(result: SeedResult) -> dict[str, int]` — 키 `ships`, `trips`, `purchases`, `gear_items`. 비어 있지 않으면 `SeedRefused`, 오류 시 롤백 후 예외 전파.
  - `format_report(result: SeedResult) -> str` (DB 불필요)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_fishing_log_seed_runner.py`

```python
"""이관 DB 쓰기 · 미리보기 보고서 (spec §3.1, §4)."""
from datetime import date

import pytest

from services.fishing_log.excel_seed import (
    GearItemSeed, PurchaseSeed, SeedIssue, SeedResult, ShipSeed, TripSeed,
)


def _result():
    return SeedResult(
        ships=[ShipSeed(name='가나다호', region='가시', port='가항', travel_time='50분', memo='메모'),
               ShipSeed(name='라마호')],
        trips=[TripSeed(trip_date=date(2026, 5, 2), status='done', ship_name='가나다호', cost=90000,
                        companions='솔로', species=['쭈꾸미'],
                        catches=[{'who': '나', 'species': '쭈꾸미', 'count': 10}],
                        catch_raw='쭈 10', memo=None, source_text='가나다호'),
               TripSeed(trip_date=date(2026, 7, 1), status='planned', ship_name='라마호', cost=None,
                        companions=None, species=[], catches=[], catch_raw=None, memo=None,
                        source_text='라마호 오전배')],
        purchases=[PurchaseSeed(purchase_date=date(2026, 3, 1), shop='Temu', item='테스트 에기',
                                category='에기', price=12000)],
        gear_items=[GearItemSeed(name='테스트 릴', memo='우핸들')],
        warnings=[SeedIssue('2026', 7, '조과 문장에 인식 못 한 숫자가 있음 - 원문만 보관', '나(12)')],
        skipped=[SeedIssue('2026', 9, '합계 또는 금액만 있는 줄', '12000')],
    )


def test_commit_inserts_all_rows(app):
    from models import FishingShip, FishingTrip, GearItem, GearPurchase
    from services.fishing_log.seed_runner import commit_seed

    counts = commit_seed(_result())

    assert counts == {'ships': 2, 'trips': 2, 'purchases': 1, 'gear_items': 1}
    trip = FishingTrip.query.filter_by(status='done').one()
    assert trip.ship.name == '가나다호'
    assert trip.catches == [{'who': '나', 'species': '쭈꾸미', 'count': 10}]
    assert trip.rating is None
    ship = FishingShip.query.filter_by(name='가나다호').one()
    assert (ship.region, ship.port, ship.travel_time) == ('가시', '가항', '50분')
    assert GearPurchase.query.one().shop == 'Temu'
    assert GearItem.query.one().name == '테스트 릴'


def test_commit_refuses_when_any_table_has_rows(app):
    from db import db
    from models import GearItem
    from services.fishing_log.seed_runner import SeedRefused, commit_seed, tables_are_empty

    db.session.add(GearItem(name='이미 있음'))
    db.session.commit()

    assert tables_are_empty() is False
    with pytest.raises(SeedRefused):
        commit_seed(_result())
    assert GearItem.query.count() == 1


def test_commit_rolls_back_on_error(app, monkeypatch):
    from models import FishingShip
    from services.fishing_log import seed_runner

    def boom(*args, **kwargs):
        raise RuntimeError('중간 실패')
    monkeypatch.setattr(seed_runner, '_add_purchases', boom)

    with pytest.raises(RuntimeError):
        seed_runner.commit_seed(_result())
    assert FishingShip.query.count() == 0
    assert seed_runner.tables_are_empty() is True


def test_boat_link_only_when_name_unique(app):
    from db import db
    from models import Boat, FishingShip
    from services.fishing_log.seed_runner import commit_seed

    db.session.add(Boat(name='가나다호', url='https://example.com/a', city='가시', port='가항'))
    db.session.add(Boat(name='라마호', url='https://example.com/b', city='나시', port='나항'))
    db.session.add(Boat(name='라마호', url='https://example.com/c', city='다시', port='다항'))
    db.session.commit()

    commit_seed(_result())

    linked = FishingShip.query.filter_by(name='가나다호').one()
    assert linked.boat is not None and linked.boat.url == 'https://example.com/a'
    assert FishingShip.query.filter_by(name='라마호').one().boat_id is None


def test_report_lists_counts_ship_mapping_warnings_and_skips():
    from services.fishing_log.seed_runner import format_report

    report = format_report(_result())

    assert '선사 2' in report
    assert '출조 2 (완료 1 · 예정 1 · 취소 0)' in report
    assert '장비 구매 1' in report
    assert '장비 노트 1' in report
    assert '라마호 오전배 → 라마호' in report
    assert '[2026 7행] 조과 문장에 인식 못 한 숫자가 있음' in report
    assert '[2026 9행] 합계 또는 금액만 있는 줄' in report
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_fishing_log_seed_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.fishing_log.seed_runner'`

- [ ] **Step 3: 구현** — `src/services/fishing_log/seed_runner.py`

```python
"""엑셀 이관 결과(SeedResult)를 DB에 넣고, 넣기 전 미리보기 보고서를 만든다.

새 테이블 4개가 모두 비어 있을 때만 한 트랜잭션으로 넣는다 - 이관은 한 번뿐이라
다시 실행해도 중복되지 않게 막고, 중간에 실패하면 전부 롤백해 빈 상태로 되돌린다.
"""
from collections import Counter

from db import db
from models import Boat, FishingShip, FishingTrip, GearItem, GearPurchase

FISHING_MODELS = (FishingShip, FishingTrip, GearItem, GearPurchase)


class SeedRefused(Exception):
    """이미 낚시 기록 데이터가 있어 이관을 거부함."""


def tables_are_empty():
    return all(model.query.count() == 0 for model in FISHING_MODELS)


def _unique_boat_ids():
    """이름이 하나뿐인 Boat 만 자동 연결 대상. 같은 이름의 배가 여러 지역에
    등록된 경우(실제로 있음)는 어느 쪽인지 알 수 없으므로 연결하지 않는다."""
    boats = Boat.query.all()
    counts = Counter(b.name for b in boats)
    return {b.name: b.id for b in boats if counts[b.name] == 1}


def _add_ships(result):
    boat_ids = _unique_boat_ids()
    ships = {}
    for seed in result.ships:
        ship = FishingShip(name=seed.name, region=seed.region, port=seed.port,
                           travel_time=seed.travel_time, memo=seed.memo,
                           boat_id=boat_ids.get(seed.name))
        db.session.add(ship)
        ships[seed.name] = ship
    return ships


def _add_trips(result, ships):
    for seed in result.trips:
        db.session.add(FishingTrip(
            trip_date=seed.trip_date, status=seed.status, ship=ships[seed.ship_name],
            cost=seed.cost, companions=seed.companions, species=seed.species,
            tags=[], catches=seed.catches, catch_raw=seed.catch_raw, memo=seed.memo))


def _add_gear_items(result):
    for seed in result.gear_items:
        db.session.add(GearItem(name=seed.name, memo=seed.memo))


def _add_purchases(result):
    for seed in result.purchases:
        db.session.add(GearPurchase(
            purchase_date=seed.purchase_date, shop=seed.shop, item=seed.item,
            category=seed.category, price=seed.price))


def commit_seed(result):
    if not tables_are_empty():
        raise SeedRefused('낚시 기록 테이블에 이미 데이터가 있어 이관하지 않습니다.')
    try:
        ships = _add_ships(result)
        _add_trips(result, ships)
        _add_gear_items(result)
        _add_purchases(result)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {'ships': len(result.ships), 'trips': len(result.trips),
            'purchases': len(result.purchases), 'gear_items': len(result.gear_items)}


def format_report(result):
    status = Counter(t.status for t in result.trips)
    lines = [
        '=== 낚시 기록 이관 미리보기 ===',
        f'선사 {len(result.ships)}',
        f"출조 {len(result.trips)} (완료 {status['done']} · 예정 {status['planned']} · 취소 {status['cancelled']})",
        f'장비 구매 {len(result.purchases)}',
        f'장비 노트 {len(result.gear_items)}',
        '',
        '--- 출조 원문 → 선사명 (틀린 줄은 --ship-map 으로 보정) ---',
    ]
    for trip in result.trips:
        catches = ', '.join(f"{c['who']} {c['species']} {c['count']}" for c in trip.catches) or '-'
        lines.append(f'{trip.trip_date} [{trip.status}] {trip.source_text} → {trip.ship_name} | 조과: {catches}')
    lines += ['', f'--- 경고 {len(result.warnings)} ---']
    lines += [f'[{w.sheet} {w.row}행] {w.reason}: {w.text}' for w in result.warnings]
    lines += ['', f'--- 제외 {len(result.skipped)} ---']
    lines += [f'[{s.sheet} {s.row}행] {s.reason}: {s.text}' for s in result.skipped]
    return '\n'.join(lines)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_fishing_log_seed_runner.py -q`
Expected: 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/services/fishing_log/seed_runner.py tests/test_fishing_log_seed_runner.py
git commit -m "낚시 기록 이관: DB 쓰기(빈 테이블만·한 트랜잭션)와 미리보기 보고서"
```

---

### Task 5: 스크립트 진입점 + 실제 파일 미리보기 + 전체 검증

**Files:**
- Create: `scripts/seed_fishing_log.py`
- Test: `tests/test_fishing_log_seed_runner.py` (테스트 추가)

**Interfaces:**
- Consumes: `parse_workbook`(Task 3), `format_report`/`commit_seed`/`SeedRefused`(Task 4)
- Produces: `scripts/seed_fishing_log.py`의 `main(argv=None, app=None, out=None) -> int` (0 성공, 1 거부/오류)

- [ ] **Step 1: 실패하는 테스트 추가** — `tests/test_fishing_log_seed_runner.py` 끝에

```python
import importlib.util
import io
import json
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from services.fishing_log.excel_seed import YEAR_HEADER

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'seed_fishing_log.py'


def _load_script():
    spec = importlib.util.spec_from_file_location('seed_fishing_log', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _xlsx(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = '2026'
    ws.append(YEAR_HEADER)
    ws.append([datetime(2026, 5, 2), '솔로', '가항', '가시', '가나다호 오전배', '문어', '선비', None, 90000, '문어 3'])
    ws.append([datetime(2026, 3, 1), None, None, None, '테스트 에기', None, '에기', '테무', 12000, None])
    path = tmp_path / 'seed.xlsx'
    wb.save(path)
    return path


def test_script_preview_does_not_touch_db(app, tmp_path):
    from services.fishing_log.seed_runner import tables_are_empty
    out = io.StringIO()

    code = _load_script().main([str(_xlsx(tmp_path)), '--today', '2026-06-15'], app=app, out=out)

    assert code == 0
    assert '출조 1 (완료 1 · 예정 0 · 취소 0)' in out.getvalue()
    assert '미리보기만 했습니다' in out.getvalue()
    assert tables_are_empty() is True


def test_script_commit_inserts_and_second_run_is_refused(app, tmp_path):
    from models import FishingTrip
    script = _load_script()
    path = str(_xlsx(tmp_path))

    assert script.main([path, '--commit', '--today', '2026-06-15'], app=app, out=io.StringIO()) == 0
    assert FishingTrip.query.one().ship.name == '가나다호'

    out = io.StringIO()
    assert script.main([path, '--commit', '--today', '2026-06-15'], app=app, out=out) == 1
    assert '이미 데이터가 있어' in out.getvalue()
    assert FishingTrip.query.count() == 1


def test_script_applies_ship_map(app, tmp_path):
    ship_map = tmp_path / 'map.json'
    ship_map.write_text(json.dumps({'가나다호 오전배': '가나다 오전호'}, ensure_ascii=False), encoding='utf-8')
    out = io.StringIO()

    _load_script().main([str(_xlsx(tmp_path)), '--ship-map', str(ship_map), '--today', '2026-06-15'],
                        app=app, out=out)

    assert '가나다호 오전배 → 가나다 오전호' in out.getvalue()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_fishing_log_seed_runner.py -q`
Expected: FAIL — `FileNotFoundError` (스크립트 없음)

- [ ] **Step 3: 구현** — `scripts/seed_fishing_log.py`

```python
"""낚시 기록 엑셀을 DB 초기값으로 한 번 옮기는 로컬 스크립트.

    python scripts/seed_fishing_log.py <엑셀경로>              # 미리보기(DB 안 건드림)
    python scripts/seed_fishing_log.py <엑셀경로> --commit     # 실제 이관

운영 DB에 넣을 때는 DATABASE_URL 을 Neon 연결 문자열로 지정하고 실행한다.
새 테이블 4개가 비어 있을 때만 넣는다. 엑셀·보정표(--ship-map)는 개인
기록이라 커밋하지 않는다 - spec: docs/superpowers/specs/
2026-09-30-fishing-log-data-model-design.md §3.
"""
import argparse
import json
import os
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, 'src')
for path in (BASE_DIR, SRC_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from openpyxl import load_workbook  # noqa: E402

from services.fishing_log.excel_seed import parse_workbook  # noqa: E402
from services.fishing_log.seed_runner import SeedRefused, commit_seed, format_report  # noqa: E402


def _args(argv):
    parser = argparse.ArgumentParser(description='낚시 기록 엑셀 → DB 초기 이관')
    parser.add_argument('path', help='엑셀 파일 경로')
    parser.add_argument('--commit', action='store_true', help='실제로 DB에 넣는다(없으면 미리보기)')
    parser.add_argument('--ship-map', help='{"원문": "선사명"} JSON 보정표 경로')
    parser.add_argument('--today', help='예정/완료 판단 기준일 YYYY-MM-DD (기본: 오늘)')
    return parser.parse_args(argv)


def main(argv=None, app=None, out=None):
    out = out or sys.stdout
    args = _args(argv)
    ship_map = None
    if args.ship_map:
        with open(args.ship_map, encoding='utf-8') as fh:
            ship_map = json.load(fh)
    today = date.fromisoformat(args.today) if args.today else date.today()

    result = parse_workbook(load_workbook(args.path, data_only=True), today, ship_map)
    print(format_report(result), file=out)

    if not args.commit:
        print('\n미리보기만 했습니다. 실제로 넣으려면 --commit 을 붙여 다시 실행하세요.', file=out)
        return 0

    if app is None:
        from src.app import create_app
        app = create_app()
    with app.app_context():
        try:
            counts = commit_seed(result)
        except SeedRefused as exc:
            print(f'\n{exc}', file=out)
            return 1
    print(f'\n이관 완료: {counts}', file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_fishing_log_seed_runner.py -q`
Expected: 모두 PASS

- [ ] **Step 5: 실제 엑셀 미리보기 (로컬, DB 안 건드림, 결과 커밋 금지)**

Run: `PYTHONIOENCODING=utf-8 python scripts/seed_fishing_log.py "<사용자가 올린 엑셀 경로>" > "<스크래치패드>/seed_preview.txt"`
Expected: 종료 코드 0. 사전 분석 기준 건수는 "출조 43 (완료 33 · 예정 5 · 취소 5)"(취소 5는 2025 시트, 예정 5는 기준일 이후인 2026년 10~11월), 장비 구매 206 + 품목 칸이 빈 줄 중 '기타'로 들어가는 줄(연도당 최대 3), 장비 노트 5. 차이가 나면 경고 목록으로 원인을 사용자에게 보고한다. "원문 → 선사명" 목록 중 틀린 줄을 뽑아 사용자에게 보여 주고 `--ship-map` 보정 여부를 묻는다. **이 결과 파일은 스크래치패드에만 두고 커밋하지 않는다.**

- [ ] **Step 6: 전체 테스트 1회**

Run: `python -m pytest -q`
Expected: 새 테스트 전부 PASS. 실패는 기존에 알려진 `tests/test_admin_visits.py::test_admin_table_shows_full_datetime_in_kst_not_utc` 1건뿐.

- [ ] **Step 7: 커밋**

```bash
git add scripts/seed_fishing_log.py tests/test_fishing_log_seed_runner.py
git commit -m "낚시 기록 이관 스크립트 추가(미리보기 기본, --commit, --ship-map)"
```

---

### Task 6: 운영 반영 (사용자 확인 필요 단계 포함)

코드 변경 없음. 각 단계는 사용자 확인 후 진행한다.

- [ ] **Step 1: push → Render 배포** — `git push origin main`(사용자 승인 후). Render 기동 시 `create_all`이 Neon에 빈 테이블 4개를 만든다. 라우트가 없으니 화면 변화 없음. `/healthz` 200 확인.
- [ ] **Step 2: 운영 DB 미리보기** — 사용자 PC에서 `DATABASE_URL`을 Neon으로 지정하고 `python scripts/seed_fishing_log.py <엑셀> --ship-map <보정표>` 실행(미리보기는 DB를 쓰지 않음). 사용자가 결과를 확인한다.
- [ ] **Step 3: 운영 DB 이관** — 같은 명령에 `--commit`. **운영 DB 쓰기이므로 실행 직전 사용자에게 다시 확인한다.** 종료 코드 0과 "이관 완료" 건수를 사용자에게 보고한다.
