# -*- coding: utf-8 -*-
"""/macro (예약 매크로 설정 화면) - /admin과 같은 로그인 세션을 재사용하는
비로그인 게이트만 검증한다. 실제 클릭 자동화는 로컬 실행 엔진
(macro_runner/, 별도 pytest 대상)이 담당하므로, 이 화면 자체는 정상
렌더되는지 · 미인증 접근이 /admin으로 리다이렉트되는지 · 로컬 엔진에
넘길 설정을 내려받는 "내보내기" 버튼이 있는지만 본다."""


def test_macro_page_requires_admin_session(client):
    rv = client.get('/macro', follow_redirects=True)
    assert '관리자 로그인' in rv.get_data(as_text=True)


def test_macro_page_renders_when_admin_authed(client):
    with client.session_transaction() as sess:
        sess['admin_authed'] = True

    rv = client.get('/macro')
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert '자동예약 매크로' in html
    assert 'sunsang24' in html
    assert 'mc-export-config' in html
    assert 'mc-rec-width' in html
    assert 'mc-rec-iframe' in html
    assert 'Tab 이동' in html
