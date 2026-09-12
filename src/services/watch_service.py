"""
감시 등록/해제. Phase C.

/status 결과 표에서 체크한 행이 여기로 들어와 Watch 한 건이 된다.
스케줄러(Phase D)는 여기서 만들어진 활성 Watch 만 수집한다. 즉 이 모듈이
수집량을 결정한다 - 전 선박을 훑지 않는 이유가 이것이다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from db import db
from models import MAX_WATCHES_PER_SUBSCRIBER, Boat, Snapshot, Subscriber, Watch, WatchCheckLog


class WatchLimitExceeded(Exception):
    """감시 상한을 넘겼다. 사용자에게 그대로 보여줄 메시지를 담는다."""

    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f'감시는 최대 {limit}척까지 등록할 수 있습니다.')


def upsert_subscriber(endpoint: str, p256dh: str, auth: str,
                      label: str | None = None, ip: str | None = None,
                      device_type: str | None = None,
                      user_agent: str | None = None) -> Subscriber:
    """푸시 구독을 저장한다. 같은 endpoint 면 갱신한다.

    브라우저는 구독을 조용히 갱신(rotate)할 수 있으므로 endpoint 를 키로 두고
    upsert 한다. 새 행을 계속 쌓으면 같은 사람에게 중복 알림이 간다.

    ip/device_type/user_agent 는 관리자 콘솔의 "알림 등록" 탭이 기기별로
    감시를 묶어 보여주기 위한 표시용 정보다(services.visit_logger 와 같은
    계산). 없으면(예: 과거 구독) 그냥 기존 값을 유지한다.
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
    if ip:
        sub.ip = ip
    if device_type:
        sub.device_type = device_type
    if user_agent:
        sub.user_agent = user_agent
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
    """Watch 목록을 API 응답 모양으로 바꾸면서 마지막 실제 확인 시각과
    최근 스냅샷 상태(상태/남은자리/예약 URL)를 같이 붙인다.

    Watch.created_at 은 "언제 체크박스를 켰는지"일 뿐이다. /watches 화면의
    체크 기록 로그는 "시스템이 실제로 이 배의 자리를 언제 확인했는지"를
    보여주려는 것이었는데 둘을 혼동해서 등록 시각을 대신 보여주는 버그가
    있었다 - 감시 5건을 서로 다른 날 등록했으면 매시간 다같이 검사돼도
    로그엔 등록한 날짜가 제각각으로 보였다. Snapshot 이 (boat_id,
    target_date, ship_name) 키를 Watch 와 공유하므로(모델 주석 참고) 그걸로
    조인해 마지막 확인 시각(checked_at)을 구한다.

    상태/남은자리/예약 URL도 같은 조인에서 같이 뽑아 내려준다(/watches
    카드를 목록형으로 바꾸며 상태 배지·남은자리·예약 링크가 필요해짐 -
    새 쿼리나 라이브 스크래핑을 추가하지 않고 이미 읽은 Snapshot 행을
    재사용한다). status/available/display_status 는 status.html의
    cachedRowToDisplayRow() 가 쓰는 것과 같은 원시 값 그대로다 - status_class
    로의 변환(open/closed/maintenance/danger)은 그쪽과 똑같이 프런트에서
    한다(같은 화면끼리 매핑 로직이 갈리지 않게). 아직 한 번도 체크되지 않은
    감시는 스냅샷이 없어 이 필드들이 전부 null이고, 예약 URL만 배 등록 정보
    (Boat.url)로 대체한다.
    """
    if not watches:
        return []

    boat_ids = {w.boat_id for w in watches}
    dates = {w.target_date for w in watches}
    snapshots = Snapshot.query.filter(
        Snapshot.boat_id.in_(boat_ids),
        Snapshot.target_date.in_(dates),
    ).all()
    snapshot_by_key = {
        (s.boat_id, s.target_date, s.ship_name): s for s in snapshots
    }

    result = []
    for w in watches:
        d = w.to_dict()
        snap = snapshot_by_key.get((w.boat_id, w.target_date, w.ship_name))
        d['last_checked_at'] = snap.checked_at.isoformat() if snap else None
        d['status'] = snap.status if snap else None
        d['available'] = snap.available if snap else None
        d['display_status'] = snap.display_status if snap else None
        d['url'] = (snap.source_url if snap and snap.source_url else None) or (w.boat.url if w.boat else None)
        result.append(d)
    return result


def check_log_history(subscriber: Subscriber, days: int = 2) -> list[dict]:
    """이 구독자가 지금 걸어둔 감시들의 확인 이력을 최신순으로 돌려준다.

    WatchCheckLog 는 구독자별로 나뉘어 있지 않다(확인 자체는 시스템 공용
    이벤트라 누가 감시하든 같다) - 그래서 이 구독자의 현재 활성 감시 키
    (boat_id, ship_name, target_date) 집합을 먼저 구하고, 그 키에 해당하는
    로그만 걸러낸다. 같은 배를 여러 사람이 감시해도 이력 자체는 동일하게
    보인다 - 정상이다.
    """
    watches = list_watches(subscriber)
    if not watches:
        return []

    watched_keys = {(w.boat_id, w.ship_name, w.target_date) for w in watches}
    boat_ids = {w.boat_id for w in watches}
    dates = {w.target_date for w in watches}

    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (WatchCheckLog.query
           .filter(WatchCheckLog.boat_id.in_(boat_ids),
                   WatchCheckLog.target_date.in_(dates),
                   WatchCheckLog.checked_at >= cutoff)
           .order_by(WatchCheckLog.checked_at.desc())
           .all())

    return [row.to_dict() for row in rows
           if (row.boat_id, row.ship_name, row.target_date) in watched_keys]


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


