"""
실제 사이트 응답을 fixture 파일로 저장한다. Phase A 하네스의 입구다.

규칙(CLAUDE.md 1): 파싱 코드를 고치기 전에 그 변형의 fixture 를 먼저 확보한다.
fixture 없이 파서를 손대면 무엇을 고쳤고 무엇을 깼는지 알 수 없다.

원본 HTML 을 그대로 저장한다. 마크다운 변환이나 정리를 하지 않는다.
정리하는 순간 그건 실제 응답이 아니게 되고 회귀를 못 잡는다.

사용법:
  # 이름과 URL 을 직접 지정
  python src/scripts/capture_fixture.py --name sunsang24/redhunter_20260905 \
      --url https://redhunter.sunsang24.com/ship/schedule_fleet/202609 --date 2026-09-05

  # 등록된 배 이름으로 (라이브 API 에서 URL 을 찾아온다)
  python src/scripts/capture_fixture.py --boat 팀에프호 --date 2026-09-05

  # PARSE_FAIL 로 진단된 배들을 한 번에
  python src/scripts/capture_fixture.py --known-failures --date 2026-09-05
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # -> src/
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import requests  # noqa: E402

from services.reservation_checker import _headers_for, build_query_url  # noqa: E402

REPO_ROOT = os.path.dirname(BASE_DIR)
FIXTURE_ROOT = os.path.join(REPO_ROOT, 'tests', 'fixtures')
LIVE_SHIPS_API = 'https://aft-hcwf.onrender.com/api/ships'

#: probe_boats.py 가 PARSE_FAIL / EMPTY_RESPONSE 로 짚은 배들.
#: Phase A 의 1순위 표적이라 이름을 코드에 남겨둔다.
KNOWN_FAILURES = ['팀에프호', '라온피싱', '나폴리호', '남해여울호']

#: 정상 동작을 대조하기 위한 표본. 이게 있어야 '고친 것'과 '깬 것'을 가른다.
CONTROL_SAMPLES = ['레드헌터', '칸피싱(KHAN)']


def platform_dir(url: str) -> str:
    host = (urlparse(url).netloc or '').lower()
    if 'sunsang24.com' in host:
        return 'sunsang24'
    if 'thefishing.kr' in host:
        return 'thefishing'
    return 'independent'


def load_live_boats() -> dict:
    resp = requests.get(LIVE_SHIPS_API, timeout=180)
    resp.raise_for_status()
    return {s['name']: s['url'] for s in resp.json()}


def capture(name: str, url: str, target_date: str) -> str:
    """URL 을 받아 fixture html 과 meta json 을 저장하고 저장 경로를 돌려준다."""
    year, month, day = (int(part) for part in target_date.split('-'))
    final_url = build_query_url(url, year, month, day)

    resp = requests.get(final_url, headers=_headers_for(final_url), timeout=20)

    path = os.path.join(FIXTURE_ROOT, f'{name}.html')
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # 원본 그대로. 인코딩만 utf-8 로 통일한다.
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(resp.text)

    # 파서에 필요한 문맥(어느 날짜를 물어본 응답인가)을 함께 남긴다.
    # 이게 없으면 나중에 이 파일이 무엇인지 알 수 없다.
    meta = {
        'source_url': url,
        'requested_url': final_url,
        'target_date': target_date,
        'http_status': resp.status_code,
        'captured_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'bytes': len(resp.text),
    }
    with open(os.path.join(FIXTURE_ROOT, f'{name}.meta.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(f'  저장 {path}  ({len(resp.text):,}바이트, HTTP {resp.status_code})')
    return path


def slug(text: str) -> str:
    keep = [ch if (ch.isalnum() or ch in '-_') else '_' for ch in text]
    return ''.join(keep).strip('_')


def main() -> int:
    default_date = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', help='fixture 이름 (예: sunsang24/redhunter_20260905)')
    ap.add_argument('--url', help='원본 URL')
    ap.add_argument('--boat', help='등록된 배 이름 (URL 을 라이브에서 찾아온다)')
    ap.add_argument('--known-failures', action='store_true',
                    help='진단에서 실패로 짚힌 배 + 대조군을 한 번에 캡처')
    ap.add_argument('--date', default=default_date, help='조회 날짜 YYYY-MM-DD')
    ap.add_argument('--delay', type=float, default=1.0)
    args = ap.parse_args()

    datestamp = args.date.replace('-', '')

    if args.name and args.url:
        capture(args.name, args.url, args.date)
        return 0

    boats = load_live_boats()

    if args.boat:
        targets = [args.boat]
    elif args.known_failures:
        targets = KNOWN_FAILURES + CONTROL_SAMPLES
    else:
        ap.error('--name/--url, --boat, --known-failures 중 하나가 필요하다')

    print(f'조회 날짜 {args.date} / 대상 {len(targets)}건')
    for index, boat_name in enumerate(targets, 1):
        url = boats.get(boat_name)
        if not url:
            print(f'[{index}/{len(targets)}] {boat_name}: 등록된 배가 아니다 - 건너뜀')
            continue
        name = f'{platform_dir(url)}/{slug(boat_name)}_{datestamp}'
        print(f'[{index}/{len(targets)}] {boat_name}')
        try:
            capture(name, url, args.date)
        except Exception as exc:
            print(f'  실패: {type(exc).__name__}: {exc}')
        if index < len(targets) and args.delay > 0:
            time.sleep(args.delay)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
