# -*- coding: utf-8 -*-
"""자동예약 매크로 - 실제 브라우저 조작 기반 녹화·테스트 재생 도구.

지금까지 "레코딩"은 /macro 웹 페이지 안의 iframe에 좌표를 기록하는
방식이었는데, 기록 환경(iframe)과 재생 환경(macro_runner가 여는 실제
브라우저)의 화면 크기·상황이 달라서 좌표가 어긋나는 근본 문제가
있었다. 이 도구는 그 문제를 원천적으로 없앤다 - **녹화도 재생과 똑같이
Playwright로 연 실제 브라우저**를 사용자가 직접 조작하게 하고, 그 실제
조작(클릭·입력·Tab 이동)을 있는 그대로 기록한다.

거기서 한 걸음 더 나아가, **녹화 → 저장 → 그 자리에서 바로 테스트
재생 → (문제가 있으면) 이어서 녹화**를 전부 오른쪽 창 하나에서 오갈 수
있다 - 예전엔 저장한 뒤 좌표가 실제로 맞는지 확인하려면 브라우저를
끄고 별도로 `run.py`를 다시 켜야 했는데, 실사이트에서 좌표가 스크롤/
레이아웃 차이로 어긋나는 걸 실측한 뒤 그 왕복이 너무 느리다는 걸
확인했다.

핵심 규칙(사용자와 합의):
- 하나의 "이벤트"(=매크로 한 단계)는 **마우스 클릭으로 마감**된다.
  클릭 전에 있었던 입력들은 그 클릭이 마감하는 이벤트 안에 묶인다.
- 메인 창(대상 사이트 첫 화면)에서는 좌표/선택자 모두 신뢰할 수 있다.
  반면 **팝업(새 창)은 화면에 뜨는 위치가 매번 다를 수 있어 좌표를
  못 쓴다** - 그래서 팝업 안에서는 항상 Tab 이동 횟수로 기록한다.
- **매크로 이름을 먼저 정해야 녹화가 시작된다** - 이름이 고정이면
  대상 URL(선사·배·날짜)이 바뀔 때마다 이전 녹화 파일을 덮어써
  버리는 문제가 실제로 있었다.

사용법:
    pip install -r requirements.txt
    playwright install chromium
    python record.py --url https://chf.sunsang24.com/ship/schedule_fleet

두 개의 실제 브라우저 창이 뜬다 - 왼쪽은 "녹화 대상" 창(사용자가 직접
조작하는 진짜 브라우저), 오른쪽은 "제어판" 창(이름 입력 → 녹화 시작 →
단계 실시간 표시 → 저장 → 테스트 재생 → 이어서 녹화/처음부터, 전부 이
창의 버튼으로 오간다). 완전히 끝내려면 터미널에서 Enter를 누른다.

구현 메모: 오른쪽 창은 Python(Playwright) 쪽에서 직접
`page.set_content(...)`를 불러 갱신하지 않는다 - 이벤트 콜백
(expose_binding)이 Playwright의 단일 디스패치 스레드에서 호출되는데,
그 안에서 또 다른 Playwright 호출을 하면 같은 스레드가 자기 자신의
응답을 기다리며 멈춰버린다(실제로 겪음). 그래서 콜백 안에서는 순수
파이썬 상태만 바꾸고 파일에 쓰기만 하며, 오른쪽 창은 그 파일을 자기
스스로(브라우저 JS의 fetch) 주기적으로 읽어가게 한다. 같은 이유로
"테스트 재생"(실제 클릭·입력을 실행해야 함)은 HTTP 요청을 받는
스레드가 아니라 **메인 스레드의 대기 루프**가 큐를 확인해 직접
수행한다."""
import argparse
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright

from winutil import position_window, LEFT_BOUNDS, RIGHT_BOUNDS
from engine import Runner
import steps_edit

