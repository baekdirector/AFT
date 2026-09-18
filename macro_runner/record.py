# -*- coding: utf-8 -*-
"""자동예약 매크로 - 실제 브라우저 조작 기반 녹화 도구.

지금까지 "레코딩"은 /macro 웹 페이지 안의 iframe에 좌표를 기록하는
방식이었는데, 기록 환경(iframe)과 재생 환경(macro_runner가 여는 실제
브라우저)의 화면 크기·상황이 달라서 좌표가 어긋나는 근본 문제가
있었다. 이 도구는 그 문제를 원천적으로 없앤다 - **녹화도 재생과 똑같이
Playwright로 연 실제 브라우저(뷰포트 1280x800)**를 사용자가 직접
조작하게 하고, 그 실제 조작(클릭·입력·Tab 이동)을 있는 그대로 기록한다.

핵심 규칙(사용자와 합의):
- 하나의 "이벤트"(=매크로 한 단계)는 **마우스 클릭으로 마감**된다.
  클릭 전에 있었던 입력들은 그 클릭이 마감하는 이벤트 안에 묶인다.
- 메인 창(대상 사이트 첫 화면)에서는 좌표/선택자 모두 신뢰할 수 있다
  (녹화·재생 둘 다 뷰포트가 1280x800으로 고정되므로). 반면 **팝업(새
  창)은 화면에 뜨는 위치가 매번 다를 수 있어 좌표를 못 쓴다** - 그래서
  팝업 안에서는 항상 Tab 이동 횟수로 기록한다(레드히어로 팝업에서
  이미 검증된 방식과 동일한 원리).

사용법:
    pip install -r requirements.txt
    playwright install chromium
    python record.py --url https://chf.sunsang24.com/ship/schedule_fleet

두 개의 실제 브라우저 창이 뜬다 - 왼쪽은 1280x800의 "녹화 대상" 창
(사용자가 직접 조작하는 진짜 브라우저), 오른쪽은 560x800의 "단계
표시" 창(지금까지 기록된 단계를 실시간으로 보여줌). 다 끝나면 단계
표시 창의 "⏹ 녹화 종료 · 저장" 버튼을 누르거나, 스크립트를 실행한
터미널에서 Enter를 누르면 저장된다.

구현 메모: 단계 표시 창은 Python(Playwright) 쪽에서 직접
`page.set_content(...)`를 불러 갱신하지 않는다 - 이벤트 콜백
(expose_binding)이 Playwright의 단일 디스패치 스레드에서 호출되는데,
그 안에서 또 다른 Playwright 호출(set_content 등)을 하면 같은
스레드가 자기 자신의 응답을 기다리며 멈춰버린다(실제로 겪음 - 처음엔
콜백 안에서 time.sleep을 했다가 멈췄고, set_content로 바꿔도 똑같이
멈췄다). 그래서 콜백 안에서는 순수 파이썬 상태만 바꾸고 파일에
쓰기만 하며, 단계 표시 창은 그 파일을 자기 스스로(브라우저 JS의
fetch) 주기적으로 읽어가게 한다 - Python 쪽에서 그 창에 대고
Playwright 호출을 전혀 하지 않으므로 안전하다."""
import argparse
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright

from winutil import position_window, LEFT_BOUNDS, RIGHT_BOUNDS

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

