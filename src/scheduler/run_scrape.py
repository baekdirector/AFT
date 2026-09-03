"""
수집 -> 스냅샷 비교 -> 알림. Phase D. GitHub Actions cron 의 진입점이다.

이 파일이 웹 앱과 분리돼 있는 이유:
Render 무료 인스턴스는 15분 무활동 후 잠들고, 잠든 동안에는 아무것도 수집하지
못한다. 그래서 수집과 발송은 Actions 에서 돌리고, 웹은 같은 DB 를 보기만 한다.
웹이 잠들어 있어도 알림은 나간다.

전 선박을 훑지 않는다. 감시 등록된 (배, 날짜) 만 수집한다. 그래서 한 번 도는
비용이 감시 수에 비례하고, 사람당 5척 상한이 곧 부하 상한이다.

필요한 환경변수:
  DATABASE_URL       웹과 같은 DB (없으면 로컬 SQLite 라 아무 의미가 없다)
  VAPID_*            발송용. 없으면 수집만 하고 발송은 건너뛴다.

사용법:
  python src/scheduler/run_scrape.py
  python src/scheduler/run_scrape.py --dry-run     # 저장/발송 없이 수집만
"""
from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # -> src/
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 'app' 이라는 이름은 루트 app.py 와 겹친다. 루트 쪽에는 create_app 이 없고
# import 하는 것만으로 앱을 하나 만들어버리므로, 패키지 경로로 명시해서 읽는다.
# 모듈 수준에서 잡아야 테스트가 monkeypatch 로 갈아끼울 수 있다.
try:
    from src.app import create_app
except ImportError:                     # 스케줄러를 src/ 안에서 직접 실행할 때
    from app import create_app

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger('run_scrape')

#: 배 사이 요청 간격(초). 원본 사이트 배려 + 차단 회피.
DEFAULT_DELAY = float(os.environ.get('SCRAPE_DELAY_SECONDS', '1.0'))


def collect_one(boat, target_date: str, dry_run: bool):
    """배 한 척, 날짜 하나를 수집하고 전환 목록을 돌려준다.

    실패는 격리한다. 한 척이 터져도 나머지 수집은 계속돼야 한다.
    """
    from models import Boat  # noqa: F401  (관계 로딩용)
    from services.reservation_checker import check_single_boat
    from services.snapshot import entries_to_observations
    from services.snapshot_repository import apply_observations

    year, month, day = (int(part) for part in target_date.split('-'))
    info = check_single_boat(boat.url, year, month, day, known_ship_name=boat.name)
    entries = info.get('entries') or []

    if info.get('error'):
        # 조회 자체가 실패했다. 관측을 만들지 않는다 - 빈 관측을 저장하면
        # 마지막으로 알던 상태를 지우거나 가짜 전환을 만들어낸다.
        logger.warning('  수집 실패 %s %s: %s', boat.name, target_date, info['error'])
        return []

    observations = entries_to_observations(boat.id, target_date, entries)
    if dry_run:
        logger.info('  [dry-run] %s %s: 관측 %d건', boat.name, target_date, len(observations))
        return []

    return apply_observations(boat.id, target_date, observations)


def run(dry_run: bool = False, delay: float = DEFAULT_DELAY) -> dict:
    """한 번 돈다. 집계를 돌려준다."""
    from models import Boat
    from services.notify import webpush
    from services.notify.dispatcher import dispatch_all
    from services.watch_service import active_watch_targets, deactivate_past_watches

    app = create_app()
    summary = {'targets': 0, 'collected': 0, 'failed': 0,
               'transitions': 0, 'sent': 0, 'expired_watches': 0}

    with app.app_context():
        today = datetime.date.today().isoformat()
        summary['expired_watches'] = deactivate_past_watches(today)
        if summary['expired_watches']:
            logger.info('지난 날짜 감시 %d건을 껐다', summary['expired_watches'])

        targets = active_watch_targets()
        summary['targets'] = len(targets)

        if not targets:
            logger.info('감시 등록된 대상이 없다. 할 일 없음.')
            return summary

        if not webpush.is_configured():
            logger.warning('VAPID 미설정 - 수집은 하되 발송은 건너뛴다.')

        logger.info('수집 대상 %d건 (감시 등록된 배·날짜만)', len(targets))

        all_transitions = []
        boat_names = {}

        for index, (boat_id, target_date) in enumerate(targets, 1):
            boat = Boat.query.get(boat_id)
            if boat is None:
                logger.warning('[%d/%d] 배 %s 가 사라졌다 - 건너뛴다',
                               index, len(targets), boat_id)
                continue
            boat_names[boat_id] = boat.name

            logger.info('[%d/%d] %s %s', index, len(targets), boat.name, target_date)
            try:
                transitions = collect_one(boat, target_date, dry_run)
                summary['collected'] += 1
            except Exception as exc:   # 실패 격리
                summary['failed'] += 1
                logger.exception('  예외 %s %s: %s', boat.name, target_date, exc)
                continue

            for transition in transitions:
                logger.info('  변화 감지: %s %s -> %s',
                            transition.ship_name,
                            transition.previous_status, transition.current_status)
            all_transitions.extend(transitions)

            if index < len(targets) and delay > 0:
                time.sleep(delay)

        if all_transitions and not dry_run:
            result = dispatch_all(all_transitions, boat_names)
            summary['transitions'] = result['transitions']
            summary['sent'] = result['sent']
            logger.info('발송 결과: %s', result)
        else:
            logger.info('알릴 변화 없음')

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true',
                    help='저장도 발송도 하지 않고 수집만 해본다')
    ap.add_argument('--delay', type=float, default=DEFAULT_DELAY,
                    help='배 사이 요청 간격(초)')
    args = ap.parse_args()

    if not os.environ.get('DATABASE_URL'):
        logger.warning('DATABASE_URL 이 없다. 로컬 SQLite 를 쓰게 되는데, '
                       '웹과 다른 DB 라 감시 대상이 없을 것이다.')

    started = time.monotonic()
    summary = run(dry_run=args.dry_run, delay=args.delay)
    logger.info('완료 (%.1f초) %s', time.monotonic() - started, summary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
