# CLAUDE.md — AFT (낚시배 자리 알림) 프로젝트 메모리

> 이 파일은 Claude Code가 세션 시작 시 자동으로 읽는 **상시 규칙**이다. 짧게 유지한다.
> 세부 설계·결정 로그는 `PLAN.md`, 실행 이력·다음 후보 작업은 `HANDOFF_PROMPT.md` 참조.

## 현재 상태 (요약)
"당김→밀기" 전환이 **완료돼 운영 중**이다. 감시 등록 → GitHub Actions(매시 정각)가
Render 앱의 `/api/scrape/run`을 트리거 → Render가 실제로 스크래핑(수집은 Actions가
아니라 Render가 한다 — 아래 "핵심 좌표" 참고) → 스냅샷 비교 → 변화 시 Web Push 발송.
텔레그램은 **채택하지 않았다**(계획엔 있었으나 Web Push만으로 충분해 보류).
UI는 Claude Design 기반으로 3화면(배 목록/예약현황/빈자리 알림)을 새로 이식했다
(`/`, `/status`, `/watches`). `weather.html`/`map.html`/`register.html`/`edit_boat.html`은
아직 옛 디자인 그대로다(스트랭글러 원칙상 필요할 때 단계적으로 이식).

## 불변 규칙 (어기면 되돌린다)
1. **하네스 우선**: 파서/조석 로직을 바꾸기 전에 그 변형의 fixture(실제 응답) + `*.expected.json` 골든을
   먼저 만든다. **fixture 없이 파싱 코드 변경 금지.**
2. **파싱/IO 분리**: 파서는 `parse(html) -> list[Slot]` 순수 함수. 네트워크는 fetcher로 격리.
3. **기존 보존(스트랭글러)**: 기존 라우트/화면/테스트를 깨지 말 것. 새 경로가 동등함을 테스트로 입증한
   뒤에만 교체한다. UI 이식은 화면별 단계적으로, 공유 템플릿(`base.html`)은 손대지 않고
   새 레이아웃(`base_design.html`)을 얹는 식으로 병행 운영한다.
4. **실패 격리**: 배 한 척 실패, 수집 실패, 발송 실패가 전체를 멈추지 않게 → 격리 후 진행.
5. **작게, 초록불에서만**: 단계마다 `pytest` 통과 후 커밋. 실패 상태로 다음 단계 진행 금지.
   서브에이전트에게 위임한 작업도 **완료 보고를 그대로 믿지 말고 직접 diff·pytest·실제
   렌더로 재검증**한 뒤 커밋한다.
6. **시크릿은 코드에 두지 않는다**: KHOA 키(`KHOA_FISHING_API_KEY`)·VAPID·`SCRAPE_TOKEN`·
   `DATABASE_URL`은 전부 Render 환경변수 + GitHub Secrets로만 관리.
7. **계획 개념을 기존 `src/` 구조에 매핑**: 리포를 재구성하지 말 것.
   `src/services/tide/`(KHOA 낚시지수), `src/services/notify/`(Web Push), `src/scheduler/`(수집
   파이프라인), `src/services/watch_service.py`(감시 등록).

> 규칙은 문맥이 아니라 **테스트로 강제**한다. "완료" 보고 전에 항상 `pytest`로 초록불을 확인한다.

## 핵심 좌표 (헷갈리기 쉬운 지점)
- 예약 파서: `src/services/reservation_checker.py`의 `check_single_boat()`. 배 이름이
  "~호"로 안 끝나거나(예: 팀에프원) 마감 시 잔여석에 정원이 남는 버그를 고쳤다
  (`_is_valid_ship_name`, `avail=0` 강제). 여전히 sunsang24/thefishing 두 플랫폼
  패턴만 정식 지원 — 독립 도메인 배(약 28척) 상당수는 fixture 미확보 상태.
- **수집은 Actions가 아니라 Render가 한다.** GitHub Actions 러너(해외 IP)는 한국
  중소 호스팅 다수에 연결 자체가 막힌다(실측). 그래서 워크플로는 `POST
  /api/scrape/run`(Render, `SCRAPE_TOKEN` 인증)을 호출만 하고, 실제 스크래핑·비교·
  발송은 Render 프로세스 안에서 `scheduler/run_scrape.py`가 수행한다.
