# 낚시배 자리 알림 서비스 — 개발 계획서 (PLAN.md)

> 목표: 등록된 낚시배의 특정 날짜 예약 현황을 **주기적으로 자동 확인**하고,
> 자리가 나거나 상태가 바뀌면 **알림(Web Push / 텔레그램)** 을 보내는 서비스.
> 사용자가 매번 접속하지 않아도 되도록 "당김(pull) → 밀기(push)" 로 전환한다.

---

## 0. 문서의 사용법

- 이 문서는 **하네스(test harness) 중심**으로 작성되었다. 각 단계의 "완료"는
  느낌이 아니라 **하네스 통과 여부**로 판정한다.
- 각 Phase는 순서대로 쌓인다. 앞 Phase의 완료 기준을 통과하지 못하면 다음으로 넘어가지 않는다.
- 새 변형(사이트/모듈 버전)이 발견되면 코드를 고치기 전에 **fixture부터 추가**한다.

---

## 1. 범위 (Scope)

### 포함
- 지역·항구별 배 등록 (※ 기존 서비스에 63척 등록 완료 — 재사용)
- 사용자가 `(배, 날짜, 조건)` 을 **감시 등록**
- 감시 대상만 주기적으로 스크래핑
- 상태 변화 감지 후 **알림 발송** (Web Push 기본 + 텔레그램 보조)
- **날짜 선택 시 물때/조석 표시** (서해 기준): 물때(N물), 만조/간조 시각·조위
  — 출처는 **국립해양조사원(KHOA) 조석예보 오픈API** (바다타임 스크래핑 아님)

### 제외 (당분간)
- 실제 예약/결제 (원본 사이트로 링크만 넘긴다 — ToS 안전)
- 카카오 알림톡 (사업자 채널·비용 필요)
- iOS 전용 최적화 (사용자층이 안드로이드 위주)

---

## 2. 아키텍처

핵심 원칙: **긁는 부분(스크래퍼+알림) 과 화면(웹 UI) 을 분리한다.**

```
[GitHub Actions cron] --30~60분마다--> run_scrape.py
      |                                      |
      | (감시 등록된 (배,날짜)만 수집)         v
      |                              adapters(파서) --> 정규화 Slot
      |                                      |
      |                              snapshot diff (이전 vs 현재)
      |                                      | (의미있는 변화)
      |                                      v
      |                              notify: Web Push / Telegram
      v
   [DB]  <----- 읽기 -----  [Render 웹 UI] (잠들어도 무방)
```

- **웹 UI (Render)**: 배 목록/등록, 감시 등록 화면, 알림 구독 설정. **잠들어도 됨.**
- **스크래퍼+알림**: GitHub Actions cron으로 독립 실행. Render 슬립과 무관. 비용 $0.
- **DB**: 취미 규모는 SQLite로 시작. 커지면 Postgres(Neon/Supabase 무료)로 이전.
  - GitHub Actions에서 쓰려면 (a) 호스팅 Postgres 무료 티어 사용, 또는
    (b) SQLite 파일을 아티팩트/리포에 커밋하는 방식 중 택1 (Phase 4에서 확정).

### 스택
- 언어: **Python** (백엔드/스크래퍼/스케줄러 공통)
- 파서: `requests` + `BeautifulSoup4`
- 웹: 기존 서비스 유지 (FastAPI/Flask 등 현행 그대로)
- 알림: `pywebpush`(VAPID) + 텔레그램 Bot API(`requests`)
- 테스트: `pytest`

---

## 3. 안정화 전략 — 테스트 하네스 (이 프로젝트의 심장)

### 3.1 원리
1. 각 사이트 변형의 **실제 HTML 응답**을 파일로 저장한다 → `fixtures/`
2. 그 fixture에 대해 **기대하는 정규화 출력**을 JSON으로 만든다 → `*.expected.json`
3. 테스트가 `adapter(fixture) == expected.json` 을 자동 비교한다.
4. 코드를 고치거나 사이트가 바뀌면 이 비교가 **회귀를 즉시 잡는다.**