def deactivate_all_watches(subscriber: Subscriber) -> int:
    """이 구독자의 활성 감시를 전부 끈다. 끈 개수를 돌려준다.

    '알림 끄기'를 누르면 감시도 모두 해제하기로 했다(사용자 결정) - 다시
    켜면 처음부터 다시 등록해야 한다. remove_watch 와 같은 이유로 하드
    삭제는 안 한다: 발송 이력(Notification)이 Watch 를 참조하므로 지우면
    중복 방지 근거가 사라져 껐다 켜는 것만으로 같은 알림을 다시 받는다.
    """
    watches = Watch.query.filter_by(subscriber_id=subscriber.id, active=True).all()
    for watch in watches:
        watch.active = False
    db.session.commit()
    return len(watches)


def purge_past_watches(today: str) -> int:
    """지난 날짜의 감시를 완전히 지운다. 지운 개수를 돌려준다.

    지난 날짜는 알림이 나갈 일도 없으므로 수집 대상에서 빼야 하고(상한이
    20개뿐이라 지나간 감시가 슬롯을 계속 먹으면 새 감시를 걸 수 없다),
    화면(/watches)에도 더 이상 보일 이유가 없다(사용자 결정 - "날짜 지나면
    화면에서도 자동 해제되고, 불필요한 감시는 아예 없어지는 게 맞다").
    스케줄러가 매 실행 앞에서 호출한다.

    remove_watch/deactivate_all_watches 는 하드 삭제를 피한다 - 사용자가
    현재/미래 감시를 껐다 켰다 할 수 있어서, 지우면 Notification dedup
    근거가 사라져 같은 알림이 중복 발송될 수 있기 때문이다. 하지만 지난
    날짜는 다시 감시할 수 없는 날짜라 그 dedup 근거가 다시 쓰일 일이 없다 -
    그래서 이 경우만 안전하게 완전히 지운다(Notification 은 Watch에
    ondelete=CASCADE 라 같이 지워진다. WatchCheckLog 는 Watch 가 아니라
    Boat 를 참조하므로 영향 없음 - 기존 2일 보관 정리가 따로 처리한다).
    """
    stale = Watch.query.filter(Watch.target_date < today).all()
    count = len(stale)
    for watch in stale:
        db.session.delete(watch)
    if stale:
        db.session.commit()
    return count


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


def admin_list_devices() -> list[dict]:
    """관리자 콘솔 "알림 등록" 탭용 - 활성 감시가 있는 구독자(기기)별로 묶어
    돌려준다.

    한 Subscriber = 브라우저 푸시 구독 하나 = 실제 기기 한 대이므로, 이걸
    그룹 키로 쓴다(IP로 묶으면 같은 공유기 아래 다른 사람이 섞일 수 있다).
    구독 시점에 저장해둔 ip/device_type/user_agent(모두 nullable - 과거
    구독자는 없을 수 있다)와, serialize_watches() 로 채운 감시 목록(배 이름·
    상태·남은자리·예약 URL 포함)을 함께 담는다.
    """
    watches = Watch.query.filter_by(active=True).all()
    if not watches:
        return []

    by_subscriber: dict[int, list[Watch]] = {}
    for w in watches:
        by_subscriber.setdefault(w.subscriber_id, []).append(w)

    subscribers = {
        s.id: s for s in
        Subscriber.query.filter(Subscriber.id.in_(by_subscriber.keys())).all()
    }

    devices = []
    for sub_id, sub_watches in by_subscriber.items():
        sub = subscribers.get(sub_id)
        if sub is None:
            continue
        devices.append({
            'subscriber_id': sub_id,
            'ip': sub.ip,
            'device_type': sub.device_type,
            'user_agent': sub.user_agent,
            'last_seen_at': sub.last_seen_at.isoformat() if sub.last_seen_at else None,
            'watches': serialize_watches(sub_watches),
        })
    devices.sort(key=lambda d: d['last_seen_at'] or '', reverse=True)
    return devices


def admin_release_watches(watch_ids: list[int]) -> int:
    """관리자가 소유 구독자와 무관하게 지정한 감시들을 일괄 해제한다.

    관리자 콘솔의 개별 해제/날짜 전체 해제/기기 전체 해제/선택 해제 4가지
    액션이 전부 이 함수 하나로 수렴한다 - 프론트가 대상 id 집합만 다르게
    계산해서 보낸다. remove_watch 와 같은 이유로 하드 삭제는 안 한다.
    """
    if not watch_ids:
        return 0
    rows = Watch.query.filter(Watch.id.in_(watch_ids), Watch.active.is_(True)).all()
    for w in rows:
        w.active = False
    if rows:
        db.session.commit()
    return len(rows)
