# 낚시 기록 3단계 — 장비 구매 설계

- 작성일: 2026-10-01
- 상태: 사용자 검토 대기
- 선행: 1단계 모델(`GearPurchase`, `GearItem`) · 2단계 출조 기록(공통 레이아웃 LNB, 화면 패턴)
- 디자인: 캔버스 ④ Gear(PC), M6 목록 · M7 주문 상세(모바일). M8 붙여넣기는 **만들지 않는다**.

## 1. 목적과 범위

admin 본인이 장비를 산 시점에 폰·PC에서 **주문 단위로 직접 입력**하고, 연도별 구매 내역과
지출을 보며, 예전 데이터의 표기를 정리하고, 릴·로드 같은 장비별 메모를 관리한다.

포함: 월별 주문 목록 · 주문 입력/수정/삭제 · 필터/검색 · 지출 요약(B) · 정리 제안(C) ·
내 장비 노트(D) · 공통 UI 부품(커스텀 드롭다운 · 달력 · 스피너) 추출과 출조 기록 화면 적용.

제외: 붙여넣기 일괄 입력(사용자 결정 — 앞으로는 항목별로 직접 입력), 엑셀 업로드.

## 2. 화면 기본 규칙 (모든 화면 공통, CLAUDE.md "화면 기본 규칙")

1. 드롭다운은 브라우저 기본(`<select>` 포함)을 쓰지 않고 커스텀 드롭다운을 쓴다.
2. 날짜는 기존 달력 컴포넌트(`date-btn` + `cal-popover`)를 쓴다.
3. 서버 조회·저장 대기 중에는 반드시 스피너를 보인다.
4. 확인·입력 팝업은 `showConfirm`/`showPrompt`.

## 3. 공통 UI 부품 — `src/templates/admin_layout.html`로 추출

출조 기록 화면에만 있던 코드를 레이아웃으로 옮겨 모든 admin 화면이 쓴다.

- **`AdmUI.select(el, {options, value, placeholder, allowCustom, onChange})`** — 버튼 + 팝오버 목록.
  options는 `[{value, label, hint?}]`. 키보드 ↑↓ · Enter · Esc, 바깥 클릭 시 닫힘, 목록이 길면 스크롤,
  `allowCustom`이면 맨 아래 "직접 입력…"(→ `showPrompt`). 반환 객체 `{set(value), setOptions(options), value}`.
- **`AdmUI.calendar(el, {value, onChange})`** — 기존 달력 마크업·동작(월 이동 · 오늘로 · 확인). 반환 `{set(value)}`.
- **스피너**: CSS `.adm-loading`(목록 로딩 영역), `.adm-spin`(인라인), `AdmUI.busy(on, msg)`(전체 화면),
  `AdmUI.btnBusy(btn, on, label)`(버튼 안 스피너).
- 출조 기록 화면의 네이티브 `<select>` 5곳(필터 어종 · 동행 · 재이용, 조과 누구 · 어종)과 달력·스피너를
  이 부품으로 교체한다. 동작은 바꾸지 않는다.

## 4. 화면 — `/admin/fishing/gear` (`gear.html`, LNB "장비 구매" 활성)

- **상단**: 제목 · 연도 칩(연도 목록 + 전체) · "+ 구매 추가".
- **도구줄**: 검색(품목 · 구매처 · 메모) · 카테고리 드롭다운 · 구매처 드롭다운.
- **본문(PC 2열)**: 왼쪽 목록, 오른쪽 360px 사이드(지출 요약 · 정리 제안 배너 · 내 장비 노트).
  모바일은 1열: 지출 요약 카드 → 정리 제안 배너 → 목록 → 내 장비 노트.
- **목록**: 월 헤더(“10월 · 주문 19건 · 645,747원”) → 주문 행(날짜 타일 · 구매처 · 품목 수 ·
  대표 품목 · 카테고리 칩 · 합계). 행을 펼치면 품목 표(품목 · 카테고리 · 가격 · 연결 장비) + [주문 수정].
  모바일은 행을 누르면 주문 상세(전체 화면, M7).
- **주문 입력·수정**(PC 오른쪽 패널 / 모바일 전체 화면): 날짜(달력) · 구매처(자동완성 — 과거 구매처) ·
  품목 줄 반복(품목명 · 카테고리 드롭다운 · 가격 · 내 장비 드롭다운 · 줄 삭제) · [+ 품목 추가] ·
  합계 자동 · 저장 / 취소 / (수정일 때) 주문 삭제. 임시저장(localStorage)과 뒤로가기 닫기는 출조 기록과 같다.
- **저장·삭제 후**: 목록 전체를 다시 조회하지 않고 바뀐 주문만 반영해 다시 그린다.
- **정리 제안 모달**: 구매처 통일 · 카테고리 제안 목록, 항목별 [적용]/[무시], [모두 적용].
  무시한 제안은 localStorage에 기억.
