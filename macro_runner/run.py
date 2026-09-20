# -*- coding: utf-8 -*-
"""자동예약 매크로 로컬 실행 엔진의 진입점.

/macro 화면(https://aft-hcwf.onrender.com/macro)에서 "⬇ 내보내기(JSON)"로
받은 설정 파일을 이 PC에서 직접 실행한다 - 마지막 "예약하기" 단계는
기본적으로 사람이 눈앞의 브라우저 창을 보고 직접 눌러야 하고, 실제
예약 사이트가 클라우드 IP를 막았던 전례가 있어(AFT 스크래핑 쪽에서
실측) 이 도구는 서버가 아니라 사용자 PC에서만 돌리도록 설계됐다.

사용법:
    pip install -r requirements.txt
    playwright install chromium
    python run.py --config aft_macro_config.json
    python run.py --config aft_macro_config.json --stepwise   # 한 단계씩 확인하며 실행

record.py로 직접 녹화한 파일(aft_macro_recording.json)도 /macro 웹
페이지를 거치지 않고 바로 실행할 수 있다 - 녹화 중 팝업에 실제로 입력한
이름·전화번호 등은 이미 그 값 그대로 기록돼 있으므로 별도로 채워
넣을 필요가 없다. 다만 "언제 시작할지"는 화면 조작만으로는 알 수
없으므로 --at/--now로 직접 지정한다:
    python run.py --config aft_macro_recording.json --at 17:00:00
    python run.py --config aft_macro_recording.json --now   # 지금 즉시(테스트용)
"""
import argparse
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# Windows 콘솔 기본 코드페이지(cp949)로는 이모지·일부 한글 조합을 출력하다가
# UnicodeEncodeError로 죽는 경우가 있다(AFT 개발 중에도 겪은 문제) - 사용자
# PC 터미널 환경과 무관하게 항상 UTF-8로 출력하도록 강제한다.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright

from engine import Runner
from winutil import position_window, LEFT_BOUNDS, RIGHT_BOUNDS