- `/status` 라이브 조회(`STATUS_MAX_WORKERS`)는 **4가 최적값**(실측: 24로 올리면
  오히려 느려짐 — 0.1 CPU 인스턴스에서 스레드 경합). 71척 라이브 조회 ≈100초.
  `/api/status/cached`는 저장된 스냅샷을 즉시(≈1초) 돌려준다 — 화면은 캐시 우선
  표시 후 라이브로 배별 교체.
- 조석/낚시지수: `src/services/tide/khoa_fishing.py` — KHOA 바다낚시지수 API
  (`GetFcstFishingApiServicev2`, `gubun=선상`). **오늘부터 +5일만 예보한다**(문서에
  없는 실측 제약). 그 밖 날짜는 오류가 아니라 `available:false`로 응답 — 몇 주 뒤
  예약 날짜 대부분이 이 범위 밖이라는 것을 UI가 담담히 알려야 한다. 이 API는
  N물 숫자가 아니라 소조기/대조기 단위만 준다 — **실제 N물 표시는 이 API와
  무관하게 `src/services/tide/mulddae.py`(음력 계산, 순수 함수)가 담당한다.**
  서해/남해 규칙이 달라서(바다타임 실측 검증, PLAN.md §4b.2) 지역별 lookup
  table 두 개를 쓴다. 예약현황 카드에 표시(`/api/status`, `/api/status/cached`
  의 `mulddae` 필드).
- 감시 상한: `MAX_WATCHES_PER_SUBSCRIBER = 20`(`src/models.py`). 원래 5였고
  "GitHub Actions 무료 분(월 2,000, private repo)"이 근거였는데, 이 리포가
  실제로 public이라 Actions 분 자체는 무제한임을 확인하고 사용자 결정으로
  20으로 올렸다(PLAN.md D16). 더 올리려면 스크래핑 부하(사람수×상한이 매시간
  수집 대상)를 먼저 가늠할 것.
- **Render keep-alive는 GitHub Actions가 아니라 UptimeRobot(외부 무료)이 5분
  간격으로 `/healthz`를 찌른다.** GitHub Actions `schedule`로 10분 간격 핑을
  먼저 시도했는데, 실행 이력을 API로 추적해보니 자동 실행이 1.75~5.5시간
  간격에 그쳐(기대치 10분) 고빈도 폴링엔 못 쓴다고 실측됨(PLAN.md D14→D15).
  `/healthz`는 06:00~24:00 KST에만 200을 주고 그 외엔 503이다(24시간 내내
  깨우면 Render 무료 티어의 워크스페이스 월 750 instance-hour 한도를 31일
  달엔 744시간까지 써서 한도 초과 위험 — 넘기면 그 달 서비스가 통째로 정지돼
  막으려던 콜드스타트보다 더 나쁘다). 이 시간대 게이팅은 라우트 자체
  (`src/routes/views.py`)가 하므로, 외부 핑 서비스는 그냥 자주 찌르기만
  하면 된다.
- **`scrape.yml`의 `schedule` cron도 "매시간 1회는 안정적"이라던 예전 결론이
  실측으로 뒤집혔다(PLAN.md D20).** 실제 실행 간격이 2시간50분~8시간33분으로
  들쭉날쭉했고, cron을 5분 간격으로 바꿔도 19분 동안 새 스케줄 실행이 한 번도
  안 돌 만큼 GitHub Actions가 워크플로 파일의 cron 변경 자체를 반영하는 데도
  크게 지연됨을 확인했다. **즉시 결과가 필요한 진단(배포 확인, 버그 재현)은
  cron을 만지지 말고 이미 있는 `workflow_dispatch`(Actions 탭의 수동 실행
  버튼, 저장소 소유자만 가능)를 쓸 것** — 실제로 수동 실행 1회로 몇 분 안에
  결과를 확인할 수 있었다. 다만 파이프라인/체크 기록 로그 자체의 정확성은
  이 실측으로 검증됐다 - 문제는 "기록이 안 된다"가 아니라 "생각보다 뜸하게
  기록된다"였다.
- **알림 켜기/끄기 토글**: `/status`, `/watches` 둘 다 같은 버튼으로 켜고 끈다.
  끄면 `PushSubscription.unsubscribe()`(브라우저) + `POST
  /api/push/unsubscribe`(`deactivate_all_watches`)로 활성 감시를 전부
  끈다(사용자 결정 - 하드 삭제 아님, remove_watch와 같은 이유).
