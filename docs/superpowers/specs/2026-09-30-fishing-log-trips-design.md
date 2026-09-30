# 낚시 기록 2단계 — 출조 기록 (admin 공통 레이아웃 + 출조 화면) 설계

- 작성일: 2026-09-30
- 상태: 사용자 검토 대기
- 선행: 1단계 `docs/superpowers/specs/2026-09-30-fishing-log-data-model-design.md`
  (모델 4개 + 운영 DB 초기 이관 완료: 출조 44 · 선사 94)
- 디자인: 캔버스(PC ② 출조 목록 · ③ 입력 패널, 모바일 M2~M5, 공통 레이아웃 L1 · L2)

## 1. 목적과 범위

admin 로그인한 본인이 **PC와 폰에서 같은 수준으로** 출조 기록을 조회 · 추가 ·
수정 · 삭제한다. 함께, admin을 "서비스 관리"와 "내 낚시 기록"으로 나누는 공통
레이아웃(LNB)을 도입한다.

### 결정 사항

- 낚시 기록은 admin 탭이 아니라 **공통 레이아웃의 LNB 메뉴**로 분리한다.
- 기존 `/admin`(항구 정보 · 접속 이력 · 알림 등록)도 이 레이아웃을 쓴다. 탭의 내용 ·
  API · 동작은 바꾸지 않는다.
- 로그인 화면에 **"로그인 유지"** 체크박스(체크 시 30일).
- 모바일 상세 · 입력 · 필터는 페이지 위에 겹치는 화면이며, 안드로이드 뒤로가기로 닫힌다.

### 범위 밖

개요 대시보드(5단계), 장비 구매(3단계), 선사 노트 화면(4단계 — 이번엔 LNB에 "준비 중"),
AFT 예약현황 · 빈자리 알림 바로가기(4단계), 엑셀 업로드(만들지 않음).

## 2. 구조

### 2.1 공통 admin 레이아웃 — `src/templates/admin_layout.html`

- `base_design.html`을 확장한다(`base.html`, `base_design.html`은 수정하지 않는다).
- 구성: 상단 바(로고 · "AFT 관리자" · 사이트 링크 날씨/배 목록/예약현황/알림 · ADMIN ·
  로그아웃) + LNB.
- LNB 항목과 주소:

  | 그룹 | 항목 | 주소 |
  |---|---|---|
  | 서비스 관리 | 항구 정보 | `/admin#ports` |
  | | 접속 이력 | `/admin#access` |
  | | 알림 등록 | `/admin#watch` |
  | 내 낚시 기록 | 개요 | (준비 중, 링크 없음) |
  | | 출조 기록 | `/admin/fishing/trips` |
  | | 장비 구매 | (준비 중) |
  | | 선사 노트 | (준비 중) |

- 템플릿 변수 `active_menu`(예: `'ports'`, `'fishing_trips'`)로 현재 항목을 강조한다.
- 폭 1024px 이상: 왼쪽 240px 고정 LNB. 미만: 상단 햄버거 버튼 → 왼쪽 서랍(300px,
  배경 어둡게, 바깥 탭 · ESC · 뒤로가기로 닫힘).
- 블록: `admin_title`, `admin_content`, `admin_scripts`.
- 토스트 · 확인 모달은 `base_design.html`의 기존 `showToast` / `showConfirm`을 쓴다.

### 2.2 기존 `/admin` 변경

- `admin.html`이 `admin_layout.html`을 확장하도록 바꾸고 자체 상단 바를 지운다.
- 로그인 전 화면(로그인 카드)은 LNB 없이 보인다.
- 안쪽 탭 줄(`.admin-tabs`)은 숨기고, 주소의 해시(`#ports` / `#access` / `#watch`)로
  탭을 고른다. 해시가 없으면 `ports`. `hashchange`에도 반응한다(같은 페이지에서
  LNB를 누를 때). 탭별 지연 로딩(`loadTabData`)은 그대로.

### 2.3 새 파일

| 파일 | 역할 |
|---|---|
| `src/routes/fishing_views.py` | Blueprint `fishing_views`: 화면 1개 + JSON API |
| `src/services/fishing_log/trip_service.py` | 검증 · 저장 · 선사 맞추기/생성 · 목록 · 직렬화 · 삭제 |
| `src/templates/fishing_trips.html` | 출조 기록 화면(PC · 모바일 반응형, JS 인라인 — 기존 관례) |
| `src/templates/admin_layout.html` | 공통 레이아웃 |

