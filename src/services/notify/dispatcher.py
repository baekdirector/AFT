"""
전환 -> 감시자 -> 발송. Phase C.

이 모듈이 하는 일은 세 가지다.
  1. 전환 하나를 지켜보는 활성 Watch 를 찾는다.
  2. 이미 같은 전환을 알린 적 있으면 건너뛴다 (중복 방지).
  3. 보내고 결과를 Notification 에 남긴다.

한 사람에게 실패해도 나머지 발송은 계속한다(실패 격리).

dispatch_all() 은 실제 네트워크 발송(webpush.send)만 동시에 여러 건
보낸다(DISPATCH_MAX_WORKERS) - 사용자 제보(라이브 조회 "마무리" 구간이
몇 초씩 걸림) 진단 결과, dispatch_all이 전환마다·감시자마다 웹푸시를
순차로 보내는 게 그 구간의 실제 원인이었다. DB 읽기(Phase A)와 쓰기
(Phase C)는 예전처럼 완전히 순차이고 전환 단위로 rollback 격리한다 -
SQLAlchemy 세션은 스레드 안전하지 않으므로, 병렬 구간(Phase B)에서는
db.session을 절대 만지지 않는다(아래 _send_jobs_parallel 참고). 이
파일은 세션 오염으로 실측 사고를 두 번 겪은 이력이 있어(아래
dispatch_all 문서 참고) 이 경계를 특히 신중하게 지킨다.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from db import db
from models import Boat, Notification, Subscriber
from services.notify import webpush
from services.watch_service import watches_for

logger = logging.getLogger(__name__)

#: 자리 열림 뒤 반복 알림 최대 횟수(사용자 요청 - "30분 간격으로 2번 더").
#: 최초 알림(reminder_index=0)과 별개로 이 숫자만큼만 더 보낸다.
MAX_REMINDERS = 2

#: dispatch_all() 한 배치 안에서 웹푸시를 동시에 몇 건까지 보낼지.
#: webpush.send()는 순수 네트워크 호출(전역 상태·DB·Flask 컨텍스트
#: 의존 없음, services/notify/webpush.py 참고)이라 늘려도 스레드 안전성
#: 문제는 없지만, 무제한으로 두면 알림이 몰리는 회차에 외부 푸시
#: 서비스(FCM/APNs 등)에 순간적으로 과도한 동시 요청을 낼 수 있어
#: STATUS_MAX_WORKERS와 같은 수준(4)으로 상한을 둔다.
DISPATCH_MAX_WORKERS = 4


def _dedup_key(transition) -> str:
    return '|'.join(str(part) for part in transition.dedup_key)


def already_notified(watch_id: int, dedup_key: str) -> bool:
    """이 감시자에게 '방금 그 알림'을 또 보내려는 것인가.

    평생 유일이 아니라 '연속 반복'만 막는다. 마지막으로 성공한 발송과 키가
    같을 때만 건너뛴다. 자리가 났다가 마감됐다가 다시 나면 그 사이에 다른
    전환이 기록되므로 마지막 키가 달라져 재발송된다(PLAN.md 6).

    평생 유일로 막으면 같은 배에 자리가 두 번째로 났을 때 영영 조용해진다.

    실패한 발송은 '보냈다'로 치지 않는다. 그래야 다음 수집 때 재시도된다.
    """
    last_sent = (Notification.query
                 .filter_by(watch_id=watch_id, result=webpush.SENT)
                 .order_by(Notification.sent_at.desc(), Notification.id.desc())
                 .first())
    return last_sent is not None and last_sent.dedup_key == dedup_key


def _prepare_jobs(transition, boat_name: str | None, watches: list) -> list[dict]:
    """전환 하나에 대해 '누구에게 무엇을 보낼지'만 계산한다 - DB 읽기만
    하고 네트워크 호출도 DB 쓰기도 하지 않는다.

    watch.subscriber.to_subscription_info() 를 여기서 미리 끝내는 게
    핵심이다 - 병렬 발송 구간(_send_jobs_parallel)에는 ORM 객체(watch,
    subscriber)가 아니라 이 순수 dict만 넘긴다. SQLAlchemy 세션은 스레드
    안전하지 않아서, 다른 스레드가 지연 로딩(lazy load)을 건드리면 예측
    못 할 오류나 세션 오염이 날 수 있다. watch_id/subscriber_id는 이미
    로드된 평범한 정수 컬럼이라(관계 아님) 그대로 들고 다녀도 안전하다.
    """
    if not watches:
        return []
    if boat_name is None:
        boat = Boat.query.get(transition.boat_id)
        boat_name = boat.name if boat else ''
    key = _dedup_key(transition)
    payload = webpush.build_payload(transition, boat_name)
    jobs = []
    for watch in watches:
        if already_notified(watch.id, key):
            continue
        jobs.append({
            'watch_id': watch.id,
            'subscriber_id': watch.subscriber_id,
            'subscription_info': watch.subscriber.to_subscription_info(),
            'payload': payload,
            'dedup_key': key,
            'kind': transition.kind,
        })
    return jobs


def _send_jobs_parallel(jobs: list[dict]) -> list[tuple[dict, str, str]]:
    """webpush.send() 호출만 동시에 여러 건 돌린다.

    DB에도 Flask 앱 컨텍스트에도 손대지 않는 순수 네트워크 호출이라
    스레드 간 공유해도 안전하다(webpush.send는 os.environ만 읽고 전역
    가변 상태가 없다 - services/notify/webpush.py 참고). 어느 한 건이
    예외를 던져도(webpush.send 자체가 이미 격리하지만 방어적으로 한 번
    더) 나머지 발송에 영향을 주지 않는다. 결과는 완료된 순서로 모이므로
    호출부가 job으로 다시 매칭해서 써야 한다.
    """
    if not jobs:
        return []
    max_workers = min(len(jobs), DISPATCH_MAX_WORKERS)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_job = {
            executor.submit(webpush.send, job['subscription_info'], job['payload']): job
            for job in jobs
        }
        for future in as_completed(future_to_job):
            job = future_to_job[future]
            try:
                result, detail = future.result()
            except Exception as exc:
                result, detail = webpush.FAILED, f'{type(exc).__name__}: {exc}'[:500]
            results.append((job, result, detail))
    return results


def _record_results(results: list[tuple[dict, str, str]]) -> list[Notification]:
    """발송 결과를 Notification 행으로 기록한다 - 반드시 메인 스레드(원래
    세션)에서만, 순차로 호출해야 한다. 커밋은 하지 않는다 - 호출부가
    원하는 단위(전환별/단건)로 커밋 경계를 정한다."""
    created = []
    for job, result, detail in results:
        record = Notification(watch_id=job['watch_id'], dedup_key=job['dedup_key'],
                              channel='webpush', result=result, detail=detail or None,
                              kind=job['kind'], reminder_index=0)
        db.session.add(record)
        created.append(record)
        if result == webpush.EXPIRED:
            # 죽은 구독을 남겨두면 매번 실패하며 발송 시간을 잡아먹는다.
            # 감시도 함께 정리된다(Subscriber cascade).
            logger.info('만료된 구독을 삭제한다: subscriber=%s', job['subscriber_id'])
            subscriber = Subscriber.query.get(job['subscriber_id'])
            if subscriber is not None:
                db.session.delete(subscriber)
    return created


def dispatch(transition, boat_name: str | None = None,
            watches: list | None = None) -> list[Notification]:
    """전환 하나를 관련 감시자 전원에게 보낸다(순차).

    돌려주는 값은 이번에 새로 만든 Notification 행들이다.
    이미 보냈거나 감시자가 없으면 빈 목록이다.

    `watches`를 이미 조회해둔 호출부는 그걸 넘겨서 같은 조건으로 또
    쿼리하지 않게 할 수 있다 - 생략하면 여기서 직접 조회한다. 단일
    전환용 공개 API라 순차로만 보낸다(보통 감시자가 몇 명 안 돼 병렬화
    이득이 작다) - 배치 병렬 처리는 dispatch_all()이 담당한다.
    """
    if watches is None:
        watches = watches_for(transition.boat_id, transition.target_date,
                              transition.ship_name)
    jobs = _prepare_jobs(transition, boat_name, watches)
    if not jobs:
        return []
    results = [(job, *webpush.send(job['subscription_info'], job['payload'])) for job in jobs]
    created = _record_results(results)
    db.session.commit()
    return created


def dispatch_all(transitions, boat_names: dict | None = None) -> dict:
    """전환 여러 건을 처리하고 집계를 돌려준다.

    전환 하나 처리 중 예외가 나도 나머지 전환은 계속 보낸다(실패 격리,
    CLAUDE.md 불변규칙 4). 예전엔 이 루프에 격리가 없어서, 배치 안 어느
    전환 하나가 dispatch() 안에서 예외를 던지면 그 뒤에 놓인 전환은
    발송 시도조차 못 해보고 그 실행이 통째로 죽었다 - 그러면서 체크 기록
    로그(WatchCheckLog)는 수집 단계에서 이미 따로 커밋된 뒤라 "변화 감지"로
    남는데 실제 푸시는 하나도 안 나가는, 겉보기엔 알 수 없는 무음 실패가
    생겼다(실측: 2026-09-14 백호호 18:30 자리남 전환 - 다음 수집 때는 상태가
    이미 '열림'이라 같은 전환이 다시 안 잡혀 영영 재시도가 안 됐다).

    db.session.rollback() 을 반드시 같이 해야 한다 - 이 격리를 처음 넣었을
    때 이걸 빠뜨렸었다(dispatch_reminders 의 같은 except 블록에는 있었는데
    여기만 없었다). SQLAlchemy 세션은 flush/commit 중 예외가 나면 그 뒤로
    rollback 전까지 어떤 쿼리도 거부하는 "오염된" 상태가 된다 - rollback
    없이 continue만 하면, 이 전환 하나의 실패가 배치의 그 뒤 모든 전환의
    처리를 전부 예외로 연쇄 실패시킨다(그것도 이 try/except가 조용히
    삼켜버려서 겉보기엔 "격리가 잘 되는 것처럼" 보인다) - 실측:
    2026-09-15 19:30 레드히어로 자리남 전환이 체크 기록 로그엔 "변경"으로
    남았는데도 그 뒤 반복 알림까지 포함해 푸시가 전혀 안 갔다.

    3단계로 나눠서 처리한다:
      Phase A(순차, DB 읽기) - 전환마다 _prepare_jobs()로 보낼 것만 계산.
        실패하면 그 전환만 위 방식대로 격리하고 다음 전환으로 넘어간다.
      Phase B(병렬, DB 없음) - 전체 배치의 모든 job을 한꺼번에
        _send_jobs_parallel()로 동시에 보낸다. 이 구간은 db.session을
        전혀 만지지 않으므로 세션 오염 위험 자체가 없다.
      Phase C(순차, DB 쓰기) - 전환 단위로 결과를 기록하고 커밋한다.
        Phase A와 똑같은 전환 단위 rollback 격리를 그대로 쓴다 - 병렬화가
        이 부분의 신뢰성을 조금도 바꾸지 않는다.
    """
    boat_names = boat_names or {}
    summary = {'transitions': 0, 'sent': 0, 'failed': 0,
               'expired': 0, 'disabled': 0, 'skipped_duplicate': 0}

    per_transition_jobs = []
    for transition in transitions:
        summary['transitions'] += 1
        try:
            watches = watches_for(transition.boat_id, transition.target_date,
                                  transition.ship_name)
            jobs = _prepare_jobs(transition, boat_names.get(transition.boat_id), watches)
            summary['skipped_duplicate'] += max(0, len(watches) - len(jobs))
            per_transition_jobs.append((transition, jobs))
        except Exception:
            db.session.rollback()
            logger.exception('전환 발송 준비 실패(격리) boat=%s date=%s ship=%s kind=%s',
                             transition.boat_id, transition.target_date,
                             transition.ship_name, transition.kind)
            continue

    all_jobs = [job for _, jobs in per_transition_jobs for job in jobs]
    all_results = _send_jobs_parallel(all_jobs)
    # watch_id는 이 배치 전체에서 유일하다 - watches_for가 전환마다 독립된
    # (boat_id, target_date, ship_name) 키로 조회하므로 같은 활성 Watch가
    # 두 전환에 동시에 걸릴 수 없다(감시 하나는 항상 정확히 그 셋의 조합
    # 하나만 가리킨다).
    results_by_watch_id = {job['watch_id']: (job, result, detail)
                           for job, result, detail in all_results}

    for transition, jobs in per_transition_jobs:
        if not jobs:
            continue
        try:
            results = [results_by_watch_id[job['watch_id']] for job in jobs]
            created = _record_results(results)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('전환 발송 기록 실패(격리) boat=%s date=%s ship=%s kind=%s',
                             transition.boat_id, transition.target_date,
                             transition.ship_name, transition.kind)
            continue
        for record in created:
            if record.result in summary:
                summary[record.result] += 1
    return summary


def dispatch_reminders(observations, boat_names: dict | None = None) -> dict:
    """자리가 계속 열려 있는 (배,날짜,선박)에 반복 알림을 보낸다.

    사용자 요청: "자리변경 알림이 왔으면 30분 뒤에도 자리가 있으면 다시
    웹푸시를 2번 더 날려달라". snapshot.py의 diff/compare 는 일부러 상태가
    그대로면 전환을 만들지 않는다("잔여석 숫자만 흔들린 것은 알리지 않는다")
    - 그 규칙은 안 건드리고, 여기서 별도로 "감시 중인 배가 지금 열려 있는데
    이번 수집에서 새 전환은 없었다"는 관측들만 받아 반복 여부를 판단한다.
    (호출부가 이번 회차에 전환이 난 (배,날짜,선박)은 걸러서 넘겨야 한다 -
    안 그러면 최초 알림과 같은 회차에 반복 알림까지 같이 나가버린다.)

    한 Watch 의 "가장 최근에 성공 발송한" Notification 을 보고:
      - SEAT_OPEN(최초, reminder_index=0) 이면 반복 1회차를 보낸다.
      - REMINDER 이고 아직 상한(MAX_REMINDERS) 미만이면 다음 회차를 보낸다.
      - 그 외(SEAT_GONE/STATUS_CHANGE 였거나 상한에 닿았거나 발송 이력이
        아예 없으면)는 조용히 건너뛴다.
    전환 하나 실패가 나머지를 막지 않게 dispatch_all 과 같은 방식으로
    watch 단위 실패를 격리한다.
    """
    boat_names = boat_names or {}
    summary = {'candidates': 0, 'sent': 0, 'failed': 0, 'expired': 0, 'disabled': 0}

    for obs in observations:
        if not obs.has_seat:
            continue
        watches = watches_for(obs.boat_id, obs.target_date, obs.ship_name)
        if not watches:
            continue

        boat_name = boat_names.get(obs.boat_id)
        if boat_name is None:
            boat = Boat.query.get(obs.boat_id)
            boat_name = boat.name if boat else ''

        for watch in watches:
            try:
                last = (Notification.query
                       .filter_by(watch_id=watch.id, result=webpush.SENT)
                       .order_by(Notification.sent_at.desc(), Notification.id.desc())
                       .first())
                if last is None:
                    continue
                if last.kind == 'SEAT_OPEN':
                    next_index = 1
                elif last.kind == 'REMINDER' and last.reminder_index < MAX_REMINDERS:
                    next_index = last.reminder_index + 1
                else:
                    continue

                summary['candidates'] += 1
                payload = webpush.build_reminder_payload(obs, boat_name)
                result, detail = webpush.send(watch.subscriber.to_subscription_info(), payload)
                record = Notification(
                    watch_id=watch.id,
                    dedup_key=f'{obs.boat_id}|{obs.target_date}|{obs.ship_name}|REMINDER|{next_index}',
                    channel='webpush', result=result, detail=detail or None,
                    kind='REMINDER', reminder_index=next_index)
                db.session.add(record)
                db.session.commit()
                if result in summary:
                    summary[result] += 1
                if result == webpush.EXPIRED:
                    logger.info('만료된 구독을 삭제한다: subscriber=%s', watch.subscriber_id)
                    db.session.delete(watch.subscriber)
                    db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception('반복 알림 실패(격리) boat=%s date=%s ship=%s watch=%s',
                                 obs.boat_id, obs.target_date, obs.ship_name, watch.id)
    return summary
