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


class NameTakenError(Exception):
    """알림 이름(label)이 이미 다른 기기에 등록돼 있다.

    사용자 확인 없이 조용히 가로채면(동명이인이거나 오타로 남의 감시
    목록을 이어받는 사고) 위험하므로, 프론트가 "본인이 맞으면 계속
    진행" 확인창을 보여준 뒤에만 confirm_takeover=True 로 재시도하게
    한다(사용자 결정 - PIN/계정 로그인 대신 이름 하나로 기기를 옮겨
    다니되, 충돌은 확인을 한 번 거친다).
    """

    def __init__(self, label: str):
        self.label = label
        super().__init__(f'"{label}"은(는) 이미 등록된 이름입니다.')


def upsert_subscriber(endpoint: str, p256dh: str, auth: str,
                      label: str | None = None, ip: str | None = None,
                      device_type: str | None = None,
                      user_agent: str | None = None,
                      device_id: str | None = None,
                      confirm_takeover: bool = False) -> Subscriber:
    """푸시 구독을 저장한다. 같은 endpoint 면 갱신하고, endpoint 가 조용히
    바뀌었어도 device_id 가 같으면 같은 기기로 보고 endpoint 만 갈아끼운다.
    이 기기가 처음 보는 endpoint/device_id인데 label(알림 이름)이 이미
    다른 기기에 등록돼 있으면, confirm_takeover 없이는 NameTakenError를
    던진다 - 있으면 그 자리를 이 기기로 옮긴다("한 번에 한 기기만 살아있는"
    방식 - PC/폰을 번갈아 쓰되 이름 하나로 감시를 이어받는다. 동시에 여러
    기기가 알림을 받게 하려면 Subscriber:기기를 1:N으로 바꾸는 별도 작업이
    필요하다 - 지금은 그 규모까지는 필요 없다는 사용자 결정).

    브라우저는 구독을 조용히 갱신(rotate)할 수 있으므로 원래는 endpoint 를
    키로 두고 upsert 했다. 그런데 endpoint 자체가 서버 모르게 바뀌는 경우
    (알림 권한 재설정, 앱 데이터 초기화, 푸시 서비스 쪽 토큰 만료 등 -
    service-worker.js 가 pushsubscriptionchange 를 못 들으면 이 사실을 서버에
    알릴 방법이 아예 없었다)엔 endpoint 만으로 찾으면 완전히 다른 사람처럼
    새 행이 생기고, 기존 감시(Watch, 이 Subscriber.id 에 연결)는 예전 행에
    그대로 남아 orphan 된다 - 실측 버그: 관리자 콘솔엔 감시가 여전히 활성으로
    보이는데 정작 그 기기 화면은 "알림 꺼짐"으로 보였다. device_id 는
    페이지 스크립트가 최초 구독 시 IndexedDB에 발급해두는 값이라 endpoint가
    바뀌어도 그대로다 - 이걸로 "같은 기기"를 찾아 endpoint/키만 갱신하면
    subscriber_id 가 그대로라 감시가 안 끊긴다. device_id 는 기기(브라우저)가
    바뀌면(예: 폰을 새로 사거나 앱 데이터를 지운 경우) 같이 사라져서 못
    알아본다 - label(사람이 직접 정한 알림 이름)은 그 경우에도 사람이 기억해
    다시 입력할 수 있는 마지막 수단이다.
    """
    if not endpoint or not p256dh or not auth:
        raise ValueError('구독 정보가 불완전합니다.')

    sub = Subscriber.query.filter_by(endpoint=endpoint).one_or_none()
    if sub is None and device_id:
        sub = Subscriber.query.filter_by(device_id=device_id).one_or_none()

    if sub is None and label and label.strip():
        name = label.strip()
        named = Subscriber.query.filter(db.func.lower(Subscriber.label) == name.lower()).one_or_none()
        if named is not None:
            if not confirm_takeover:
                raise NameTakenError(name)
            sub = named

    if sub is None:
        sub = Subscriber(endpoint=endpoint, p256dh=p256dh, auth=auth, label=label, device_id=device_id)
        db.session.add(sub)
    else:
        sub.endpoint = endpoint
        sub.p256dh = p256dh
        sub.auth = auth
        if label:
            sub.label = label
        if device_id:
            sub.device_id = device_id
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


