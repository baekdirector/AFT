"""
실제 응답 fixture 회귀 하네스 (Phase A).

CLAUDE.md 규칙 1: 파싱 코드를 고치기 전에 그 변형의 fixture 와 골든 파일을
먼저 만든다. 이 파일이 그 하네스다.

동작 방식:
  tests/fixtures/<플랫폼>/<이름>.html        실제 응답 원본
  tests/fixtures/<플랫폼>/<이름>.meta.json   어느 URL·날짜를 물어본 응답인가
  tests/fixtures/<플랫폼>/<이름>.expected.json  기대하는 정규화 출력(골든)

네트워크는 타지 않는다. requests.get 을 fixture 를 돌려주는 함수로 바꾼다.
골든이 없으면 그 fixture 는 xfail 로 남겨 '아직 판정하지 않았음'을 드러낸다.

골든 갱신:
  python src/scripts/update_goldens.py        # 현재 동작을 골든으로 굳힌다
사이트 구조가 바뀌어 테스트가 깨지면, 원인을 눈으로 확인한 뒤에만 갱신한다.
"""
import io
import json
from pathlib import Path

import pytest

from services import reservation_checker

FIXTURE_ROOT = Path(__file__).parent / 'fixtures'


def discover():
    """(fixture 이름, html 경로, meta 경로) 목록."""
    found = []
    for html_path in sorted(FIXTURE_ROOT.rglob('*.html')):
        meta_path = html_path.with_suffix('.meta.json')
        if meta_path.exists():
            rel = html_path.relative_to(FIXTURE_ROOT).as_posix()[:-len('.html')]
            found.append(pytest.param(rel, id=rel))
    return found


FIXTURES = discover()


def load(name):
    html = io.open(FIXTURE_ROOT / f'{name}.html', encoding='utf-8').read()
    meta = json.loads(io.open(FIXTURE_ROOT / f'{name}.meta.json', encoding='utf-8').read())
    return html, meta


class FixtureResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


def parse_fixture(name, monkeypatch):
    """fixture 를 기존 파서에 먹이고 정규화된 결과를 돌려준다."""
    html, meta = load(name)
    monkeypatch.setattr(reservation_checker.requests, 'get',
                        lambda *a, **kw: FixtureResponse(html))
    reservation_checker.clear_cache()   # 캐시가 fixture 간에 새지 않게

    year, month, day = (int(p) for p in meta['target_date'].split('-'))
    result = reservation_checker.check_single_boat(
        meta['source_url'], year, month, day)

    # 골든에 담을 값만 추린다. used_url 처럼 실행마다 달라질 수 있는 것은 뺀다.
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


@pytest.mark.parametrize('name', FIXTURES)
def test_fixture_matches_golden(name, monkeypatch):
    """fixture 를 파싱한 결과가 골든과 일치해야 한다.

    깨졌다면 둘 중 하나다.
      - 파서를 고쳐서 출력이 달라졌다 (의도한 것이면 골든을 갱신한다)
      - 사이트 구조가 바뀌어 파서가 못 읽는다 (파서를 고쳐야 한다)
    어느 쪽인지 눈으로 확인하기 전에는 골든을 갱신하지 않는다.
    """
    golden_path = FIXTURE_ROOT / f'{name}.expected.json'
    if not golden_path.exists():
        pytest.skip(f'골든 없음 - update_goldens.py 로 만든다: {name}')

    expected = json.loads(io.open(golden_path, encoding='utf-8').read())
    actual = parse_fixture(name, monkeypatch)

    assert actual == expected


@pytest.mark.parametrize('name', FIXTURES)
def test_parsing_is_deterministic(name, monkeypatch):
    """같은 fixture 는 항상 같은 결과를 낸다 (PLAN.md 3b.4)."""
    first = parse_fixture(name, monkeypatch)
    second = parse_fixture(name, monkeypatch)
    assert first == second


def test_fixture_set_is_not_empty():
    """하네스가 빈 채로 초록불이 되면 아무것도 지켜주지 못한다."""
    assert FIXTURES, 'tests/fixtures 에 캡처된 응답이 하나도 없다'


# --- 이 하네스로 잡아서 고친 것들 -------------------------------------------
# 골든 비교만으로도 회귀는 막히지만, 무엇을 왜 고쳤는지는 골든 JSON 을 봐도
# 알 수 없다. 아래 테스트가 그 이유를 남긴다.

def test_fleet_ships_without_ho_suffix_are_parsed(monkeypatch):
    """이름이 '호'로 끝나지 않는 선단이 통째로 사라지던 문제.

    팀에프호 페이지에는 '팀에프원', '팀에프투' 가 각각 정원 20명·예약마감으로
    실려 있는데, 이름에 '호'가 없고 하드코딩 목록에도 없어서 0척이 나왔다.
    판단 근거를 이름에서 구조(정원·예약상태 유무)로 옮겨 해결했다.
    """
    result = parse_fixture('sunsang24/팀에프호_20261003', monkeypatch)
    names = [e['ship_name'] for e in result['entries']]

    assert names == ['팀에프원', '팀에프투']


def test_tackle_shop_row_is_not_a_boat(monkeypatch):
    """같은 페이지의 '동양낚시마트'(낚시점 안내 행)는 배가 아니다.

    구조로 판별하도록 바꾸면서 이 행까지 배로 딸려 들어오면 안 된다.
    """
    result = parse_fixture('sunsang24/팀에프호_20261003', monkeypatch)
    names = [e['ship_name'] for e in result['entries']]

    assert not any('낚시마트' in n for n in names)


@pytest.mark.parametrize('name', [
    'sunsang24/팀에프호_20261003',
    'sunsang24/레드헌터_선단_20261003',
])
def test_closed_boats_report_zero_remaining(name, monkeypatch):
    """예약마감인 배의 잔여석은 0이어야 한다.

    .number 는 잔여석이 아니라 정원이다. 예전에는 마감이어도 그 숫자가 그대로
    남아 '20자리 남음'으로 저장됐다. 화면은 두 렌더 경로 모두 마감이면 0으로
    덮어쓰고 있어 가려져 있었지만, DB 에는 잘못된 값이 들어가 알림 판단을 망친다.
    """
    result = parse_fixture(name, monkeypatch)
    closed = [e for e in result['entries'] if e['status'] in ('full', 'reserved')]

    assert closed, '이 fixture 에는 마감된 배가 있어야 검증이 성립한다'
    assert all(e['available'] == 0 for e in closed), \
        f"마감인데 잔여석이 남아있다: {[(e['ship_name'], e['available']) for e in closed]}"
