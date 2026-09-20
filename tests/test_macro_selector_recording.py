# -*- coding: utf-8 -*-
"""macro_runner/record.py 녹화기가 메인 창 클릭에서 만들어내는 선택자 품질 -
실제 레드헌터 예약 페이지(fixtures/redhunter_schedule.html, 스크립트 제거본)에
녹화기 JS를 그대로 주입하고 진짜 클릭을 발생시켜, 나온 선택자가 (1) 페이지에서
딱 한 요소만 가리키고 (2) 그 요소가 실제로 클릭한 요소이며 (3) 날짜 같은
안정적 앵커에 매여 있는지를 본다.

브라우저(playwright + chromium)가 있는 환경에서만 돈다 - macro_runner는 로컬
실행 전용이라 없으면 건너뛴다."""
import sys
from pathlib import Path

import pytest

MACRO_DIR = Path(__file__).parent.parent / 'macro_runner'
sys.path.insert(0, str(MACRO_DIR))

sync_api = pytest.importorskip('playwright.sync_api')
try:
    import record  # noqa: E402  (playwright·winutil에 의존)
except Exception as exc:  # pragma: no cover - 로컬 실행 전용 모듈
    pytest.skip('record.py를 불러올 수 없음: {}'.format(exc), allow_module_level=True)

FIXTURE = (MACRO_DIR / 'fixtures' / 'redhunter_schedule.html').read_text(encoding='utf-8')
URL = 'http://fixture.test/ship/schedule_fleet'


@pytest.fixture(scope='module')
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:
            pytest.skip('chromium을 띄울 수 없음: {}'.format(exc))
        yield b
        b.close()


@pytest.fixture()
def rec(browser):
    """(page, events) - 녹화기 JS가 심어진 페이지와, 그 JS가 보고한 이벤트 목록."""
    context = browser.new_context(viewport={'width': 1280, 'height': 800})
    events = []
    context.expose_binding('__aftRecordEvent', lambda source, payload: events.append(payload))
    context.add_init_script(record._RECORDER_INIT_SCRIPT)
    page = context.new_page()
    page.route('**/*', lambda route: route.fulfill(body=FIXTURE, content_type='text/html; charset=utf-8'))
    page.goto(URL)
    yield page, events
    context.close()


def click_and_get(page, events, css):
    events.clear()
    page.locator(css).first.click()
    page.wait_for_timeout(80)
    clicks = [e for e in events if e['type'] == 'click']
    assert clicks, '클릭 이벤트가 기록되지 않음'
    return clicks[-1]


def resolves_to(page, selector, css):
    """selector가 정확히 1개를 가리키고, 그게 css의 첫 요소와 같은 요소인지."""
    return page.evaluate(
        '([sel, css]) => { const all = document.querySelectorAll(sel);'
        ' return all.length === 1 && all[0] === document.querySelector(css); }',
        [selector, css])


def test_date_link_selector_is_unique_and_keeps_the_date(rec):
    page, events = rec
    payload = click_and_get(page, events, 'a.d2026-09-23')
    assert 'd2026-09-23' in payload['selector']
    assert payload['selectorUnique'] is True
    assert resolves_to(page, payload['selector'], 'a.d2026-09-23')


def test_every_september_date_link_gets_a_unique_selector(rec):
    page, events = rec
    classes = page.evaluate(
        "() => [...document.querySelectorAll('a')].map(a => a.className.split(/\\s+/)[0])"
        ".filter(c => /^d2026-09-\\d\\d$/.test(c))")
    assert len(classes) >= 28
    for cls in classes:
        payload = click_and_get(page, events, 'a.' + cls)
        assert payload['selectorUnique'] is True, cls
        assert resolves_to(page, payload['selector'], 'a.' + cls), (cls, payload['selector'])


def test_state_classes_do_not_leak_into_selector(rec):
    # 오늘 날짜 링크는 schedule_month_today/select 같은 상태 클래스가 붙는다 -
    # 내일이면 사라질 클래스가 선택자에 들어가면 재생 때 못 찾는다.
    page, events = rec
    payload = click_and_get(page, events, 'a.d2026-09-20')
    assert 'today' not in payload['selector'] and 'select' not in payload['selector']
    assert resolves_to(page, payload['selector'], 'a.d2026-09-20')


def test_memo_click_is_anchored_to_its_date_table(rec):
    # 페이지에 editor_memo_pc가 33개라 클래스만으로는 모호하다 - 그 날짜 표의
    # id(#d2026-09-23)를 앵커로 잡아야 한다(우연히 지금만 유일한 경로는 안 됨).
    page, events = rec
    css = '#d2026-09-23 div.editor_memo_pc'
    payload = click_and_get(page, events, css)
    assert payload['selector'].startswith('#d2026-09-23')
    assert payload['selectorUnique'] is True
    assert resolves_to(page, payload['selector'], css)


def test_reservation_button_enter_uses_stable_selector(rec):
    page, events = rec
    css = '#d2026-09-23 button.btn_ship_reservation'
    events.clear()
    page.locator(css).first.focus()
    page.keyboard.press('Enter')
    page.wait_for_timeout(80)
    enters = [e for e in events if e['type'] == 'enter']
    assert enters, 'Enter 이벤트가 기록되지 않음'
    assert enters[-1]['selectorUnique'] is True
    assert resolves_to(page, enters[-1]['selector'], css)


def test_pick_main_mode_trusts_only_unique_selectors():
    recorder = record.Recorder()
    assert recorder._pick_main_mode('a.d2026-09-23', True) == 'selector'
    assert recorder._pick_main_mode('div.editor_memo_pc', False) == 'coord'
    assert recorder._pick_main_mode('', True) == 'coord'
    # 예전 이벤트(selectorUnique 없음)는 기존 규칙(id/name만 신뢰)을 그대로 따른다.
    assert recorder._pick_main_mode('#agree', None) == 'selector'
    assert recorder._pick_main_mode('div > a:nth-of-type(2)', None) == 'coord'


# ---- 재생 쪽(engine.py): 선택자 클릭은 즉시 실패 + 스크린샷 ----

def make_runner(page):
    import engine
    return engine.Runner({'steps': []}, page, page.context)


def test_selector_click_hits_the_recorded_element_even_when_scrolled(rec):
    page, _events = rec
    page.evaluate("() => { window.__clicked = []; document.addEventListener('click', e => window.__clicked.push(e.target.className), true); }")
    page.evaluate('window.scrollTo(0, 5000)')  # 녹화 때와 스크롤이 달라도 상관없어야 한다
    runner = make_runner(page)
    runner._click_composite({'mode': 'selector', 'selector': 'a.d2026-09-23.week_3'})
    clicked = page.evaluate('window.__clicked')
    assert len(clicked) == 1 and 'd2026-09-23' in clicked[0]


def test_missing_selector_fails_fast_with_screenshot(rec, tmp_path, monkeypatch):
    page, _events = rec
    page.set_default_timeout(500)
    monkeypatch.chdir(tmp_path)
    runner = make_runner(page)
    with pytest.raises(Exception):
        runner._click_composite({'mode': 'selector', 'selector': '#d2099-01-01 button.nope'})
    assert list(tmp_path.glob('macro_fail_*.png')), '실패 스크린샷이 남지 않음'
