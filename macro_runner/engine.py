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
import json
import os
import time

from substitute import resolve_value


class Runner:
    def __init__(self, config, page, context, stepwise=False, progress_path=None):
        self.config = config
        self.page = page
        self.context = context
        # stepwise=True면 각 단계 실행 전에 무엇을 할지 예고하고 Enter로
        # 승인받는다 - 실제 브라우저가 이미 떠 있으니, 승인 즉시 그
        # 자리에서 진짜 Tab 이동/클릭/입력/팝업 전환이 일어나는 걸 한
        # 단계씩 눈으로 확인할 수 있다.
        self.stepwise = stepwise
        # run.py가 오른쪽에 띄우는 진행 상황 창이 이 파일을 폴링한다 -
        # 실행 중 어느 단계에서 멈췄는지 터미널 로그와 별개로 눈으로도
        # 바로 확인할 수 있게 한다(실제로 팝업이 안 뜨는 실패가 나서
        # "몇 번째 단계인지조차 알 수 없다"는 문제를 겪었다).
        self.progress_path = progress_path
        self._progress_steps = None

    def run(self):
        steps = self.config.get('steps', [])
        total = len(steps)
        for i, step in enumerate(steps):
            # stepwise 여부와 무관하게 항상 어떤 단계를 실행하는지는
            # 보여준다 - 예전엔 stepwise가 아니면(실전 실행) 아무 로그도
            # 없어서 실패했을 때 몇 번째 단계였는지조차 알 수 없었다.
            self._announce(i, total, step)
            if self.stepwise and not step.get('manual'):
                input('  Enter를 누르면 이 단계를 실행합니다 ↵ ')
            self._write_progress(i, total, steps, '진행')
            try:
                self._execute(step)
            except Exception as e:
                self._write_progress(i, total, steps, '오류: {}'.format(e))
                print('  → 오류: {}: {}'.format(type(e).__name__, e))
                raise
            self._write_progress(i, total, steps, '완료')
            if self.stepwise and not step.get('manual'):
                print('  → 완료')
            time.sleep((step.get('sleep') or 0) / 1000)

    def _write_progress(self, i, total, steps, status):
        if not self.progress_path:
            return
        if self._progress_steps is None:
            self._progress_steps = [{
                'label': s.get('label') or '(라벨 없음)',
                'target': self._describe_target(s['click']) if 'click' in s else self._describe_target(s),
                'status': '대기',
            } for s in steps]
        self._progress_steps[i]['status'] = status
        data = {'total': total, 'current': i, 'steps': self._progress_steps}
        tmp = self.progress_path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.progress_path)
        except OSError:
            pass  # 진행 상황 창은 참고용 - 파일 쓰기 실패로 실행 자체를 막지 않는다

    def _announce(self, i, total, step):
        if 'click' in step:
            print('\n[{}/{}] {}'.format(i + 1, total, step.get('label') or '(라벨 없음)'))
            for sub in step.get('inputs', []):
                print('  입력: ' + resolve_value(sub.get('value') or '', self.config))
            print('  클릭: ' + self._describe_target(step['click']))
            return
        target = self._describe_target(step)
        value = step.get('value')
        preview = ' → ' + resolve_value(value, self.config) if value else ''
        print('\n[{}/{}] {}'.format(i + 1, total, step.get('label') or '(라벨 없음)'))
        print('  ' + target + preview)

    def _describe_target(self, step):
        # src/templates/macro.html의 describeStepTarget()과 같은 규칙 -
        # 화면 미리보기와 실제 실행이 같은 문구를 쓰도록 그대로 옮겼다.
        # 복합 단계의 click 딕셔너리도 같은 mode/x/y/selector 모양이라
        # 그대로 재사용할 수 있다.
        mode = step.get('mode') or 'selector'
        if mode == 'coord':
            return '좌표 (' + str(step.get('x')) + ', ' + str(step.get('y')) + ')'
        if mode == 'tab':
            suffix = ' 후 Enter' if step.get('useKey') == 'Enter' else ''
            return 'Tab ' + str(step.get('tabCount') or 1) + '회 이동' + suffix
        return '선택자 ' + str(step.get('selector') or '?')

    def _execute(self, step):
        if step.get('manual'):
            print("\n🖐 '{}' 단계입니다 - 브라우저 창에서 직접 확인 후 눌러주세요.".format(
                step.get('label') or '(라벨 없음)'))
            input('완료했으면 여기서 Enter ↵ ')
            return

        # record.py(실제 브라우저 조작 녹화 도구)가 만드는 "복합 단계"는
        # click 키가 있다 - 클릭 하나로 마감되는 이벤트 안에 그 전까지의
        # 입력들(inputs[])이 묶여 있는 모양이다. 기존 평면 단계(action
        # 기반)와는 완전히 다른 모양이라 여기서 분기하고, 없으면 기존
        # 로직을 그대로 탄다(손으로 만든 단계·기존 프리셋은 전혀 안
        # 건드림).
        if 'click' in step:
            self._execute_composite(step)
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
        return self._resolve_locator(step['selector'])

    def _resolve_locator(self, raw_selector):
        # 선택자에 {날짜} 같은 변수가 남아있으면 실제 값으로 치환한다 -
        # 값(value) 필드만 치환하고 선택자는 그대로 두면 {날짜}가 문자
        # 그대로 남아 어떤 실제 페이지에서도 절대 매칭되지 않는다
        # (macro.html의 webQuerySelector와 동일한 이유로 고친 버그).
        sel = resolve_value(raw_selector, self.config) or ''
        # ':first'/':last'는 jQuery/Sizzle 전용 의사 선택자라 Playwright도
        # 모른다(CSS 표준도 아님) - 그대로 넘기면 SyntaxError가 난다.
        # 접미사를 떼어내고 Playwright의 .first/.last로 좁힌다.
        if sel.endswith(':first'):
            return self.page.locator(sel[:-len(':first')]).first
        if sel.endswith(':last'):
            return self.page.locator(sel[:-len(':last')]).last
        return self.page.locator(sel)

    def _execute_composite(self, step):
        # record.py가 만드는 복합 단계 실행 - 클릭 전에 있었던 입력들을
        # 순서대로 채운 뒤 마지막 클릭을 수행한다. 팝업 안 입력/클릭은
        # 항상 mode='tab'(화면 위치가 매번 달라 좌표를 못 씀 - 이미
        # Tab 이동 방식으로 검증된 것과 같은 원리), 메인 창은 선택자
        # 또는 좌표(녹화·재생 둘 다 뷰포트가 1280x800으로 고정되므로
        # 좌표도 신뢰 가능).
        for sub in step.get('inputs', []):
            value = resolve_value(sub.get('value') or '', self.config)
            if (sub.get('mode') or 'selector') == 'tab':
                for _ in range(int(sub.get('tabCount') or 0)):
                    self.page.keyboard.press('Tab')
                self.page.keyboard.type(value)
            else:
                self._resolve_locator(sub.get('selector') or '').fill(value)

        click = step.get('click') or {}
        if step.get('opensPopup'):
            with self.context.expect_page() as popup_info:
                self._click_composite(click)
            self.page = popup_info.value
            self.page.wait_for_load_state()
        else:
            self._click_composite(click)

    def _click_composite(self, click):
        mode = click.get('mode') or 'selector'
        if mode == 'tab':
            for _ in range(int(click.get('tabCount') or 0)):
                self.page.keyboard.press('Tab')
            if click.get('useKey') == 'Enter':
                # 녹화할 때 마우스 클릭이 아니라 Enter로 확정한
                # 단계다 - 좌표가 아예 필요 없어 스크롤/레이아웃
                # 드리프트와 무관하다.
                self.page.keyboard.press('Enter')
            else:
                self._click_focused()
        elif mode == 'coord':
            # 녹화 당시 스크롤돼 있던 위치까지 먼저 맞춰야 좌표가 같은
            # 지점을 가리킨다(record.py가 클릭 시점의 scrollX/scrollY도
            # 같이 기록해 둔다). 다만 실제 사이트는 공지/배너 이미지
            # 높이가 매번 달라질 수 있어(실제로 겪음 - 스크롤을 정확히
            # 복원해도 그 사이 페이지 레이아웃 자체가 바뀌면 좌표가
            # 어긋난다) 완벽히 보장되진 않는다 - 그래서 클릭 직전에
            # 실제로 그 좌표에 뭐가 있는지 한 줄 출력해 둔다. 팝업이
            # 안 뜨는 등 실패가 나면 이 로그로 "버튼이 아니라 엉뚱한
            # 걸 클릭했다"를 바로 확인할 수 있다.
            if click.get('scrollX') is not None or click.get('scrollY') is not None:
                self.page.evaluate(
                    '([x, y]) => window.scrollTo(x, y)',
                    [click.get('scrollX') or 0, click.get('scrollY') or 0],
                )
            x, y = int(click['x']), int(click['y'])
            hit = self.page.evaluate(
                '''([x, y]) => {
                    // 클릭 직전 그 자리에 실제로 눈에 보이는 표시(빨간 점)를
                    // 잠깐 찍어둔다 - 좌표가 어긋났는지 화면으로 바로 확인할
                    // 수 있다(콘솔 로그만으로는 실제 화면 위치를 가늠하기
                    // 어렵다는 피드백).
                    var old = document.getElementById('__aftClickMarker');
                    if (old) old.remove();
                    var marker = document.createElement('div');
                    marker.id = '__aftClickMarker';
                    marker.style.cssText = 'position:fixed;left:' + (x - 9) + 'px;top:' + (y - 9) + 'px;' +
                        'width:18px;height:18px;border-radius:50%;background:rgba(255,0,0,0.45);' +
                        'border:2px solid #ff0000;box-shadow:0 0 6px rgba(255,0,0,0.8);' +
                        'z-index:2147483647;pointer-events:none;';
                    document.body.appendChild(marker);
                    setTimeout(function () { if (marker.parentNode) marker.remove(); }, 2500);

                    const el = document.elementFromPoint(x, y);
                    if (!el) return '(요소 없음)';
                    const txt = (el.textContent || '').trim().slice(0, 30);
                    return el.tagName + (el.id ? '#' + el.id : '') + (txt ? ' "' + txt + '"' : '');
                }''',
                [x, y],
            )
            print('  좌표 ({}, {}) 대상 확인: {}'.format(x, y, hit))
            self.page.mouse.click(x, y)
        else:
            self._resolve_locator(click.get('selector') or '').click()

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
