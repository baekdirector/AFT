"""
알림 발송 테스트 (Phase C).

네트워크를 타지 않는다. webpush.send 를 목으로 대체한다.
중복 방지가 핵심이다. 여기가 느슨하면 자리 하나 났을 때 알림이 계속 온다.
"""
import pytest

from db import add_boat_instance, db
from models import Notification, Subscriber, Watch
from services.notify import dispatcher, webpush
from services.snapshot import Observation, compare
from services.watch_service import add_watch, upsert_subscriber

DATE = '2026-09-05'
SHIP = '레드헌터(22인승)'


@pytest.fixture
def target(app):
    with app.app_context():
        boat = add_boat_instance(name='레드헌터', url='https://redhunter.example/x',
                                 city='인천', port='남항(인천항)', note='', is_shared=False)
        sub = upsert_subscriber('https://push.example/aaa', 'k', 'a', '나')
        add_watch(sub, boat.id, SHIP, DATE)
        yield boat.id, sub.id


def seat_open_transition(boat_id):
    """만석 -> 자리남 전환 하나를 만든다."""
    before = Observation(boat_id=boat_id, target_date=DATE, ship_name=SHIP,
                         status='full', available=0)
    after = Observation(boat_id=boat_id, target_date=DATE, ship_name=SHIP,
                        status='open', available=3, display_status='남은자리 3명',
                        source_url='https://redhunter.example/x')
    return compare(before, after)


@pytest.fixture
def sent_ok(monkeypatch):
    """발송이 항상 성공하는 것으로 만든다. 보낸 내용을 기록한다."""
    calls = []

    def fake_send(subscription_info, payload, timeout=10):
        calls.append((subscription_info, payload))
        return webpush.SENT, ''

    monkeypatch.setattr(webpush, 'send', fake_send)
    return calls


# --- 기본 발송 -------------------------------------------------------------

def test_transition_reaches_the_watcher(app, target, sent_ok):
    boat_id, _ = target
    with app.app_context():
        records = dispatcher.dispatch(seat_open_transition(boat_id))

        assert len(records) == 1 and records[0].result == webpush.SENT
        assert len(sent_ok) == 1
        _, payload = sent_ok[0]
        assert '자리 3석 열림' in payload['title']
        assert '남은자리 3석' in payload['body']
        assert payload['url'] == 'https://redhunter.example/x', '원본 링크를 담아야 한다'


def test_transition_without_watcher_sends_nothing(app, target, sent_ok):
    """아무도 안 보는 배는 알리지 않는다."""
    with app.app_context():
        other = add_boat_instance(name='딴배', url='https://x.example/y',
                                  city='인천', port='남항(인천항)', note='', is_shared=False)
        assert dispatcher.dispatch(seat_open_transition(other.id)) == []
        assert sent_ok == []


def test_all_watchers_of_the_same_target_get_it(app, target, sent_ok):
    boat_id, _ = target
    with app.app_context():
        friend = upsert_subscriber('https://push.example/bbb', 'k2', 'a2', '친구')
        add_watch(friend, boat_id, SHIP, DATE)

        records = dispatcher.dispatch(seat_open_transition(boat_id))

        assert len(records) == 2 and len(sent_ok) == 2


# --- 중복 방지 -------------------------------------------------------------

def test_same_transition_is_not_sent_twice(app, target, sent_ok):
    """수집이 30분마다 돌아도 자리 하나에 알림은 한 번이다."""
    boat_id, _ = target
    with app.app_context():
        dispatcher.dispatch(seat_open_transition(boat_id))
        again = dispatcher.dispatch(seat_open_transition(boat_id))

        assert again == []
        assert len(sent_ok) == 1, '두 번째는 발송조차 시도하지 않는다'
        assert Notification.query.count() == 1


def test_reopening_after_close_notifies_again(app, target, sent_ok):
    """열림 -> 닫힘 -> 다시 열림 은 다시 알린다 (PLAN.md 6)."""
    boat_id, _ = target
    with app.app_context():
        dispatcher.dispatch(seat_open_transition(boat_id))

        closed = compare(
            Observation(boat_id=boat_id, target_date=DATE, ship_name=SHIP,
                        status='open', available=3),
            Observation(boat_id=boat_id, target_date=DATE, ship_name=SHIP,
                        status='full', available=0))
        dispatcher.dispatch(closed)
        dispatcher.dispatch(seat_open_transition(boat_id))

        assert len(sent_ok) == 3


