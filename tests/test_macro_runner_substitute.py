# -*- coding: utf-8 -*-
"""macro_runner/substitute.py - 매크로 단계 값의 {이름}/{전화1-3}/{인원}/
{날짜} 치환 규칙. src/templates/macro.html의 JS resolveValue()와 동작이
같아야 하므로(화면 미리보기와 실제 실행이 같은 값을 써야 함), 그 규칙을
그대로 옮긴 순수 함수만 검증한다. macro_runner/는 로컬 실행 전용이라
Flask 앱과 무관하게 import 경로만 sys.path에 추가한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'macro_runner'))

from substitute import resolve_value  # noqa: E402


CONFIG = {
    'guestName': '홍기백',
    'guestPhone1': '010',
    'guestPhone2': '1234',
    'guestPhone3': '5678',
    'party': 2,
    'date': '2026-09-23',
}


def test_resolve_value_substitutes_name_and_split_phone():
    assert resolve_value('{이름}', CONFIG) == '홍기백'
    assert resolve_value('{전화1}', CONFIG) == '010'
    assert resolve_value('{전화2}', CONFIG) == '1234'
    assert resolve_value('{전화3}', CONFIG) == '5678'
    assert resolve_value('{전화}', CONFIG) == '01012345678'


def test_resolve_value_substitutes_party_as_string():
    assert resolve_value('{인원}', CONFIG) == '2'


def test_resolve_value_substitutes_date():
    assert resolve_value('{날짜}', CONFIG) == '2026-09-23'


def test_resolve_value_handles_multiple_tokens_in_one_string():
    assert resolve_value('{이름}/{전화1}-{전화2}-{전화3}', CONFIG) == '홍기백/010-1234-5678'


def test_resolve_value_returns_plain_text_unchanged():
    assert resolve_value('바로예약', CONFIG) == '바로예약'


def test_resolve_value_returns_falsy_input_as_is():
    assert resolve_value('', CONFIG) == ''
    assert resolve_value(None, CONFIG) is None


def test_resolve_value_missing_config_fields_substitute_as_empty():
    assert resolve_value('{이름}', {}) == ''
    assert resolve_value('{전화1}{전화2}{전화3}', {}) == ''
