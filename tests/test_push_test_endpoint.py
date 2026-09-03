"""
테스트 알림 엔드포인트 (POST /api/push/test).

알림이 실제로 도착하는지 자리가 날 때까지 기다려서 확인할 수는 없다.
켠 직후 한 통 보내보고 VAPID 키·구독 정보·서비스워커가 맞물려 있는지
확인할 수 있어야 한다.
"""
import pytest

from models import Subscriber
from services.notify import webpush
from services.watch_service import upsert_subscriber

EP = 'https://push.example/aaa'


@pytest.fixture
def subscribed(app, monkeypatch):
    monkeypatch.setenv('VAPID_PUBLIC_KEY', 'pub')
    monkeypatch.setenv('VAPID_PRIVATE_KEY', 'priv')
    with app.app_context():
        upsert_subscriber(EP, 'k', 'a', '나')
        yield


def test_sends_a_notification_to_this_browser(client, subscribed, monkeypatch):
    sent = []
    monkeypatch.setattr(webpush, 'send',
                        lambda info, payload, timeout=10: (sent.append((info, payload)),
                                                          (webpush.SENT, ''))[1])

    resp = client.post('/api/push/test', json={'endpoint': EP})

    assert resp.status_code == 200 and resp.get_json()['result'] == webpush.SENT
    info, payload = sent[0]
    assert info['endpoint'] == EP
    assert '테스트' in payload['title']


def test_unknown_endpoint_is_rejected(client, subscribed):
    resp = client.post('/api/push/test', json={'endpoint': 'https://push.example/nope'})
    assert resp.status_code == 404


def test_without_vapid_it_says_so(client, subscribed, monkeypatch):
    monkeypatch.delenv('VAPID_PUBLIC_KEY', raising=False)
    monkeypatch.delenv('VAPID_PRIVATE_KEY', raising=False)

    resp = client.post('/api/push/test', json={'endpoint': EP})

    assert resp.status_code == 503
    assert 'VAPID' in resp.get_json()['error']


def test_expired_subscription_is_cleaned_up(app, client, subscribed, monkeypatch):
    """죽은 구독을 남겨두면 매 발송마다 실패하며 시간을 잡아먹는다."""
    monkeypatch.setattr(webpush, 'send',
                        lambda *a, **kw: (webpush.EXPIRED, '구독 만료 (HTTP 410)'))

    resp = client.post('/api/push/test', json={'endpoint': EP})

    assert resp.status_code == 410
    with app.app_context():
        assert Subscriber.query.count() == 0


def test_send_failure_is_surfaced_not_swallowed(client, subscribed, monkeypatch):
    """실패를 성공으로 보고하면 테스트 기능 자체가 무의미해진다."""
    monkeypatch.setattr(webpush, 'send',
                        lambda *a, **kw: (webpush.FAILED, '푸시 서버 오류'))

    resp = client.post('/api/push/test', json={'endpoint': EP})

    assert resp.status_code == 502
    assert resp.get_json()['error'] == '푸시 서버 오류'


def test_does_not_touch_watches_or_snapshots(app, client, subscribed, monkeypatch):
    """테스트 알림이 감시 상태나 스냅샷을 건드리면 안 된다."""
    from models import Notification, Snapshot, Watch
    monkeypatch.setattr(webpush, 'send', lambda *a, **kw: (webpush.SENT, ''))

    client.post('/api/push/test', json={'endpoint': EP})

    with app.app_context():
        assert Watch.query.count() == 0
        assert Snapshot.query.count() == 0
        assert Notification.query.count() == 0, '테스트는 발송 이력을 남기지 않는다'
