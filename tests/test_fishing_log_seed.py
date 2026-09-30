"""엑셀 초기 이관 파서 (spec §3). 실제 엑셀은 커밋하지 않는다 - 값은 전부
지어낸 것이고, 필요한 엑셀은 테스트 안에서 openpyxl로 만든다."""
from services.fishing_log.excel_seed import (
    extract_ship_name, normalize_category, normalize_shop, parse_catches,
    ship_match_key, to_int,
)


def test_to_int_accepts_numbers_and_digit_strings():
    assert to_int(12000) == 12000
    assert to_int(12000.0) == 12000
    assert to_int(1234.6) == 1235
    assert to_int('12,000') == 12000


def test_to_int_returns_none_for_text_and_blanks():
    assert to_int('11만원') is None
    assert to_int('무료') is None
    assert to_int(None) is None
    assert to_int('') is None
    assert to_int(True) is None


def test_normalize_shop_merges_known_spellings():
    assert normalize_shop('테무') == 'Temu'
    assert normalize_shop('temu') == 'Temu'
    assert normalize_shop('aliexpress') == 'AliExpress'
    assert normalize_shop('Aliexpress') == 'AliExpress'
    assert normalize_shop('에프마켓 인천') == '에프마켓인천'
    assert normalize_shop('  가나낚시 ') == '가나낚시'
    assert normalize_shop(None) is None


def test_normalize_category_maps_synonyms_and_blank():
    assert normalize_category('줄') == '라인'
    assert normalize_category('낚시대') == '로드'
    assert normalize_category('에기') == '에기'
    assert normalize_category(None) == '기타'


def test_ship_match_key_ignores_spaces_case_and_trailing_ho():
    assert ship_match_key('가나다호') == ship_match_key(' 가나 다 ')
    assert ship_match_key('ABC호') == ship_match_key('abc')


def test_extract_ship_name_prefers_word_ending_in_ho():
    assert extract_ship_name('가나다호 - (농어, 우럭)') == ('가나다호', '(농어, 우럭)')
    assert extract_ship_name('라마낚시 바사호 문어') == ('바사호', '라마낚시 문어')
    assert extract_ship_name('테스트도 원강호(다른호)') == ('원강호', '테스트도 (다른호)')
    assert extract_ship_name('하늘폭스') == ('하늘폭스', None)
    assert extract_ship_name('가나다 호') == ('가나다 호', None)


def test_parse_catches_simple_forms():
    assert parse_catches('쭈 10, 갑 2') == (
        [{'who': '나', 'species': '쭈꾸미', 'count': 10},
         {'who': '나', 'species': '갑오징어', 'count': 2}], False)
    assert parse_catches('문어3마리') == ([{'who': '나', 'species': '문어', 'count': 3}], False)


def test_parse_catches_tracks_people():
    catches, leftover = parse_catches('마눌 문5, 나 문7')
    assert catches == [{'who': '마눌', 'species': '문어', 'count': 5},
                       {'who': '나', 'species': '문어', 'count': 7}]
    assert leftover is False

    catches, _ = parse_catches('마눌 쭈4,갑1')
    assert [c['who'] for c in catches] == ['마눌', '마눌']

    catches, _ = parse_catches('가: 쭈3, 나: 쭈5')
    assert [(c['who'], c['count']) for c in catches] == [('가', 3), ('나', 5)]


def test_parse_catches_ignores_percent_and_weight_and_flags_leftover_digits():
    catches, leftover = parse_catches('쭈 10, 입질 60~70%')
    assert catches == [{'who': '나', 'species': '쭈꾸미', 'count': 10}]
    assert leftover is True

    catches, leftover = parse_catches('쭈70%')
    assert catches == [] and leftover is True


def test_parse_catches_no_digits_is_not_a_warning():
    assert parse_catches('꽝') == ([], False)
    assert parse_catches('배 깨끗함') == ([], False)
    assert parse_catches(None) == ([], False)


def test_parse_catches_does_not_treat_na_inside_words_as_person():
    catches, _ = parse_catches('나름 괜찮음 쭈 3')
    assert catches == [{'who': '나', 'species': '쭈꾸미', 'count': 3}]
