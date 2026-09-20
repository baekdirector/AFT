# -*- coding: utf-8 -*-
"""macro_runner/steps_edit.py - record.py 제어판의 단계 삭제·순서 이동과
저장된 녹화 불러오기 규칙. playwright에 의존하는 record.py 대신 그 안에서
쓰는 순수 함수만 검증한다."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'macro_runner'))

import steps_edit  # noqa: E402


def make_steps(n):
    return [{'id': i + 1, 'label': 'S{}'.format(i + 1), 'context': 'main',
             'inputs': [], 'click': None} for i in range(n)]


def labels(steps):
    return [s['label'] for s in steps]


def test_delete_removes_and_renumbers():
    steps = make_steps(4)
    assert steps_edit.delete_step(steps, 1) is True
    assert labels(steps) == ['S1', 'S3', 'S4']
    assert [s['id'] for s in steps] == [1, 2, 3]


@pytest.mark.parametrize('index', [-1, 4, 99, None, '1'])
def test_delete_out_of_range_is_noop(index):
    steps = make_steps(4)
    assert steps_edit.delete_step(steps, index) is False
    assert labels(steps) == ['S1', 'S2', 'S3', 'S4']


def test_move_up_and_down_swap_neighbours_and_renumber():
    steps = make_steps(3)
    assert steps_edit.move_step(steps, 2, -1) is True
    assert labels(steps) == ['S1', 'S3', 'S2']
    assert [s['id'] for s in steps] == [1, 2, 3]
    assert steps_edit.move_step(steps, 0, 1) is True
    assert labels(steps) == ['S3', 'S1', 'S2']


@pytest.mark.parametrize('index,delta', [(0, -1), (2, 1), (5, -1), (1, 0), (1, None)])
def test_move_beyond_edges_is_noop(index, delta):
    steps = make_steps(3)
    assert steps_edit.move_step(steps, index, delta) is False
    assert labels(steps) == ['S1', 'S2', 'S3']


def write_recording(directory, name, steps=2, url='https://x.sunsang24.com/ship/schedule_fleet'):
    (directory / name).write_text(
        json.dumps({'url': url, 'steps': make_steps(steps)}, ensure_ascii=False), encoding='utf-8')


def test_list_saved_keeps_only_recording_format_newest_first(tmp_path):
    write_recording(tmp_path, 'old.json', steps=1)
    write_recording(tmp_path, 'new.json', steps=3)
    import os
    os.utime(tmp_path / 'old.json', (1_000_000_000, 1_000_000_000))
    # /macro 웹에서 내려받은 실행 설정(action 필드, context 없음)·깨진 파일·다른 확장자는 제외
    (tmp_path / 'web.json').write_text(json.dumps({'steps': [{'action': 'click'}]}), encoding='utf-8')
    (tmp_path / 'broken.json').write_text('{not json', encoding='utf-8')
    (tmp_path / 'note.txt').write_text('x', encoding='utf-8')

    result = steps_edit.list_saved(str(tmp_path))

    assert [f['file'] for f in result] == ['new.json', 'old.json']
    assert result[0]['stepCount'] == 3
    assert result[0]['name'] == 'new'
    assert result[0]['url'].startswith('https://')


def test_load_saved_returns_data(tmp_path):
    write_recording(tmp_path, 'red.json', steps=2)
    data = steps_edit.load_saved(str(tmp_path), 'red.json')
    assert len(data['steps']) == 2


@pytest.mark.parametrize('name', ['../red.json', 'sub/red.json', 'red.txt', '', None, '..'])
def test_load_saved_rejects_bad_names(tmp_path, name):
    write_recording(tmp_path, 'red.json')
    with pytest.raises(ValueError):
        steps_edit.load_saved(str(tmp_path), name)


def test_load_saved_rejects_missing_and_wrong_format(tmp_path):
    (tmp_path / 'web.json').write_text(json.dumps({'steps': [{'action': 'click'}]}), encoding='utf-8')
    with pytest.raises(ValueError):
        steps_edit.load_saved(str(tmp_path), 'nope.json')
    with pytest.raises(ValueError):
        steps_edit.load_saved(str(tmp_path), 'web.json')