def test_failed_send_is_retried_next_time(app, target, monkeypatch):
    """실패한 발송은 '보냈다'로 치지 않는다. 다음 수집 때 다시 시도돼야 한다."""
    boat_id, _ = target
    attempts = []

    def flaky(subscription_info, payload, timeout=10):
        attempts.append(payload)
        if len(attempts) == 1:
            return webpush.FAILED, '일시적 오류'
        return webpush.SENT, ''

    monkeypatch.setattr(webpush, 'send', flaky)

    with app.app_context():
        dispatcher.dispatch(seat_open_transition(boat_id))
        dispatcher.dispatch(seat_open_transition(boat_id))

        assert len(attempts) == 2
        assert Notification.query.filter_by(result=webpush.SENT).count() == 1


# --- 죽은 구독 정리 --------------------------------------------------------

def test_expired_subscription_is_removed(app, target, monkeypatch):
    """만료된 구독을 남겨두면 매번 실패하며 발송 시간을 잡아먹는다."""
    boat_id, _ = target
    monkeypatch.setattr(webpush, 'send',
                        lambda *a, **kw: (webpush.EXPIRED, '구독 만료 (HTTP 410)'))

    with app.app_context():
        dispatcher.dispatch(seat_open_transition(boat_id))

        assert Subscriber.query.count() == 0
        assert Watch.query.count() == 0, '구독자와 함께 감시도 정리된다'


def test_one_failure_does_not_stop_the_others(app, target, monkeypatch):
    """실패 격리: 한 사람에게 못 보내도 나머지는 받아야 한다."""
    boat_id, _ = target
    with app.app_context():
        friend = upsert_subscriber('https://push.example/bbb', 'k2', 'a2', '친구')
        add_watch(friend, boat_id, SHIP, DATE)

        seen = []

        def half_broken(subscription_info, payload, timeout=10):
            seen.append(subscription_info['endpoint'])
            if subscription_info['endpoint'].endswith('aaa'):
                return webpush.FAILED, '터짐'
            return webpush.SENT, ''

        monkeypatch.setattr(webpush, 'send', half_broken)
        records = dispatcher.dispatch(seat_open_transition(boat_id))

        assert len(seen) == 2
        assert sorted(r.result for r in records) == [webpush.FAILED, webpush.SENT]


# --- VAPID 미설정 ----------------------------------------------------------

def test_missing_vapid_keys_disable_sending_without_crashing(app, target, monkeypatch):
    """키가 없어도 앱이 죽지 않는다. 개발 환경에서 나머지 기능이 돌아야 한다."""
    monkeypatch.delenv('VAPID_PUBLIC_KEY', raising=False)
    monkeypatch.delenv('VAPID_PRIVATE_KEY', raising=False)

    assert webpush.is_configured() is False
    assert webpush.vapid_public_key() is None
    result, detail = webpush.send({'endpoint': 'x', 'keys': {}}, {'title': 't'})
    assert result == webpush.DISABLED and 'VAPID' in detail


# --- 집계 ------------------------------------------------------------------

def test_dispatch_all_summarises(app, target, sent_ok):
    boat_id, _ = target
    with app.app_context():
        transition = seat_open_transition(boat_id)
        first = dispatcher.dispatch_all([transition])
        second = dispatcher.dispatch_all([transition])

        assert first['transitions'] == 1 and first['sent'] == 1
        assert second['sent'] == 0 and second['skipped_duplicate'] == 1


def test_payload_falls_back_to_status_text_when_no_seat_count(app, target):
    with app.app_context():
        t = compare(
            Observation(boat_id=target[0], target_date=DATE, ship_name=SHIP, status='full'),
            Observation(boat_id=target[0], target_date=DATE, ship_name=SHIP,
                        status='maintenance', display_status='점검일'))
        payload = webpush.build_payload(t, '레드헌터')
        assert '점검일' in payload['body']


# --- 발송 실패 격리(dispatch_all) --------------------------------------------

