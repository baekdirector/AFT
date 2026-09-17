# -*- coding: utf-8 -*-
"""/macro (예약 매크로 설정 화면) - /admin과 같은 로그인 세션을 재사용하는
비로그인 게이트만 검증한다. 실제 클릭 자동화 엔진은 아직 없으므로(화면만),
화면이 정상 렌더되는지와 미인증 접근이 /admin으로 리다이렉트되는지만 본다."""


def test_macro_page_requires_admin_session(client):
    rv = client.get('/macro', follow_redirects=True)
    assert '관리자 로그인' in rv.get_data(as_text=True)


def test_macro_page_renders_when_admin_authed(client):
    with client.session_transaction() as sess:
        sess['admin_authed'] = True

    rv = client.get('/macro')
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert '예약 매크로' in html
    assert '레드히어로' in html