### 3.2 디렉터리 구조

```
fishing-notify/
├── adapters/
│   ├── base.py            # Adapter 인터페이스, Slot 데이터클래스, Status enum
│   ├── sunsang24.py
│   └── thefishing.py      # v5.1 / v5.2_seat1 변형을 내부 분기
├── fixtures/
│   ├── sunsang24/
│   │   ├── redhunter_202608.html
│   │   ├── redhunter_202608.expected.json
│   │   ├── teamf_202608.html          # 예약마감/오픈일미정/낚시점행 포함
│   │   └── teamf_202608.expected.json
│   ├── thefishing_v51/
│   │   ├── shinmyungho_20260827.html  # r_x_NN.gif 자리 인코딩
│   │   └── shinmyungho_20260827.expected.json
│   └── thefishing_v52/
│       ├── khan_20260827.html         # icon_fix_1.gif (정비일)
│       └── khan_20260827.expected.json
├── core/
│   ├── normalize.py       # Slot 정규화 공통 규칙
│   ├── snapshot.py        # 이전/현재 비교(diff) 로직
│   └── notify/
│       ├── webpush.py
│       └── telegram.py
├── scheduler/
│   └── run_scrape.py      # GitHub Actions 진입점
├── tests/
│   ├── test_parsers.py    # fixture ↔ expected.json 비교
│   └── test_snapshot.py   # diff 로직 단위 테스트
├── tools/
│   └── capture_fixture.py # 실제 사이트 HTML을 fixtures/로 저장하는 도구
└── .github/workflows/
    └── scrape.yml         # cron
```

### 3.3 하네스 운영 규칙
- **fixture 없는 파서 코드 변경 금지.** 변경 전에 그 변형을 대표하는 fixture가 있어야 한다.
- fixture 캡처는 `tools/capture_fixture.py` 로 한다 (원본 HTML 그대로 저장, 마크다운 변환 X).
- `expected.json` 은 사람이 눈으로 확인 후 커밋한다 (골든 파일).
- 사이트 구조 변경으로 테스트가 깨지면 → 원인 확인 후 fixture/expected를 **의도적으로** 갱신.

---

## 3b. 코드 안정성 원칙 (생성되는 코드가 지킬 규칙)

> 목표: "돌아가긴 하는데 왜 되는지 모르는" 코드를 만들지 않는다.
> 아래 원칙은 하네스와 함께 코드 품질의 하한선이다.

1. **파싱과 I/O를 분리한다.** 파서 함수는 `parse(html) -> list[Slot]` 처럼 **순수 함수**로 짠다.
   네트워크 요청은 파서 바깥(fetcher)에서만. → 파서를 fixture로 100% 테스트 가능.
2. **실패는 격리한다(fail-soft).** 배 한 척 파싱 실패가 전체 수집을 멈추지 않는다.
   실패는 `UNKNOWN`/`BLOCKED`로 기록하고 다음으로 넘어간다.
3. **네트워크는 방어적으로.** timeout(예: 10s), 재시도 3회 + 지수 백오프,
   식별 가능한 User-Agent(연락처 포함), 요청 간 지연(원본 배려).
4. **결정론적 출력.** 같은 fixture는 항상 같은 결과. 순서 정렬 고정, 시간 의존 로직 배제.
5. **타입 명시.** `dataclass` + 타입힌트. `Slot`/`Tide`/`Status`는 스키마를 코드로 강제.
6. **시크릿은 코드에 두지 않는다.** API 키·VAPID·봇 토큰은 환경변수/Actions Secret.
7. **구조화 로깅.** 어느 배·날짜·플랫폼에서 무엇이 실패했는지 남긴다(디버깅·회귀 추적).
8. **작게 커밋, 하네스 초록불에서만 병합.** 테스트 실패 상태로 다음 Phase 진행 금지.

---

## 4. 파서 변형 카탈로그 (실측 기반)

> 이 표가 곧 fixture 체크리스트다. 새 변형 발견 시 여기에 행을 추가한다.

