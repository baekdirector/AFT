# 낚시 기록 1단계 — 데이터 모델 + 초기 이관 설계

- 작성일: 2026-09-30
- 상태: 사용자 검토 대기
- 관련 기획: admin "낚시 기록" 메뉴 디자인 캔버스(PC 6 + 모바일 11 화면)

## 1. 목적과 범위

admin에 개인 낚시 기록(출조 · 장비 구매 · 선사 노트 · 내 장비 노트)을 관리하는
"낚시 기록" 메뉴를 만든다. 전체를 5단계로 나누며, 이 문서는 **1단계**만 다룬다.

1. **데이터 모델 + 초기 이관** ← 이 문서
2. 출조 기록 (API + PC/모바일 화면)
3. 장비 구매
4. 선사 노트 (AFT 예약현황 · 빈자리 알림 연결)
5. 개요 대시보드

### 결정 사항

- 사용자는 admin 로그인한 본인 1명. 기록은 개인 데이터라 일반 사용자 화면·API에
  절대 노출하지 않는다.
- 기존 엑셀은 **초기값 설정에만 한 번** 쓴다. 이후 입력·수정은 전부 웹에서 한다.
  → 앱에 엑셀 업로드 기능을 만들지 않는다.
- 초기 이관은 **로컬에서 한 번 실행하는 스크립트**로 한다. 엑셀·변환 결과 같은
  개인 데이터는 리포(public)에 커밋하지 않는다.

### 1단계 결과물

- `src/models.py`: 새 모델 4개
- `src/services/fishing_log/excel_seed.py`: 엑셀 → 기록 변환 순수 함수
- `scripts/seed_fishing_log.py`: 미리보기(기본) / `--commit` 이관 스크립트
- 위 셋의 테스트

### 1단계에서 하지 않는 것

admin 탭 · 라우트 · API · 화면, 통계 계산, AFT 배 목록 연결 화면, 엑셀 내보내기.

## 2. 데이터 모델

원칙: 데이터가 작다(연 출조 수십 건, 구매 수백 건). 통계용 테이블은 두지 않고
필요할 때 파이썬에서 집계한다. 새 테이블만 추가하므로 기존 `db.create_all()`이
생성하고 ALTER 보정은 필요 없다. 기존 테이블은 건드리지 않는다.

### 2.1 `fishing_ships` — 선사 (`FishingShip`)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | Integer PK | |
| name | String(100), NOT NULL, UNIQUE | 표시 이름 |
| region | String(50), NULL | 예: 여수 |
| port | String(100), NULL | 예: 돌산항 |
| fleet | String(100), NULL | 선단 이름 |
| travel_time | String(50), NULL | 예: "1시간 7분" (원문 그대로) |
| memo | Text, NULL | |
| boat_id | FK boats.id, NULL, ON DELETE SET NULL | AFT 배 목록 연결 |
| created_at / updated_at | DateTime | UTC |

- 출조는 항상 선사 하나를 가리킨다. 처음 보는 배는 저장 시 선사가 자동 생성된다
  (2단계 화면에서 처리). 선사별 집계의 기준이다.
- 항구 · 지역은 선사에만 둔다(출조마다 따로 두지 않는다).

### 2.2 `fishing_trips` — 출조 (`FishingTrip`)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | Integer PK | |
| trip_date | Date, NOT NULL, index | |
| status | String(16), NOT NULL | `planned` / `done` / `cancelled` |
| ship_id | FK fishing_ships.id, NOT NULL, ON DELETE RESTRICT | 출조가 있는 선사는 삭제 불가 |
| cost | Integer, NULL | 원 |
| companions | String(100), NULL | 동행 (자유 입력) |
| rating | String(16), NULL | `again` / `maybe` / `never`, NULL = 미평가 |
| species | JSON list, 기본 `[]` | 대상 어종 |
| tags | JSON list, 기본 `[]` | 빠른 태그 |
| catches | JSON list, 기본 `[]` | `[{"who": "나", "species": "쭈꾸미", "count": 12}]` |
| catch_raw | Text, NULL | 조과 원문 (이관 시 엑셀 문장 그대로) |
| memo | Text, NULL | 후기 메모 |
| created_at / updated_at | DateTime | UTC |

허용값은 모듈 상수로 둔다: `TRIP_STATUSES`, `TRIP_RATINGS`.

### 2.3 `gear_items` — 내 장비 노트 (`GearItem`)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | Integer PK | |
| name | String(200), NOT NULL | |
| kind | String(50), NULL | 릴 / 로드 등 |
| memo | Text, NULL | |
| created_at | DateTime | |