`views.py`(약 1,900줄)에는 추가하지 않는다. Blueprint는 `create_app`에서 등록한다.

### 2.4 주소

| 메서드 · 주소 | 설명 |
|---|---|
| `GET /admin/fishing/trips` | 화면. 미로그인 → `/admin`으로 이동 |
| `GET /admin/api/fishing/trips?year=YYYY\|all` | 연도별 목록 + 요약 + 추천값 |
| `POST /admin/api/fishing/trips` | 추가 |
| `GET /admin/api/fishing/trips/<id>` | 한 건 |
| `PUT /admin/api/fishing/trips/<id>` | 수정(전체 필드) |
| `DELETE /admin/api/fishing/trips/<id>` | 삭제(하드) |
| `GET /admin/api/fishing/ships?q=...` | 선사 자동완성 |

- 모든 API: 미로그인 `403`, 없는 id `404`, 검증 실패 `400 {"error": "...", "field": "..."}`.
- 쓰기 요청(POST/PUT/DELETE)은 기존 admin처럼 `X-CSRFToken` 헤더를 요구한다.

### 2.5 로그인 유지

- `AdminLoginForm`에 `remember`(BooleanField "로그인 유지") 추가.
- 로그인 성공 시 `session.permanent = bool(remember)`. 앱 설정
  `PERMANENT_SESSION_LIFETIME = 30일`.
- 로그아웃은 `admin_authed`를 지우고 `session.permanent = False`.

## 3. 데이터 규칙 (`trip_service`)

### 3.1 입력 검증

| 필드 | 규칙 |
|---|---|
| trip_date | 필수, `YYYY-MM-DD` |
| status | `planned` / `done` / `cancelled` 필수. 새 기록 화면의 기본값은 날짜 > 오늘(KST)이면 planned, 아니면 done |
| ship_name | 필수, 앞뒤 공백 제거 후 1~100자 |
| ship_region / ship_port | 선택, 각 50/100자. **새 선사를 만들 때만** 쓴다 |
| boat_id | 선택. AFT 배를 골라 새 선사를 만들 때 |
| cost | 선택. 정수 또는 "100,000" 형태, 0 이상 |
| companions | 선택, 100자 |
| species, tags | 문자열 목록, 각 20자, 최대 20개, 빈 값 · 중복 제거 |
| catches | `[{who, species, count}]`, who · species 각 20자, count 0~9999 정수, 셋 중 빈 칸이 있는 줄은 버림 |
| rating | `again` / `maybe` / `never` / 없음 |
| memo | 선택, 2000자 |

`catch_raw`는 API로 바꿀 수 없다(읽기 전용).

### 3.2 선사 맞추기 · 생성

저장 시 `ship_name`을 1단계의 `ship_match_key`(공백 제거 · 소문자 · 끝 `호` 제거)로
기존 `FishingShip`과 맞춘다.

1. 맞는 선사가 있으면 그 선사를 쓴다(지역 · 항구 입력은 무시).
2. 없으면 새 선사를 만든다: name = 입력값, region/port = 입력값.
   `boat_id`가 오면 그 Boat가 있는지 확인하고 연결하며, region/port가 비었으면
   Boat의 city/port로 채운다.
3. 출조의 선사를 바꿔도 이전 선사는 지우지 않는다.

`GET /ships?q=`: q(공백 무시 부분 일치)로 ① 기존 선사(출조 횟수 포함, 횟수 많은
순) ② 아직 어느 선사에도 연결되지 않은 AFT Boat(name · city · port)를 합쳐 최대
10개. q가 비면 출조 많은 선사 10개.

### 3.3 목록 응답

`GET /trips?year=` (기본: 올해 KST, `all` 가능) 응답:

- `trips`: 한 건 = id, trip_date, status, ship{id, name, region, port, boat_id},
  cost, companions, rating, species, tags, catches, catch_raw, memo,
  `needs_result`(status가 planned인데 날짜 < 오늘), `d_day`(planned이고 날짜 ≥
  오늘이면 남은 일수, 아니면 null).
- 정렬: planned은 날짜 오름차순(가까운 것 먼저), done · cancelled은 날짜 내림차순.
- `years`: 데이터에 있는 연도 + 올해, 내림차순.
- `summary`: planned/done/cancelled 건수, 비용 합계(취소 제외).
- `suggestions`: companions · species · tags별로 과거 사용 빈도 높은 순 상위 10개
  (species · tags는 기본값 목록과 합침).