# 실제(합성 아님) click/change/keydown(Tab)만 감지해서 파이썬으로 보고한다.
# change는 텍스트류 입력에서만 듣는다 - 체크박스/라디오는 change도 같이
# 뜨는데, 그건 "클릭 자체"로 이미 완전히 설명되는 동작이라(체크 여부는
# 클릭이 곧 값이다) 별도 입력으로 기록하면 클릭 이벤트와 순서가
# 꼬이기 쉽다. 드롭다운(select)은 이번 버전에서는 다루지 않는다(실제
# 대상 흐름에 없음 - 필요해지면 나중에 추가).
_RECORDER_INIT_SCRIPT = r"""
(function () {
  if (window.__aftRecorderInstalled) return;
  window.__aftRecorderInstalled = true;

  // ---- 선택자 만들기 ----
  // 재생 때 좌표 대신 이 선택자로 요소를 찾아 누를 수 있으려면 (1) 페이지에서
  // 딱 그 요소 하나만 가리켜야 하고 (2) 내일 페이지가 조금 달라져도 안
  // 깨지는 것(id·이름·날짜 같은 식별 클래스)에 매여 있어야 한다. 예전엔
  // 부모를 4단계까지만 올라가 nth-of-type 경로를 만들고 유일한지도 안
  // 봐서(레드헌터 예약 페이지에 editor_memo_pc가 33개) 좌표로만 재생할
  // 수 있었다.
  //
  // 우선순위: 안정적 id → name → data-schedule_no → 날짜/긴 숫자가 든
  // 식별 클래스(a.d2026-09-23) → 가장 가까운 안정적 id 조상(예:
  // table#d2026-09-23)을 앵커로 한 경로 → (앵커가 없으면) 유일해질 때까지
  // 올라간 경로. 앵커가 있으면 "지금 우연히 유일한" 짧은 경로에서 멈추지
  // 않고 반드시 앵커까지 올라간다 - 내일 다른 날짜에 같은 모양이 생기면
  // 깨질 선택자이기 때문이다.
  var STATE_CLASS = /(^|[_-])(select(ed)?|active|on|off|current|today|hover|focus(ed)?|open(ed)?|checked|show(n)?|hide|hidden|disabled|over)($|[_-])/i;
  var IDENTIFYING_CLASS = /\d{4}-\d{2}-\d{2}|\d{4,}/;

  function stableId(el) {
    return !!el.id && !/^(__aft|ui-id-|ember|react-|:r)/i.test(el.id);
  }
  function matchCount(sel) {
    try { return document.querySelectorAll(sel).length; } catch (e) { return 0; }
  }
  function usableClasses(el) {
    if (typeof el.className !== 'string') return [];
    var cls = el.className.trim().split(/\s+/).filter(function (c) { return c && !STATE_CLASS.test(c); });
    // 식별 클래스를 앞으로 - 2개까지만 쓰므로 밀려나면 안 된다.
    return cls.filter(function (c) { return IDENTIFYING_CLASS.test(c); })
      .concat(cls.filter(function (c) { return !IDENTIFYING_CLASS.test(c); }));
  }
  function segment(el, withPosition) {
    var seg = el.tagName.toLowerCase();
    var cls = usableClasses(el).slice(0, 2);
    if (cls.length) seg += '.' + cls.map(function (c) { return CSS.escape(c); }).join('.');
    var parent = el.parentElement;
    if (withPosition && parent) {
      var siblings = Array.prototype.filter.call(parent.children, function (c) { return c.tagName === el.tagName; });
      if (siblings.length > 1) seg += ':nth-of-type(' + (siblings.indexOf(el) + 1) + ')';
    }
    return seg;
  }
  function describeTarget(el) {
    if (!el || el.nodeType !== 1) return { selector: '', selectorUnique: false };
    function done(sel) { return { selector: sel, selectorUnique: matchCount(sel) === 1 }; }
    var sel;
    if (stableId(el)) {
      sel = '#' + CSS.escape(el.id);
      if (matchCount(sel) === 1) return done(sel);
    }
    var tag = el.tagName.toLowerCase();
    var name = el.getAttribute && el.getAttribute('name');
    if (name) {
      sel = tag + '[name="' + name + '"]';
      if (matchCount(sel) === 1) return done(sel);
    }
    var scheduleNo = el.getAttribute && el.getAttribute('data-schedule_no');
    if (scheduleNo) {
      sel = tag + '[data-schedule_no="' + scheduleNo + '"]';
      if (matchCount(sel) === 1) return done(sel);
    }
    if (usableClasses(el).some(function (c) { return IDENTIFYING_CLASS.test(c); })) {
      sel = segment(el, false);
      if (matchCount(sel) === 1) return done(sel);
    }
    var chain = [];
    var anchor = null;
    var node = el;
    for (var i = 0; i < 12 && node && node.nodeType === 1 && node !== document.documentElement; i++) {
      if (i > 0 && stableId(node)) { anchor = node; break; }
      chain.unshift(segment(node, true));
      node = node.parentElement;
    }
    if (anchor) return done('#' + CSS.escape(anchor.id) + ' > ' + chain.join(' > '));
    for (var k = 1; k <= chain.length; k++) {
      sel = chain.slice(-k).join(' > ');
      if (matchCount(sel) === 1) return done(sel);
    }
    return done(chain.join(' > '));
  }
  function describeSelector(el) { return describeTarget(el).selector; }

  // 녹화 중 클릭한 자리에도 재생 때(engine.py)와 똑같은 빨간 점을
  // 잠깐 찍어둔다 - "녹화할 때 위치와 재생할 때 위치가 다른가?"를
  // 직접 눈으로 비교할 수 있게(둘 다 같은 e.clientX/clientY 좌표계를
  // 쓰므로 마커가 뜨는 화면 픽셀 위치 자체는 항상 같다 - 다만 그 사이
  // 스크롤/레이아웃이 바뀌면 그 자리의 "내용"이 달라질 수 있다).
  function showClickMarker(x, y) {
    var old = document.getElementById('__aftClickMarker');
    if (old) old.remove();
    var marker = document.createElement('div');
    marker.id = '__aftClickMarker';
    marker.style.cssText = 'position:fixed;left:' + (x - 9) + 'px;top:' + (y - 9) + 'px;' +
      'width:18px;height:18px;border-radius:50%;background:rgba(0,140,255,0.45);' +
      'border:2px solid #008cff;box-shadow:0 0 6px rgba(0,140,255,0.8);' +
      'z-index:2147483647;pointer-events:none;';
    document.body.appendChild(marker);
    setTimeout(function () { if (marker.parentNode) marker.remove(); }, 1200);
  }

  // document가 아니라 window에 붙인다 - 실제 선상24 팝업에서 클릭은
  // 잡히는데 Tab/텍스트 입력만 하나도 안 잡히는 문제가 실측됐다. 많은
  // 실사이트 팝업/모달은 포커스를 가두려고(포커스 트랩) 자기 스크립트
  // 안에서 keydown을 capturing 단계로 듣고 stopPropagation을 부른다 -
  // 그 리스너가 document에 붙어 있으면 document보다 늦게 실행되는
  // 우리 리스너까지는 이벤트가 아예 안 내려온다. 반면 이 스크립트는
  // Playwright의 add_init_script로 그 페이지의 어떤 스크립트보다도
  // 먼저 실행되므로, 캡처링 단계에서 가장 바깥쪽인 window에 리스너를
  // 먼저 등록해 두면(같은 대상에 등록된 capturing 리스너는 등록
  // "순서"대로 실행된다) 사이트 스크립트가 나중에 stopPropagation을
  // 불러도 이미 우리 리스너는 실행된 뒤라 절대 못 막는다.
  var lastEnterAt = 0;
  window.addEventListener('click', function (e) {
    // 포커스된 <button>/<a>에서 Enter를 누르면 브라우저가 표준 동작으로
    // click 이벤트를 자체적으로 만들어낸다 - 그러면 아래 keydown
    // 리스너가 이미 'enter' 이벤트로 같은 동작을 기록했는데 여기서
    // 또 'click'으로 중복 기록하게 된다. 방금(50ms 이내) Enter가
    // 있었다면 그 결과물이므로 건너뛴다.
    if (Date.now() - lastEnterAt < 50) return;
    showClickMarker(e.clientX, e.clientY);
    var target = describeTarget(e.target);
    window.__aftRecordEvent({ type: 'click', x: e.clientX, y: e.clientY, scrollX: window.scrollX, scrollY: window.scrollY, selector: target.selector, selectorUnique: target.selectorUnique });
  }, true);

  function isTextLike(t) {
    return !!(t && (t.tagName === 'TEXTAREA' ||
      (t.tagName === 'INPUT' && ['text', 'tel', 'email', 'search', 'password', 'number', ''].indexOf((t.type || '').toLowerCase()) !== -1)));
  }

  // change가 뜬 게 방금 Tab 때문인지(포커스가 이미 다음 칸으로
  // 넘어간 상태) 아닌지 Python에 같이 알려준다 - 텍스트 입력칸에서
  // Enter를 누르면(버튼 활성화가 아니라 이 칸에서), 포커스는 그
  // 칸에 그대로 있는데도 브라우저가 change를 발화한다는 걸 실측으로
  // 확인했다(Tab처럼 다음 칸으로 넘어가는 게 아님). Tab이 원인일
  // 때만 "그 Tab 자체가 다음 칸으로의 첫 이동이기도 하다"는 보정이
  // 맞다 - Enter가 원인이면 포커스가 안 움직였으니 그 보정을 하면
  // 안 된다(실제로 겪음 - 첫 번째 필드 값이 엉뚱한 tabCount로 기록됨).
  var lastKeyWasTab = false;
  window.addEventListener('change', function (e) {
    if (isTextLike(e.target)) {
      window.__aftRecordEvent({ type: 'input', value: e.target.value, selector: describeSelector(e.target), viaTab: lastKeyWasTab });
    }
  }, true);

  window.addEventListener('keydown', function (e) {
    if (e.key === 'Tab') {
      lastKeyWasTab = true;
      window.__aftRecordEvent({ type: 'tab' });
      return;
    }
    lastKeyWasTab = false;
    // Enter로 포커스된 버튼/링크를 "누르는"것도 하나의 단계로
    // 기록한다 - 마우스 좌표 없이 Tab 이동 + Enter만으로 진행할 수
    // 있는 구간은 좌표/스크롤 드리프트와 완전히 무관해진다(요청:
    // "계속 바뀌는 x,y 문제를 해결"). document.activeElement가 지금
    // 포커스된, 곧 Enter로 활성화될 요소다. 단, 텍스트 입력칸에
    // 포커스가 있을 때 누른 Enter는 기록하지 않는다 - 타이핑 도중
    // 습관적으로/실수로 누르는 경우가 많고, 그게 하나의 "단계"로
    // 잘못 끼어들면 그 뒤 모든 Tab 카운트가 밀려버리는 걸 실측으로
    // 확인했다(값이 엉뚱한 필드에 들어가는 문제로 이어짐).
    if (e.key === 'Enter' && !isTextLike(document.activeElement)) {
      lastEnterAt = Date.now();
      var focused = describeTarget(document.activeElement);
      window.__aftRecordEvent({ type: 'enter', selector: focused.selector, selectorUnique: focused.selectorUnique });
    }
  }, true);

  // 🎯 좌표 인식기 - 날짜 클릭 등으로 페이지가 새로 불러와지면(완전한
  // 재로딩) 그때그때 주입한 스크립트는 같이 사라져 버린다(실제로
  // 겪음 - "계속 표시해달라"는 요청). 이 스크립트는 add_init_script로
  // 모든 새 문서에서 항상 다시 실행되므로, 배지 자체를 여기 아예
  // 심어두고 켜져 있었는지만 localStorage로 페이지 이동 너머까지
  // 기억한다.
  var coordBadge = document.createElement('div');
  coordBadge.id = '__aftCoordBadge';
  coordBadge.style.cssText = 'position:fixed;top:8px;left:8px;background:rgba(0,0,0,0.78);' +
    'color:#5fd08a;font:bold 13px monospace;padding:5px 10px;border-radius:7px;' +
    'z-index:2147483647;pointer-events:none;display:none;';
  coordBadge.textContent = 'x: -, y: -';
  function attachCoordBadge() {
    if (document.body && !document.getElementById('__aftCoordBadge')) {
      document.body.appendChild(coordBadge);
      try {
        if (localStorage.getItem('aftCoordTrackerOn') === '1') coordBadge.style.display = 'block';
      } catch (e) { /* 스토리지 접근이 막혀 있으면 그냥 꺼진 채로 둔다 */ }
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attachCoordBadge);
  } else {
    attachCoordBadge();
  }
  window.addEventListener('mousemove', function (e) {
    coordBadge.textContent = 'x: ' + e.clientX + ', y: ' + e.clientY;
  }, true);
  window.__aftCoordBadge = coordBadge;
})();
"""

