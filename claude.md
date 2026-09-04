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
  예약 날짜 대부분이 이 범위 밖이라는 것을 UI가 담담히 알려야 한다. 물때는
  N물 숫자가 아니라 소조기/대조기 단위만 제공.
- 감시 상한: `MAX_WATCHES_PER_SUBSCRIBER = 5`(`src/models.py`). GitHub Actions
  무료 분(월 2,000, private repo)과 직결되므로 임의로 올리지 말 것 — 올리려면
  cron 주기(현재 매시)도 같이 조정해야 한다.
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