def test_dispatch_all_isolates_a_failing_transition(app, target, monkeypatch):
    """전환 하나가 dispatch() 안에서 예외를 던져도 나머지 전환은 계속 나가야
    한다. 실측: 이 격리가 없던 시절 배치 중간의 예외 하나가 그 뒤 전환
    전부(백호호 포함)를 무음으로 삼켰다."""
    boat_id, _ = target
    with app.app_context():
        other = add_boat_instance(name='딴배', url='https://x.example/y',
                                  city='인천', port='남항(인천항)', note='', is_shared=False)
        sub2 = upsert_subscriber('https://push.example/ccc', 'k3', 'a3', '친구2')
        add_watch(sub2, other.id, '딴배호', DATE)

        broken = seat_open_transition(boat_id)          # 이게 먼저 터진다
        healthy = compare(
            Observation(boat_id=other.id, target_date=DATE, ship_name='딴배호',
                        status='full', available=0),
            Observation(boat_id=other.id, target_date=DATE, ship_name='딴배호',
                        status='open', available=2, display_status='남은자리 2명'))

        calls = []

        def fake_send(subscription_info, payload, timeout=10):
            calls.append(subscription_info['endpoint'])
            return webpush.SENT, ''

        monkeypatch.setattr(webpush, 'send', fake_send)

        import services.watch_service as watch_service_module
        original_watches_for = watch_service_module.watches_for

        def blow_up_for_broken(boat_id_arg, target_date_arg, ship_name_arg):
            if boat_id_arg == boat_id:
                raise RuntimeError('디비 순간 장애')
            return original_watches_for(boat_id_arg, target_date_arg, ship_name_arg)

        monkeypatch.setattr('services.notify.dispatcher.watches_for', blow_up_for_broken)

        summary = dispatcher.dispatch_all([broken, healthy])

        assert summary['transitions'] == 2
        assert summary['sent'] == 1, '터진 전환 하나 빼고는 정상 발송돼야 한다'
        assert calls == ['https://push.example/ccc']


def test_dispatch_all_rolls_back_session_after_a_db_failure(app, target, sent_ok, monkeypatch):
    """실측 버그(2026-09-15 레드히어로): 위 격리 테스트는 순수 파이썬
    예외(RuntimeError)로만 실패를 흉내 냈는데, 그 경우엔 SQLAlchemy 세션
    자체는 멀쩡해서 다음 전환이 문제없이 발송됐다. 그런데 실패 격리를
    처음 넣었을 때 db.session.rollback() 을 빠뜨렸었다 - DB 쪽 예외
    (제약 조건 위반 등 db.session.flush/commit 이 실제로 실패하는 경우)가
    한 번 나면 SQLAlchemy 세션이 rollback 전까지 그 뒤 모든 쿼리를 거부하는
    상태가 되고, 이 상태에서 rollback 없이 다음 전환으로 넘어가면 그
    전환의 기록까지 연쇄로 조용히 실패한다. 이 테스트는 진짜 DB 제약
    위반(NOT NULL)으로 세션을 오염시켜 이 정확한 실패 모드를 재현한다.

    발송 병렬화(dispatch_all의 Phase A/B/C 분리) 이후로는 이 테스트가
    검증하는 대상이 살짝 좁아졌다 - 이제 모든 전환의 실제 발송(Phase B)이
    기록(Phase C)보다 먼저, 배치 전체가 한꺼번에 끝나므로, 한 전환의
    "기록" 실패가 다른 전환의 "발송" 자체를 막는 것은 이제 구조적으로
    불가능하다(그래서 sent_ok 호출 수는 2건 - 두 전환 다 실제로 보내려고
    시도한다). 그래도 여전히 중요한 건: 기록 단계에서 세션이 오염돼도
    그 뒤 전환의 기록(=Notification 행 생성, 중복 방지/반복 알림의
    근거)까지 조용히 실패하면 안 된다는 것 - 그건 이 테스트가 그대로
    지킨다."""
    boat_id, _ = target
    with app.app_context():
        other = add_boat_instance(name='딴배', url='https://x.example/y',
                                  city='인천', port='남항(인천항)', note='', is_shared=False)
        sub2 = upsert_subscriber('https://push.example/ccc', 'k3', 'a3', '친구2')
        add_watch(sub2, other.id, '딴배호', DATE)

        broken = seat_open_transition(boat_id)          # 이게 기록 단계에서 진짜 DB 오류로 터진다
        healthy = compare(
            Observation(boat_id=other.id, target_date=DATE, ship_name='딴배호',
                        status='full', available=0),
            Observation(boat_id=other.id, target_date=DATE, ship_name='딴배호',
                        status='open', available=2, display_status='남은자리 2명'))

        original_record_results = dispatcher._record_results

        def record_results_with_a_real_db_failure_for_broken(results):
            if results and results[0][0]['dedup_key'].split('|')[0] == str(boat_id):
                # watch_id 는 nullable=False - 실제 제약 조건 위반으로
                # flush 를 실패시켜 세션을 진짜로 오염시킨다.
                db.session.add(Notification(watch_id=None, dedup_key='x', channel='webpush', result='sent'))
                db.session.flush()
                return []
            return original_record_results(results)

        monkeypatch.setattr(dispatcher, '_record_results', record_results_with_a_real_db_failure_for_broken)

        summary = dispatcher.dispatch_all([broken, healthy])

        assert summary['sent'] == 1, (
            'rollback 없이 세션이 오염되면 이 두 번째(정상) 전환의 기록까지 '
            '조용히 실패한다 - rollback 이 빠지면 이 assert 가 실패해야 한다'
        )
        assert len(sent_ok) == 2, 'Phase B는 기록 성공 여부와 무관하게 두 전환 모두 실제 발송을 시도한다'


