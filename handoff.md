# 코딩 에이전트 핸드오프 — AFT(낚시배 자리 알림) 현재 상태

> 이 파일은 원래 "Phase A→F 실행 지시서"였다. 그 Phase들은 전부 완료됐고(아래
> 표), 이 문서의 역할은 이제 **다음 세션이 빠르게 따라잡기 위한 현재 상태 요약 +
> 다음 후보 작업 목록**으로 바뀌었다. 세부 결정 근거·리스크·데이터모델은
> `PLAN.md`(§7 실행결과, §10 결정로그)가 단일 출처다. 상시 규칙은 `CLAUDE.md`.

---

## 지금 뭐가 되어 있나 (실측 기준, 2026-09)

**서비스는 실제로 돌아간다.** 매시 정각 GitHub Actions → Render `/api/scrape/run`
트리거 → Render가 감시 등록된 (배,날짜)만 스크래핑 → 스냅샷 비교 → 변화 시
Web Push 발송. 웹 UI는 3화면(배 목록/예약현황/빈자리 알림)이 Claude Design 기반
새 디자인으로 배포돼 있다.

| 영역 | 상태 | 위치 |
|---|---|---|
| 예약 파서 | 실측 버그 2건 수정, fixture 하네스 5건 | `src/services/reservation_checker.py`, `tests/fixtures/` |
| 스냅샷/변화감지 | 완료 | `src/services/snapshot.py`, `snapshot_repository.py` |
| 감시 등록 | 완료(5척/사람 상한) | `src/services/watch_service.py`, `/api/watches` |
| Web Push | 완료(테스트발송 기능 포함) | `src/services/notify/webpush.py`, `/api/push/*` |
| 텔레그램 | **미구현**(의도적 보류) | — |
| 스케줄러 | 완료, Actions는 트리거만 | `src/scheduler/run_scrape.py`, `.github/workflows/scrape.yml` |
| `/status` 성능 | 캐시우선표시로 해결 | `/api/status/cached`, ≈1초 |
| 조석/물때 | KHOA 낚시지수 API로 대체 구현, +5일 한정 | `src/services/tide/khoa_fishing.py`, `/weather` |
| UI 재디자인 | 3화면 완료(배 목록/예약현황/알림) | `index.html`/`status.html`/`watches.html` + `base_design.html` |
| 나머지 화면 | 옛 디자인 그대로 | `weather.html`/`map.html`/`register.html`/`edit_boat.html` |
| Render keep-alive | 완료. UptimeRobot(외부) 5분 핑, `/healthz`가 06:00~24:00 KST만 200 | `/healthz`(`src/routes/views.py`) |

`pytest` 229 passed, 1 xfailed(badatime 아이콘 파싱 — fixture 확보 전까지 의도적 보류).

## 계획과 실제가 갈린 지점 (다음 세션이 헷갈리지 않도록)

1. **조석은 KHOA 조석예보 API가 아니라 KHOA 낚시지수 API로 갔다.** 사용자가
   발급받은 키가 이 API였고, N물 대신 소조기/대조기 + 어종별 낚시지수를 준다.
   **오늘부터 +5일만 예보한다**(문서에 없던 제약, 직접 호출해서 알아냄). 정밀
   조석(N물/만조·간조 시각)이 필요해지면 별도 작업이다 — PLAN.md §11 참고.
2. **스크래핑은 GitHub Actions가 아니라 Render가 한다.** Actions 러너(해외 IP)가
   한국 중소 호스팅 다수에 연결이 막혀서(실측: 동일 배가 Render 6/6 성공,
   Actions 1/6 성공) 아키텍처를 바꿨다. Actions는 `SCRAPE_TOKEN`으로 인증하며
   `POST /api/scrape/run`을 트리거만 한다.
3. **`STATUS_MAX_WORKERS`는 4가 맞다.** 24로 올리면 오히려 느려진다(Render
   0.1 CPU에서 스레드 경합). "동시성을 올리면 빨라진다"는 직관이 이 환경에서는
   틀렸다 — 다시 올리기 전에 반드시 라이브에서 실측할 것.
4. **텔레그램은 안 만들었다.** `Subscriber.telegram_chat_id` 필드는 모델에
   남아있으니 필요해지면 그 필드부터 살리면 된다.
