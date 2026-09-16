"""
라우트(views.py/watch_views.py) 공용 HTTP 응답 헬퍼.

두 블루프린트가 각자 복제해 갖고 있던 것을 한 곳으로 모았다 - 동작은
그대로다(순수 유틸리티, 파싱/스크래핑 로직과 무관).
"""
from flask import jsonify


def no_store_response(payload: dict):
    """이 응답을 브라우저가 캐시하지 못하게 한다.

    실측 버그: 관리자 콘솔 "새로고침" 버튼(admin.html)이 fetch()를 다시
    불러도, 시크릿 창이 아닌 일반 창에서는 브라우저가 같은 URL의 예전
    응답을 그대로 재사용해 어제 데이터만 계속 보였다(사용자가 시크릿
    창과 비교해서 직접 확인함). 프런트에서 fetch(..., {cache:'no-store'})
    로 고쳤지만, 엔드포인트 자체도 캐시 가능한 응답으로 보이면 안 되므로
    (다른 호출부나 중간 프록시까지 안전하게) 서버 쪽에서도 명시적으로
    막는다."""
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


#: 기기 종류 표시용 라벨. 관리자 콘솔의 "알림 등록"/"접속 이력" 탭이 같이 쓴다.
DEVICE_LABELS = {'pc': 'PC', 'mobile': '모바일', 'tablet': '태블릿', 'unknown': '알 수 없음'}
