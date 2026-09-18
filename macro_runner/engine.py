# -*- coding: utf-8 -*-
"""매크로 단계 실행기. src/templates/macro.html의 단계 편집기가 만드는
JSON(내보내기 파일)을 그대로 읽어 Playwright로 재생한다.

지원하는 세 가지 동작 지점 지정 방식(step['mode']):
- 'selector': Playwright 문법과 그대로 호환되는 문자열
  (예: "text=바로예약", "#agree_all")을 page.locator()에 넘긴다.
- 'coord': 화면 좌표(x, y)를 그대로 클릭한다 - 레코딩 당시 화면
  크기와 실행 환경이 다르면 어긋날 수 있어 보조 수단으로만 권장된다.
- 'tab': 현재 포커스에서 Tab을 tabCount번 눌러 이동한 뒤 그 자리에서
  동작한다. 선상24 예약 팝업처럼 뜨는 위치가 매번 달라지는 새 창에서도
  포커스 이동 순서는 고정이라는 걸 사용자가 실제로 확인해 알려준
  방식이다(가장 안정적).

'popup' 액션은 클릭이 새 창(window.open)을 띄우는 경우다 - Playwright는
그 클릭을 context.expect_page()로 감싸야 새 창을 잡을 수 있어서,
별도 '전환' 단계가 아니라 클릭 자체의 속성으로 다룬다.

'manual: true'인 단계(기본값: 마지막 예약하기)에서는 자동 클릭을 하지
않고 사람이 브라우저에서 직접 확인 후 누르도록 멈춘다 - 실제 결제/예약이
확정되는 지점이기 때문이다."""
import time

from substitute import resolve_value


class Runner:
    def __init__(self, config, page, context):
        self.config = config
        self.page = page
        self.context = context

    def run(self):
        for step in self.config.get('steps', []):
            self._execute(step)
            time.sleep((step.get('sleep') or 0) / 1000)

    def _execute(self, step):
        if step.get('manual'):
            print("\n🖐 '{}' 단계입니다 - 브라우저 창에서 직접 확인 후 눌러주세요.".format(
                step.get('label') or '(라벨 없음)'))
            input('완료했으면 여기서 Enter ↵ ')
            return

        action = step.get('action')

        if action == 'popup':
            with self.context.expect_page() as popup_info:
                self._click_target(step)
            self.page = popup_info.value
            self.page.wait_for_load_state()
            return

        mode = step.get('mode') or 'selector'
        if mode == 'tab':
            for _ in range(int(step.get('tabCount') or 1)):
                self.page.keyboard.press('Tab')

        if action in (None, 'none', 'wait'):
            return
        if action == 'click':
            self._click_focused() if mode == 'tab' else self._click_target(step)
        elif action == 'clickTimes':
            n = int(resolve_value(step.get('value') or '1', self.config) or 0)
            for _ in range(max(0, n)):
                self._click_focused() if mode == 'tab' else self._click_target(step)
        elif action == 'input':
            value = resolve_value(step.get('value') or '', self.config)
            if mode == 'tab':
                self.page.keyboard.type(value)
            else:
                self._locator(step).fill(value)
        elif action == 'waitFor':
            self._locator(step).wait_for()
        # select/scroll/reload: 아직 실제 사용 사례가 없어 필요해지면 추가한다.

    def _locator(self, step):
        return self.page.locator(step['selector'])

    def _click_target(self, step):
        mode = step.get('mode') or 'selector'
        if mode == 'coord':
            self.page.mouse.click(int(step['x']), int(step['y']))
        elif mode == 'selector':
            self._locator(step).click()
        else:
            self._click_focused()

    def _click_focused(self):
        self.page.evaluate('document.activeElement && document.activeElement.click()')
