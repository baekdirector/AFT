# -*- coding: utf-8 -*-
"""record.py/run.py가 공통으로 쓰는 창 배치 유틸.

두 도구 모두 같은 레이아웃을 쓴다 - 왼쪽엔 실제 동작 대상(또는 실행)
브라우저, 오른쪽엔 진행 상황을 실시간으로 보여주는 작은 창.
`browser.new_context(viewport=...)`는 페이지 "내부" 렌더링 크기만
정하고 실제 OS 창 위치는 안 건드리는데, 그러면 두 창이 화면 기본
위치에 겹쳐 떠서 나중에 뜬 창이 먼저 뜬 창을 완전히 가려버리는 문제가
실제로 있었다("오른쪽 창이 안 보인다") - CDP의 Browser.setWindowBounds로
명시적으로 좌/우로 떨어뜨려 놓는다."""

LEFT_BOUNDS = {'left': 0, 'top': 0, 'width': 1290, 'height': 860}
RIGHT_BOUNDS = {'left': 1290, 'top': 0, 'width': 580, 'height': 860}


def position_window(page, left, top, width, height):
    try:
        cdp = page.context.new_cdp_session(page)
        window_id = cdp.send('Browser.getWindowForTarget')['windowId']
        cdp.send('Browser.setWindowBounds', {
            'windowId': window_id,
            'bounds': {'left': left, 'top': top, 'width': width, 'height': height},
        })
    except Exception as e:
        print('창 위치 지정에 실패했습니다({}) - 창을 직접 옮겨 주세요.'.format(e))
