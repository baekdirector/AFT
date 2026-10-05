"""금액 입력칸 계산식(_amount_calc.html)을 Node 로 직접 돌려 검증한다."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / 'src' / 'templates' / '_amount_calc.html'
pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='node 없음')


def _run(inputs):
    js = re.search(r'<script>(.*)</script>', SRC.read_text(encoding='utf-8'), re.S).group(1)
    code = 'global.window = {};' + js + (
        'const out = JSON.parse(process.argv[1]).map(t => window.AmountCalc.evaluate(t));'
        'console.log(JSON.stringify(out));')
    res = subprocess.run(['node', '-e', code, json.dumps(inputs)], capture_output=True, text=True,
                         encoding='utf-8', check=True)
    return json.loads(res.stdout)


@pytest.mark.parametrize('text,value', [
    ('=5000*3', 15000), ('5000*3', 15000), ('=(12000+3000)*2', 30000), ('=30000/4', 7500),
    ('7,144', 7144), ('12000', 12000), ('= 1,500 x 2', 3000), ('=1000×3+500', 3500),
    ('=10/3', 3), ('=-5+10', 5), ('=2*(3+4)', 14),
])
def test_valid_expressions(text, value):
    assert _run([text]) == [{'ok': True, 'value': value}]


def test_empty_is_ok_and_null():
    assert _run(['', '  ', '=']) == [{'ok': True, 'value': None}] * 3


@pytest.mark.parametrize('text', ['=5000*', '=abc', '=1/0', '=-5', '=(1+2', '1+2)', '=1++', 'alert(1)', '=2**3', '5000원'])
def test_invalid_expressions(text):
    assert _run([text]) == [{'ok': False}]
