# 낚시 기록 4단계: 선사 노트(선사별 통계) 설계

- 날짜: 2026-10-01
- 선행: 1단계 데이터 모델(`FishingShip`, `FishingTrip`), 2단계 출조 기록 화면, 3단계 장비 구매 화면
- 디자인 원본: 디자인 캔버스 `ShipNote`(PC), `MobileShips`·`MobileShipDetail`(모바일)

## 1. 목적과 범위

출조 기록을 선사(배) 단위로 모아 "이 배를 또 탈까"를 판단할 수 있게 한다. 새 테이블 없이
기존 `FishingTrip`을 선사별로 집계한다.

포함:
- 선사 목록(지역별 묶음, 검색, 필터)과 선사 상세(통계·조과 추이·탄 기록·자주 남긴 말·선사 정보)
- 선사 정보 수정(이름·지역·항구·선단·이동시간·메모·AFT 배 연결)
- 바로가기(예약현황·빈자리 알림·예약 페이지), "이 배로 출조 기록 추가"

제외(준비 중으로 표시):
- "가 볼 곳" 필터 탭과 "+ 가 볼 선사 메모" 버튼 — 보이되 비활성(`disabled`, "준비 중" 표시)
- 선사 삭제, 선사 단독 추가(새 선사는 지금처럼 출조 기록 저장 시 자동 생성)

## 2. 통계 정의 (`src/services/fishing_log/ship_service.py`, 순수 계산)

기준일 `today`를 인자로 받는다(테스트 고정용). 출조 상태는 `done`/`planned`/`cancelled`.

- **완료 횟수** = `done` 건수. **예정 수** = `planned` 이면서 `trip_date >= today` 건수.
  `cancelled`는 모든 횟수·금액·조과·평가 집계에서 제외(탄 기록 목록에는 흐리게 표시).
- **가장 가까운 예정일** = 예정 중 가장 이른 날짜.
- **최근 평가** = 날짜가 가장 늦은 `done` 중 `rating`이 있는 건의 평가.
- **목록 태그 문구**: 완료 N>0 → `N회`, 예정이 있으면 ` · 예정` 추가(완료 0이면 `예정 M/D`),
  둘 다 없으면 `기록 없음`.
- **태그 색(tone)**: 최근 평가 `again` → `good`, `never` → `bad`, 완료 0·예정만 → `plan`,
  그 외(평가 없음/`maybe`/기록 없음) → `memo`(회색). `maybe`의 노랑은 상세 탄 기록의 평가 배지에서만 쓴다.
- **쓴 돈** = `done` 건의 `cost` 합(없으면 0). **예정 선입금** = 예정 중 `prepaid=True`인 `cost` 합(0이면 표시 안 함).
- **내 조과**: `catches` 중 `who == '나'`만 사용. 이 배의 `done` 출조에서 어종별 합계를 내고,
  합계 상위 2개 어종에 대해 `평균 = 합계 / (그 배의 done 건수)`(소수 첫째 자리 반올림, 정수면 정수로)를 준다.
  조과 기록이 전혀 없으면 빈 목록.
- **대표 어종** = 위 상위 1위 어종. 없으면 `None`(추이 영역은 "조과 기록이 없어요").
- **조과 추이** = 대표 어종 기준, `done` 출조를 날짜 오름차순으로 `{date, count}`(그 출조에서 '나'의 그 어종 마릿수, 없으면 0).
  예정 출조는 `{date, planned: true}`로 뒤에 붙인다. 최근 8건(완료) + 예정 전부까지만.
- **또 탈까** = `done` 건의 `rating`별 개수 `{again, maybe, never}`.
- **자주 남긴 말** = 이 배의 `done`/`planned` 출조 `tags` 빈도순(동률은 이름순) 상위 12개.
- **탄 기록** = 이 배의 모든 출조(취소 포함), 날짜 내림차순. 각 항목: id, 날짜, 상태, 동행, 선비, 선입금,
  평가, 조과 요약 문자열(`나 문어 6 · 마눌 3`, 조과 없고 done이면 `조과 없음`, 꽝 표시 규칙은 출조 기록 화면과 동일),
  메모.

## 3. 목록 묶음 규칙

- 지역(`region`)별 묶음. 묶음 순서 = 묶음 안 완료 횟수 합 내림차순, 동률은 지역 이름순. 지역 없는 선사는
  마지막 "지역 미입력" 묶음.
- 묶음 안 순서: 기록 있는 선사(완료+예정 > 0) 먼저 — 완료 횟수 내림차순, 가장 최근 출조일 내림차순, 이름순.
  기록 없는 선사는 그 뒤 이름순.
- 필터: `전체`(모두), `타 본 곳`(완료 ≥ 1), `가 볼 곳`(비활성). 검색은 이름·항구·선단·메모 부분일치
  (브라우저에서, 목록 데이터로).

## 4. API (`src/routes/fishing_views.py`, admin 세션 필수 — 미로그인 403, 쓰기는 `X-CSRFToken` 400)