| 플랫폼 | 모듈/식별 | URL 패턴 | 자리/상태 표기 | fixture |
|---|---|---|---|---|
| sunsang24 | `/ship/schedule_fleet` | `.../schedule_fleet/YYYYMM` (월) | 텍스트: `남은자리 N명`, `남은자리 N명 예약/M명`, `예약마감 N명 예약/N명`, `점검일`, `기상악화`, `오픈일 미정`; 링크상태 `바로예약`/`대기하기` | redhunter, teamf |
| thefishing v5.1 | `reservation_boat_v5.1` | `?mid=bk&year=&month=&day=&mode=list` (일) | 이미지 파일명 `r_x_NN.gif` (잔여석), `r_x_0.gif`=만석; 입금자/입금대기/대기자 목록 | shinmyungho |
| thefishing v5.2 | `reservation_boat_v5.2_seat1` | 위와 동일 | 정비일 `icon_fix_1.gif` + "배 점검으로…"; **열린 날 자리 인코딩 미확인(TODO)** | khan |
| (차단) | robots.txt disallow | — | 봇 접근 거부 (예: 명성호) | 별도 처리 |

### 정규화 상태 enum (플랫폼 공통)
```
OPEN         자리 있음 (remaining > 0)
FULL         만석 / 예약마감 / 예약완료
MAINTENANCE  점검일 / 배정비일
WEATHER      기상악화
NOT_OPEN     오픈일 미정 (아직 예약 안 열림)
BLOCKED      스크래핑 차단 (robots 등)
UNKNOWN      파싱 실패 / 미분류
```

### 정규화 Slot 스키마
```json
{
  "boat_name": "레드헌터(22인승)",
  "date": "2026-08-29",
  "status": "OPEN",
  "remaining": 6,
  "total": 20,
  "fish_type": "문어",
  "departure_time": "02:30 ~ 12:00",
  "source_url": "https://redhunter.sunsang24.com/ship/schedule_fleet/202608",
  "raw": "남은자리 6명 예약/14명"
}
```

### 상태 판정 규칙 (sunsang24) — 애매함 제거
파서가 텍스트를 Status로 매핑하는 우선순위. 위에서부터 먼저 매칭되는 것을 채택한다.

| 순위 | 원문 신호 | Status | remaining / total |
|---|---|---|---|
| 1 | `점검일` | MAINTENANCE | null |
| 2 | `기상악화` | WEATHER | null |
| 3 | `오픈일 미정` / 낚시점 행(어종:출조안내 등) | NOT_OPEN (낚시점 행은 제외) | null |
| 4 | `예약마감 N명 예약/N명` | FULL | 0 / N |
| 5 | `남은자리 N명 예약/M명` | OPEN | N / (N+M) |
| 6 | `남은자리 N명` (예약수 없음) | OPEN | N / null |
| 7 | 위 어디에도 안 맞음 | UNKNOWN | null |

- `바로예약`/`대기하기` 링크상태는 **보조 신호**로만 쓴다(대기하기=만석 가능성). 자리 숫자가 우선.
- thefishing은 별도 규칙: `r_x_(\d+)\.gif` → remaining(0=FULL), `icon_fix_*` → MAINTENANCE.

---

## 4b. 물때 / 조석 (KHOA 오픈API)

### 4b.1 출처와 원칙
- **출처: 국립해양조사원(KHOA) 조석예보 오픈API** (공공데이터포털, dataset 15038991).
  - 제공 항목: 관측소ID·관측소명·좌표, 고/저조 구분, 예측 극치시간(만조/간조 시각), 극치값(조위 cm).
  - 이용 조건: 공공데이터포털 회원가입 + 활용신청(무료·자동승인), API 키 필요.
- **바다타임 등 2차 사이트는 긁지 않는다.** (KHOA 라이선스 데이터의 재복제 + 구조 종속 리스크)
- 물때/조석은 **날짜+관측소 기준 결정론적 데이터**이므로 캐싱이 잘 된다 (한 번 받으면 재사용).

