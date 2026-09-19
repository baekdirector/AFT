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

  function describeSelector(el) {
    if (!el || el.nodeType !== 1) return '';
    if (el.id) return '#' + CSS.escape(el.id);
    if (el.getAttribute && el.getAttribute('name')) {
      return el.tagName.toLowerCase() + '[name="' + el.getAttribute('name') + '"]';
    }
    var path = [];
    var node = el;
    for (var i = 0; i < 4 && node && node.nodeType === 1 && node !== document.body; i++) {
      var seg = node.tagName.toLowerCase();
      if (typeof node.className === 'string' && node.className.trim()) {
        var cls = node.className.trim().split(/\s+/).filter(Boolean).slice(0, 2);
        if (cls.length) seg += '.' + cls.map(function (c) { return CSS.escape(c); }).join('.');
      }
      var parent = node.parentElement;
      if (parent) {
        var siblings = Array.prototype.filter.call(parent.children, function (c) { return c.tagName === node.tagName; });
        if (siblings.length > 1) seg += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')';
      }
      path.unshift(seg);
      node = parent;
    }
    return path.join(' > ');
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
  window.addEventListener('click', function (e) {
    window.__aftRecordEvent({ type: 'click', x: e.clientX, y: e.clientY, scrollX: window.scrollX, scrollY: window.scrollY, selector: describeSelector(e.target) });
  }, true);

  window.addEventListener('change', function (e) {
    var t = e.target;
    var textLike = t && (t.tagName === 'TEXTAREA' ||
      (t.tagName === 'INPUT' && ['text', 'tel', 'email', 'search', 'password', 'number', ''].indexOf((t.type || '').toLowerCase()) !== -1));
    if (textLike) {
      window.__aftRecordEvent({ type: 'input', value: t.value, selector: describeSelector(t) });
    }
  }, true);

  window.addEventListener('keydown', function (e) {
    if (e.key === 'Tab') window.__aftRecordEvent({ type: 'tab' });
  }, true);
})();
"""

# "🎯 좌표 인식기" - 좌표(coord) 모드 단계를 만들 때 실제 화면 어디가
# x, y인지 눈으로 바로 확인하고 싶다는 요청으로 추가했다. 녹화 스크립트와
# 달리 이건 main_page에만, 켜고 끌 때 딱 한 번씩만 주입하면 되는
# 일회성 evaluate라 add_init_script로 항상 심어둘 필요는 없다.
_COORD_TRACKER_START_JS = r"""
(function () {
  if (window.__aftCoordTracker) return;
  var badge = document.createElement('div');
  badge.id = '__aftCoordBadge';
  badge.style.cssText = 'position:fixed;top:8px;left:8px;background:rgba(0,0,0,0.78);' +
    'color:#5fd08a;font:bold 13px monospace;padding:5px 10px;border-radius:7px;' +
    'z-index:2147483647;pointer-events:none;';
  badge.textContent = 'x: -, y: -';
  document.body.appendChild(badge);
  function onMove(e) { badge.textContent = 'x: ' + e.clientX + ', y: ' + e.clientY; }
  document.addEventListener('mousemove', onMove, true);
  window.__aftCoordTracker = { badge: badge, onMove: onMove };
})();
"""

_COORD_TRACKER_STOP_JS = r"""
(function () {
  if (!window.__aftCoordTracker) return;
  document.removeEventListener('mousemove', window.__aftCoordTracker.onMove, true);
  window.__aftCoordTracker.badge.remove();
  delete window.__aftCoordTracker;
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
<script>
function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
function describeClick(c) {
  if (c.mode === 'tab') return 'Tab ' + c.tabCount + '회 이동';
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
  document.getElementById('undoBtn').disabled = !hasSteps || replaying;
  document.getElementById('saveBtn').disabled = !hasSteps || replaying;
  document.getElementById('clearBtn').disabled = !named || replaying;

  const trackerBtn = document.getElementById('coordTrackerBtn');
  trackerBtn.textContent = data.coordTracker ? '⏹ 좌표 인식기 중지' : '🎯 좌표 인식기';
  trackerBtn.className = data.coordTracker ? 'btn-rec-active' : 'btn-ghost';
  trackerBtn.disabled = replaying;

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

function renderSteps(data) {
  const wrap = document.getElementById('list');
  const steps = data.steps || [];
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
    return '<div class="step' + (isCurrent ? ' current' : '') + '"><div class="num">' + (i + 1) + '</div><div class="body">' +
      '<div class="label">' + esc(s.label) + '</div>' + inputsHtml +
      '<div class="target">' + esc(describeClick(s.click)) + '</div>' + statusHtml + '</div></div>';
  }).join('');
}

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

    def _maybe_apply_pending_popup(self):
        if self.pending_popup and self.steps:
            self.pending_popup = False
            last = self.steps[-1]
            if not last['opensPopup']:
                last['opensPopup'] = True
                last['label'] = self._label_for(last)
                self.on_change()

    def _label_for(self, step):
        base = ('입력 {}개 → 클릭'.format(len(step['inputs'])) if step['inputs'] else '클릭')
        if step['context'] == 'popup':
            base = '(팝업) ' + base
        if step['opensPopup']:
            base += ' · 새 창 열림'
        return base

    def _pick_main_mode(self, selector):
        # id나 name처럼 비교적 안정적인 선택자만 "선택자 우선"으로 쓰고,
        # 그 외(자동 추정한 nth-of-type 경로)는 좌표를 기본으로 삼는다.
        if selector and (selector.startswith('#') or '[name=' in selector):
            return 'selector'
        return 'coord'

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
            # 그런데 그 blur를 일으킨 Tab 키 입력의 기본 동작(포커스 이동)이
            # change 발화보다 먼저 끝나 있으므로, change가 뜨는 시점엔
            # 이미 포커스가 "다음" 필드로 넘어가 있다. 즉 방금 센 Tab
            # 카운트의 마지막 1회는 이 필드에 "도달"한 것과 무관하고
            # 다음 필드를 향한 첫 이동이다 - 그걸 그대로 이 필드의
            # tabCount로 쓰면 재생 시 한 칸씩 밀려서 엉뚱한 필드에
            # 값이 들어간다(실제로 겪음). 그래서 이 필드용 tabCount는
            # (지금까지 센 값 - 1)로 기록하고, 방금 뺀 1회는 다음
            # 필드 카운트의 시작값으로 넘긴다.
            is_tab_mode = (role == 'popup')
            if is_tab_mode:
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
            self.current_inputs.append(entry)
            self.tab_counter = carry
            print('  · 입력 감지: {!r}'.format(entry['value']), flush=True)
            return

        if kind == 'click':
            selector = payload.get('selector') or ''
            mode = 'tab' if role == 'popup' else self._pick_main_mode(selector)
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
            self.seed += 1
            step = {
                'id': self.seed,
                'label': '',
                'context': role,
                'inputs': self.current_inputs,
                'click': click,
                # 이 클릭이 실제로 팝업을 띄웠는지는 아직 모른다 - 다음
                # 이벤트가 들어올 때 _maybe_apply_pending_popup이 이
                # 자리를 True로 고쳐 쓴다.
                'opensPopup': False,
                'sleep': 300,
                'manual': False,
            }
            step['label'] = self._label_for(step)
            self.steps.append(step)
            self.current_inputs = []
            self.tab_counter = 0
            print('  · [{}단계 기록] {} · {}'.format(len(self.steps), step['label'], self._describe_click(click)), flush=True)
            self.on_change()
            return

    def _describe_click(self, click):
        if click['mode'] == 'tab':
            return 'Tab {}회 이동'.format(click['tabCount'])
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

    def __init__(self, state_path):
        self.recorder = Recorder()
        self.recorder.on_change = self._write_state
        self.state_path = state_path
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

    def _write_state(self):
        data = {
            'mode': self.mode,
            'name': self.name,
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
        os.replace(tmp, self.state_path)

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

    def save(self, url):
        # 저장은 "지금까지를 파일에 남긴다"는 뜻일 뿐, 녹화 중이든
        # 멈춰 있든 언제든 부를 수 있다 - 녹화를 멈추는 건 stop()의 몫.
        if not self.out_path:
            return False
        data = self.recorder.to_json(url)
        tmp = self.out_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.out_path)
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


def _prepare_replay(session, main_page, context, url, kind):
    """"▶ 테스트 재생"을 누른 시점에 한 번만 하는 준비 작업 - 이전
    재생이 남긴 팝업 정리, 페이지를 새로 불러오기(run.py의 실전 실행과
    똑같이 매번 깨끗한 상태에서 시작), engine.py의 Runner 생성. 이
    Runner를 Session에 보관해 두어야 "한 단계씩" 모드에서 여러 번의
    /replay-next 요청에 걸쳐 같은 실행 상태(팝업 전환으로 바뀐
    self.page 등)를 이어갈 수 있다."""
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

    main_page.goto(url)
    session.replay_steps = steps
    session.replay_runner = Runner({'steps': steps}, main_page, context)
    session.replay_index = -1


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
    _prepare_replay(session, main_page, context, url, 'auto')
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
    _prepare_replay(session, main_page, context, url, 'step')
    _execute_replay_step(session)


def run_replay_step_next(session):
    if session.mode != 'replaying' or session.replay_runner is None:
        return
    _execute_replay_step(session)


def _start_control_server(viewer_dir, session, url):
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

        def do_POST(self):
            body = self._read_body()

            if self.path == '/start':
                ok = session.start(body.get('name') or '')
                return self._reply(200 if ok else 400, {'ok': ok})

            if self.path == '/save':
                ok = session.save(url)
                return self._reply(200 if ok else 400, {'ok': ok})

            if self.path == '/stop':
                session.stop()
                return self._reply(200, {'ok': True})

            if self.path == '/undo':
                session.recorder.undo()
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
    session = Session(state_path)
    server = _start_control_server(viewer_dir, session, args.url)
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
            if kind == 'auto':
                run_replay_auto(session, main_page, record_context, args.url, cmd.get('delayMs') or 300)
            elif kind == 'step-start':
                run_replay_step_start(session, main_page, record_context, args.url)
            elif kind == 'step-next':
                run_replay_step_next(session)
            elif kind == 'coord-tracker-start':
                try:
                    main_page.evaluate(_COORD_TRACKER_START_JS)
                except Exception:
                    pass  # 페이지 전환 중 등 - 다음에 다시 켜면 된다
            elif kind == 'coord-tracker-stop':
                try:
                    main_page.evaluate(_COORD_TRACKER_STOP_JS)
                except Exception:
                    pass

        # 아직 저장 안 한 녹화 중 상태로 종료하는 경우를 대비해 마지막으로
        # 한 번 더 저장해 둔다(이름이 정해져 있을 때만).
        if session.out_path and session.recorder.steps:
            session.save(args.url)

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