def test_dispatch_all_sends_concurrently_not_one_at_a_time(app, monkeypatch):
    """실측 진단(라이브 조회 "마무리" 구간 지연)의 실제 개선 효과를 증명한다
    - 그냥 "안 깨졌다"가 아니라 "진짜 동시에 나간다"를 확인한다.

    전환 4건(DISPATCH_MAX_WORKERS와 같은 수)을 각자 다른 배·구독자로
    준비하고, webpush.send가 0.2초씩 걸리게 만든다. 순차였다면 4건
    합쳐 0.8초 이상 걸려야 하는데, 병렬이면 한 번에 겹쳐 나가 0.2초대에
    끝나야 한다 - 넉넉히 잡아도 배치 전체 절반(0.4초) 밑으로 끝나야
    "확실히 겹쳐서 나갔다"고 볼 수 있다."""
    import time

    def seat_open_transition_for(boat_id, ship_name):
        before = Observation(boat_id=boat_id, target_date=DATE, ship_name=ship_name,
                             status='full', available=0)
        after = Observation(boat_id=boat_id, target_date=DATE, ship_name=ship_name,
                            status='open', available=3, display_status='남은자리 3명',
                            source_url='https://example/x')
        return compare(before, after)

    with app.app_context():
        transitions = []
        for i in range(4):
            boat = add_boat_instance(name=f'배{i}호', url=f'https://b{i}.example/x',
                                     city='인천', port='남항(인천항)', note='', is_shared=False)
            sub = upsert_subscriber(f'https://push.example/p{i}', f'k{i}', f'a{i}', f'친구{i}')
            add_watch(sub, boat.id, f'선박{i}', DATE)
            transitions.append(seat_open_transition_for(boat.id, f'선박{i}'))

        def slow_send(subscription_info, payload, timeout=10):
            time.sleep(0.2)
            return webpush.SENT, ''

        monkeypatch.setattr(webpush, 'send', slow_send)

        started = time.perf_counter()
        summary = dispatcher.dispatch_all(transitions)
        elapsed = time.perf_counter() - started

        assert summary['sent'] == 4
        assert elapsed < 0.4, (
            f'{elapsed:.2f}초 걸림 - 순차 발송(0.2초 x 4건 = 0.8초 이상)이었다면 '
            '이 상한을 넘겨야 정상이다. 병렬로 겹쳐 나가지 않고 있다는 뜻'
        )


# --- 반복 알림(dispatch_reminders) -------------------------------------------

def open_observation(boat_id, available=3):
    return Observation(boat_id=boat_id, target_date=DATE, ship_name=SHIP,
                       status='open', available=available,
                       display_status=f'남은자리 {available}명',
                       source_url='https://redhunter.example/x')


def test_reminder_fires_after_the_initial_seat_open_notification(app, target, sent_ok):
    """최초 자리남 알림 뒤, 그 자리가 여전히 열려 있으면 반복 알림이 나간다."""
    boat_id, _ = target
    with app.app_context():
        dispatcher.dispatch(seat_open_transition(boat_id))   # 최초 알림
        sent_ok.clear()

        result = dispatcher.dispatch_reminders([open_observation(boat_id)])

        assert result['sent'] == 1
        assert len(sent_ok) == 1
        _, payload = sent_ok[0]
        assert '아직' in payload['title']

        record = Notification.query.order_by(Notification.id.desc()).first()
        assert record.kind == 'REMINDER' and record.reminder_index == 1


def test_reminder_stops_after_two_repeats(app, target, sent_ok):
    """"30분 간격 2번 더"라는 사용자 요청대로 반복은 정확히 2회에서 멈춘다."""
    boat_id, _ = target
    with app.app_context():
        dispatcher.dispatch(seat_open_transition(boat_id))          # 최초
        dispatcher.dispatch_reminders([open_observation(boat_id)])  # 반복 1
        dispatcher.dispatch_reminders([open_observation(boat_id)])  # 반복 2
        sent_ok.clear()

        third = dispatcher.dispatch_reminders([open_observation(boat_id)])

        assert third['sent'] == 0, '2회를 넘는 반복은 나가면 안 된다'
        assert sent_ok == []
        assert (Notification.query.filter_by(kind='REMINDER').count() == 2)