### 4b.2 "물때(N물)" 유도 — 하드코딩 금지
- KHOA API는 만조/간조 시각·조위는 주지만 **물때 이름(N물/사리/조금)은 주지 않는다.**
- 물때는 **음력 날짜 → 물때** 매핑으로 유도한다. 단:
  - **서해/남해 규칙이 다르다** (실측: 2026-08-27 → 서해 6물 / 남해(여수) 7물).
  - 사용자 요구가 **"서해 기준"** 이므로 **서해 규칙에 앵커링**한다.
  - 매핑은 기억/추정 공식이 아니라 **KHOA·바다타임의 알려진 값으로 하네스 검증**한 lookup table로 확정한다.
- 참고: 낚시배 스케줄 페이지에도 날짜별 물때가 이미 표기됨 → **교차검증용 보조 근거**로 활용 가능.

### 4b.3 정규화 Tide 스키마
```json
{
  "station_id": "DT_0001",
  "station_name": "인천",
  "date": "2026-08-29",
  "lunar": "7.17",
  "mulddae_west": "8물",
  "high_tides": [
    {"time": "02:06", "level_cm": 317},
    {"time": "14:13", "level_cm": 286}
  ],
  "low_tides": [
    {"time": "07:52", "level_cm": 68},
    {"time": "19:52", "level_cm": 35}
  ],
  "source": "KHOA"
}
```

### 4b.4 관측소 매핑 (결정됨 → §10 D5)
- **1차: 서해 단일 참조 관측소로 통일** (예: 인천). 지역별 매핑은 이후 확장.
- 근거: **물때(N물)는 서해 연안 전체가 사실상 동일**하므로 단일 관측소로도 정확하다.
  만조/간조 "시각·조위"만 위치에 따라 다르므로, 1차에서는 서해 대표값으로 근사하고
  UI에 "서해(인천) 기준"임을 명시한다.
- 확장(Phase 5+): `station` 테이블에 지역별 KHOA 관측소를 채워 배의 지역에 맞는 시각·조위를 제공.

---

## 5. 데이터 모델 (DB)

```
boat        (id, region, port, name, url, platform, notes)       # 기존 63척
subscriber  (id, name, webpush_sub_json, telegram_chat_id, created_at)
watch       (id, subscriber_id, boat_id, target_date,
             condition, active, created_at)
             # condition 예: SEAT_OPEN(자리 1↑), STATUS_CHANGE, FISH_IS(어종)
snapshot    (boat_id, date, status, remaining, total, fish_type,
             departure_time, checked_at)                          # 최신 상태 1행
notification(id, watch_id, sent_at, channel, payload, result)     # 발송 이력/중복방지
tide        (station_id, date, lunar, mulddae_west,
             high_tides_json, low_tides_json, fetched_at)         # KHOA 조석 캐시
station     (id, khoa_station_id, name, lat, lon, region)         # 항구↔관측소 매핑
```

핵심: `snapshot` 이 있어야 **이전과 비교**가 가능하고, `notification` 이력으로 **중복 알림을 방지**한다.

---

## 6. 알림 정책

- **의미 있는 전환에만** 발송한다 (예: `FULL/MAINTENANCE → OPEN`, `remaining 0 → >0`).
- 같은 `(watch, 전환)` 은 한 번만. 상태가 원복 후 다시 열리면 재발송.
- 채널: **Web Push 기본** (VAPID, 서비스워커) + **텔레그램 보조** (봇 chat_id).
- 발송 실패 시 재시도 & `notification.result` 에 기록.
- 원문 링크를 함께 담아 실제 예약은 원본 사이트에서 하도록 유도.

---

## 7. 단계별 실행 계획 (Phased Checklist) — 실행 결과 반영

> 아래 체크는 "계획대로 됐는지"가 아니라 "실제로 뭐가 만들어졌는지"를 표시한다.
> 계획과 다르게 간 부분은 **왜 다르게 갔는지**를 그대로 남겨둔다 — 이 프로젝트의
> 원칙(테스트/실측 우선)상 사후 실측이 사전 계획을 뒤집은 경우가 여러 번 있었다.

