"""
감시 등록 API. Phase C.

/status 결과 표의 체크박스가 여기를 호출한다.

사람을 식별하는 수단은 브라우저 푸시 구독 endpoint 하나뿐이다(로그인 없음).
그래서 모든 요청이 endpoint 를 함께 보내고, 서버는 그것으로 Subscriber 를 찾는다.
친구 5명 규모에서 계정 체계를 만드는 것은 과설계다.
"""
import hmac
import os
import time

from flask import Blueprint, current_app, jsonify, request

from models import MAX_WATCHES_PER_SUBSCRIBER, Boat, Subscriber
from services.notify import webpush
from services.watch_service import (
    WatchLimitExceeded,
    add_watch,
    list_watches,
    remove_watch,
    upsert_subscriber,
)

watch_views = Blueprint('watch_views', __name__)


def _find_subscriber(endpoint):
    if not endpoint:
        return None
    return Subscriber.query.filter_by(endpoint=endpoint).one_or_none()


@watch_views.route('/api/scrape/run', methods=['POST'])
def trigger_scrape():
    """수집 파이프라인을 이 서버에서 한 번 돌린다. GitHub Actions 가 호출한다.

    왜 Actions 가 직접 긁지 않는가:
    Actions 러너에서는 한국 중소 호스팅 상당수에 TCP 연결이 되지 않는다.
    실측(2026-09) 감시 6척 중 5척이 connect timeout 이었고, 타임아웃을 20초로
    늘려도 같았다. SYN 에 응답이 없다는 뜻이라 방화벽 드롭이다. 같은 배들이
    이 서버에서는 6/6 이 8.9초에 붙는다. 그래서 긁는 일은 여기서 하고 Actions 는
    방아쇠만 당긴다. 덤으로 Actions 실행 시간이 짧아져 무료 분을 아끼고,
    매시간 이 서버를 깨워 콜드스타트도 줄인다.

    인증: SCRAPE_TOKEN 환경변수와 X-Scrape-Token 헤더가 일치해야 한다.
    토큰이 설정돼 있지 않으면 아무도 호출할 수 없다(열어두지 않는다).
    이 엔드포인트는 외부 사이트로 요청을 내보내므로 공개되면 남용될 수 있다.
    """
    expected = os.environ.get('SCRAPE_TOKEN')
    if not expected:
        return jsonify({'error': 'SCRAPE_TOKEN 이 설정되지 않아 비활성 상태입니다.'}), 503

    provided = request.headers.get('X-Scrape-Token', '')
    # 길이/내용 차이로 토큰을 추측하지 못하게 상수 시간 비교를 쓴다
    if not hmac.compare_digest(provided, expected):
        return jsonify({'error': '인증에 실패했습니다.'}), 403

    dry_run = str(request.args.get('dry_run', '')).lower() in ('1', 'true', 'yes')

    from scheduler.run_scrape import run_pipeline

    started = time.monotonic()
    try:
        summary = run_pipeline(dry_run=dry_run, delay=float(
            request.args.get('delay', os.environ.get('SCRAPE_DELAY_SECONDS', 0.5))))
    except Exception as exc:
        current_app.logger.exception('수집 실행 실패: %s', exc)
        return jsonify({'error': f'{type(exc).__name__}: {exc}'}), 500

    summary['elapsed_seconds'] = round(time.monotonic() - started, 1)
    summary['dry_run'] = dry_run
    current_app.logger.info('수집 완료: %s', summary)
    return jsonify(summary)


@watch_views.route('/api/push/public-key', methods=['GET'])
def push_public_key():
    """브라우저가 구독할 때 필요한 VAPID 공개키.

    키가 없으면 configured=false 로 알려준다. 프론트는 이때 구독 버튼을
    숨기면 된다. 키 미설정이 에러가 되어선 안 된다.
    """
    key = webpush.vapid_public_key()
    return jsonify({'configured': bool(key), 'public_key': key})


@watch_views.route('/api/push/subscribe', methods=['POST'])
def push_subscribe():
    """브라우저 푸시 구독을 저장한다. 같은 endpoint 면 갱신한다."""
    data = request.get_json(silent=True) or {}
    keys = data.get('keys') or {}
    try:
        subscriber = upsert_subscriber(
            endpoint=data.get('endpoint'),
            p256dh=keys.get('p256dh'),
            auth=keys.get('auth'),
            label=data.get('label'),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'subscriber_id': subscriber.id,
        'limit': MAX_WATCHES_PER_SUBSCRIBER,
        'watches': [w.to_dict() for w in list_watches(subscriber)],
    })


@watch_views.route('/api/watches', methods=['GET'])
def get_watches():
    """이 브라우저가 걸어둔 감시 목록. 화면 로드 시 체크박스를 복원하는 데 쓴다."""
    subscriber = _find_subscriber(request.args.get('endpoint'))
    if subscriber is None:
        return jsonify({'watches': [], 'limit': MAX_WATCHES_PER_SUBSCRIBER})
    return jsonify({
        'watches': [w.to_dict() for w in list_watches(subscriber)],
        'limit': MAX_WATCHES_PER_SUBSCRIBER,
    })


@watch_views.route('/api/watches', methods=['POST'])
def create_watch():
    """감시 한 건을 건다. 체크박스를 켤 때 호출된다."""
    data = request.get_json(silent=True) or {}
    subscriber = _find_subscriber(data.get('endpoint'))
    if subscriber is None:
        return jsonify({'error': '먼저 알림 구독을 해주세요.'}), 409

    boat_id = data.get('boat_id')
    if boat_id is None:
        # 프론트가 배 이름만 아는 경우를 위해 이름으로도 찾아준다
        boat = Boat.query.filter_by(name=data.get('boat_name') or '').one_or_none()
        boat_id = boat.id if boat else None

    try:
        watch = add_watch(subscriber, boat_id,
                          data.get('ship_name'), data.get('target_date'))
    except WatchLimitExceeded as exc:
        return jsonify({'error': str(exc), 'limit': exc.limit}), 409
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        current_app.logger.error('감시 등록 실패: %s', exc)
        return jsonify({'error': '감시 등록 중 오류가 발생했습니다.'}), 500

    return jsonify({
        'watch': watch.to_dict(),
        'watches': [w.to_dict() for w in list_watches(subscriber)],
        'limit': MAX_WATCHES_PER_SUBSCRIBER,
    })


@watch_views.route('/api/watches', methods=['DELETE'])
def delete_watch():
    """감시를 끈다. 체크박스를 해제할 때 호출된다."""
    data = request.get_json(silent=True) or {}
    subscriber = _find_subscriber(data.get('endpoint'))
    if subscriber is None:
        return jsonify({'error': '구독 정보를 찾을 수 없습니다.'}), 404

    boat_id = data.get('boat_id')
    if boat_id is None:
        boat = Boat.query.filter_by(name=data.get('boat_name') or '').one_or_none()
        boat_id = boat.id if boat else None

    removed = remove_watch(subscriber, boat_id,
                           data.get('ship_name'), data.get('target_date'))
    return jsonify({
        'removed': removed,
        'watches': [w.to_dict() for w in list_watches(subscriber)],
        'limit': MAX_WATCHES_PER_SUBSCRIBER,
    })