- **내 장비 노트**: 카드(이름 · 종류 · 메모 요약 · 연결 구매 N건 · 금액) → 편집 패널(이름 · 종류 · 메모 ·
  연결된 구매 목록 · 삭제). "+ 장비 추가".

## 5. 데이터 규칙 — `src/services/fishing_log/gear_service.py`

### 5.1 주문

- 주문 키 = (`purchase_date`, `shop` 또는 빈 값). 조회 응답에서 품목을 이 키로 묶는다.
- **주문 저장**: `{original: {date, shop} | null, date, shop, items: [{id?, item, category, price, gear_id, memo}]}`
  - 한 트랜잭션. id 있는 품목은 수정(날짜 · 구매처 포함), id 없는 품목은 추가,
    `original` 주문에 있던 품목 중 items에 없는 id는 삭제.
  - id가 `original` 주문에 속하지 않으면 400(다른 주문 품목을 건드리지 않게).
- **주문 삭제**: `{date, shop}`의 품목을 모두 삭제.

### 5.2 검증 (실패 시 400 + field)

| 항목 | 규칙 |
|---|---|
| date | 필수, YYYY-MM-DD |
| shop | 선택, 100자 이하, 앞뒤 공백 제거 |
| items | 1개 이상 |
| item | 필수, 500자 이하 |
| category | 50자 이하, 비면 `기타` (1단계 동의어 규칙 `줄→라인`, `낚시대→로드` 적용) |
| price | 선택, 0 이상 정수(쉼표 허용) |
| gear_id | 선택, 존재하는 GearItem |
| memo | 선택, 1000자 이하 |

### 5.3 목록 응답 `GET /admin/api/fishing/gear?year=YYYY|all`

- `orders`: 날짜 내림차순. 주문 = `{date, shop, total, items: [{id, item, category, price, gear_id, gear_name, memo}]}`.
- `years`(데이터 연도 + 올해), `categories`(기본 목록 + 사용한 값), `shops`(과거 구매처, 많이 쓴 순).
- `summary`: `{total, count, by_category: [{category, amount, count}], top_shops: [{shop, amount, count}] (5개)}`.
- `gear_items`: `[{id, name, kind, memo, purchase_count, purchase_total}]`.
- 기본 카테고리: 에기 · 채비 · 봉돌 · 도래 · 라인 · 로드 · 릴 · 의류 · 기타.

### 5.4 정리 제안 `GET /admin/api/fishing/gear/cleanup` · 적용 `POST …/gear/cleanup`

- **구매처 통일**: 공백 제거 · 소문자 키가 같은데 표기가 2개 이상 → 가장 많이 쓴 표기(동률이면 먼저 나온 것)로.
  `{kind: 'shop', key, to, from: [표기…], count}`.
- **카테고리 제안**: category가 `기타`인 품목 중 품목명에 키워드가 있으면
  `{kind: 'category', id, item, to}`. 키워드(먼저 맞는 것):
  봉돌→봉돌 / 도래 · 스위블 · 스냅 · 핀도래→도래 / 합사 · 라인 · 원줄 · 목줄→라인 /
  채비 · 천평 · 바늘 · 훅 · 슬리브→채비 / 에기→에기 / 장갑 · 모자 · 조끼 · 우의 · 레인→의류 /
  로드 · 낚시대→로드 / 릴→릴.
- 적용 요청 `{shops: [{from: [...], to}], categories: [{id, category}]}` → 해당 행만 수정, 수정 건수 응답.

### 5.5 내 장비 노트

- `GET/POST /admin/api/fishing/gear/items`, `PUT/DELETE …/gear/items/<id>`, 항목 응답에 연결된 구매 목록.
- 검증: name 필수 200자 · kind 50자 · memo 2000자. 삭제 시 구매의 gear_id는 NULL(1단계 모델 동작).

## 6. API 공통

- 전부 admin 세션 필요(미로그인 403, 화면은 `/admin`으로), 쓰기는 `X-CSRFToken`(출조 기록과 같은 가드).
- 라우트는 `src/routes/fishing_views.py`에 추가한다.

## 7. 테스트 (admin 전용 변경 규칙: admin · fishing 테스트만)

- `tests/test_gear_service.py`: 주문 저장(추가 · 수정 · 삭제 동시, 날짜/구매처 변경 전파, 다른 주문 id 거부),
  검증 필드, 목록 묶음 · 정렬 · summary · years · shops, 정리 제안(구매처 · 카테고리) · 적용, 장비 CRUD · 연결 해제.
- `tests/test_gear_views.py`: 로그인 403 · 리다이렉트, CSRF 거부, 주문 저장/삭제 왕복, 400 field, 정리 적용, 장비 API.
- 기존 출조 기록 테스트가 공통 부품 교체 후에도 통과.
- 브라우저 확인은 완성 후 1회(PC · 모바일: 목록 → 주문 입력 → 저장, 커스텀 드롭다운, 달력, 스피너, 정리 제안, 장비 노트).

## 8. 배포

DB 변경 없음. 기능 브랜치 → admin · fishing 테스트 → main push → 운영 확인.