### Phase A-1 — 테스트 하네스 복구 [완료]
`tests/conftest.py`의 `src.db` vs `db` 모듈 이중 import 문제로 14개 테스트가
`RuntimeError`로 막혀 있던 것을 고쳤다. 원래 계획엔 없던 단계 — 착수 전 빨간불
기준선을 그린불로 만들어야 이후 "회귀 없음"을 증명할 수 있어서 추가했다.

### Phase A0 — 60~71척 조회 타임아웃 [완료, 처방이 실측으로 두 번 뒤집힘]
증상: 71척 조회 시 19척에서 스트림이 끊김. **원인은 동시성이 아니라 gunicorn
기본 `--timeout 30`**이었다(Procfile/Render Start Command에 `--timeout 120` 추가로 해결).
`STATUS_MAX_WORKERS`는 4→24로 올렸다가, 라이브 실측(Render 0.1 CPU)에서 **24가 4보다
느리다**는 걸 확인하고 4로 되돌렸다 — 스레드 경합이 병목이지 IO 대기가 아니었다.
이후 Phase F(캐시 우선 표시)로 근본 해결.

### Phase A — 파서 안정화 [부분 완료]
계획한 `adapters/` 순수 함수 분리는 하지 않았다 — 대신 `reservation_checker.py`
안에서 실제로 겪은 버그 2건을 fixture 하네스로 고쳤다:
1. 배 이름이 "~호"로 안 끝나면(예: 팀에프원/팀에프투) 통째로 걸러지던 필터를
   구조 기반(정원/예약상태 유무) 판정으로 교체.
2. 예약마감인데 `.number`(정원)가 잔여석으로 잘못 저장되던 것을 마감 시 강제 0으로.

fixture(`tests/fixtures/`): sunsang24(팀에프호/레드헌터), 독립도메인(라온피싱/
나폴리호/칸피싱) 확보. **미완료**: khan v5.2 열린 날 인코딩(R1)을 명시적으로
검증하는 회귀 테스트는 없다(칸피싱 fixture가 9척을 정상 반환하는 건 확인했으나
R1이 우려하던 케이스와 정확히 같은지는 별도 확인 안 됨). 독립 도메인 배 약 28척
중 다수가 여전히 fixture 미확보 — 실제로 조회 안 되는 배가 남아있을 수 있다.

### Phase B — 스냅샷 & 상태변화 감지 [완료]
`src/services/snapshot.py`(순수 함수: `Observation`/`Transition`/`diff`) +
`snapshot_repository.py`(DB). `unknown`은 양방향 전환으로 안 치고, 마감 시
잔여석 숫자를 안 믿는 방어(`effective_status`)까지 포함.

### Phase 3(C) — 감시 등록 & 알림 발송 [완료, 텔레그램 드롭]
`Watch`/`Subscriber`/`Notification` 모델, `/api/watches`, `/api/push/*`(구독/
테스트발송 포함). **텔레그램은 만들지 않았다** — Web Push만으로 충분해 보류
(D4 개정, 아래 §10 D8).  감시 상한 5척/사람 — GitHub Actions 무료 분과 직결.

### Phase T/E — 물때/조석 [계획과 다른 API로 완료]
당초 계획(KHOA 조석예보 dataset 15038991, 관측소 기반 만조/간조+N물lookup)은
**채택하지 않았다.** 대신 사용자가 발급받은 **KHOA 바다낚시지수 API**
(`GetFcstFishingApiServicev2`, 別도 dataset)를 썼다 — `/weather` 페이지에 낚시지수
카드로 표시. 이 API는 물때를 N물이 아니라 소조기/대조기 단위로만 주고, **오늘부터
+5일만 예보**한다(문서에 없는 실측 제약). 그래서 §9 DoD 3번("서해 물때+만조/간조")은
**부분 충족**이다 — 정확한 N물·만조/간조 시각이 필요하면 원래 계획한 조석예보 API를
별도로 더 붙여야 한다. `badatime_parser.py`(바다타임)는 손대지 않고 그대로 남아있다.