5. **UI가 중간에 통째로 바뀌었다.** 사용자가 Claude Design으로 새 디자인을
   보내와서 원래 계획(Phase 5, 기존 화면에 감시 버튼만 추가)보다 훨씬 큰
   작업(화면 3개 전체 재구성)이 들어갔다. `base.html`은 안 건드리고
   `base_design.html`을 새로 만들어 화면별로 갈아탔다 — 나머지 4개 화면은
   아직 옛 디자인이라 언젠가 마저 이어가야 한다.

## 이 환경에서 반드시 알아야 할 함정

- **로컬 서버 실행**: `python app.py`는 `create_app()`만 만들고 `.run()`을 안
  불러서 서버가 안 뜬다. `FLASK_APP=wsgi.py PYTHONPATH=src python -m flask run`
  을 쓴다.
- **`lsof`가 이 환경(Windows Git-Bash)에서 포트 점유 프로세스를 못 찾는다.**
  로컬 서버를 재기동하기 전에 `ps aux | grep python`으로 PID를 직접 찾아
  `kill -9`할 것 — 안 그러면 옛 프로세스가 계속 응답해서 변경사항이 반영 안
  됐다고 착각하게 된다(이번 세션에서 실제로 겪었고, 재검증하다 잡아냈다).
- **User-Agent가 Chrome/Firefox로 위장돼 있다.** PLAN.md R4(ToS 취지)와
  반대지만, 바꾸면 403이 늘 위험이 있어 그대로 뒀다. 건드릴 거면 라이브에서
  먼저 재보고 결정할 것.
- **서브에이전트(Sonnet)에게 코딩을 위임했다면, 완료 보고를 그대로 믿지 말고
  직접 `git diff`·`pytest`·실제 렌더로 재검증**한 뒤에만 커밋한다. 이번
  세션에서 "미사용이라 제거했다"는 보고를 실제로 `git show`로 대조해서
  확인한 사례, 로컬 검증에서 옛 서버 프로세스를 새 서버로 착각한 사례가
  둘 다 있었다.
- **Render 무료 티어를 24시간 내내 깨워두지 말 것.** 워크스페이스 전체 월
  750 instance-hour 한도가 있어서, 31일짜리 달에 24시간 always-on을 하면
  744시간을 써서 여유가 6시간뿐이다 — 한도를 넘기면 그 달 서비스가 통째로
  정지된다(막으려던 콜드스타트보다 더 나쁜 상황). 그래서 keep-alive는
  06:00~24:00 KST(하루 18시간, 월 최대 558시간)로만 범위를 좁혔다(D15). 이
  시간대를 넓히자는 얘기가 나오면 이 한도부터 다시 계산할 것.
- **GitHub Actions `schedule`을 고빈도(10분 등) 폴링에 쓰지 말 것.** 원래
  keep-alive를 GitHub Actions 10분 cron으로 만들었는데(D14), 실제 실행
  이력을 API로 추적해보니 자동 실행이 1.75~5.5시간 간격에 그쳤다(기대치
  10분, 60회 이상 vs 실제 4회/11시간). `scrape.yml`처럼 매시간 1회는
  안정적으로 도는 것과 대비된다 — GitHub Actions cron은 저빈도(시간 단위)
  작업엔 쓰고, 분 단위 고빈도 폴링은 UptimeRobot 같은 전용 외부 서비스로
  보낼 것(D15, `/healthz`).

## 다음 후보 작업 (우선순위는 사용자와 상의)

PLAN.md §11과 동일:
1. 독립 도메인 배(~28척) 중 fixture 미확보분 캡처 — 실제로 조회 안 되는 배가
   더 있을 수 있다.
2. 정밀 조석(N물/만조·간조)이 필요하면 원래 계획한 KHOA 조석예보 API
   (dataset 15038991)를 별도로 추가.
3. 텔레그램 보조 알림(iOS 사용자 대응).
4. 나머지 4개 화면(`weather`/`map`/`register`/`edit_boat`)을 새 디자인으로 이식.
5. robots 차단 배 처리, User-Agent 정직화 — 지금까지 문제 없었어서 낮은 우선순위.

## 명령어

- 테스트: `pytest`
- 로컬 서버: `FLASK_APP=wsgi.py PYTHONPATH=src python -m flask run`
- 라이브: https://aft-hcwf.onrender.com (Render, `main` push 시 자동 배포)
- 배포 확인 루틴: push → `curl`로 신규 마커 문자열이 뜰 때까지 폴링(보통 2~4회,
  20초 간격) → 실제 기능까지 curl/로컬 렌더로 확인.