# "🎯 좌표 인식기" 켜고 끄기 - 배지 자체는 _RECORDER_INIT_SCRIPT 안에
# 항상 심어져 있다(페이지 이동에도 살아남게). 여기서는 지금 열려 있는
# 페이지의 배지를 즉시 보이거나/숨기고, localStorage 플래그도 같이
# 갱신해 다음 페이지 이동 뒤에도 상태가 이어지게 한다.
_COORD_TRACKER_START_JS = r"""
(function () {
  try { localStorage.setItem('aftCoordTrackerOn', '1'); } catch (e) {}
  if (window.__aftCoordBadge) window.__aftCoordBadge.style.display = 'block';
})();
"""

_COORD_TRACKER_STOP_JS = r"""
(function () {
  try { localStorage.setItem('aftCoordTrackerOn', '0'); } catch (e) {}
  if (window.__aftCoordBadge) window.__aftCoordBadge.style.display = 'none';
})();
"""

_VIEWER_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>매크로 녹화 · 재생 제어판</title>
<style>
  /* hidden 속성은 항상 이겨야 한다 - 아래 .btn-primary/.panel류처럼
     display를 직접 지정하는 클래스와 같이 쓰면(둘 다 author 스타일이라
     명시도가 같아 나중에 나온 규칙이 이긴다) hidden이 무시돼 여러 화면이
     동시에 보이는 버그가 실제로 있었다 - 여기서 한 번에 막는다. */
  [hidden]{display:none!important;}
  body{font-family:-apple-system,"Malgun Gothic",sans-serif;margin:0;background:#1c1f26;color:#eee;padding:14px;}
  h1{font-size:14px;margin:14px 0 10px;color:#9fc4ff;}
  .bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:9px;padding:11px 12px;background:#242a38;border-radius:10px;}
  input[type=text],input[type=number]{background:#151922;border:1px solid #3a4152;color:#eee;border-radius:6px;padding:8px 9px;font-size:13px;}
  input[type=text]{flex:1;min-width:120px;}
  input[type=text]:disabled{opacity:0.6;}
  input[type=number]{width:76px;}
  button{border:none;border-radius:8px;padding:9px 13px;font-size:12.5px;font-weight:bold;cursor:pointer;white-space:nowrap;}
  button:disabled{opacity:0.35;cursor:default;}
  .btn-primary{background:#4f9bff;color:#fff;}
  .btn-danger{background:#e2554f;color:#fff;}
  .btn-ghost{background:#333c4d;color:#eee;}
  .btn-rec-active{background:#e2554f;color:#fff;opacity:1;cursor:default;}
  .btn-quit{position:fixed;top:10px;right:10px;background:#3a4152;color:#bbb;font-size:11px;padding:5px 9px;z-index:5;}
  .seg{display:flex;gap:2px;background:#151922;border-radius:8px;padding:2px;}
  .seg-btn{background:transparent;color:#9ba5b8;padding:6px 10px;border-radius:6px;}
  .seg-btn.active{background:#3a4152;color:#fff;}
  .hint{font-size:10.5px;color:#8b93a3;width:100%;}
  .step{display:flex;gap:8px;background:#262b35;border-radius:8px;padding:9px 11px;margin-bottom:7px;border-left:3px solid transparent;}
  .step.current{border-left-color:#4f9bff;background:#2b3245;}
  .num{flex:none;width:20px;height:20px;border-radius:50%;background:#3b7ddd;color:#fff;
       font-size:11px;font-weight:bold;display:flex;align-items:center;justify-content:center;}
  .label{font-size:12.5px;font-weight:bold;}
  .input-row{font-size:11px;color:#9fb0c8;margin-top:3px;}
  .target{font-size:11px;color:#7fd6a0;margin-top:3px;font-family:monospace;}
  .rstatus{font-size:10.5px;font-weight:bold;margin-top:4px;}
  .rstatus.done{color:#5fd08a;} .rstatus.running{color:#4f9bff;} .rstatus.error{color:#e2554f;}
  .empty{color:#888;font-size:12px;}
  .step .body{flex:1;min-width:0;}
  .actions{flex:none;display:flex;gap:4px;align-items:flex-start;}
  .icon-btn{background:#333c4d;color:#cfd6e4;padding:0;width:26px;height:26px;border-radius:6px;font-size:12px;line-height:1;}
  .icon-btn.del{color:#ff8a85;}
  .icon-btn:hover:not(:disabled){background:#414c62;}
  .modal{position:fixed;inset:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:20;}
  .modal-card{background:#242a38;border-radius:12px;padding:16px;width:min(460px,92vw);max-height:80vh;overflow:auto;}
  .modal-title{font-size:14px;font-weight:bold;color:#9fc4ff;margin-bottom:10px;}
  .modal-msg{font-size:12.5px;line-height:1.5;margin-bottom:12px;}
  .modal-btns{display:flex;gap:8px;justify-content:flex-end;}
  .file-item{display:block;width:100%;text-align:left;background:#2b3245;color:#eee;margin-bottom:7px;font-weight:normal;}
  .file-item:hover{background:#354060;}
  .file-name{font-size:13px;font-weight:bold;}
  .file-meta{font-size:11px;color:#9fb0c8;margin-top:3px;}
  .file-url{font-size:10.5px;color:#7fd6a0;margin-top:2px;font-family:monospace;overflow:hidden;text-overflow:ellipsis;}
</style></head>
<body>
  <button type="button" class="btn-quit" id="quitBtn">🔚 완전히 종료</button>

  <div class="bar" id="nameBar">
    <div class="hint">매크로 이름을 먼저 정해주세요(파일 이름이 됩니다) - URL이 바뀌면 다른 이름을 써야 예전 녹화를 안 덮어씁니다.</div>
    <input type="text" id="nameInput" placeholder="예: 레드헌터_9월23일">
    <button type="button" class="btn-primary" id="recToggleBtn">🔴 녹화 시작</button>
    <button type="button" class="btn-ghost" id="stopBtn" hidden>⏹ 중지</button>
  </div>

  <div class="bar" id="editBar">
    <button type="button" class="btn-ghost" id="loadBtn">📂 불러오기</button>
    <button type="button" class="btn-ghost" id="undoBtn">↩ 마지막 단계 취소</button>
    <button type="button" class="btn-primary" id="saveBtn">💾 저장</button>
    <button type="button" class="btn-danger" id="clearBtn">🗑 처음부터</button>
    <button type="button" class="btn-ghost" id="coordTrackerBtn">🎯 좌표 인식기</button>
  </div>

  <h1 id="title">기록된 단계 (0개)</h1>

  <div class="bar" id="testBar">
    <div class="seg">
      <button type="button" class="seg-btn active" id="modeAutoBtn">한 번에 쭉</button>
      <button type="button" class="seg-btn" id="modeStepBtn">한 단계씩</button>
    </div>
    <span class="hint" style="width:auto;">지연(ms)</span>
    <input type="number" id="delayInput" value="300" min="0" step="50">
    <button type="button" class="btn-primary" id="replayBtn">▶ 테스트 재생</button>
    <button type="button" class="btn-primary" id="replayNextBtn" hidden>다음 단계 ▶</button>
    <button type="button" class="btn-danger" id="replayStopBtn" hidden>⏸ 재생 중지</button>
  </div>

  <div id="list" class="empty">대상 창에서 클릭하면 여기 단계가 하나씩 쌓입니다.</div>

  <div class="modal" id="modal" hidden>
    <div class="modal-card">
      <div class="modal-title" id="modalTitle">저장된 녹화 불러오기</div>
      <div id="modalBody"></div>
      <div class="modal-btns" id="modalBtns"><button type="button" class="btn-ghost" id="modalClose">닫기</button></div>
    </div>
  </div>
<script>
function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
function describeClick(c) {
  if (!c) return '(입력만 - 클릭 없음)';
  if (c.mode === 'tab') return 'Tab ' + c.tabCount + '회 이동' + (c.useKey === 'Enter' ? ' 후 Enter' : '');
  if (c.mode === 'coord') return '좌표 (' + c.x + ', ' + c.y + ')';
  return c.selector || '?';
}
function post(path, body) {
  return fetch(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }).catch(function () {});
}

const nameInput = document.getElementById('nameInput');
const recToggleBtn = document.getElementById('recToggleBtn');
let stopRequested = false;

function renderBars(data) {
  const named = data.mode !== 'naming';
  const recording = data.mode === 'recording';
  const replaying = data.mode === 'replaying';
  const hasSteps = (data.steps || []).length > 0;

  nameInput.disabled = named;
  if (named && document.activeElement !== nameInput) nameInput.value = data.name;

  if (!named) {
    recToggleBtn.textContent = '🔴 녹화 시작';
    recToggleBtn.className = 'btn-primary';
    recToggleBtn.disabled = !nameInput.value.trim();
    recToggleBtn.onclick = function () { post('/start', { name: nameInput.value }); };
  } else if (recording) {
    recToggleBtn.textContent = '⏺ 녹화중';
    recToggleBtn.className = 'btn-rec-active';
    recToggleBtn.disabled = true;
    recToggleBtn.onclick = null;
  } else {
    recToggleBtn.textContent = '✏ 이어서 녹화';
    recToggleBtn.className = 'btn-ghost';
    recToggleBtn.disabled = replaying;
    recToggleBtn.onclick = function () { post('/resume'); };
  }

  document.getElementById('stopBtn').hidden = !recording;
  document.getElementById('loadBtn').disabled = recording || replaying;
  document.getElementById('undoBtn').disabled = !hasSteps || replaying;
  document.getElementById('saveBtn').disabled = !hasSteps || replaying;
  document.getElementById('clearBtn').disabled = !named || replaying;

  // 재생(특히 "한 단계씩") 중에도 좌표를 계속 확인하고 싶다는 요청 -
  // 재생 자체를 방해하지 않으므로(수동 마우스 이동을 그냥 화면에
  // 표시만 함) 막을 이유가 없다.
  const trackerBtn = document.getElementById('coordTrackerBtn');
  trackerBtn.textContent = data.coordTracker ? '⏹ 좌표 인식기 중지' : '🎯 좌표 인식기';
  trackerBtn.className = data.coordTracker ? 'btn-rec-active' : 'btn-ghost';

  const replayKind = data.replay && data.replay.kind;
  const isStepReplay = replaying && replayKind === 'step';
  document.getElementById('delayInput').disabled = replaying || !hasSteps;
  document.getElementById('modeAutoBtn').disabled = replaying;
  document.getElementById('modeStepBtn').disabled = replaying;
  document.getElementById('replayBtn').hidden = replaying;
  document.getElementById('replayBtn').disabled = !hasSteps;
  document.getElementById('replayNextBtn').hidden = !isStepReplay;
  const stopBtn2 = document.getElementById('replayStopBtn');
  stopBtn2.hidden = !replaying;
  if (!replaying) {
    stopRequested = false;
  } else if (!stopRequested) {
    stopBtn2.disabled = false;
    stopBtn2.textContent = isStepReplay ? '■ 종료' : '⏸ 재생 중지';
  }
}

// 0.4초마다 다시 그리면 ▲▼✕ 버튼을 누르는 도중(마우스 누름~뗌 사이)에
// 요소가 교체돼 클릭이 씹힐 수 있다 - 내용이 바뀌었을 때만 다시 그린다.
let lastStepsSig = null;
function renderSteps(data) {
  const wrap = document.getElementById('list');
  const steps = data.steps || [];
  const sig = JSON.stringify([data.name, data.mode, steps, data.replay]);
  if (sig === lastStepsSig) return;
  lastStepsSig = sig;
  const locked = data.mode === 'replaying';
  document.getElementById('title').textContent = (data.name ? data.name + ' · ' : '') + '기록된 단계 (' + steps.length + '개)';
  if (!steps.length) {
    wrap.className = 'empty';
    wrap.textContent = '대상 창에서 클릭하면 여기 단계가 하나씩 쌓입니다.';
    return;
  }
  wrap.className = '';
  const replay = data.replay;
  wrap.innerHTML = steps.map(function (s, i) {
    const inputsHtml = (s.inputs || []).map(function (inp) {
      return '<div class="input-row">입력: ' + esc(inp.value) + '</div>';
    }).join('');
    const isCurrent = replay && i === replay.current;
    let statusHtml = '';
    if (replay && replay.statuses && replay.statuses[i] && replay.statuses[i] !== '대기') {
      const st = replay.statuses[i];
      const cls = st === '완료' ? 'done' : st === '진행' ? 'running' : 'error';
      statusHtml = '<div class="rstatus ' + cls + '">' + esc(st) + '</div>';
    }
    const actionsHtml = '<div class="actions">' +
      '<button type="button" class="icon-btn" data-act="up" data-idx="' + i + '" title="위로"' + (locked || i === 0 ? ' disabled' : '') + '>▲</button>' +
      '<button type="button" class="icon-btn" data-act="down" data-idx="' + i + '" title="아래로"' + (locked || i === steps.length - 1 ? ' disabled' : '') + '>▼</button>' +
      '<button type="button" class="icon-btn del" data-act="del" data-idx="' + i + '" title="이 단계 삭제"' + (locked ? ' disabled' : '') + '>✕</button></div>';
    return '<div class="step' + (isCurrent ? ' current' : '') + '"><div class="num">' + (i + 1) + '</div><div class="body">' +
      '<div class="label">' + esc(s.label) + '</div>' + inputsHtml +
      '<div class="target">' + esc(describeClick(s.click)) + '</div>' + statusHtml + '</div>' + actionsHtml + '</div>';
  }).join('');
}

// 단계 목록은 다시 그려질 때마다 요소가 새로 만들어지므로 위임으로 듣는다.
document.getElementById('list').addEventListener('click', function (e) {
  const btn = e.target.closest('[data-act]');
  if (!btn || btn.disabled) return;
  const index = parseInt(btn.getAttribute('data-idx'), 10);
  const act = btn.getAttribute('data-act');
  if (act === 'del') post('/step/delete', { index: index });
  else post('/step/move', { index: index, delta: act === 'up' ? -1 : 1 });
});

// ---- 저장된 녹화 불러오기 (커스텀 모달 - 브라우저 기본 다이얼로그 안 씀) ----
const modal = document.getElementById('modal');
const modalBody = document.getElementById('modalBody');
const modalTitle = document.getElementById('modalTitle');
let savedFiles = [];
function closeModal() { modal.hidden = true; }
function showModalMessage(title, msgHtml, buttonsHtml) {
  modalTitle.textContent = title;
  modalBody.innerHTML = '<div class="modal-msg">' + msgHtml + '</div>';
  document.getElementById('modalBtns').innerHTML = buttonsHtml + '<button type="button" class="btn-ghost" id="modalClose">닫기</button>';
  document.getElementById('modalClose').addEventListener('click', closeModal);
}
async function openLoadModal() {
  modal.hidden = false;
  modalTitle.textContent = '저장된 녹화 불러오기';
  modalBody.innerHTML = '<div class="empty">불러오는 중...</div>';
  document.getElementById('modalBtns').innerHTML = '<button type="button" class="btn-ghost" id="modalClose">닫기</button>';
  document.getElementById('modalClose').addEventListener('click', closeModal);
  savedFiles = [];
  try {
    const res = await fetch('/saved?_=' + Date.now(), { cache: 'no-store' });
    savedFiles = (await res.json()).files || [];
  } catch (e) { /* 아래에서 빈 목록으로 처리 */ }
  if (!savedFiles.length) {
    modalBody.innerHTML = '<div class="empty">저장된 녹화 파일이 없습니다.</div>';
    return;
  }
  modalBody.innerHTML = savedFiles.map(function (f, i) {
    return '<button type="button" class="file-item" data-idx="' + i + '">' +
      '<div class="file-name">' + esc(f.file) + '</div>' +
      '<div class="file-meta">' + f.stepCount + '단계 · ' + esc(f.modified) + '</div>' +
      '<div class="file-url">' + esc(f.url) + '</div></button>';
  }).join('');
}
async function loadFile(file, force) {
  let res;
  try {
    res = await fetch('/load', { method: 'POST', body: JSON.stringify({ file: file, force: !!force }) });
  } catch (e) { return; }
  if (res.ok) { closeModal(); return; }
  let info = {};
  try { info = await res.json(); } catch (e) { /* 본문 없음 */ }
  if (res.status === 409) {
    showModalMessage('저장 안 된 변경이 있습니다',
      '지금 편집 중인 단계에 저장하지 않은 변경이 있습니다.<br>불러오면 그 변경은 사라집니다.',
      '<button type="button" class="btn-danger" id="forceLoadBtn">덮어쓰고 불러오기</button>');
    document.getElementById('forceLoadBtn').addEventListener('click', function () { loadFile(file, true); });
    return;
  }
  showModalMessage('불러오지 못했습니다', esc(info.reason === 'busy' ? '녹화 중이거나 재생 중에는 불러올 수 없습니다.' : (info.reason || '알 수 없는 오류')), '');
}
document.getElementById('loadBtn').addEventListener('click', openLoadModal);
modalBody.addEventListener('click', function (e) {
  const item = e.target.closest('.file-item');
  if (!item) return;
  const f = savedFiles[parseInt(item.getAttribute('data-idx'), 10)];
  if (f) loadFile(f.file, false);
});
document.getElementById('modalClose').addEventListener('click', closeModal);

async function refresh() {
  try {
    const res = await fetch('state.json?_=' + Date.now(), { cache: 'no-store' });
    const data = await res.json();
    renderBars(data);
    renderSteps(data);
  } catch (e) { /* 서버가 아직 안 떠 있을 수도 있음 - 다음 폴링에 재시도 */ }
}

nameInput.addEventListener('input', function () {
  if (!nameInput.disabled) recToggleBtn.disabled = !nameInput.value.trim();
});
document.getElementById('stopBtn').addEventListener('click', function () { post('/stop'); });
document.getElementById('undoBtn').addEventListener('click', function () { post('/undo'); });
document.getElementById('saveBtn').addEventListener('click', function () { post('/save'); });
document.getElementById('clearBtn').addEventListener('click', function () { post('/clear'); });
document.getElementById('coordTrackerBtn').addEventListener('click', function () {
  const on = this.textContent.indexOf('중지') !== -1;
  post(on ? '/coord-tracker/stop' : '/coord-tracker/start');
});

let replayMode = 'auto';
document.getElementById('modeAutoBtn').addEventListener('click', function () {
  replayMode = 'auto';
  this.classList.add('active');
  document.getElementById('modeStepBtn').classList.remove('active');
});
document.getElementById('modeStepBtn').addEventListener('click', function () {
  replayMode = 'step';
  this.classList.add('active');
  document.getElementById('modeAutoBtn').classList.remove('active');
});
document.getElementById('replayBtn').addEventListener('click', function () {
  const delay = parseInt(document.getElementById('delayInput').value, 10) || 0;
  post('/replay', { delayMs: delay, mode: replayMode });
});
document.getElementById('replayNextBtn').addEventListener('click', function () { post('/replay-next'); });
document.getElementById('replayStopBtn').addEventListener('click', function () {
  // 지금 실행 중인 단계가 막혀 있으면(예: 팝업이 안 뜸) 그 단계의
  // 대기가 끝나야 실제로 멈춘다(최대 몇 초) - 누른 게 먹혔다는 걸
  // 바로 보여준다.
  stopRequested = true;
  this.disabled = true;
  this.textContent = '중지 중...';
  post('/replay-stop');
});
document.getElementById('quitBtn').addEventListener('click', function () {
  // 네이티브 confirm() 대신 - 종료해도 이름이 정해져 있으면 지금까지
  // 기록된 내용을 자동으로 한 번 더 저장한 뒤 끝나므로 안전하다.
  this.disabled = true;
  this.textContent = '종료 중...';
  post('/quit');
});
setInterval(refresh, 400);
refresh();
</script>
</body></html>
"""


def _sanitize_name(raw):
    name = re.sub(r'[^0-9A-Za-z가-힣_-]+', '_', (raw or '').strip())
    return name.strip('_')[:60]


def _atomic_replace(tmp, dest):
    # 오른쪽 창(viewer.html)이 state.json을 0.4초마다 fetch로 폴링하는데,
    # Windows는 다른 프로세스/핸들이 읽고 있는 파일을 rename으로
    # 덮어쓰는 걸 거부할 수 있다(POSIX와 달리 - 실제로
    # PermissionError [WinError 5]가 재생 도중 반복 발생했다). 그 잠금은
    # 보통 요청 하나 처리하는 짧은 순간만 걸리므로, 몇 번 짧게 재시도
    # 하면 대부분 풀린다.
    for attempt in range(25):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if attempt == 24:
                raise
            time.sleep(0.03)


class Recorder:
    """실제 브라우저 이벤트를 복합 단계로 조립한다. 이 클래스의 메서드는
    Playwright의 바인딩 콜백에서 호출되므로 **Playwright API를 절대
    호출하지 않는다** - 순수 파이썬 상태 변경만 하고, 바뀔 때마다
    on_change() 콜백(파일 쓰기 등)을 부른다."""

    def __init__(self):
        self.page_roles = {}
        self.tab_counter = 0
        self.current_inputs = []
        self.steps = []
        self.seed = 0
        self.pending_popup = False
        # 이름을 정하기 전(naming)이나 테스트 재생 중에는 꺼둔다 - 그
        # 사이 클릭이 들어와도 새 단계로 기록하지 않는다.
        self.enabled = False
        self.on_change = lambda: None

    def register_page(self, page, role):
        self.page_roles[page] = role

    def on_new_page(self, new_page):
        self.register_page(new_page, 'popup')
        self.pending_popup = True

    def undo(self):
        if self.steps:
            self.steps.pop()
            self.on_change()

    def clear(self):
        self.steps = []
        self.current_inputs = []
        self.tab_counter = 0
        self.seed = 0
        self.pending_popup = False
        self.on_change()

    def delete_step(self, index):
        if steps_edit.delete_step(self.steps, index):
            self.seed = len(self.steps)
            self.on_change()
            return True
        return False

    def move_step(self, index, delta):
        if steps_edit.move_step(self.steps, index, delta):
            self.on_change()
            return True
        return False

    def load_steps(self, steps):
        """저장된 녹화의 단계를 통째로 바꿔 끼운다 - 이어붙일 게 남아 있으면
        안 되므로 입력 대기·Tab 카운트·팝업 대기 상태도 함께 초기화한다."""
        self.steps = steps
        self.current_inputs = []
        self.tab_counter = 0
        self.seed = steps_edit.renumber(self.steps)
        self.pending_popup = False
        self.on_change()

    def _maybe_apply_pending_popup(self):
        if self.pending_popup and self.steps:
            self.pending_popup = False
            last = self.steps[-1]
            if not last['opensPopup']:
                last['opensPopup'] = True
                last['label'] = self._label_for(last)
                self.on_change()

    def _label_for(self, step):
        click = step['click']
        if click is None:
            # Tab으로 필드를 벗어나며 값만 커밋된, 클릭/Enter 없는 단계.
            base = '입력'
        else:
            finish = 'Enter' if click.get('useKey') == 'Enter' else '클릭'
            base = ('입력 {}개 → {}'.format(len(step['inputs']), finish) if step['inputs'] else finish)
        if step['context'] == 'popup':
            base = '(팝업) ' + base
        if step['opensPopup']:
            base += ' · 새 창 열림'
        return base

    def _pick_main_mode(self, selector, unique=None):
        # 녹화기 JS가 "페이지에서 그 요소 하나만 가리킨다"고 확인해 준(unique)
        # 선택자만 selector 모드로 쓴다 - 재생 때 스크롤·배너 높이 같은
        # 레이아웃 변화와 무관하다(Playwright가 알아서 스크롤해서 누름).
        # 유일하지 않으면 좌표로 남긴다. unique가 없는 예전 이벤트는 옛 규칙
        # (id/name만 신뢰)을 그대로 따른다.
        if not selector:
            return 'coord'
        if unique is None:
            return 'selector' if (selector.startswith('#') or '[name=' in selector) else 'coord'
        return 'selector' if unique else 'coord'

    def handle_event(self, source, payload):
        if not self.enabled:
            return
        self._maybe_apply_pending_popup()

        page = source['page']
        role = self.page_roles.get(page, 'main')
        kind = payload.get('type')

        if kind == 'tab':
            self.tab_counter += 1
            return

        if kind == 'input':
            # change 이벤트는 필드에서 포커스가 빠져나갈 때(blur) 뜬다 -
            # 그런데 그 blur를 일으킨 게 Tab이었다면, Tab 키 입력의
            # 기본 동작(포커스 이동)이 change 발화보다 먼저 끝나 있으므로
            # change가 뜨는 시점엔 이미 포커스가 "다음" 필드로 넘어가
            # 있다. 즉 방금 센 Tab 카운트의 마지막 1회는 이 필드에
            # "도달"한 것과 무관하고 다음 필드를 향한 첫 이동이다 -
            # 그걸 그대로 이 필드의 tabCount로 쓰면 재생 시 한 칸씩
            # 밀려서 엉뚱한 필드에 값이 들어간다(실제로 겪음). 그래서
            # 이 필드용 tabCount는 (지금까지 센 값 - 1)로 기록하고,
            # 방금 뺀 1회는 다음 필드 카운트의 시작값으로 넘긴다.
            #
            # 단, 이 blur가 Tab이 아니라 Enter 때문이면 얘기가 다르다 -
            # 텍스트 입력칸에서 Enter를 누르면 포커스가 그 칸에 그대로
            # 있는 채로 change가 뜬다는 걸 실측으로 확인했다(Tab처럼
            # 다음 칸으로 넘어가는 게 아님). 이때 위 "-1" 보정을 그대로
            # 적용하면 tabCount가 실제보다 1 적게 기록돼 첫 필드부터
            # 어긋난다 - viaTab이 False면 보정 없이 지금까지 센 값을
            # 그대로 쓰고, carry도 0으로 둔다(포커스가 안 움직였으니
            # 다음 이동에 넘겨줄 "이미 지나온 한 칸"이 없다).
            caused_by_tab = bool(payload.get('viaTab'))
            is_tab_mode = (role == 'popup' or self.tab_counter > 0)
            if is_tab_mode and caused_by_tab:
                tab_count = max(0, self.tab_counter - 1)
                carry = 1
            else:
                tab_count = self.tab_counter
                carry = 0
            entry = {
                'mode': 'tab' if is_tab_mode else 'selector',
                'tabCount': tab_count,
                'selector': payload.get('selector') or '',
                'value': payload.get('value') or '',
            }
            print('  · 입력 감지: {!r}'.format(entry['value']), flush=True)
            if is_tab_mode:
                # Tab으로 이 필드를 벗어나며 값이 커밋된 것도 그 자체로
                # 하나의 완결된 단계로 즉시 마감한다(클릭/Enter 없음) -
                # 여러 필드를 한 클릭이 마감하는 큰 단계로 묶어두면,
                # 중간에 엉뚱한 이벤트(예: 타이핑 도중 실수로 누른
                # Enter) 하나가 끼어드는 순간 그 뒤로 tabCount 계산이
                # 전부 밀려버리는 걸 실측으로 확인했다 - 필드 하나마다
                # 독립된 단계면 그런 연쇄 오류가 안 생기고, 어느 필드가
                # 잘못됐는지도 단계 목록에서 바로 짚을 수 있다.
                self._finalize_step(role, click=None, inputs=[entry])
            else:
                # 클릭으로(Tab 없이) 필드를 벗어나는 경우는 기존처럼
                # 이어질 클릭이 함께 확정할 때까지 모아둔다.
                self.current_inputs.append(entry)
            self.tab_counter = carry
            return

        if kind == 'click':
            selector = payload.get('selector') or ''
            # 팝업은 항상 그렇듯 Tab 모드. 메인 창도 이 클릭 직전에
            # 실제로 Tab을 눌러 이동해 왔다면(tab_counter > 0) 좌표/
            # 선택자 대신 Tab 모드로 기록한다 - 반복 재생할수록 좌표가
            # 잘 안 맞는다는 문제(스크롤·레이아웃 드리프트)를 키보드
            # 내비게이션이 가능한 구간에서는 아예 우회한다.
            mode = 'tab' if (role == 'popup' or self.tab_counter > 0) else self._pick_main_mode(selector, payload.get('selectorUnique'))
            click = {
                'mode': mode,
                'tabCount': self.tab_counter,
                'selector': selector,
                'x': payload.get('x'),
                'y': payload.get('y'),
                # coord 모드로 재생할 때, 녹화 당시 페이지가 스크롤돼
                # 있었다면 그 위치까지 먼저 스크롤한 뒤 좌표를 클릭해야
                # 같은 지점을 가리킨다.
                'scrollX': payload.get('scrollX'),
                'scrollY': payload.get('scrollY'),
            }
            self._finalize_step(role, click)
            return

        if kind == 'enter':
            # Tab으로 이동한 뒤 마우스 클릭 대신 Enter로 확정한 것도
            # 하나의 단계다 - 좌표가 전혀 필요 없어 드리프트 문제와
            # 완전히 무관하다.
            click = {
                'mode': 'tab',
                'tabCount': self.tab_counter,
                'selector': payload.get('selector') or '',
                'x': None, 'y': None, 'scrollX': None, 'scrollY': None,
                'useKey': 'Enter',
            }
            self._finalize_step(role, click)
            return

    def _finalize_step(self, role, click, inputs=None):
        # click이 None이면 "입력만 있고 클릭/Enter는 없는" 단계다(Tab으로
        # 필드를 벗어나며 값만 커밋된 경우) - inputs를 따로 안 주면
        # 그동안 모아둔 self.current_inputs를 쓴다(기존 클릭/Enter 확정
        # 방식과 동일).
        self.seed += 1
        step = {
            'id': self.seed,
            'label': '',
            'context': role,
            'inputs': self.current_inputs if inputs is None else inputs,
            'click': click,
            # 이 클릭(또는 Enter)이 실제로 팝업을 띄웠는지는 아직
            # 모른다 - 다음 이벤트가 들어올 때 _maybe_apply_pending_popup이
            # 이 자리를 True로 고쳐 쓴다.
            'opensPopup': False,
            'sleep': 600,
            'manual': False,
        }
        step['label'] = self._label_for(step)
        self.steps.append(step)
        self.current_inputs = []
        self.tab_counter = 0
        print('  · [{}단계 기록] {} · {}'.format(len(self.steps), step['label'], self._describe_click(click)), flush=True)
        self.on_change()

    def _describe_click(self, click):
        if click is None:
            return '(입력만 - 클릭 없음)'
        if click['mode'] == 'tab':
            suffix = ' 후 Enter' if click.get('useKey') == 'Enter' else ''
            return 'Tab {}회 이동{}'.format(click['tabCount'], suffix)
        if click['mode'] == 'coord':
            return '좌표 ({}, {})'.format(click['x'], click['y'])
        return '선택자 {}'.format(click['selector'] or '?')

    def to_json(self, url):
        return {
            'url': url,
            'recWidth': 1280,
            'recHeight': 800,
            'steps': self.steps,
        }


class Session:
    """녹화·저장·재생 상태 기계. HTTP 핸들러 스레드는 이 객체의 필드를
    바꾸고 파일 I/O만 하며(둘 다 스레드에 안전), 실제 Playwright 호출이
    필요한 "재생"만 큐에 넣어 메인 스레드가 처리한다."""

    def __init__(self, state_path, url='', save_dir=None):
        self.recorder = Recorder()
        self.recorder.on_change = self._on_recorder_change
        self.state_path = state_path
        # 재생·저장이 쓰는 대상 URL - 저장된 녹화를 불러오면 그 파일의
        # URL로 바뀐다(다른 배 녹화를 불러왔는데 저장 때 엉뚱한 URL로
        # 덮어쓰는 걸 막는다).
        self.url = url
        # 녹화 파일은 실행한 폴더(현재 작업 디렉터리)에 저장/조회한다.
        self.save_dir = save_dir or os.getcwd()
        # 마지막 저장/불러오기 이후 바뀐 게 있는지 - 불러오기로 작업 중이던
        # 내용을 덮어쓰기 전에 확인을 받는 데 쓴다.
        self.dirty = False
        self.mode = 'naming'  # naming | recording | stopped | replaying
        self.name = ''
        self.out_path = None
        self.replay_queue = queue.Queue()
        self.replay_stop = threading.Event()
        self.quit_event = threading.Event()
        self.replay_current = -1
        self.replay_statuses = None
        # "한 단계씩" 재생 도중 상태 - 여러 /replay-next 요청에 걸쳐
        # 이어가야 하므로 Session에 보관한다(요청마다 새로 만들면 팝업
        # 전환 등으로 바뀐 self.page를 잃어버린다).
        self.replay_kind = None
        self.replay_runner = None
        self.replay_steps = None
        self.replay_index = -1
        self.coord_tracker_on = False
        self._write_state()

    def _on_recorder_change(self):
        self.dirty = True
        self._write_state()

    def _write_state(self):
        data = {
            'mode': self.mode,
            'name': self.name,
            'url': self.url,
            'dirty': self.dirty,
            'steps': self.recorder.steps,
            'coordTracker': self.coord_tracker_on,
            'replay': None if self.replay_statuses is None else {
                'current': self.replay_current,
                'total': len(self.recorder.steps),
                'statuses': self.replay_statuses,
                'kind': self.replay_kind,
            },
        }
        tmp = self.state_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        _atomic_replace(tmp, self.state_path)

    def start(self, raw_name):
        name = _sanitize_name(raw_name)
        if not name:
            return False
        self.name = name
        self.out_path = name + '.json'
        self.recorder.enabled = True
        self.mode = 'recording'
        self._write_state()
        return True

    def save(self):
        # 저장은 "지금까지를 파일에 남긴다"는 뜻일 뿐, 녹화 중이든
        # 멈춰 있든 언제든 부를 수 있다 - 녹화를 멈추는 건 stop()의 몫.
        if not self.out_path:
            return False
        data = self.recorder.to_json(self.url)
        tmp = self.out_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, self.out_path)
        self.dirty = False
        self._write_state()
        print('{} 개 단계를 {} 에 저장했습니다.'.format(len(self.recorder.steps), self.out_path), flush=True)
        return True

    def stop(self):
        self.recorder.enabled = False
        self.mode = 'stopped'
        self._write_state()

    def resume(self):
        self.recorder.enabled = True
        self.mode = 'recording'
        self._write_state()

    def clear(self):
        self.recorder.clear()
        self.recorder.enabled = True
        self.mode = 'recording'
        self.replay_statuses = None
        self.replay_current = -1
        self._write_state()

    def list_saved(self):
        return steps_edit.list_saved(self.save_dir)

    def load(self, filename):
        """저장된 녹화를 불러와 현재 단계를 통째로 바꾼다. 불러온 직후엔
        "멈춘 녹화"와 같은 상태(stopped)라 바로 재생하거나 "이어서 녹화"로
        더 붙일 수 있다. 실패하면 ValueError."""
        data = steps_edit.load_saved(self.save_dir, filename)
        self.recorder.enabled = False
        self.recorder.load_steps(data['steps'])
        self.name = filename[:-5]
        # 저장 위치는 실행한 폴더 기준이라 경로 없이 파일명만 쓴다.
        self.out_path = filename
        if data.get('url'):
            self.url = data['url']
        self.mode = 'stopped'
        self.replay_statuses = None
        self.replay_current = -1
        self.dirty = False
        self._write_state()


def _prepare_replay(session, main_page, context, url, kind):
    """"▶ 테스트 재생"을 누른 시점에 한 번만 하는 준비 작업 - 이전
    재생이 남긴 팝업 정리, 페이지를 새로 불러오기(run.py의 실전 실행과
    똑같이 매번 깨끗한 상태에서 시작), engine.py의 Runner 생성. 이
    Runner를 Session에 보관해 두어야 "한 단계씩" 모드에서 여러 번의
    /replay-next 요청에 걸쳐 같은 실행 상태(팝업 전환으로 바뀐
    self.page 등)를 이어갈 수 있다.

    준비 단계(특히 main_page.goto)가 실패하면(예: 이전 재생이 열어둔
    팝업 정리 도중 대상 페이지가 이미 닫혀 있는 등) 여기서 예외가
    새어나가 메인 루프 전체가 죽고 브라우저가 통째로 닫히는 사고가
    실제로 있었다 - 그래서 여기서 잡아 재생만 조용히 취소한다."""
    steps = list(session.recorder.steps)

    for page, role in list(session.recorder.page_roles.items()):
        if role == 'popup' and page != main_page:
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                pass
            session.recorder.page_roles.pop(page, None)

    session.mode = 'replaying'
    session.recorder.enabled = False
    session.replay_kind = kind
    session.replay_current = -1
    session.replay_statuses = ['대기'] * len(steps)
    session._write_state()

    try:
        main_page.goto(url)
        # 실사이트는 공지/배너 이미지가 'load' 이벤트 이후에도 계속
        # 불러와지면서 레이아웃을 밀어낸다 - 같은 좌표가 재생마다
        # 어떤 땐 날짜 링크를, 어떤 땐 배너 DIV를 가리키는 걸 실측으로
        # 반복 확인했다. 네트워크가 잠잠해질 때까지 조금 더 기다려
        # 그 불안정한 창을 최대한 줄인다 - 그래도 완전히 없어지진
        # 않을 수 있으니(광고 스크립트가 계속 폴링하는 사이트 등) 이
        # 대기 자체가 실패해도 재생은 그냥 진행한다.
        try:
            main_page.wait_for_load_state('networkidle', timeout=4000)
        except Exception:
            pass
        session.replay_steps = steps
        session.replay_runner = Runner({'steps': steps}, main_page, context)
        session.replay_index = -1
    except Exception as e:
        print('  → 재생 준비 실패: {}'.format(e), flush=True)
        _finish_replay(session)
        return False
    return True


def _finish_replay(session):
    session.mode = 'stopped'
    session.replay_runner = None
    session.replay_steps = None
    session.replay_index = -1
    session._write_state()


def _execute_replay_step(session):
    """다음 단계를 하나 실행한다 - engine.py의 Runner._execute()를
    그대로 재사용한다(새로 만들지 않음). 더 실행할 단계가 없거나
    오류가 나면 재생을 마무리하고 False를 돌려준다."""
    idx = session.replay_index + 1
    steps = session.replay_steps
    if idx >= len(steps):
        _finish_replay(session)
        return False
    session.replay_index = idx
    session.replay_current = idx
    session.replay_statuses[idx] = '진행'
    session._write_state()
    is_last = (idx == len(steps) - 1)
    try:
        session.replay_runner._execute(steps[idx])
    except Exception as e:
        session.replay_statuses[idx] = '오류: {}'.format(e)
        session._write_state()
        print('  → 재생 오류({}단계): {}'.format(idx + 1, e), flush=True)
        _finish_replay(session)
        return False
    session.replay_statuses[idx] = '완료'
    if is_last:
        # 마지막 단계까지 실행했으면 "한 단계씩" 모드에서 의미 없는
        # 확인용 클릭을 한 번 더 요구하지 않고 바로 종료한다 - auto
        # 모드 루프도 여기서 그대로 멈춘다(False를 돌려주므로).
        _finish_replay(session)
        return False
    session._write_state()
    return True


def run_replay_auto(session, main_page, context, url, delay_ms):
    """"한 번에 쭉" - 단계 사이마다 지정한 지연시간만큼 쉬면서 끝까지
    자동으로 실행한다. 사용자가 정한 지연시간을 반영하기 위해(기록된
    sleep을 그대로 쓰지 않음) 직접 루프를 돈다."""
    if not session.recorder.steps:
        return
    if not _prepare_replay(session, main_page, context, url, 'auto'):
        return
    while True:
        if session.replay_stop.is_set():
            _finish_replay(session)
            return
        if not _execute_replay_step(session):
            return
        time.sleep(delay_ms / 1000)


def run_replay_step_start(session, main_page, context, url):
    """"한 단계씩" 시작 - 첫 단계만 바로 실행하고 멈춘다. 이후는
    /replay-next가 한 단계씩 이어간다."""
    if not session.recorder.steps:
        return
    if not _prepare_replay(session, main_page, context, url, 'step'):
        return
    _execute_replay_step(session)


def run_replay_step_next(session):
    if session.mode != 'replaying' or session.replay_runner is None:
        return
    _execute_replay_step(session)


def _start_control_server(viewer_dir, session):
    with open(os.path.join(viewer_dir, 'viewer.html'), 'w', encoding='utf-8') as f:
        f.write(_VIEWER_HTML)

    class ControlHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=viewer_dir, **kw)

        def log_message(self, fmt, *args):
            pass  # 폴링 요청 로그로 터미널이 도배되는 걸 막는다

        def _reply(self, status, payload):
            body = json.dumps(payload).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self):
            length = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(length) if length else b''
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return {}

        def do_GET(self):
            if self.path.split('?')[0] == '/saved':
                return self._reply(200, {'files': session.list_saved()})
            return super().do_GET()

        def do_POST(self):
            body = self._read_body()

            if self.path == '/start':
                ok = session.start(body.get('name') or '')
                return self._reply(200 if ok else 400, {'ok': ok})

            if self.path == '/save':
                ok = session.save()
                return self._reply(200 if ok else 400, {'ok': ok})

            if self.path == '/stop':
                session.stop()
                return self._reply(200, {'ok': True})

            if self.path == '/undo':
                session.recorder.undo()
                return self._reply(200, {'ok': True})

            if self.path in ('/step/delete', '/step/move'):
                # 재생 중엔 단계 번호 기준으로 진행 상태를 그리고 있어서 손대면 안 된다.
                if session.mode == 'replaying':
                    return self._reply(400, {'ok': False})
                index = body.get('index')
                if self.path == '/step/delete':
                    ok = session.recorder.delete_step(index)
                else:
                    ok = session.recorder.move_step(index, body.get('delta'))
                return self._reply(200 if ok else 400, {'ok': ok})

            if self.path == '/load':
                # 녹화 중/재생 중엔 불러오지 않는다 - 진행 중인 기록이 섞인다.
                if session.mode in ('recording', 'replaying'):
                    return self._reply(400, {'ok': False, 'reason': 'busy'})
                if session.dirty and session.recorder.steps and not body.get('force'):
                    return self._reply(409, {'ok': False, 'reason': 'dirty'})
                try:
                    session.load(body.get('file'))
                except ValueError as e:
                    return self._reply(400, {'ok': False, 'reason': str(e)})
                session.replay_queue.put({'kind': 'goto'})
                return self._reply(200, {'ok': True})

            if self.path == '/clear':
                session.clear()
                return self._reply(200, {'ok': True})

            if self.path == '/resume':
                session.resume()
                return self._reply(200, {'ok': True})

            if self.path == '/replay':
                if session.mode in ('naming', 'replaying') or not session.recorder.steps:
                    return self._reply(400, {'ok': False})
                # 실제 Playwright 호출(재생)은 이 핸들러 스레드가 아니라
                # 메인 스레드가 처리한다(콜백 스레드 안에서 Playwright API
                # 호출 금지 원칙과 같은 이유).
                session.replay_stop.clear()
                if (body.get('mode') or 'auto') == 'step':
                    session.replay_queue.put({'kind': 'step-start'})
                else:
                    session.replay_queue.put({'kind': 'auto', 'delayMs': int(body.get('delayMs') or 300)})
                return self._reply(200, {'ok': True})

            if self.path == '/replay-next':
                if session.mode != 'replaying' or session.replay_kind != 'step':
                    return self._reply(400, {'ok': False})
                session.replay_queue.put({'kind': 'step-next'})
                return self._reply(200, {'ok': True})

            if self.path == '/replay-stop':
                session.replay_stop.set()
                # "한 단계씩" 모드는 단계 사이에 대기 루프가 없으므로
                # (각 단계가 별도 HTTP 요청으로만 진행된다) 이 자리에서
                # 바로 끝내야 한다 - Playwright 호출 없이 상태만
                # 바꾸는 것이라 핸들러 스레드에서 해도 안전하다.
                if session.mode == 'replaying' and session.replay_kind == 'step':
                    _finish_replay(session)
                return self._reply(200, {'ok': True})

            if self.path == '/quit':
                session.quit_event.set()
                return self._reply(200, {'ok': True})

            if self.path == '/coord-tracker/start':
                session.coord_tracker_on = True
                session._write_state()
                session.replay_queue.put({'kind': 'coord-tracker-start'})
                return self._reply(200, {'ok': True})

            if self.path == '/coord-tracker/stop':
                session.coord_tracker_on = False
                session._write_state()
                session.replay_queue.put({'kind': 'coord-tracker-stop'})
                return self._reply(200, {'ok': True})

            self.send_error(404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), ControlHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main():
    parser = argparse.ArgumentParser(description='자동예약 매크로 - 실제 브라우저 조작 녹화·테스트 재생 도구')
    parser.add_argument('--url', required=True, help='녹화를 시작할 선사 예약 페이지 URL')
    args = parser.parse_args()

    viewer_dir = tempfile.mkdtemp(prefix='aft_macro_record_')
    state_path = os.path.join(viewer_dir, 'state.json')
    session = Session(state_path, url=args.url)
    server = _start_control_server(viewer_dir, session)
    port = server.server_address[1]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        # 녹화 대상 창 - 실제 사용자가 직접 조작한다(자동 조작 아님).
        record_context = browser.new_context(viewport={'width': 1280, 'height': 800})
        # 테스트 재생 중 클릭이 엉뚱한 곳을 눌러 팝업이 안 열리면
        # context.expect_page()가 기본 30초를 그대로 기다려 버린다 -
        # 그동안은 "⏸ 재생 중지"를 눌러도 지금 실행 중인 단계의 대기가
        # 끝나야만 멈출 수 있어(단계 사이에서만 중지 신호를 확인하므로)
        # 사실상 안 먹히는 것처럼 보인다(실제로 겪음). 녹화 자체는
        # 사람이 직접 조작하는 것이라 이 타임아웃과 무관하니, 재생에서
        # 쓰는 이 컨텍스트의 기본 타임아웃을 짧게 낮춰 막힌 단계가 훨씬
        # 빨리 실패하고 다음 정지 확인 지점으로 넘어가게 한다.
        record_context.set_default_timeout(6000)

        # 제어판 창 - 완전히 별도 컨텍스트라 녹화 스크립트가 안 심어진다
        # (여기서 클릭해도 기록되지 않음 - 이 창 자체가 기록 대상이 되면
        # 안 되므로).
        viewer_context = browser.new_context(viewport={'width': 560, 'height': 800})
        viewer_page = viewer_context.new_page()
        viewer_page.goto('http://127.0.0.1:{}/viewer.html'.format(port))
        position_window(viewer_page, **RIGHT_BOUNDS)

        record_context.expose_binding('__aftRecordEvent', session.recorder.handle_event)
        record_context.add_init_script(_RECORDER_INIT_SCRIPT)

        main_page = record_context.new_page()
        session.recorder.register_page(main_page, 'main')
        record_context.on('page', session.recorder.on_new_page)

        main_page.goto(args.url)
        position_window(main_page, **LEFT_BOUNDS)

        print('제어판(오른쪽 창)에서 이름을 정하고 "녹화 시작"을 누르세요.')
        print('완전히 종료하려면 오른쪽 창의 "🔚 완전히 종료" 버튼을 누르거나, 여기서 Enter를 누르세요 ↵ ')

        # 터미널의 input()이 메인 스레드를 통째로 막고 있는 동안에는
        # 실제로 사람이 클릭해도 그 이벤트가 콜백으로 즉시 넘어오지
        # 않고 한참 지연되는 현상이 실측됐다(Windows에서 재현). 그래서
        # input()으로 무작정 막는 대신, 실제 Playwright 동기 API 호출
        # (wait_for_timeout)을 짧은 간격으로 계속 불러 대기하면서 그
        # 사이사이 이벤트/재생 요청이 정상적으로 처리되게 한다.
        def _wait_for_enter():
            try:
                input()
            except EOFError:
                pass
            session.quit_event.set()
        threading.Thread(target=_wait_for_enter, daemon=True).start()

        while not session.quit_event.is_set():
            main_page.wait_for_timeout(200)
            try:
                cmd = session.replay_queue.get_nowait()
            except queue.Empty:
                continue
            kind = cmd.get('kind')
            # 이 블록 안 어디서든 예상 못 한 예외가 새어나가면 while
            # 루프 자체가 끝나버리고 곧바로 browser.close()로 떨어져
            # 재생 도중 브라우저가 통째로 꺼져버린다(실제로 겪음) -
            # 명령 하나 처리 실패가 전체 세션을 죽이지 않도록 여기서
            # 한 번에 막는다(_prepare_replay 안쪽에도 별도로 방어가
            # 있지만, 그걸로 못 잡는 경우까지 대비한 마지막 방어선).
            try:
                if kind == 'auto':
                    run_replay_auto(session, main_page, record_context, session.url, cmd.get('delayMs') or 300)
                elif kind == 'step-start':
                    run_replay_step_start(session, main_page, record_context, session.url)
                elif kind == 'step-next':
                    run_replay_step_next(session)
                elif kind == 'goto':
                    # 저장된 녹화를 불러오면 그 녹화의 URL을 왼쪽 창에도 띄운다.
                    main_page.goto(session.url)
                elif kind == 'coord-tracker-start':
                    main_page.evaluate(_COORD_TRACKER_START_JS)
                elif kind == 'coord-tracker-stop':
                    main_page.evaluate(_COORD_TRACKER_STOP_JS)
            except Exception as e:
                print('  → 처리 중 오류({}): {}'.format(kind, e), flush=True)
                if session.mode == 'replaying':
                    _finish_replay(session)

        # 아직 저장 안 한 녹화 중 상태로 종료하는 경우를 대비해 마지막으로
        # 한 번 더 저장해 둔다(이름이 정해져 있을 때만).
        if session.out_path and session.recorder.steps:
            session.save()

        browser.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl+C가 프로세스에 전달되면(터미널에서 선택된 텍스트 없이
        # Ctrl+C를 누르면 복사 대신 이게 발생한다 - 실제로 겪음) 여기서
        # 잡힌다. run.py와 같은 방식으로 트레이스백 대신 안내만 출력한다.
        print('\n\n중단했습니다. 열려 있던 브라우저 창은 직접 닫아 주세요.')
        sys.exit(1)