### Phase 4/D — 상시화 배포 [완료, 아키텍처가 계획과 달라짐]
당초 계획(D2): "GitHub Actions가 직접 스크랩". **실측으로 이게 안 된다는 걸
확인**했다 — Actions 러너(해외 IP)가 한국 중소 호스팅 다수에 TCP 연결 자체가
막힌다(동일 배가 Render에선 6/6 성공, Actions에선 1/6). 그래서 아키텍처를
바꿨다: Actions는 `POST /api/scrape/run`(Render, `SCRAPE_TOKEN` 인증)을
**트리거만** 하고, 실제 수집·비교·발송은 Render 프로세스 안에서 수행한다.
덤으로 매시 Render를 깨워 콜드스타트도 줄었다. `.github/workflows/scrape.yml`
매시 정각. DB는 Neon Postgres(사용자가 이미 갖고 있던 인스턴스)로 확정 — 파일
커밋 방식은 검토도 안 함.

### Phase 5 — 웹 UI 통합 [완료, Phase C(2/2) + G1-G3로 흡수]
"감시 등록/해제 화면"은 Phase C(2/2)에서 기존 `/status` 표 안에 체크박스로
먼저 얹었고, 이후 Phase G3에서 전용 페이지(`/watches`)로 승격했다.

### Phase G — UI 재디자인 (계획에 없던 추가 단계, 사용자 요청) [완료]
사용자가 Claude Design 캔버스에서 새 UI(oklch 색상 체계, 카드/칩 스타일,
하단 탭바 3개)를 만들어 화면별로 단계적 이식했다. `base.html`은 그대로 두고
`base_design.html`(새 헤더/탭바 셸)을 만들어 화면별로 갈아탔다 — 스트랭글러
원칙 그대로.
- **G1**: 배 목록(홈) — `index.html` 재작성, 기존 검색/필터/지도/등록모달 로직
  100% 재사용(마크업만 교체).
- **G2**: 예약현황 조회 — `status.html` 재작성. 캐시우선표시/스트리밍/`end`마커/
  Watch모듈/500대응 전부 보존. 이후 사용자가 다시 보내온 디자인으로 브라우저
  기본 날짜입력 대신 커스텀 팝오버 달력 이식, 결과 정렬 버튼(예약가능순/지역별)
  추가.
- **G3**: 빈자리 알림 전용 페이지(`/watches`) — 계획엔 없던 완전 신규 화면.
  서버는 정적 셸만 렌더하고(로그인이 없어 감시 목록은 브라우저의 푸시 구독
  endpoint로만 식별 가능), 클라이언트가 `GET /api/watches`로 채운다. 일괄삭제는
  새 API 없이 기존 `DELETE /api/watches`를 병렬 반복 호출.
- `weather.html`/`map.html`/`register.html`/`edit_boat.html`은 **아직 옛 디자인
  그대로**다 — 필요해지면 같은 패턴(base_design.html 상속, 로직 재사용)으로
  이어가면 된다.

---

## 8. 리스크 & 미해결 항목 (Open Questions) — 갱신