def check_log_history(subscriber: Subscriber, days: int = 2,
                      watches: list[Watch] | None = None) -> list[dict]:
    """이 구독자가 지금 걸어둔 감시들의 확인 이력을 최신순으로 돌려준다.

    WatchCheckLog 는 구독자별로 나뉘어 있지 않다(확인 자체는 시스템 공용
    이벤트라 누가 감시하든 같다) - 그래서 이 구독자의 현재 활성 감시 키
    (boat_id, ship_name, target_date) 집합을 먼저 구하고, 그 키에 해당하는
    로그만 걸러낸다. 같은 배를 여러 사람이 감시해도 이력 자체는 동일하게
    보인다 - 정상이다.

    `watches`를 이미 조회해둔 호출부(admin_list_devices)는 그걸 그대로
    넘겨서 같은 활성 감시를 또 쿼리하지 않게 할 수 있다 - 생략하면(기존
    /watches 화면 호출부처럼) 여기서 직접 조회한다.
    """
    if watches is None:
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


def admin_list_devices(include_check_log: bool = True) -> list[dict]:
    """관리자 콘솔 "알림 등록" 탭용 - 활성 감시가 있는 구독자(기기)별로 묶어
    돌려준다.

    `include_check_log=False`면 기기별 확인 이력(`check_log`)을 빼고 돌려준다 -
    탭을 여는 데 꼭 필요하지 않은 WatchCheckLog 쿼리를 기기 수만큼 날리지
    않기 위해서다. 화면은 사용자가 "체크 기록 로그"를 펼칠 때 그 기기 것만
    `admin_device_check_log()`로 따로 불러온다.

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
            'label': sub.label,
            'ip': sub.ip,
            'device_type': sub.device_type,
            'user_agent': sub.user_agent,
            # 구독 시점(=대략 "알림 켜기"를 누른 시점) - ip/device_type이 없는
            # 과거 구독자를 VisitLog로 추정 보완할 때 기준 시각으로 쓴다
            # (views.admin_page 참고).
            'created_at': sub.created_at.isoformat() if sub.created_at else None,
            'last_seen_at': sub.last_seen_at.isoformat() if sub.last_seen_at else None,
            'watches': serialize_watches(sub_watches),
        })
        if include_check_log:
            # 이 기기가 지금 감시 중인 것들의 확인 이력(최근 2일) - 사용자
            # 요청: "어드민에서도 기기별 로그 정보를 확인하고 싶어". 이미
            # /watches 화면이 쓰는 것과 같은 함수를 구독자만 바꿔 그대로
            # 재사용한다(로직 중복 없음). sub_watches를 넘겨 check_log_history가
            # 같은 활성 감시를 또 쿼리하지 않게 한다(위 by_subscriber 그룹핑에서
            # 이미 읽어둔 것과 동일한 데이터).
            devices[-1]['check_log'] = check_log_history(sub, days=2, watches=sub_watches)
    devices.sort(key=lambda d: d['last_seen_at'] or '', reverse=True)
    return devices


def admin_device_check_log(subscriber_id: int) -> list[dict] | None:
    """관리자 콘솔에서 기기 하나의 확인 이력(최근 2일)만 지연 조회한다.

    구독자가 없으면 None(404 판단용), 있으면 - 활성 감시가 없어도 - 목록(빈
    목록일 수 있음)을 돌려준다. 기기 목록 조회(admin_list_devices)가 이걸
    미리 다 채우던 걸 "체크 기록 로그"를 펼칠 때로 미룬 것이다."""
    sub = Subscriber.query.get(subscriber_id)
    if sub is None:
        return None
    return check_log_history(sub, days=2)


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


def admin_set_device_label(subscriber_id: int, label: str | None) -> Subscriber | None:
    """관리자 콘솔에서 기기(구독자)에 별명을 붙이거나(예: "백감독", "김조사")
    지운다. IP만으로는 누가 누군지 알아보기 어렵다는 요청으로 추가했다 -
    Subscriber.label 은 원래 있던 컬럼(예전엔 아무도 안 채웠다)을 그대로
    쓴다. 빈 문자열/공백은 지우는 것으로 취급한다."""
    sub = Subscriber.query.get(subscriber_id)
    if sub is None:
        return None
    label = (label or '').strip()
    sub.label = label or None
    db.session.commit()
    return sub
