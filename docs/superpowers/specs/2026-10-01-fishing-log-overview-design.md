# 낚시 기록 5단계: 개요 대시보드 설계

- 날짜: 2026-10-01
- 선행: 2단계 출조 기록, 3단계 장비 구매, 4단계 선사 노트(다녀온 배 중심으로 수정됨)
- 디자인 원본: 디자인 캔버스 `Main`(PC 개요), `MobileOverview`(모바일)

## 1. 목적과 범위

"내 낚시 기록"의 첫 화면. 두 가지 역할을 한다(사용자 결정 B).

1. **지금 챙길 것** — 다가오는 출조, 결과 입력이 필요한 지난 출조, 입금 전 선비. 연도와 무관하게 항상 오늘 기준.
2. **연간 결산** — 고른 연도(또는 전체 기간)의 출조+장비 지출 흐름을 돌아본다.

역할 구분: 선사 노트 = 다녀온 배끼리 비교, 개요 = 출조와 장비 전체의 흐름. 개요의 "이용 선사"는 상위 5척만 보이고
선사 노트로 넘긴다. 새 테이블 없이 기존 `FishingTrip`·`GearPurchase`·`FishingShip`만 집계한다.
admin 첫 화면(`/admin`)은 바꾸지 않는다.

## 2. 집계 정의 (`src/services/fishing_log/overview_service.py`, 순수 계산, `today` 인자)

### 2.1 지금 챙길 것 (`todo`, 연도 무관)
- `upcoming`: `planned` 이면서 `trip_date >= today`, 가까운 순 최대 3건.
  각 항목 `{id, date, d_day, ship, region, cost, prepaid, companions}`. `upcoming_total`은 전체 건수.
- `needs_result`: `planned` 이면서 `trip_date < today` 인 건수와 가장 오래된 날짜(`oldest`).
- `unpaid`: `planned`·`trip_date >= today`·`prepaid=False` 인 건수와 선비 합계(선비 미입력은 0).
- 세 항목이 모두 0이면 화면은 띠 자체를 숨긴다.

### 2.2 연간 결산 (`year` = 정수 또는 `None`(전체 기간))
- **출조 지출** = 기간 안 `done` 출조의 `cost` 합. **장비 지출** = 기간 안 `GearPurchase.price` 합.
  **총 지출** = 둘의 합. 예정 출조의 선입금은 포함하지 않는다(아직 간 출조가 아님).
- `trips`: `{done, cancelled}` 건수(`planned`는 결산에서 제외).
- `gear`: `{items: 구매 행 수, orders: (날짜, 구매처) 묶음 수}`.
- `top_ship`: 기간 안 `done` 횟수 최다 선사(동률은 최근 출조, 이름) `{id, name, count, region, port}`, 없으면 `null`.
- `best_catch`: 기간 안 `done` 출조 중 '나'의 한 번 조과 합계 최대(동률은 최근), 그날 상위 2개 어종
  `{label, date, ship}` — 선사 노트의 `_best_catch` 규칙과 같다. 없으면 `null`.
- `flow`:
  - 연도 선택 시 1~12월 `[{key: 월, trip: 금액, gear: 금액, trips: 출조 횟수}]`.
  - 전체 기간이면 연도별(오래된 해 → 최근) 같은 형태(`key`=연도).
- `flow_note`(한 줄 요약):
  - 연도 선택 시: 연속 3개월 창(1~3월 … 10~12월) 중 총 지출이 가장 큰 창. 그 창이 연간 총 지출의 50% 이상이면
    `"{a}~{b}월에 출조 {n}회 · 지출의 {p}%가 몰렸어요"`, 아니면 `null`. 총 지출 0이면 `null`.
  - 전체 기간이면 지출 최대 연도 `"{y}년에 가장 많이 썼어요 ({금액}원)"`, 지출 0이면 `null`.
