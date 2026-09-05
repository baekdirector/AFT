"""
감시 등록/해제. Phase C.

/status 결과 표에서 체크한 행이 여기로 들어와 Watch 한 건이 된다.
스케줄러(Phase D)는 여기서 만들어진 활성 Watch 만 수집한다. 즉 이 모듈이
수집량을 결정한다 - 전 선박을 훑지 않는 이유가 이것이다.
"""
from __future__ import annotations

from datetime import datetime

from db import db
from models import MAX_WATCHES_PER_SUBSCRIBER, Boat, Snapshot, Subscriber, Watch


class WatchLimitExceeded(Exception):
    """감시 상한을 넘겼다. 사용자에게 그대로 보여줄 메시지를 담는다."""

    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f'감시는 최대 {limit}척까지 등록할 수 있습니다.')


def upsert_subscriber(endpoint: str, p256dh: str, auth: str,
                      label: str | None = None) -> Subscriber:
    """푸시 구독을 저장한다. 같은 endpoint 면 갱신한다.

    브라우저는 구독을 조용히 갱신(rotate)할 수 있으므로 endpoint 를 키로 두고
    upsert 한다. 새 행을 계속 쌓으면 같은 사람에게 중복 알림이 간다.
    """
    if not endpoint or not p256dh or not auth:
        raise ValueError('구독 정보가 불완전합니다.')

    sub = Subscriber.query.filter_by(endpoint=endpoint).one_or_none()
    if sub is None:
        sub = Subscriber(endpoint=endpoint, p256dh=p256dh, auth=auth, label=label)
        db.session.add(sub)
    else:
        sub.p256dh = p256dh
        sub.auth = auth
        if label:
            sub.label = label
    sub.last_seen_at = datetime.utcnow()
    db.session.commit()
    return sub


def list_watches(subscriber: Subscriber) -> list[Watch]:
    return (Watch.query
            .filter_by(subscriber_id=subscriber.id, active=True)
            .order_by(Watch.target_date, Watch.ship_name)
            .all())


def count_watches(subscriber: Subscriber) -> int:
    return Watch.query.filter_by(subscriber_id=subscriber.id, active=True).count()


def serialize_watches(watches: list[Watch]) -> list[dict]:
    """Watch 목록을 API 응답 모양으로 바꾸면서 마지막 실제 확인 시각을 붙인다.

    Watch.created_at 은 "언제 체크박스를 켰는지"일 뿐이다. /watches 화면의
    체크 기록 로그는 "시스템이 실제로 이 배의 자리를 언제 확인했는지"를
    보여주려는 것이었는데 둘을 혼동해서 등록 시각을 대신 보여주는 버그가
    있었다 - 감시 5건을 서로 다른 날 등록했으면 매시간 다같이 검사돼도
    로그엔 등록한 날짜가 제각각으로 보였다. Snapshot 이 (boat_id,
    target_date, ship_name) 키를 Watch 와 공유하므로(모델 주석 참고) 그걸로
    조인해 마지막 확인 시각(checked_at)을 구한다.
    """
    if not watches:
        return []

    boat_ids = {w.boat_id for w in watches}
    dates = {w.target_date for w in watches}
    snapshots = Snapshot.query.filter(
        Snapshot.boat_id.in_(boat_ids),
        Snapshot.target_date.in_(dates),
    ).all()
    checked_at_by_key = {
        (s.boat_id, s.target_date, s.ship_name): s.checked_at for s in snapshots
    }

    result = []
    for w in watches:
        d = w.to_dict()
        checked_at = checked_at_by_key.get((w.boat_id, w.target_date, w.ship_name))
        d['last_checked_at'] = checked_at.isoformat() if checked_at else None
        result.append(d)
    return result


def add_watch(subscriber: Subscriber, boat_id: int, ship_name: str,
              target_date: str) -> Watch:
    """감시 한 건을 건다.

    같은 대상을 다시 걸면 새로 만들지 않고 기존 것을 되살린다. 그래야
    껐다 켰다 해도 상한 계산이 어긋나지 않는다.
    """
    if not ship_name or not target_date:
        raise ValueError('선박명과 날짜가 필요합니다.')
    if Boat.query.get(boat_id) is None:
        raise ValueError('등록되지 않은 배입니다.')

    existing = Watch.query.filter_by(
        subscriber_id=subscriber.id, boat_id=boat_id,
        ship_name=ship_name, target_date=target_date).one_or_none()

    if existing is not None:
        if not existing.active:
            # 되살리는 것도 상한을 넘으면 안 된다
            if count_watches(subscriber) >= MAX_WATCHES_PER_SUBSCRIBER:
                raise WatchLimitExceeded(MAX_WATCHES_PER_SUBSCRIBER)
            existing.active = True
            db.session.commit()
        return existing

    if count_watches(subscriber) >= MAX_WATCHES_PER_SUBSCRIBER:
        raise WatchLimitExceeded(MAX_WATCHES_PER_SUBSCRIBER)

    watch = Watch(subscriber_id=subscriber.id, boat_id=boat_id,
                  ship_name=ship_name, target_date=target_date, active=True)
    db.session.add(watch)
    db.session.commit()
    return watch


def remove_watch(subscriber: Subscriber, boat_id: int, ship_name: str,
                 target_date: str) -> bool:
    """감시를 끈다. 행은 지우지 않고 비활성으로 둔다.

    발송 이력(Notification)이 Watch 를 참조하므로, 지워버리면 중복 방지
    근거까지 함께 사라져 껐다 켜는 것만으로 같은 알림을 다시 받게 된다.
    """
    watch = Watch.query.filter_by(
        subscriber_id=subscriber.id, boat_id=boat_id,
        ship_name=ship_name, target_date=target_date, active=True).one_or_none()
    if watch is None:
        return False
    watch.active = False
    db.session.commit()
    return True


def deactivate_past_watches(today: str) -> int:
    """지난 날짜의 감시를 끈다. 끈 개수를 돌려준다.

    슬롯이 5개뿐이라 지나간 날짜의 감시가 남아 있으면 새 감시를 걸 수 없다.
    지난 날짜는 알림이 나갈 일도 없으므로 수집 대상에서 빼는 것이 맞다.
    스케줄러가 매 실행 앞에서 호출한다.

    행은 지우지 않고 비활성으로 둔다. 발송 이력이 이 행을 참조하기 때문이다.
    """
    stale = Watch.query.filter(Watch.active.is_(True),
                               Watch.target_date < today).all()
    for watch in stale:
        watch.active = False
    if stale:
        db.session.commit()
    return len(stale)


def active_watch_targets() -> list[tuple[int, str]]:
    """스케줄러가 수집해야 할 (boat_id, target_date) 목록.

    여러 사람이 같은 배·날짜를 감시해도 수집은 한 번만 하면 되므로 중복을 없앤다.
    결정론적 순서로 돌려준다.
    """
    rows = (db.session.query(Watch.boat_id, Watch.target_date)
            .filter(Watch.active.is_(True))
            .distinct()
            .all())
    return sorted((boat_id, target_date) for boat_id, target_date in rows)


def watches_for(boat_id: int, target_date: str, ship_name: str) -> list[Watch]:
    """특정 (배, 날짜, 선박) 을 지켜보는 활성 감시들."""
    return (Watch.query
            .filter_by(boat_id=boat_id, target_date=target_date,
                       ship_name=ship_name, active=True)
            .all())