### 2.4 `gear_purchases` — 장비 구매 (`GearPurchase`, 품목 1개 = 1행)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | Integer PK | |
| purchase_date | Date, NOT NULL, index | |
| shop | String(100), NULL | 구매처 |
| item | Text, NOT NULL | 품목 · 색상 · 수량 설명 |
| category | String(50), NOT NULL, 기본 `기타` | |
| price | Integer, NULL | 원 |
| memo | Text, NULL | |
| gear_id | FK gear_items.id, NULL, ON DELETE SET NULL | |
| created_at / updated_at | DateTime | |

- "주문"은 테이블로 두지 않는다. **같은 purchase_date + 같은 shop**을 한 주문으로
  묶어 보여 준다(3단계).
- 삭제는 하드 삭제(알림 쪽과 달리 중복 발송 방지 근거가 필요 없다). 화면에서
  확인 모달을 띄운다.

## 3. 초기 이관

### 3.1 구성

- `src/services/fishing_log/excel_seed.py` — DB를 모르는 순수 함수.

  ```python
  def parse_workbook(wb, today: date, ship_map: dict[str, str] | None = None) -> SeedResult
  ```

  `SeedResult`(dataclass): `ships`, `trips`, `purchases`, `gear_items`,
  `warnings: list[SeedIssue]`, `skipped: list[SeedIssue]`
  (`SeedIssue` = 시트명 · 행 번호 · 사유 · 원문 요약).

- `scripts/seed_fishing_log.py <엑셀경로> [--commit] [--ship-map 파일.json] [--today YYYY-MM-DD]`
  - 앱은 `from src.app import create_app`로 불러온다(wsgi.py와 같은 경로 → 같은 DB).
  - 기본은 **미리보기**: 건수, 출조별 "원문 → 선사명", 조과 인식 결과, 경고·제외 목록을 출력하고 DB는 건드리지 않는다.
  - `--commit`: 새 테이블 4개가 **모두 비어 있을 때만** 한 트랜잭션으로 넣는다. 하나라도 행이 있으면 거부하고 종료 코드 1(중복 방지).
  - `--ship-map`: 선사명 추출이 틀린 줄을 바로잡는 로컬 JSON(`{"원문": "선사명"}`). 커밋하지 않는다.

### 3.2 연도 시트 (시트명이 4자리 연도)

첫 행은 헤더 `일자, 함께, 항구, 지역, 내용, 어종, 품목, 비고, 가격, 조과`(0~9열)여야
한다. 다르면 경고하고 그 시트를 건너뛴다. 10열 이후는 무시한다(시트 옆에 둔 참고표 등).

- **공통**
  - 모든 칸이 빈 줄은 무시한다.
  - 일자가 빈 줄은 **윗줄 일자를 이어받는다**(같은 주문의 여러 품목). 시트 첫 데이터
    줄부터 일자가 없으면 이어받을 값이 없으므로 경고하고 제외한다.
  - 일자 칸 값이 `합계`인 줄, 또는 내용과 품목이 모두 비어 있고 가격만 있는 줄은
    **제외**(skipped)한다.
- **출조**: 품목이 `선비` 또는 `배`.
  - status: 일자 > today → `planned`, 아니면 `done`.
  - 선사명: `ship_map`에 원문이 있으면 그 값. 없으면 내용에서 ` - `나 `(` 앞부분을
    취하고, 그 안에 "호"로 끝나는 단어가 있으면 그 단어를 선사명으로 쓴다
    (예: `가나다호 - (농어, 우럭)` → `가나다호`, `라마낚시 바사호 문어` → `바사호`).
    원문에서 선사명을 뺀 나머지 글은 memo 앞에 붙인다.
  - companions = 함께, species = 어종을 `,`로 나눠 공백 제거, cost = 가격(정수).
  - memo = 비고 + (선사명 외 나머지 글), catch_raw = 조과 원문.
  - rating = NULL(엑셀에 없으므로 추측하지 않는다).
  - 선사의 region/port는 그 줄의 지역/항구(선사가 새로 만들어질 때만 채운다).
- **취소된 출조**: 품목이 비어 있고 비고에 `취소` 또는 `최소`(오타)가 포함된 줄 →
  status `cancelled`, 선사명은 출조와 같은 규칙.
- **장비 구매**: 그 밖에 품목이 있는 줄.
  - item = 내용, category = 품목, shop = 비고, price = 가격(정수, 없으면 NULL).
  - 구매처 표기 통일: `테무`→`Temu`, `aliexpress`/`Aliexpress`→`AliExpress`,
    `에프마켓 인천`→`에프마켓인천`(대소문자·공백 무시 비교).
  - 카테고리 동의어: `줄`→`라인`, `낚시대`→`로드`.
- **분류 불가**: 품목이 비었고 취소도 아닌데 내용이 있는 줄 → category `기타`
  장비 구매로 넣고 **경고**를 남긴다.

### 3.3 조과 인식

`catch_raw`에는 항상 원문을 보관한다. 숫자 인식은 단순한 형태만 한다.

