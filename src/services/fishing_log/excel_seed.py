"""기존 낚시 기록 엑셀을 DB 초기값으로 옮기기 위한 순수 변환.

DB·Flask 를 모른다(파싱/IO 분리 원칙). 엑셀은 초기값 설정에 한 번만 쓰고
앱에 업로드 기능은 두지 않는다 - docs/superpowers/specs/
2026-09-30-fishing-log-data-model-design.md §3.
"""
import re

SHOP_ALIASES = {
    '테무': 'Temu',
    'temu': 'Temu',
    'aliexpress': 'AliExpress',
    '에프마켓인천': '에프마켓인천',
}
CATEGORY_ALIASES = {'줄': '라인', '낚시대': '로드'}
DEFAULT_CATEGORY = '기타'

SPECIES_ALIASES = {
    '쭈꾸미': '쭈꾸미', '주꾸미': '쭈꾸미', '쭈구미': '쭈꾸미', '쭈': '쭈꾸미',
    '갑오징어': '갑오징어', '갑': '갑오징어',
    '문어': '문어', '문': '문어',
    '우럭': '우럭', '광어': '광어', '농어': '농어', '놀래미': '놀래미', '낙지': '낙지',
}
PEOPLE = ('나', '마눌', '와이프', '엄마')

_SPECIES_PATTERN = '|'.join(sorted(SPECIES_ALIASES, key=len, reverse=True))
# 어종 뒤 숫자. 숫자 바로 뒤가 %·kg·호·시면 조과가 아니다("쭈70%", "2kg").
_CATCH_RE = re.compile(rf'({_SPECIES_PATTERN})\s*(\d+)(?!\d)(?!\s*(?:%|kg|호|시))')
_PERSON_RE = re.compile(r'(?<![가-힣])(' + '|'.join(PEOPLE) + r')(?![가-힣])')
_COLON_NAME_RE = re.compile(r'([가-힣A-Za-z]+)\s*:')


def _text(value):
    """셀 값을 앞뒤 공백 없는 문자열로. 비었으면 None. 12.0 같은 정수형
    실수는 '12'로."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def to_int(value):
    """금액 칸 → 원 단위 int. 숫자가 아닌 글("11만원")은 None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    text = _text(value)
    if text and re.fullmatch(r'[\d,]+', text):
        return int(text.replace(',', ''))
    return None


def normalize_shop(value):
    text = _text(value)
    if text is None:
        return None
    key = re.sub(r'\s+', '', text).lower()
    return SHOP_ALIASES.get(key, text)


def normalize_category(value):
    text = _text(value)
    if text is None:
        return DEFAULT_CATEGORY
    return CATEGORY_ALIASES.get(text, text)


def ship_match_key(name):
    """선사 이름 비교용 키: 공백 제거, 소문자, 끝의 '호' 제거."""
    key = re.sub(r'\s+', '', name or '').lower()
    if len(key) > 1 and key.endswith('호'):
        key = key[:-1]
    return key


def extract_ship_name(content):
    """출조 '내용' 칸에서 선사명을 뽑는다. ' - '나 '(' 앞부분을 보고, 그 안에
    '호'로 끝나는 단어가 있으면 그 단어를 쓴다. 나머지 글은 메모로 돌려준다
    (추출이 틀리면 스크립트의 --ship-map 으로 바로잡는다)."""
    text = content.strip()
    head = re.split(r'\s+-\s+|\(', text, maxsplit=1)[0].strip()
    # '호' 한 글자 단어("가나다 호")는 선사명이 아니다 - 두 글자 이상만 본다.
    ho_words = [w for w in head.split() if len(w) > 1 and w.endswith('호')]
    name = ho_words[0] if ho_words else (head or text)
    rest = text.replace(name, '', 1).strip(' -')
    rest = re.sub(r'\s{2,}', ' ', rest).strip()
    return name, (rest or None)


def parse_catches(text):
    """조과 문장에서 (사람, 어종, 마릿수)를 뽑는다. 단순한 형태만 인식하고,
    인식에 쓰이지 않은 숫자가 원문에 남아 있으면 두 번째 값을 True 로 돌려
    호출자가 경고하게 한다(틀린 숫자를 넣느니 비워 둔다)."""
    text = _text(text)
    if text is None:
        return [], False
    catches = []
    who = '나'
    pos = 0
    leftovers = []
    for match in _CATCH_RE.finditer(text):
        gap = text[pos:match.start()]
        named = _COLON_NAME_RE.findall(gap)
        people = _PERSON_RE.findall(gap)
        if named:
            who = named[-1]
        elif people:
            who = people[-1]
        catches.append({'who': who, 'species': SPECIES_ALIASES[match.group(1)],
                        'count': int(match.group(2))})
        leftovers.append(gap)
        pos = match.end()
    leftovers.append(text[pos:])
    return catches, bool(re.search(r'\d', ''.join(leftovers)))