_VIEWER_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>매크로 녹화 - 단계 표시</title>
<style>
  body{font-family:-apple-system,"Malgun Gothic",sans-serif;margin:0;background:#1c1f26;color:#eee;padding:14px;}
  h1{font-size:14px;margin:0 0 10px;color:#9fc4ff;}
  .finishbar{display:flex;justify-content:flex-end;margin-bottom:10px;}
  .finishbtn{background:#e2554f;color:#fff;border:none;border-radius:8px;padding:9px 14px;font-size:12.5px;font-weight:bold;cursor:pointer;}
  .finishbtn:disabled{opacity:0.5;cursor:default;}
  .step{display:flex;gap:8px;background:#262b35;border-radius:8px;padding:9px 11px;margin-bottom:7px;}
  .num{flex:none;width:20px;height:20px;border-radius:50%;background:#3b7ddd;color:#fff;
       font-size:11px;font-weight:bold;display:flex;align-items:center;justify-content:center;}
  .label{font-size:12.5px;font-weight:bold;}
  .input-row{font-size:11px;color:#9fb0c8;margin-top:3px;}
  .target{font-size:11px;color:#7fd6a0;margin-top:3px;font-family:monospace;}
  .empty{color:#888;font-size:12px;}
</style></head>
<body>
  <div class="finishbar"><button type="button" class="finishbtn" id="finishBtn">⏹ 녹화 종료 · 저장</button></div>
  <h1 id="title">기록된 단계 (0개)</h1>
  <div id="list" class="empty">대상 창에서 클릭하면 여기 단계가 하나씩 쌓입니다.</div>
<script>
function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
function describeClick(c) {
  if (c.mode === 'tab') return 'Tab ' + c.tabCount + '회 이동';
  if (c.mode === 'coord') return '좌표 (' + c.x + ', ' + c.y + ')';
  return c.selector || '?';
}
async function refresh() {
  try {
    const res = await fetch('state.json?_=' + Date.now(), { cache: 'no-store' });
    const steps = await res.json();
    document.getElementById('title').textContent = '기록된 단계 (' + steps.length + '개)';
    const list = document.getElementById('list');
    if (!steps.length) {
      list.className = 'empty';
      list.textContent = '대상 창에서 클릭하면 여기 단계가 하나씩 쌓입니다.';
    } else {
      list.className = '';
      list.innerHTML = steps.map(function (s, i) {
        const inputsHtml = (s.inputs || []).map(function (inp) {
          return '<div class="input-row">입력: ' + esc(inp.value) + '</div>';
        }).join('');
        return '<div class="step"><div class="num">' + (i + 1) + '</div><div class="body">' +
          '<div class="label">' + esc(s.label) + '</div>' + inputsHtml +
          '<div class="target">' + esc(describeClick(s.click)) + '</div></div></div>';
      }).join('');
    }
  } catch (e) { /* 서버가 아직 안 떠 있을 수도 있음 - 다음 폴링에 재시도 */ }
}
document.getElementById('finishBtn').addEventListener('click', function () {
  this.disabled = true;
  this.textContent = '저장 중...';
  fetch('/finish', { method: 'POST' }).catch(function () {});
});
setInterval(refresh, 500);
refresh();
</script>
</body></html>
"""


class Recorder:
    """실제 브라우저 이벤트를 복합 단계로 조립한다. 이 클래스의 메서드는
    Playwright의 바인딩 콜백에서 호출되므로 **Playwright API를 절대
    호출하지 않는다** - 순수 파이썬 상태 변경 + 파일 쓰기만 한다."""

    def __init__(self, state_path):
        self.state_path = state_path
        self.page_roles = {}
        self.tab_counter = 0
        self.current_inputs = []
        self.steps = []
        self.seed = 0
        self.pending_popup = False
        self._write_state()

    def register_page(self, page, role):
        self.page_roles[page] = role

    def on_new_page(self, new_page):
        self.register_page(new_page, 'popup')
        self.pending_popup = True

    def _maybe_apply_pending_popup(self):
        if self.pending_popup and self.steps:
            self.pending_popup = False
            last = self.steps[-1]
            if not last['opensPopup']:
                last['opensPopup'] = True
                last['label'] = self._label_for(last)
                self._write_state()

    def _label_for(self, step):
        base = ('입력 {}개 → 클릭'.format(len(step['inputs'])) if step['inputs'] else '클릭')
        if step['context'] == 'popup':
            base = '(팝업) ' + base
        if step['opensPopup']:
            base += ' · 새 창 열림'
        return base

    def _pick_main_mode(self, selector):
        # id나 name처럼 비교적 안정적인 선택자만 "선택자 우선"으로 쓰고,
        # 그 외(자동 추정한 nth-of-type 경로)는 좌표를 기본으로 삼는다 -
        # 좌표는 어차피 녹화 뷰포트와 재생 뷰포트가 똑같이 1280x800이라
        # 안전하다.
        if selector and (selector.startswith('#') or '[name=' in selector):
            return 'selector'
        return 'coord'

    def handle_event(self, source, payload):
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
                # 같은 지점을 가리킨다 - 그렇지 않으면 재생 시점의
                # 스크롤 위치에 따라 엉뚱한 요소를 클릭한다.
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
            self._write_state()
            # 단계 표시 창이 안 보이는 상황(창이 겹쳐 가려짐 등)에서도
            # 최소한 터미널에서 "지금 이 클릭이 잡혔다"를 바로 확인할 수
            # 있어야 한다 - 실제로 사용자가 클릭을 여러 번 했는데도 0개
            # 단계로 저장된 사례가 있어(원인 특정 전) 매 클릭마다 실시간
            # 확인 가능하게 해 둔다.
            print('  · [{}단계 기록] {} · {}'.format(len(self.steps), step['label'], self._describe_click(click)), flush=True)
            return

    def _describe_click(self, click):
        if click['mode'] == 'tab':
            return 'Tab {}회 이동'.format(click['tabCount'])
        if click['mode'] == 'coord':
            return '좌표 ({}, {})'.format(click['x'], click['y'])
        return '선택자 {}'.format(click['selector'] or '?')

    def _write_state(self):
        # 단계 표시 창은 이 파일을 자기 스스로(fetch) 폴링한다 - Python
        # 쪽에서 그 창에 Playwright 호출을 하지 않는다(위 파일 docstring
        # 참고).
        tmp = self.state_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.steps, f, ensure_ascii=False)
        os.replace(tmp, self.state_path)

    def to_json(self, url):
        return {
            'url': url,
            'recWidth': 1280,
            'recHeight': 800,
            'steps': self.steps,
        }


def _start_viewer_server(viewer_dir, finish_event):
    with open(os.path.join(viewer_dir, 'viewer.html'), 'w', encoding='utf-8') as f:
        f.write(_VIEWER_HTML)

    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=viewer_dir, **kw)

        def log_message(self, fmt, *args):
            pass  # 폴링 요청 로그로 터미널이 도배되는 걸 막는다

        def do_POST(self):
            if self.path == '/finish':
                finish_event.set()
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main():
    parser = argparse.ArgumentParser(description='자동예약 매크로 - 실제 브라우저 조작 녹화 도구')
    parser.add_argument('--url', required=True, help='녹화를 시작할 선사 예약 페이지 URL')
    parser.add_argument('--out', default='aft_macro_recording.json', help='저장할 JSON 파일 경로')
    args = parser.parse_args()

    viewer_dir = tempfile.mkdtemp(prefix='aft_macro_record_')
    state_path = os.path.join(viewer_dir, 'state.json')
    finish_event = threading.Event()
    server = _start_viewer_server(viewer_dir, finish_event)
    port = server.server_address[1]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        # 녹화 대상 창 - 실제 사용자가 직접 조작한다(자동 조작 아님).
        record_context = browser.new_context(viewport={'width': 1280, 'height': 800})

        # 단계 표시 창 - 완전히 별도 컨텍스트라 녹화 스크립트가 안 심어진다
        # (여기서 클릭해도 기록되지 않음 - 이 창 자체가 기록 대상이 되면
        # 안 되므로).
        viewer_context = browser.new_context(viewport={'width': 560, 'height': 800})
        viewer_page = viewer_context.new_page()
        viewer_page.goto('http://127.0.0.1:{}/viewer.html'.format(port))
        position_window(viewer_page, **RIGHT_BOUNDS)

        recorder = Recorder(state_path)

        record_context.expose_binding('__aftRecordEvent', recorder.handle_event)
        record_context.add_init_script(_RECORDER_INIT_SCRIPT)

        main_page = record_context.new_page()
        recorder.register_page(main_page, 'main')
        record_context.on('page', recorder.on_new_page)

        main_page.goto(args.url)
        position_window(main_page, **LEFT_BOUNDS)

        print('녹화 중입니다 - 대상 창에서 직접 조작하세요.')
        print('다 끝났으면 단계 표시 창의 "⏹ 녹화 종료 · 저장" 버튼을 누르거나, 여기서 Enter를 누르세요 ↵ ')

        # 터미널의 input()이 메인 스레드를 통째로 막고 있는 동안에는
        # 실제로 사람이 클릭해도 그 이벤트가 콜백으로 즉시 넘어오지
        # 않고 한참 지연되는 현상이 실측됐다(Windows에서 재현 - Enter를
        # 누른 직후에야 그동안 쌓인 클릭들이 한꺼번에 처리됨). 그래서
        # input()으로 무작정 막는 대신, 실제 Playwright 동기 API 호출
        # (wait_for_timeout)을 짧은 간격으로 계속 불러 대기하면서 그
        # 사이사이 이벤트가 정상적으로 처리되게 한다. 터미널 Enter는
        # 별도 스레드에서 그대로 받아 같은 finish_event를 세팅한다
        # (기존처럼 터미널에서 바로 끝내고 싶은 사람도 그대로 쓸 수 있게).
        def _wait_for_enter():
            try:
                input()
            except EOFError:
                pass
            finish_event.set()
        threading.Thread(target=_wait_for_enter, daemon=True).start()

        while not finish_event.is_set():
            main_page.wait_for_timeout(200)

        data = recorder.to_json(args.url)
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print('{} 개 단계를 {} 에 저장했습니다.'.format(len(recorder.steps), args.out))

        browser.close()


if __name__ == '__main__':
    main()