- `GET /admin/fishing/ships` → 화면(미로그인 시 `/admin`으로 302), LNB `active_menu='fishing_ships'`.
- `GET /admin/api/fishing/ships/notes` → `{ships: [요약...], regions: [...], boats: [{id, name, port}]}`
  - 요약: `id, name, region, port, fleet, travel_time, memo, boat_id, done_count, planned_count,
    next_planned, last_trip, last_rating, tag, tone`
  - `regions`: 선사 지역값 빈도순(수정 드롭다운 옵션), `boats`: AFT 등록 배(`Boat`) 이름순(연결 드롭다운 옵션)
- `GET /admin/api/fishing/ships/<id>` → `{ship: 요약 + 상세}`. 상세: `spent, prepaid_planned, my_catch,
  main_species, trend, ratings, tags, visits, boat`(`boat` = 연결 시 `{id, name, url}` 아니면 `null`). 없으면 404.
- `PUT /admin/api/fishing/ships/<id>` body `{name, region, port, fleet, travel_time, memo, boat_id}`
  - 검증: 이름 필수·100자, 지역 50자, 항구·선단 100자, 이동시간 50자, 메모 2000자, `boat_id`는 존재하는 `Boat`
    또는 null. 이름이 다른 선사와 중복이면 400. 오류는 `{error, field}` 400.
  - 성공 시 `{ship: 요약 + 상세}` — 화면은 그 선사만 교체.
- 기존 `GET /admin/api/fishing/ships`(출조 기록 자동완성)는 변경하지 않는다.

## 5. 화면 (`src/templates/fishing_ships.html`, `admin_layout.html` 확장)

- LNB "선사 노트"를 링크로 전환(`/admin/fishing/ships`).
- PC(≥ 900px): 왼쪽 목록 패널(검색, 필터 칩, 지역별 목록) + 오른쪽 상세. 처음엔 첫 선사 자동 선택,
  URL 해시 `#ship-<id>`로 선택 상태 유지(새로고침 복원).
- 모바일: 목록 → 상세는 전체 화면 오버레이, history에 쌓아 뒤로가기로 닫힘.
- 상세:
  - 헤더: 이름, 배지(AFT 배 목록 연결됨 / 대표 어종), 선단·항구·이동시간·메모 첫 줄, "정보 수정" 버튼.
  - 바로가기 3개: 예약현황(`/status`), 빈자리 알림(`/watches`), 예약 페이지(`boat.url`, 새 탭).
    AFT 배 연결이 없으면 셋 다 비활성 + "AFT 배를 연결하면 쓸 수 있어요" 안내.
  - 통계 카드 4개: 탄 횟수(+예정), 쓴 돈(+예정 선입금), 내 평균 조과, 또 탈까.
  - 조과 추이 막대(대표 어종, 예정은 점선 칸), 탄 기록 타임라인(누르면 `/admin/fishing/trips#trip-<id>`),
    자주 남긴 말 칩, 선사 정보(선단·이동시간·메모 전문).
  - 하단 "이 배로 출조 기록 추가" → `/admin/fishing/trips#new?ship=<id>`.
- 정보 수정: 오른쪽 패널(모바일 전체 화면) 편집기. 지역은 `AdmUI.select`(직접 입력 허용), AFT 배 연결은
  `AdmUI.select`("연결 안 함" 포함), 저장 버튼은 `AdmUI.btnBusy`. 저장 후 목록·상세에서 그 선사만 교체(전체 재조회 없음).
- 서버 대기 중엔 스피너: 목록 로딩(`AdmUI.loadingHtml`), 상세 로딩, 저장 버튼.
- 기록 없는 선사: 목록에 회색 `기록 없음` 태그, 상세는 헤더·바로가기·선사 정보만(통계 영역은 "아직 탄 기록이 없어요").

## 6. 출조 기록 화면 연동 (`fishing_trips.html`, 최소 변경)

- 로드 시 해시 `#trip-<id>`면 그 기록이 있는 연도로 이동해 펼치고 스크롤.
- 해시 `#new?ship=<id>`면 새 기록 편집기를 열고 선사 이름을 채운다(선사 이름은 notes API가 아니라
  `GET /admin/api/fishing/ships/<id>` 요약에서 얻는다). 처리 후 해시 제거.

## 7. 테스트

- `tests/test_fishing_ship_service.py`: 횟수(취소 제외·과거 planned 제외), 태그 문구·tone, 쓴 돈·예정 선입금,
  내 조과 평균(상위 2개·'나'만), 추이(대표 어종·예정 꼬리), 평가 집계, 태그 빈도, 탄 기록 순서·조과 요약,
  기록 없는 선사, 목록 묶음·정렬, 수정 검증(중복 이름·없는 boat_id·길이).
- `tests/test_fishing_ship_views.py`: 로그인 302/403, CSRF 400, 404, 400 필드, 수정 왕복, 화면 렌더.
- `tests/test_admin_layout.py`: LNB 선사 노트 링크·active.
- 커밋 전에는 admin/낚시 기록 테스트(`tests/test_admin_*.py`, `tests/test_fishing_*.py`, `tests/test_gear_*.py`)만 실행.
- 시각 검증은 기능 묶음 끝에 로컬 Playwright 1회(PC·모바일 목록/상세/수정).
