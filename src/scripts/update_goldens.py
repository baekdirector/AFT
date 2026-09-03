"""
fixture 의 골든 파일(*.expected.json)을 현재 파서 출력으로 갱신한다.

골든은 사람이 눈으로 확인하고 커밋하는 파일이다(PLAN.md 3.3). 이 도구는 손으로
JSON 을 쓰는 수고를 덜어줄 뿐이고, 나온 값이 옳은지 판단하는 것은 사람 몫이다.

갱신하기 전에 반드시 diff 를 본다. 파서를 고쳐서 좋아진 것인지, 사이트가 바뀌어
나빠진 것인지는 값을 봐야만 알 수 있다.

사용법:
  python src/scripts/update_goldens.py --dry-run     # 무엇이 달라지는지만 본다
  python src/scripts/update_goldens.py               # 전부 갱신
  python src/scripts/update_goldens.py --only 팀에프  # 이름에 포함된 것만
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # -> src/
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

REPO_ROOT = Path(BASE_DIR).parent
FIXTURE_ROOT = REPO_ROOT / 'tests' / 'fixtures'

from services import reservation_checker  # noqa: E402


class FixtureResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


def parse(name: str) -> dict:
    html = io.open(FIXTURE_ROOT / f'{name}.html', encoding='utf-8').read()
    meta = json.loads(io.open(FIXTURE_ROOT / f'{name}.meta.json', encoding='utf-8').read())

    original_get = reservation_checker.requests.get
    reservation_checker.requests.get = lambda *a, **kw: FixtureResponse(html)
    reservation_checker.clear_cache()
    try:
        year, month, day = (int(p) for p in meta['target_date'].split('-'))
        result = reservation_checker.check_single_boat(meta['source_url'], year, month, day)
    finally:
        reservation_checker.requests.get = original_get

    return {
        'entries': [
            {
                'ship_name': e.get('ship_name'),
                'status': e.get('status'),
                'available': e.get('available'),
                'display_status': e.get('display_status'),
                'fish': e.get('fish'),
            }
            for e in (result.get('entries') or [])
        ],
        'tide': result.get('tide'),
        'error': result.get('error'),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true', help='쓰지 않고 차이만 보여준다')
    ap.add_argument('--only', help='이름에 이 문자열이 들어간 fixture 만')
    args = ap.parse_args()

    names = sorted(
        p.relative_to(FIXTURE_ROOT).as_posix()[:-len('.html')]
        for p in FIXTURE_ROOT.rglob('*.html')
        if p.with_suffix('.meta.json').exists()
    )
    if args.only:
        names = [n for n in names if args.only in n]

    changed = 0
    for name in names:
        actual = parse(name)
        golden_path = FIXTURE_ROOT / f'{name}.expected.json'
        old = None
        if golden_path.exists():
            old = json.loads(io.open(golden_path, encoding='utf-8').read())

        state = '신규' if old is None else ('동일' if old == actual else '변경')
        ships = [e['ship_name'] for e in actual['entries']]
        print(f'[{state}] {name}  ({len(actual["entries"])}척) {ships}')

        if state == '변경':
            before = [e['ship_name'] for e in old['entries']]
            print(f'         이전: ({len(old["entries"])}척) {before}')

        if state != '동일':
            changed += 1
            if not args.dry_run:
                with io.open(golden_path, 'w', encoding='utf-8') as fh:
                    json.dump(actual, fh, ensure_ascii=False, indent=2)
                    fh.write('\n')

    verb = '변경될' if args.dry_run else '갱신한'
    print(f'\n{verb} 골든: {changed}건 / 전체 {len(names)}건')
    if args.dry_run and changed:
        print('실제로 쓰려면 --dry-run 없이 다시 실행한다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