# record.py의 단계 표시 창과 같은 방식(정적 페이지가 상태 파일을
# fetch로 폴링) - 실행 중 어느 단계인지, 성공/실패했는지를 오른쪽 창에
# 실시간으로 보여준다. 실제로 팝업이 안 뜨는 실패가 나서 "몇 번째
# 단계인지조차 알 수 없다"는 문제를 겪은 뒤 추가했다.
_PROGRESS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>매크로 실행 - 진행 상황</title>
<style>
  body{font-family:-apple-system,"Malgun Gothic",sans-serif;margin:0;background:#1c1f26;color:#eee;padding:14px;}
  h1{font-size:14px;margin:0 0 10px;color:#9fc4ff;}
  .step{display:flex;gap:8px;background:#262b35;border-radius:8px;padding:9px 11px;margin-bottom:7px;border-left:3px solid transparent;}
  .step.current{border-left-color:#4f9bff;background:#2b3245;}
  .num{flex:none;width:20px;height:20px;border-radius:50%;background:#3b7ddd;color:#fff;
       font-size:11px;font-weight:bold;display:flex;align-items:center;justify-content:center;}
  .label{font-size:12.5px;font-weight:bold;}
  .target{font-size:11px;color:#9fb0c8;margin-top:3px;font-family:monospace;}
  .status{font-size:10.5px;font-weight:bold;margin-top:4px;}
  .status.done{color:#5fd08a;} .status.running{color:#4f9bff;} .status.waiting{color:#77808f;} .status.error{color:#e2554f;}
  .empty{color:#888;font-size:12px;}
</style></head>
<body>
  <h1 id="title">실행 준비 중...</h1>
  <div id="list" class="empty">단계 정보를 불러오는 중입니다.</div>
<script>
function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
function statusClass(st) {
  if (st === '완료') return 'done';
  if (st === '진행') return 'running';
  if (st.indexOf('오류') === 0) return 'error';
  return 'waiting';
}
async function refresh() {
  try {
    const res = await fetch('progress.json?_=' + Date.now(), { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    document.getElementById('title').textContent = '실행 중 · ' + (data.current + 1) + ' / ' + data.total + '단계';
    document.getElementById('list').className = '';
    document.getElementById('list').innerHTML = data.steps.map(function (s, i) {
      return '<div class="step' + (i === data.current ? ' current' : '') + '">' +
        '<div class="num">' + (i + 1) + '</div><div class="body">' +
        '<div class="label">' + esc(s.label) + '</div>' +
        '<div class="target">' + esc(s.target) + '</div>' +
        '<div class="status ' + statusClass(s.status) + '">' + esc(s.status) + '</div>' +
        '</div></div>';
    }).join('');
  } catch (e) { /* 서버가 아직 안 떠 있을 수도 있음 - 다음 폴링에 재시도 */ }
}
setInterval(refresh, 300);
refresh();
</script>
</body></html>
"""


def _start_progress_server(viewer_dir):
    with open(os.path.join(viewer_dir, 'viewer.html'), 'w', encoding='utf-8') as f:
        f.write(_PROGRESS_HTML)

    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=viewer_dir, **kw)

        def log_message(self, fmt, *args):
            pass  # 폴링 요청 로그로 터미널이 도배되는 걸 막는다

    server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def resolve_url(url, config_path):
    """'local:mock_list.html'처럼 config 파일 기준 상대 경로를 file://
    URI로 바꾼다 - fixtures/로 로컬 연습 실행을 할 때만 쓰는 표기법이고,
    실제 사용(https://...)에는 영향 없다."""
    if url.startswith('local:'):
        rel = url[len('local:'):]
        base_dir = os.path.dirname(os.path.abspath(config_path))
        return 'file://' + os.path.join(base_dir, rel).replace('\\', '/')
    return url


def compute_target(config, at=None, now=False):
    """실행 시작 시각을 계산한다.

    --now/--at은 config의 실행 시각 필드보다 항상 우선한다 -
    record.py가 그대로 만든 원본 녹화 JSON(/macro를 거치지 않은)에는
    timeMode/date/startClock이 아예 없으므로, 이 두 옵션으로 명령줄에서
    바로 실행 시각을 정할 수 있어야 한다.

    config 자체에 실행 시각 정보가 있으면(timeMode가 'relative'거나,
    /macro에서 내려받은 것처럼 date/startClock이 있으면) 그걸 쓴다.
    반대로 그런 필드가 전혀 없으면(record.py 원본 그대로) "오늘 17시"
    같은 걸 마음대로 가정하지 않고 지금 이 명령을 실행한 시점을 그대로
    실행 시각으로 삼는다 - 예전엔 기본값을 17:00:00으로 가정해서,
    이미 지난 시각이면 하루를 꼬박 기다리는 것처럼 보이는 문제가
    있었다(실제로 겪음 - "브라우저가 안 뜬다"고 오해했지만 사실은
    다음날 17시까지 정상적으로 대기 중이었다)."""
    if now:
        return datetime.now()
    if at:
        at = at.strip()
        if ' ' not in at:
            at = datetime.now().strftime('%Y-%m-%d') + ' ' + at
        return datetime.strptime(at, '%Y-%m-%d %H:%M:%S')

    if config.get('timeMode') == 'relative':
        delay = float(config.get('delaySec') or 1)
        return datetime.now() + timedelta(seconds=delay)

    if not config.get('date') and not config.get('startClock'):
        return datetime.now()

    date_str = config.get('date') or datetime.now().strftime('%Y-%m-%d')
    time_str = config.get('startClock') or '17:00:00'
    target = datetime.strptime('{} {}'.format(date_str, time_str), '%Y-%m-%d %H:%M:%S')
    lead_ms = int(config.get('leadMs') or 0)
    return target - timedelta(milliseconds=lead_ms)


def wait_until(target):
    """목표 시각까지 대기한다. 초 단위 예약 경쟁이 걸릴 수 있어 마지막
    200ms는 time.sleep 대신 바쁜 대기로 정밀도를 높인다(OS 스케줄링
    지연으로 수십~수백 ms 밀리는 걸 피하기 위함)."""
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return
        if remaining > 0.2:
            time.sleep(min(1.0, remaining - 0.2))
        else:
            pass  # 마지막 200ms는 바쁜 대기


def main():
    parser = argparse.ArgumentParser(description='AFT 자동예약 매크로 로컬 실행 엔진')
    parser.add_argument('--config', required=True, help='/macro에서 내려받은 설정 JSON 파일 경로')
    parser.add_argument('--stepwise', action='store_true',
                         help='각 단계 실행 전에 무엇을 할지 보여주고 Enter로 승인받은 뒤 실행한다')
    parser.add_argument('--at', help='실행 시작 시각. "17:00:00"(오늘) 또는 "2026-09-23 17:00:00" - config의 실행 시각 필드보다 우선한다')
    parser.add_argument('--now', action='store_true', help='대기 없이 즉시 실행한다(테스트/즉석 실행용) - --at보다 우선한다')
    args = parser.parse_args()

    with open(args.config, encoding='utf-8') as f:
        config = json.load(f)

    target = compute_target(config, at=args.at, now=args.now)
    print('{} 에 시작합니다. 대기 중...'.format(target.isoformat(sep=' ', timespec='seconds')))
    wait_until(target)
    print('시작!')

    # recWidth/recHeight는 /macro의 레코딩 캔버스와 정확히 같은 크기다 -
    # 좌표(coord) 단계가 기록 시점과 다른 창 크기에서 재생되면 어긋나므로,
    # 실행 브라우저를 반드시 이 크기로 강제한다.
    viewport = {
        'width': int(config.get('recWidth') or 1280),
        'height': int(config.get('recHeight') or 800),
    }

    viewer_dir = tempfile.mkdtemp(prefix='aft_macro_run_')
    progress_path = os.path.join(viewer_dir, 'progress.json')
    server = _start_progress_server(viewer_dir)
    port = server.server_address[1]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport=viewport)
        page = context.new_page()
        page.goto(resolve_url(config['url'], args.config))
        position_window(page, **LEFT_BOUNDS)

        # 오른쪽 진행 상황 창 - record.py의 단계 표시 창과 같은 자리에
        # 같은 크기로 뜬다.
        viewer_context = browser.new_context(viewport={'width': 560, 'height': 1000})
        viewer_page = viewer_context.new_page()
        viewer_page.goto('http://127.0.0.1:{}/viewer.html'.format(port))
        position_window(viewer_page, **RIGHT_BOUNDS)

        runner = Runner(config, page, context, stepwise=args.stepwise, progress_path=progress_path)
        runner.run()

        print('\n모든 단계를 마쳤습니다(마지막 단계가 수동이었다면 이미 처리하셨을 것입니다).')
        input('Enter를 누르면 브라우저를 닫습니다 ↵ ')
        browser.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl+C로 중단 - 실제 브라우저에서 이미 일어난 클릭/입력은 되돌릴
        # 수 없으므로(부작용), 여기서는 트레이스백 대신 안내만 하고 조용히
        # 종료한다. 열려 있던 브라우저 창은 사용자가 직접 닫으면 된다.
        print('\n\n중단했습니다. 열려 있던 브라우저 창은 직접 닫아 주세요.')
        sys.exit(1)
