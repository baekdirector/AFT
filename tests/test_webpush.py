"""
webpush.send() 발송 파라미터 테스트.

실측 버그: 자리남 알림이 감지 직후가 아니라 정확히 다음 30분 주기에야
도착했다 - Urgency 헤더 없이 보내면 안드로이드 Doze(절전) 모드에 들어간
기기는 다음 유지보수 창이 열릴 때까지 배달을 미룬다. 이 테스트는 그
회귀를 막는다: pywebpush.webpush()가 항상 Urgency: high와 넉넉한 ttl로
불리는지 확인한다(실제 네트워크는 타지 않는다 - pywebpush.webpush 자체를
목으로 대체).
"""
import pytest

from services.notify import webpush


@pytest.fixture
def vapid_configured(monkeypatch):
    monkeypatch.setenv('VAPID_PUBLIC_KEY', 'pub')
    monkeypatch.setenv('VAPID_PRIVATE_KEY', 'priv')
    monkeypatch.setenv('VAPID_SUBJECT', 'mailto:test@example.com')


def test_send_requests_high_urgency_and_a_generous_ttl(vapid_configured, monkeypatch):
    calls = []

    def fake_webpush(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr('pywebpush.webpush', fake_webpush)

    result, detail = webpush.send({'endpoint': 'https://push.example/x',
                                   'keys': {'p256dh': 'k', 'auth': 'a'}},
                                  {'title': '테스트'})

    assert result == webpush.SENT
    assert len(calls) == 1
    assert calls[0]['headers'] == {'Urgency': 'high'}, (
        'Urgency: high가 없으면 안드로이드 Doze 모드에서 배달이 다음 주기까지 밀릴 수 있다'
    )
    assert calls[0]['ttl'] > 0, 'ttl 기본값(0)은 즉시 배달 안 되면 버려질 수 있다'