- `species`: 기간 안 `done` 출조의 `species` 목록 기준 어종별 출조 횟수, 많은 순 상위 6개 `[{name, count}]`.
- `categories`: 기간 안 장비 지출 카테고리별 `[{name, amount, pct}]` 금액 순 상위 4개(pct는 장비 지출 대비 정수 %).
- `ships`: 기간 안 `done` 횟수 순 상위 5척 `[{id, name, count, region, port, best, last_rating}]`
  (`best` = 그 배에서의 최고 조과 label).
- `years`: 출조(취소 제외)·장비 기록이 있는 연도 ∪ 올해, 내림차순.

## 3. API (`src/routes/fishing_views.py`, admin 세션 필수 — 미로그인 403)

- `GET /admin/fishing` → 화면(미로그인 시 `/admin`으로 302), `active_menu='fishing_overview'`.
- `GET /admin/api/fishing/overview?year=` → `{todo, year, total, trip_spent, gear_spent, trips, gear, top_ship,
  best_catch, flow, flow_note, species, categories, ships, years}`.
  `year` 생략 시 올해, `all`이면 전체 기간, 숫자가 아니면 400 `{error, field:'year'}`.

## 4. 화면 (`src/templates/fishing_overview.html`, `admin_layout.html` 확장)

- LNB "개요"를 링크로 전환(준비 중 표시 제거).
- 머리: 제목 + 연도 칩(전체/연도들, 기본 올해, 로딩 중 칩 안 스피너).
- **지금 챙길 것** 띠: 다가오는 출조 카드(최대 3, D-day·배·입금 여부 → 누르면 `/admin/fishing/trips#trip-<id>`),
  "결과 입력 필요 N건"(→ `/admin/fishing/trips`), "입금 전 N건 · 합계"(→ `/admin/fishing/trips`).
- **연간 결산**:
  - 총 지출 히어로 카드(비율 막대 + 출조/장비 금액).
  - 카드 4개: 출조 N회(취소 M회 별도) / 장비 N개(주문 M건) / 가장 많이 탄 배 / 최고 조과(날짜·배).
  - 월별 흐름: 쌓은 막대(선비·장비 두 색) + `flow_note`. 전체 기간이면 연도별 막대.
  - 어종별 출조(가로 막대), 장비 카테고리(상위 4, "전체 보기" → `/admin/fishing/gear`),
    이용 선사(상위 5, 각 줄 → `/admin/fishing/ships#ship-<id>`, "선사 노트" 링크).
  - 기록이 하나도 없는 연도: "이 해에는 기록이 없어요" 안내.
- 하단 바로가기: "출조 기록 추가"(→ `/admin/fishing/trips#new`), "장비 구매 추가"(→ `/admin/fishing/gear#new`).
- PC: 2열(결산 카드·흐름 왼쪽 넓게, 어종·카테고리·선사 오른쪽). 모바일: 1열, 바로가기는 하단 고정 버튼 2개.
- 서버 대기 중 스피너(`AdmUI.loadingHtml`), 실패 시 안내 + 다시 시도.

## 5. 다른 화면 연동 (최소 변경)

- `fishing_trips.html`: 기존 해시 처리(`#trip-<id>`, `#new?ship=<id>`)에 `#new`(빈 새 기록 편집기) 추가.
- `gear.html`: 로드 후 해시 `#new`면 새 주문 편집기를 연다. 처리 후 해시 제거.

## 6. 테스트

- `tests/test_fishing_overview_service.py`: todo 3종(지난 예정·입금 전·최대 3건), 지출 정의(취소·예정 제외,
  장비 합산), top_ship·best_catch, 월별 flow·flow_note(50% 미만이면 null, 0이면 null), 전체 기간 연도별 flow·note,
  species·categories(pct)·ships 상위 N, years, 빈 연도.
- `tests/test_fishing_overview_views.py`: 로그인 302/403, year 400, 화면 렌더(active 메뉴 1개).
- `tests/test_admin_layout.py`: LNB 개요 링크.
- 커밋 전에는 admin/낚시 기록 테스트만. 시각 검증은 로컬 Playwright 1회(PC·모바일).
