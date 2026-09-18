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
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

# Windows 콘솔 기본 코드페이지(cp949)로는 이모지·일부 한글 조합을 출력하다가
# UnicodeEncodeError로 죽는 경우가 있다(AFT 개발 중에도 겪은 문제) - 사용자
# PC 터미널 환경과 무관하게 항상 UTF-8로 출력하도록 강제한다.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright

from engine import Runner


def resolve_url(url, config_path):
    """'local:mock_list.html'처럼 config 파일 기준 상대 경로를 file://
    URI로 바꾼다 - fixtures/로 로컬 연습 실행을 할 때만 쓰는 표기법이고,
    실제 사용(https://...)에는 영향 없다."""
    if url.startswith('local:'):
        rel = url[len('local:'):]
        base_dir = os.path.dirname(os.path.abspath(config_path))
        return 'file://' + os.path.join(base_dir, rel).replace('\\', '/')
    return url


def compute_target(config):
    """실행 시작 시각을 계산한다. timeMode가 'relative'면 지금부터
    delaySec초 뒤(테스트용), 'absolute'면 date + startClock(KST, 이 PC
    시간대가 한국시간이라고 가정) - leadMs(서버 시간 보정)."""
    if config.get('timeMode') == 'relative':
        delay = float(config.get('delaySec') or 1)
        return datetime.now() + timedelta(seconds=delay)

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
    args = parser.parse_args()

    with open(args.config, encoding='utf-8') as f:
        config = json.load(f)

    target = compute_target(config)
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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport=viewport)
        page = context.new_page()
        page.goto(resolve_url(config['url'], args.config))

        runner = Runner(config, page, context, stepwise=args.stepwise)
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
