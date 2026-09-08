"""
Web Push 발송. Phase C.

시크릿은 코드에 두지 않는다. VAPID 키는 환경변수로만 받는다.
  VAPID_PUBLIC_KEY    브라우저가 구독할 때 쓰는 공개키 (URL-safe base64)
  VAPID_PRIVATE_KEY   서버가 서명할 때 쓰는 개인키
  VAPID_SUBJECT       연락처 (mailto:... 또는 https://...)

키가 없으면 예외를 던지지 않고 '설정 안 됨'으로 조용히 비활성화된다.
개발/테스트 환경에서 키 없이도 앱이 뜨고 나머지 기능이 돌아야 하기 때문이다.

키 생성:  python src/scripts/gen_vapid_keys.py
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# 발송 결과
SENT = 'sent'
FAILED = 'failed'
EXPIRED = 'expired'      # 구독이 죽었다. 해당 Subscriber 를 지워야 한다.
DISABLED = 'disabled'    # VAPID 미설정


def vapid_public_key() -> str | None:
    """프론트에 내려줄 공개키. 없으면 None."""
    return os.environ.get('VAPID_PUBLIC_KEY') or None


def is_configured() -> bool:
    return bool(os.environ.get('VAPID_PUBLIC_KEY')
                and os.environ.get('VAPID_PRIVATE_KEY'))


_WEEKDAY_KOR = '월화수목금토일'


def _format_date_kor(date_str: str) -> str:
    """'YYYY-MM-DD' -> '9월 12일(토)'. 파싱 실패하면 원본을 그대로 돌려준다."""
    try:
        import datetime
        year, month, day = (int(part) for part in date_str.split('-'))
        weekday = _WEEKDAY_KOR[datetime.date(year, month, day).weekday()]
        return f'{month}월 {day}일({weekday})'
    except Exception:
        return date_str


_MUTE_ACTION = {'action': 'mute', 'title': '알림 끄기'}


def build_payload(transition, boat_name: str) -> dict:
    """전환 하나를 사람이 읽을 알림으로 바꾼다.

    "푸시 알림 디자인" 스펙(Claude Design) 반영. 예전엔 제목이 앱 이름
    ("AFT 배 자리 확인")이라 알림만 봐서는 어느 배에 무슨 일이 생겼는지 알
    수 없었다 - 이제 제목 한 줄에 배 이름 + 무슨 일이 생겼는지를 담는다
    (iOS 는 액션 버튼이 안 뜨므로 특히 중요하다). 실제 예약은 원본 사이트
    에서 하도록 링크와 "예약 페이지 열기"/"알림 끄기" 액션 버튼을 함께
    담는다(PLAN.md 6). 잔여석 표기는 화면(status.html seatText)과 통일해
    "명"이 아니라 "석"을 쓴다.

    actions 는 showNotification 이 실제 버튼으로 그려준다(new Notification()
    으로는 안 뜬다) - 서비스워커가 이 배열을 그대로 넘겨받는다.
    """
    ship = transition.ship_name
    date_label = _format_date_kor(transition.target_date)
    seats = transition.current_available
    fleet = boat_name if boat_name and boat_name != ship else None

    if transition.kind == 'SEAT_OPEN':
        if seats and seats <= 2:
            title = f'{ship} · 마지막 {seats}석'
        elif seats:
            title = f'{ship} · 자리 {seats}석 열림'
        else:
            title = f'{ship} · 자리 열림'
        body = ' · '.join(filter(None, [date_label, fleet]))
        if seats:
            body += f'\n예약완료 → 남은자리 {seats}석'
        actions = [{'action': 'open', 'title': '예약 페이지 열기'}, _MUTE_ACTION]
    elif transition.kind == 'SEAT_GONE':
        title = f'{ship} · 마감됐습니다'
        body = ' · '.join(filter(None, [date_label, fleet]))
        actions = [_MUTE_ACTION]
    else:
        title = f'{ship} · 상태 변경'
        body = f'{date_label} · {transition.display_status or transition.current_status}'
        actions = [_MUTE_ACTION]

    return {
        'title': title,
        'body': body,
        'url': transition.source_url or '/status',
        'tag': f'{transition.boat_id}-{transition.target_date}-{transition.ship_name}',
        'boatId': transition.boat_id,
        'shipName': transition.ship_name,
        'targetDate': transition.target_date,
        'actions': actions,
    }


def send(subscription_info: dict, payload: dict, timeout: int = 10) -> tuple[str, str]:
    """푸시 하나를 보낸다. (결과, 상세) 를 돌려준다.

    예외를 밖으로 던지지 않는다. 한 사람에게 못 보낸 것이 전체 발송 루프를
    멈추면 안 된다(실패 격리).
    """
    if not is_configured():
        return DISABLED, 'VAPID 키가 설정되지 않았습니다.'

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return DISABLED, 'pywebpush 가 설치되지 않았습니다.'

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=os.environ['VAPID_PRIVATE_KEY'],
            vapid_claims={'sub': os.environ.get('VAPID_SUBJECT', 'mailto:admin@example.com')},
            timeout=timeout,
        )
        return SENT, ''
    except WebPushException as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        # 404/410 은 구독이 만료됐다는 뜻이다. 재시도해도 소용없고 지워야 한다.
        if status in (404, 410):
            return EXPIRED, f'구독 만료 (HTTP {status})'
        logger.warning('webpush 실패: %s', exc)
        return FAILED, str(exc)[:500]
    except Exception as exc:  # 네트워크 등 예상 밖 실패도 격리한다
        logger.warning('webpush 예외: %s', exc)
        return FAILED, f'{type(exc).__name__}: {exc}'[:500]