def test_reminder_is_not_sent_without_a_prior_notification(app, target, sent_ok):
    """이 배를 한 번도 알린 적이 없으면(최초 알림도 없었으면) 반복 알림도
    없다 - 반복은 어디까지나 최초 알림의 연장이다."""
    boat_id, _ = target
    with app.app_context():
        result = dispatcher.dispatch_reminders([open_observation(boat_id)])

        assert result['sent'] == 0
        assert sent_ok == []


def test_reminder_is_not_sent_once_the_seat_closed(app, target, sent_ok):
    """마지막으로 보낸 알림이 마감(SEAT_GONE)이면, 그 뒤 다시 열린 자리는
    새 전환(SEAT_OPEN)으로만 알려야지 반복 알림 경로로는 안 나가야 한다."""
    boat_id, _ = target
    with app.app_context():
        dispatcher.dispatch(seat_open_transition(boat_id))
        closed = compare(
            Observation(boat_id=boat_id, target_date=DATE, ship_name=SHIP,
                        status='open', available=3),
            Observation(boat_id=boat_id, target_date=DATE, ship_name=SHIP,
                        status='full', available=0))
        dispatcher.dispatch(closed)
        sent_ok.clear()

        result = dispatcher.dispatch_reminders([open_observation(boat_id)])

        assert result['sent'] == 0
        assert sent_ok == []


def test_reminder_skips_ships_nobody_is_watching(app, sent_ok):
    """감시자가 없는 배는 최초 알림이 있을 수 없으니 반복 알림도 없다."""
    with app.app_context():
        boat = add_boat_instance(name='안봄호', url='https://x.example/z',
                                 city='인천', port='남항(인천항)', note='', is_shared=False)
        result = dispatcher.dispatch_reminders([open_observation(boat.id)])
        assert result['sent'] == 0
        assert sent_ok == []


def test_ensure_notification_reminder_columns_backfills_missing_columns(app, target, sent_ok):
    """db.create_all()은 이미 배포된 notifications 테이블에 새 컬럼(kind,
    reminder_index)을 얹어주지 않는다 - 앱 시작 시 idempotent ALTER TABLE로
    보정한다(_ensure_snapshot_shiptime_columns 등과 같은 패턴)."""
    from sqlalchemy import text

    from src.app import _ensure_notification_reminder_columns

    boat_id, _ = target
    with app.app_context():
        dispatcher.dispatch(seat_open_transition(boat_id))
        db.session.execute(text('ALTER TABLE notifications DROP COLUMN kind'))
        db.session.execute(text('ALTER TABLE notifications DROP COLUMN reminder_index'))
        db.session.commit()

        _ensure_notification_reminder_columns(app)

        record = Notification.query.one()
        assert record.kind is None, '컬럼 보정 후 기존 행은 지워지지 않고 NULL로 남아야 한다'
        assert record.reminder_index == 0, '기본값 0이라 기존 행도 곧바로 최초 알림으로 해석된다'


def test_ensure_notification_reminder_columns_is_noop_when_already_present(app, target, sent_ok):
    """이미 컬럼이 있으면(정상 배포 상태) 기존 데이터를 건드리지 않는다."""
    from src.app import _ensure_notification_reminder_columns

    boat_id, _ = target
    with app.app_context():
        dispatcher.dispatch(seat_open_transition(boat_id))

        _ensure_notification_reminder_columns(app)

        record = Notification.query.one()
        assert record.kind == 'SEAT_OPEN' and record.reminder_index == 0


def test_one_reminder_failure_does_not_stop_the_others(app, target, monkeypatch, sent_ok):
    """반복 알림도 한 사람 실패가 나머지를 막으면 안 된다(실패 격리)."""
    boat_id, _ = target
    with app.app_context():
        friend = upsert_subscriber('https://push.example/bbb', 'k2', 'a2', '친구')
        add_watch(friend, boat_id, SHIP, DATE)

        dispatcher.dispatch(seat_open_transition(boat_id))   # sent_ok 로 성공 처리됨

        seen = []

        def half_broken(subscription_info, payload, timeout=10):
            seen.append(subscription_info['endpoint'])
            if subscription_info['endpoint'].endswith('aaa'):
                raise RuntimeError('네트워크 순간 장애')
            return webpush.SENT, ''

        monkeypatch.setattr(webpush, 'send', half_broken)

        result = dispatcher.dispatch_reminders([open_observation(boat_id)])

        assert len(seen) == 2
        assert result['sent'] == 1