| # | 항목 | 상태 |
|---|---|---|
| R1 | khan(v5.2) 열린 날 자리 인코딩 | **미확정.** 칸피싱 fixture가 9척을 정상 반환하는 건 확인했지만 이 리스크를 겨냥한 회귀 테스트는 없다. |
| R2 | robots 차단 사이트(명성호 등) | 그대로 열려있음. `BLOCKED` 처리 미구현. |
| R3 | 사이트 구조 변경 | 하네스로 대응 중(fixture 5건). 독립도메인 28척 중 다수는 아직 fixture 없음. |
| R4 | ToS 무단사용 금지 | User-Agent를 실제 Chrome/Firefox로 위장 중(R4 취지와 반대) — 바꾸면 403이 늘 위험이 있어 보류 중. |
| R5 | DB 영속화 | **해결(D9 관련)**: Neon Postgres. Actions/Render 둘 다 같은 DB. |
| R6 | Web Push iOS 제약 | 텔레그램 보조가 없어졌으므로(D8) 아직 미해결 — 안드로이드 위주 사용자층이라 실무 영향은 낮음. |
| R7 | 물때 음력→N물 매핑 | **채택 안 함(D8)**: 낚시지수 API가 소조기/대조기만 주고 N물 계산 자체를 안 한다. |
| R8 | 항구↔관측소 매핑 | **다른 형태로 해결**: 낚시지수 API의 지점 위경도를 `PORT_COORDINATES`와 하버사인 거리로 매칭(`nearest_position`). 관측소 개념 자체가 필요 없어짐. |
| R9 | KHOA API 파라미터 | **해결**: `gubun=선상` 하나만 필수. 문서에 없어 실측/역공학으로 확정(HWP 메타데이터에서 정확한 엔드포인트 추출). |
| R10(신규) | GitHub Actions 무료 분(월 2,000, private) | 현재 감시 5척+매시 실행 기준 여유 있음. 감시 상한을 올리려면 cron 주기도 같이 늘려야 함. |
| R11(신규) | 낚시지수 API 예보범위 +5일 한정 | 몇 주 뒤 예약 날짜 대부분에는 낚시지수가 안 뜬다(정상). UI는 `available:false`를 오류 아닌 안내로 처리. |

---

## 9. MVP 완료 정의 (Definition of Done) — 현재 충족 여부

1. ✅ 서해권 배를 감시 등록하고 자리가 나면 Web Push가 온다 — 인프라 완성, 테스트
   발송(`/api/push/test`)으로 기기 수신 확인됨. 실제 자리남 트리거는 자연 발생을
   기다리는 중.
2. ✅ 알림에 날짜·배·남은자리·원문 링크 — 스케줄러 경로 URL 버그(항상 `/status`로
   가던 것)를 고쳐서 실제 배 페이지로 링크됨.
3. ⚠️ **부분 충족**: 낚시지수(물때 근사+어종별 지수)가 뜨지만 오늘+5일만, N물 숫자
   없음, 만조/간조 시각 없음. 원래 계획한 정밀 조석 정보가 필요하면 별도 작업.
4. ✅ GitHub Actions가 매시 자동 실행(Render 트리거 방식), `pytest` 221 passed
   유지.

---

## 10. 결정 로그 (Decision Log)

