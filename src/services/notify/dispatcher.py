"""
전환 -> 감시자 -> 발송. Phase C.

이 모듈이 하는 일은 세 가지다.
  1. 전환 하나를 지켜보는 활성 Watch 를 찾는다.
  2. 이미 같은 전환을 알린 적 있으면 건너뛴다 (중복 방지).
  3. 보내고 결과를 Notification 에 남긴다.

한 사람에게 실패해도 나머지 발송은 계속한다(실패 격리).
"""
from __future__ import annotations

import logging

from db import db
from models import Boat, Notification
from services.notify import webpush
from services.watch_service import watches_for

logger = logging.getLogger(__name__)

#: 자리 열림 뒤 반복 알림 최대 횟수(사용자 요청 - "30분 간격으로 2번 더").
#: 최초 알림(reminder_index=0)과 별개로 이 숫자만큼만 더 보낸다.
MAX_REMINDERS = 2


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


def dispatch(transition, boat_name: str | None = None) -> list[Notification]:
    """전환 하나를 관련 감시자 전원에게 보낸다.

    돌려주는 값은 이번에 새로 만든 Notification 행들이다.
    이미 보냈거나 감시자가 없으면 빈 목록이다.
    """
    watches = watches_for(transition.boat_id, transition.target_date,
                          transition.ship_name)
    if not watches:
        return []

    if boat_name is None:
        boat = Boat.query.get(transition.boat_id)
        boat_name = boat.name if boat else ''

    key = _dedup_key(transition)
    payload = webpush.build_payload(transition, boat_name)
    created = []

    for watch in watches:
        if already_notified(watch.id, key):
            continue

        result, detail = webpush.send(watch.subscriber.to_subscription_info(), payload)
        record = Notification(watch_id=watch.id, dedup_key=key,
                              channel='webpush', result=result, detail=detail or None,
                              kind=transition.kind, reminder_index=0)
        db.session.add(record)
        created.append(record)

        if result == webpush.EXPIRED:
            # 죽은 구독을 남겨두면 매번 실패하며 발송 시간을 잡아먹는다.
            # 감시도 함께 정리된다(Subscriber cascade).
            logger.info('만료된 구독을 삭제한다: subscriber=%s', watch.subscriber_id)
            db.session.delete(watch.subscriber)

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
    dispatch() 호출을 전부 예외로 연쇄 실패시킨다(그것도 이 try/except가
    조용히 삼켜버려서 겉보기엔 "격리가 잘 되는 것처럼" 보인다) - 실측:
    2026-09-15 19:30 레드히어로 자리남 전환이 체크 기록 로그엔 "변경"으로
    남았는데도 그 뒤 반복 알림까지 포함해 푸시가 전혀 안 갔다.
    """
    boat_names = boat_names or {}
    summary = {'transitions': 0, 'sent': 0, 'failed': 0,
               'expired': 0, 'disabled': 0, 'skipped_duplicate': 0}

    for transition in transitions:
        summary['transitions'] += 1
        try:
            before = len(watches_for(transition.boat_id, transition.target_date,
                                     transition.ship_name))
            records = dispatch(transition, boat_names.get(transition.boat_id))
        except Exception:
            db.session.rollback()
            logger.exception('전환 발송 실패(격리) boat=%s date=%s ship=%s kind=%s',
                             transition.boat_id, transition.target_date,
                             transition.ship_name, transition.kind)
            continue
        summary['skipped_duplicate'] += max(0, before - len(records))
        for record in records:
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
