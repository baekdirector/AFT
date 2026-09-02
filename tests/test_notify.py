"""
알림 발송 테스트 (Phase C).

네트워크를 타지 않는다. webpush.send 를 목으로 대체한다.
중복 방지가 핵심이다. 여기가 느슨하면 자리 하나 났을 때 알림이 계속 온다.
"""
import pytest

from db import add_boat_instance
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
        assert '자리 났습니다' in payload['title']
        assert '남은자리 3명' in payload['body']
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
