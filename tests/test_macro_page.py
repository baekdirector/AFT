# -*- coding: utf-8 -*-
"""/macro (예약 매크로 설정 화면) - /admin과 같은 로그인 세션을 재사용하는
비로그인 게이트만 검증한다. 실제 선사 사이트에 대한 최종 클릭 자동화는
로컬 실행 엔진(macro_runner/, 별도 pytest 대상)이 담당하므로, 이 화면
자체는 정상 렌더되는지 · 미인증 접근이 /admin으로 리다이렉트되는지 ·
로컬 엔진에 넘길 설정을 내려받는 "내보내기" 버튼이 있는지 · 같은
도메인 목업(웹 리허설용, macro_runner/fixtures와 소스 공유)이 admin
세션에서만 서빙되는지를 본다."""


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
    assert 'mc-webrun-overlay' in html
    assert 'mc-webrun-iframe' in html


def test_macro_mock_page_requires_admin_session(client):
    rv = client.get('/macro/mock/mock_list.html')
    assert rv.status_code == 404


def test_macro_mock_page_rejects_unknown_filenames(client):
    with client.session_transaction() as sess:
        sess['admin_authed'] = True

    rv = client.get('/macro/mock/not_a_real_mock.html')
    assert rv.status_code == 404


def test_macro_mock_page_serves_fixture_when_admin_authed(client):
    with client.session_transaction() as sess:
        sess['admin_authed'] = True

    rv = client.get('/macro/mock/mock_list.html')
    assert rv.status_code == 200
    assert b'reserve-btn' in rv.data

    rv2 = client.get('/macro/mock/mock_popup.html')
    assert rv2.status_code == 200
    assert b'party-plus' in rv2.data
