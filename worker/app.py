"""
예약 스크래핑 워커 (Google Cloud Run, Tokyo 리전).

Render 는 이 서비스를 "배 한 척, 날짜 하나를 대신 긁어와줘" 라고 부르는
용도로만 쓴다 - DB 도, 감시/알림 로직도 이 서비스는 전혀 모른다. 존재
이유는 순전히 물리적 거리다: Render 서버에서 한국 중소 호스팅 사이트까지
왕복이 배당 평균 7.9초(최대 15.3초) 걸리는 것이 실측됐고, 코드 레벨
튜닝(세션 재사용, lxml 파서, 워커 수 조정)으로는 더 줄지 않았다 - 이건
거리 문제이지 코드 문제가 아니었다. Tokyo 리전은 그 사이트들과 물리적으로
훨씬 가깝다.

실제 fetch+parse 로직은 이 파일에 없다. src/services/reservation_checker.py
의 _check_single_boat_locally() 를 그대로 불러 쓴다(Dockerfile 이 빌드 시
그 파일과 src/config/ 를 이 이미지 안으로 복사해 넣는다) - 파싱 로직의
원본은 하나뿐이고, 이 서비스는 그 원본을 실행하는 자리만 옮긴 것이다.
"""
import hmac
import os

from flask import Flask, jsonify, request

from services.reservation_checker import _check_single_boat_locally

app = Flask(__name__)

#: Render -> 워커 인증. src/routes/watch_views.py 의 SCRAPE_TOKEN/
#: X-Scrape-Token 패턴과 동일하게 상수 시간 비교를 쓴다. 비어 있으면
#: (개발 중 로컬 실행 등) 인증을 건너뛴다 - Render 쪽 SCRAPE_WORKER_TOKEN
#: 이 비어 있을 때 오늘 동작으로 완전히 폴백하는 것과 대칭이다.
WORKER_TOKEN = os.environ.get('SCRAPE_WORKER_TOKEN')


@app.route('/healthz')
def healthz():
    return 'ok', 200


@app.route('/check', methods=['POST'])
def check():
    if WORKER_TOKEN:
        provided = request.headers.get('X-Worker-Token', '')
        if not hmac.compare_digest(provided, WORKER_TOKEN):
            return jsonify({'error': '인증에 실패했습니다.'}), 403

    data = request.get_json(silent=True) or {}
    try:
        boat_url = data['boat_url']
        year = int(data['year'])
        month = int(data['month'])
        day = int(data['day'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'boat_url/year/month/day 가 필요합니다.'}), 400
    known_ship_name = data.get('known_ship_name')

    result = _check_single_boat_locally(boat_url, year, month, day,
                                        debug_enabled=False,
                                        known_ship_name=known_ship_name)
    return jsonify(result)
