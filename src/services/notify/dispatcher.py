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
                              channel='webpush', result=result, detail=detail or None)
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
    """전환 여러 건을 처리하고 집계를 돌려준다."""
    boat_names = boat_names or {}
    summary = {'transitions': 0, 'sent': 0, 'failed': 0,
               'expired': 0, 'disabled': 0, 'skipped_duplicate': 0}

    for transition in transitions:
        summary['transitions'] += 1
        before = len(watches_for(transition.boat_id, transition.target_date,
                                 transition.ship_name))
        records = dispatch(transition, boat_names.get(transition.boat_id))
        summary['skipped_duplicate'] += max(0, before - len(records))
        for record in records:
            if record.result in summary:
                summary[record.result] += 1
    return summary
