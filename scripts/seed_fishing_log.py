"""낚시 기록 엑셀을 DB 초기값으로 한 번 옮기는 로컬 스크립트.

    python scripts/seed_fishing_log.py <엑셀경로>              # 미리보기(DB 안 건드림)
    python scripts/seed_fishing_log.py <엑셀경로> --commit     # 실제 이관

운영 DB에 넣을 때는 DATABASE_URL 을 Neon 연결 문자열로 지정하고 실행한다.
새 테이블 4개가 비어 있을 때만 넣는다. 엑셀·보정표(--ship-map)는 개인
기록이라 커밋하지 않는다 - spec: docs/superpowers/specs/
2026-09-30-fishing-log-data-model-design.md §3.
"""
import argparse
import json
import os
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, 'src')
for path in (BASE_DIR, SRC_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from openpyxl import load_workbook  # noqa: E402

from services.fishing_log.excel_seed import parse_workbook  # noqa: E402
from services.fishing_log.seed_runner import SeedRefused, commit_seed, format_report  # noqa: E402


def _args(argv):
    parser = argparse.ArgumentParser(description='낚시 기록 엑셀 → DB 초기 이관')
    parser.add_argument('path', help='엑셀 파일 경로')
    parser.add_argument('--commit', action='store_true', help='실제로 DB에 넣는다(없으면 미리보기)')
    parser.add_argument('--ship-map', help='{"원문": "선사명"} JSON 보정표 경로')
    parser.add_argument('--allow-sqlite', action='store_true',
                        help='Postgres 가 아닌 DB(로컬 SQLite)에 넣는 것을 허용')
    parser.add_argument('--today', help='예정/완료 판단 기준일 YYYY-MM-DD (기본: 오늘)')
    return parser.parse_args(argv)


def main(argv=None, app=None, out=None):
    out = out or sys.stdout
    args = _args(argv)
    ship_map = None
    if args.ship_map:
        with open(args.ship_map, encoding='utf-8') as fh:
            ship_map = json.load(fh)
    today = date.fromisoformat(args.today) if args.today else date.today()

    result = parse_workbook(load_workbook(args.path, data_only=True), today, ship_map)
    print(format_report(result), file=out)

    if not args.commit:
        print('\n미리보기만 했습니다. 실제로 넣으려면 --commit 을 붙여 다시 실행하세요.', file=out)
        return 0

    if app is None:
        from src.app import create_app
        app = create_app()
    # DATABASE_URL 이 빠지면 create_app() 이 조용히 로컬 SQLite 를 쓴다 - 어디에
    # 넣는지 보여주고, 운영(Postgres)이 아니면 명시적으로 허용했을 때만 넣는다.
    from sqlalchemy.engine import make_url
    target = make_url(app.config['SQLALCHEMY_DATABASE_URI'])
    print(f'\n대상 DB: {target.render_as_string(hide_password=True)}', file=out)
    if target.get_backend_name() != 'postgresql' and not args.allow_sqlite:
        print('운영(Postgres) DB가 아니라 넣지 않았습니다. DATABASE_URL 을 확인하거나, '
              '로컬에 넣으려면 --allow-sqlite 를 붙이세요.', file=out)
        return 1
    with app.app_context():
        try:
            counts = commit_seed(result)
        except SeedRefused as exc:
            print(f'\n{exc}', file=out)
            return 1
    print(f'\n이관 완료: {counts}', file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
