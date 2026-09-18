# -*- coding: utf-8 -*-
"""매크로 단계 값에 들어있는 {이름}/{전화1-3}/{인원}/{날짜} 같은 변수를
실제 값으로 치환하는 순수 함수. src/templates/macro.html의 JS
resolveValue()와 규칙이 동일해야 한다 - 화면에서 미리보기로 보여주는
값과 실제 실행 엔진이 입력하는 값이 달라지면 안 되기 때문이다."""


def resolve_value(raw, config):
    """raw 문자열 안의 변수 토큰을 config(내보내기 JSON을 그대로 dict로
    읽은 것)의 값으로 치환한다. raw가 비어있으면 그대로 반환한다."""
    if not raw:
        return raw

    phone1 = config.get('guestPhone1', '') or ''
    phone2 = config.get('guestPhone2', '') or ''
    phone3 = config.get('guestPhone3', '') or ''
    phone = phone1 + phone2 + phone3

    return (str(raw)
            .replace('{이름}', config.get('guestName', '') or '')
            .replace('{전화1}', phone1)
            .replace('{전화2}', phone2)
            .replace('{전화3}', phone3)
            .replace('{전화}', phone)
            .replace('{인원}', str(config.get('party', '') or ''))
            .replace('{날짜}', config.get('date', '') or ''))