| ID | 결정 | 근거 |
|---|---|---|
| D1 | 방식 = 서버 스크래핑 + 스케줄 캐싱 + 플랫폼 어댑터 | iframe/CORS 불가, 원본 API 없음 |
| D2 | 스크래퍼/알림 ↔ 웹 UI **분리**, GitHub Actions cron | Render 슬립 회피, 비용 $0 — **D9로 구체 방식 수정** |
| D3 | 백엔드 = Python(FastAPI/requests/BS4), 저장 = SQLite 시작 | 지인용 취미 규모, 운영 편의 — 실제로는 Flask, 저장은 처음부터 Neon Postgres 사용(사용자가 이미 갖고 있었음) |
| D4 | 알림 = ~~Web Push 기본 + 텔레그램 보조~~ **Web Push 단독** | **D8로 개정**: 텔레그램 없이도 충분해 개발 안 함 |
| D5 | 물때/조석 = ~~KHOA 조석예보 API~~ | **D8로 대체**: 다른 KHOA API(낚시지수) 채택 |
| D6 | 물때 이름 = ~~음력→물때 lookup~~ | **D8로 대체**: 낚시지수 API가 소조기/대조기를 직접 줌, lookup 불필요 |
| D7 | 진행 방식 = 테스트 하네스 중심, fixture 우선 | 유지. 이번 세션 내내 실제로 지켰다(fixture 5건, 매 Phase pytest 그린 확인). |
| **D8** | 조석·물때는 KHOA **바다낚시지수 API**(`GetFcstFishingApiServicev2`)로, 텔레그램은 미채택 | 사용자가 발급받은 키가 이 API였고, 낚시지수(어종별 5단계)가 정밀 조석보다 실용적 판단. 텔레그램은 Web Push로 충분하다고 판단해 우선순위 밀림 — 필요해지면 §5 데이터모델의 Subscriber.telegram_chat_id 필드는 이미 있으니 재개 가능. |
| **D9** | 스크래핑 실행 주체 = **Render**(Actions는 트리거만) | 실측: Actions 러너가 한국 중소 호스팅 다수에 연결 차단됨(6/6 vs 1/6). `POST /api/scrape/run` + `SCRAPE_TOKEN` 인증으로 전환. |
| **D10** | `STATUS_MAX_WORKERS` = **4**로 유지(24 아님) | 실측: Render 0.1 CPU 인스턴스에서 24는 4보다 느림(스레드 경합, IO 대기 아님). |
| **D11** | `/status`는 **캐시 우선 표시** + 라이브 배별 교체 | 71척 라이브 조회 ≈100초 문제의 근본 해결. 라이브 조회 결과 자체를 스냅샷으로 저장해 다음 조회는 즉시(≈1초). |
| **D12** | UI는 Claude Design 기반으로 **화면별 단계적** 재이식(G1→G2→G3) | 사용자가 새 디자인을 캔버스로 제공. 전체 일괄 교체 대신 화면 하나씩 검증 후 배포 — 스트랭글러 원칙 유지, `base.html` 비파괴. |
| **D13** | 계획 단계=상위 모델(Opus), 코딩 단계=Sonnet 5 | 사용자 지시(토큰 최적화). `CLAUDE.md` 작업 프로토콜 4번에 반영. |
| **D14** | Render keep-alive = GitHub Actions로 **06:00~24:00 KST만** 10분 간격 핑(`/healthz`) | 리포가 public이라 Actions 분 무제한 확인됨. 24시간 내내 깨우면 Render 무료 티어의 워크스페이스 월 750 instance-hour 한도를 31일 달엔 744시간(여유 6h)까지 써서 위험 — 사용자가 직접 활동시간대만으로 범위를 좁혔다. 새벽(00:00~06:00)엔 기존처럼 슬립을 허용한다. |

---

## 11. 다음 행동 (후보, 우선순위 미정 — 사용자와 상의 후 진행)

- **파서 커버리지 확대**: 독립 도메인 배 약 28척 중 fixture 미확보분 캡처 →
  실제로 조회 안 되는 배가 더 있는지 확인(Phase A 마무리).
- **정밀 조석 정보**: 현재 낚시지수 API가 못 주는 N물/만조·간조 시각이 꼭
  필요하면 원래 계획한 KHOA 조석예보 API(dataset 15038991)를 별도로 추가.
- **텔레그램 보조 알림**: Web Push만으로 부족하면(iOS 사용자 등) 재개 —
  `Subscriber.telegram_chat_id` 필드는 이미 있다.
- **남은 화면 UI 이식**: `weather.html`/`map.html`/`register.html`/`edit_boat.html`을
  G1-G3와 같은 디자인 시스템으로 이어서 이식할지 여부.
- **robots 차단 배 처리**(R2), **User-Agent 정직화**(R4) — 우선순위 낮음, ToS
  리스크는 현재까지 문제 없었음.

---

## 부록 A. 용어 / 물때 글로서리
- **물때**: 조석 주기를 낚시 문화에서 부르는 이름. 서해는 N물(예: 6물)·사리·조금 체계.
- **사리(대조)**: 조차가 가장 큰 시기(음력 보름/그믐 전후). **조금(소조)**: 조차가 가장 작은 시기.
- **만조(고조)**: 해수면이 가장 높은 때. **간조(저조)**: 가장 낮은 때. 조위는 cm.
- **월령**: 달의 나이(음력 근사). 물때 유도의 기준.
- **한객기·대객기·무시**: 조금~사리 전환 구간의 물때 이름(사이트별 표기 편차 있음).
- ※ 같은 날짜라도 **서해/남해 물때 숫자가 다를 수 있음**(실측 확인). 본 서비스는 서해 기준.