- 어종 약칭: `쭈`/`쭈꾸미`/`주꾸미`/`쭈구미`→쭈꾸미, `갑`/`갑오징어`→갑오징어,
  `문`/`문어`→문어, `우럭`, `광어`, `농어`, `놀래미`, `낙지`.
- 패턴: 어종 약칭 뒤에 (공백 선택) 숫자. 숫자 바로 뒤가 `%`, `kg`, `호`, `시`면
  조과가 아니다. `마리`는 허용.
- 사람: 매치 앞쪽에서 가장 가까운 사람 단어(`나`, `마눌`, `와이프`, `엄마`) —
  없으면 `나`.
- 인식 결과가 없거나, 원문에 인식에 쓰이지 않은 숫자가 남아 있으면 **경고**
  (catches는 인식된 것만 넣는다. 틀린 숫자를 넣느니 비워 둔다).
- `꽝`만 있는 경우 catches = `[]`, 경고 없음.

### 3.4 `낚시배` 시트 → 선사

- 열 구조: 0열 지역, 2열 항구, 3열 선사명, 4열 이후 메모. 지역 · 항구가 빈 줄은
  윗줄 값을 이어받는다. 선사명은 적힌 그대로 쓴다(예: `가나 / 다라`처럼 선단 두
  이름이 함께 적혀 있어도 그대로 두고, 화면에서 고친다).
- 3열이 비어 있는데 다른 칸에 값이 있는 줄은 경고하고 건너뛴다.
- 4열 이후 값 중 `\d+시간( \d+분)?` 또는 `\d+분` 형태는 travel_time으로, 나머지는
  memo로 이어 붙인다.
- 이름이 같은(공백 제거, 대소문자 무시) 선사는 하나로 합치고 memo를 이어 붙인다.
- 출조의 선사명은 이 목록과 **정규화 이름**(공백 제거, 끝의 `호` 제거)으로 맞춘다.
  맞는 게 없으면 새 선사를 만든다.
- AFT `Boat`와는 `Boat.name`이 선사 이름과 **정확히 같을 때만** `boat_id`를 연결한다
  (스크립트 단계에서 DB 조회). 나머지는 4단계 화면에서 연결한다.

### 3.5 그 밖의 시트

- `지도` 시트는 무시한다.
- 연도 · `낚시배` · `지도`가 아닌 시트 중 **값이 있는 시트만** 장비 노트로 만든다:
  name = 시트명, memo = 값들을 줄 단위로 이어 붙인 것. 빈 시트는 건너뛴다.

## 4. 오류 처리

- 파서는 행 단위로 격리한다. 한 줄을 해석하지 못해도 경고로 남기고 계속한다.
- 스크립트는 미리보기가 기본이라 실수로 운영 DB에 쓰지 않는다. `--commit`은 빈
  테이블 확인 후 한 트랜잭션으로 넣고, 실패하면 전부 롤백한다.

## 5. 테스트

- **모델** (`tests/test_fishing_log_models.py`): 생성, JSON 칸 기본값, 선사 이름
  UNIQUE, 출조가 있는 선사 삭제 거부, gear_item 삭제 시 구매의 gear_id NULL.
- **파서** (`tests/test_fishing_log_seed.py`): 가짜 엑셀을 **테스트 코드 안에서
  openpyxl로 생성**해 검증한다(바이너리 · 개인 데이터 커밋 없음). 다룰 경우:
  날짜 이어받기, 합계 행 제외, 출조/구매 분류, 미래 날짜 → planned, `취소`와 `최소`
  → cancelled, 가격 없는 출조, 선사명 추출과 `ship_map` 우선, 조과 인식(단순형 ·
  사람 구분 · `%` 제외 · 인식 불가 경고), 구매처 · 카테고리 통일, 분류 불가 경고,
  `낚시배` 이어받기와 이동시간, 장비 시트 비어 있음/있음, 헤더가 다른 시트 건너뜀.
- **스크립트** (`tests/test_seed_fishing_log_script.py`): 미리보기는 DB에 쓰지 않음,
  `--commit`은 건수대로 들어감, 테이블이 비어 있지 않으면 거부.
- 실제 엑셀 미리보기는 로컬에서 한 번 돌려 결과를 사람이 검토한다.

## 6. 운영 반영 순서

1. 모델만 들어간 코드를 배포 → Render 기동 시 `create_all`이 Neon에 빈 테이블 생성.
   라우트가 없으므로 사용자에게 보이는 변화 없음.
2. 사용자 PC에서 `DATABASE_URL`을 Neon으로 지정하고 스크립트 미리보기 확인,
   필요하면 `--ship-map`으로 선사명 보정.
3. `--commit`으로 이관 (운영 DB 쓰기 — 실행 전 사용자 확인).