필터(상태 · 어종 · 동행 · 재이용)와 검색(선사 · 항구 · 메모)은 화면에서 처리한다
(연간 수십 건).

### 3.4 기본 추천값과 태그 색

- 어종 기본값: 쭈꾸미, 갑오징어, 문어, 우럭, 광어, 농어
- 긍정 태그(초록): 신조선배, 배 컨디션 좋음, 줄 잘 잡아줌, 사무장 있음, 밥 맛있음
- 부정 태그(빨강): 선장이 낚시함, 준비물 부족, 너무 멀다, 포인트 이동 적음
- 그 밖에 직접 만든 태그는 회색.

## 4. 화면 동작 (`fishing_trips.html`)

- PC: 캔버스 L1 · ②. 상단 = 제목 · 연도 칩 · "출조 기록 추가", 도구줄(검색 · 상태
  세그먼트 · 어종/동행/재이용 필터), "다가오는 출조" 카드 줄(D-day), "다녀온 출조"
  표(행 펼침 → 후기 · 태그 · 수정/이 배로 다음 출조 추가/삭제), 하단 연도 합계.
  "결과 입력 필요" 출조는 다녀온 출조 표 맨 위에 강조 배지로.
- PC 입력: 오른쪽 패널(③) — 상태, 날짜, 선사 자동완성(지역 · 항구 자동 채움 /
  새 선사면 직접 입력), 비용, 동행 칩, 어종 칩, 사람별 조과(+/- 버튼), 재이용,
  빠른 태그, 메모. 수정일 때 삭제 버튼.
- 모바일: M2 목록(검색 + 필터 버튼, 다가오는 출조 가로 스크롤), M3 상세(전체 화면),
  M4 입력(전체 화면, 하단 고정 저장), M5 필터(바텀시트). 겹친 화면을 열 때
  `history.pushState`, 뒤로가기(`popstate`)로 닫는다.
- "이 배로 다음 출조 추가": 선사만 채운 새 기록(상태 planned).
- 삭제: `showConfirm`(커스텀 모달) 후 DELETE.

## 5. 오류 처리

- 저장 중 저장 버튼 잠금(중복 저장 방지).
- 실패 시 입력 유지 + `showToast`(서버가 준 field가 있으면 그 입력칸 강조).
- 입력 중 내용은 기기 localStorage에 자동 임시저장(새 기록 · 수정 각각 키 분리).
  다시 열면 복원 여부를 묻지 않고 이어서 채우고 "임시저장된 내용을 불러왔어요"
  토스트. 저장 성공 · 취소 확인 시 삭제. localStorage 접근 실패는 무시.
- API `403`이면 "로그인이 만료됐어요" 토스트 + 로그인 링크(임시본은 남음).

## 6. 테스트

- `tests/test_fishing_trip_service.py`: 검증(필드별 400 사유), 선사 맞추기(공백/`호`
  차이), 새 선사 생성, Boat 연결 · city/port 채움, 선사 변경 시 이전 선사 유지,
  목록 정렬 · `needs_result` · `d_day` · years · summary · suggestions, 삭제,
  ships 자동완성(기존 선사 + 미연결 Boat, 10개 제한).
- `tests/test_fishing_views.py`: 미로그인 403 / 화면 리다이렉트, CSRF 없는 쓰기
  거부, 추가 → 조회 → 수정 → 삭제, 400 field, 404.
- `tests/test_admin_layout.py`: `/admin` 로그인 후 LNB 항목 · 링크 존재,
  `/admin/fishing/trips`에서 "출조 기록" 활성, 기존 admin 테스트 전부 통과.
- 로그인 유지: remember 체크 → 세션 쿠키에 Expires, 미체크 → 없음, 로그아웃 후 해제.
- 브라우저 확인은 기능 완성 후 **한 번에 모아 1회**(PC · 모바일 폭: 목록 → 입력 →
  저장, 상세, 필터, 서랍 메뉴, 뒤로가기로 닫기).

## 7. 배포

- 기능 브랜치에서 작업, 병합 직전 전체 `pytest` 1회.
- DB 변경 없음(테이블은 1단계에서 생성).
- push → Render 배포 → 운영 `/admin/fishing/trips`에서 2026년 출조 9건(예정 5 · 완료
  4) 확인.