- **예약현황(`/status`) 결과 카드는 선사(등록된 배) 단위로 묶여 있다** -
  `renderRows()`의 `groupByCompany()`가 정렬된 평면 배열(배 1척=행 1개)을
  `registered_name`으로 묶는다. 선단(한 URL이 여러 척을 내놓음)이면 카드 안에
  `fleet-ship-row`가 척마다 있고 각자 알림 토글(`buildWatchToggle(r, true)`)이
  붙는다. `updateStatsCards`/`sortRows`는 여전히 배(ship) 단위 평면 배열을
  본다 - 그룹핑은 순수 렌더링 단계에서만 일어난다. 백엔드는 안 바뀌었다.
- **알림 토글(`.bell-toggle`, `buildWatchToggle`)은 감시 불가능한 배도 `disabled`
  상태로 항상 그린다** - 예전엔 `Watch.canWatch(r)`가 false면 토글 자체를 안
  그려서 "왜 버튼이 없는지" 알 길이 없었다(빈 동그라미 문제, D19). 이제 켜짐/
  꺼짐/비활성 3상태 모두 🔔/🔕 아이콘 + 글자 라벨을 같이 보여준다. 선단 카드는
  `fleet-ship-list` 아래에 `buildFleetMasterToggle()`(all-on/partial/none
  3상태 + n/N 카운터)이 붙어 척 전체를 한 번에 켜고 끌 수 있다 - 새 API 없이
  기존 체크박스들을 순차로 `Watch.toggle()` 호출한 뒤 `renderRows()`로 다시
  그린다.
- **체크 기록 로그**(`/watches`)는 `WatchCheckLog`(`src/models.py`) 이력
  테이블로 동작한다 - Snapshot 은 최신 1건만 들고 있어 과거 확인을 복원 못 해서
  따로 뒀다. `run_scrape.collect_one()`이 감시 중인 ship만 골라 기록하고(같은
  배 페이지의 감시 안 하는 다른 선박은 안 남김), `run_pipeline()`이 매 실행마다
  2일 초과분을 정리한다(`purge_old_check_logs`, 별도 cron 불필요). 조회는
  `GET /api/watches/history`.
- 새 UI 디자인 원본(Claude Design export)은 리포 밖 스크래치패드에 있다 — 재이식이
  필요하면 사용자에게 다시 export를 요청해야 한다(리포에 커밋된 원본 없음).
- 이 환경(Windows Git-Bash)에서 `lsof`가 포트 점유 프로세스를 못 찾는다. 로컬 서버
  재기동 전엔 `ps aux | grep python`으로 PID를 직접 찾아 `kill -9`할 것 — 안 그러면
  옛 프로세스가 계속 응답해서 "확인했는데 반영이 안 됐다"는 착각을 하게 된다(실제로
  겪음).

## 명령어
- 테스트: `pytest`
- 로컬 서버: `FLASK_APP=wsgi.py PYTHONPATH=src python -m flask run` (`python app.py`는
  `create_app()`만 만들고 `.run()`을 안 불러서 서버가 안 뜬다 — 알려진 함정)
- 의존성: `pip install -r requirements.txt`

## 작업 프로토콜
1. 코드 전에 갭 분석/계획을 제시하고 승인받는다. 큰 변경(다중 파일, 아키텍처 판단)은
   플랜 모드로 먼저 정리한다.
2. 작게 커밋, 각 단계 `pytest` 초록불에서만 다음으로.
3. 파괴적 변경(DB 초기화, 강제 push, 시크릿 재발급 등) 전에는 질문한다.
4. **모델 사용 정책(토큰 최적화)**: 정보가 많거나 설계 판단이 필요한 **계획 단계**(갭 분석,
   여러 화면/파일에 걸친 아키텍처 설계, 트레이드오프 검토)는 Opus 5 등 상위 모델을 쓴다.
   설계가 이미 정해진 뒤의 **코딩/구현 단계**(정해진 계획을 따라 파일을 고치고, 테스트를
   쓰고, 반복적인 이식 작업을 하는 것)는 Sonnet 5을 최대한 활용한다. 서브에이전트에게
   위임했다면 결과를 상위 모델이 직접 diff·테스트로 재검증한 뒤 커밋한다.

## 사람이 제공 (환경변수 — Render + GitHub Secrets 양쪽에 동일 값)
`DATABASE_URL`(Neon Postgres) · `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_SUBJECT` ·
`KHOA_FISHING_API_KEY` · `SCRAPE_TOKEN`(Render만, Actions가 호출 시 인증).
