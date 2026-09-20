# -*- coding: utf-8 -*-
"""record.py 제어판의 "단계 편집(삭제·순서 이동)"과 "저장된 녹화 불러오기"에서
쓰는 순수 함수 모음. record.py는 playwright에 의존해서 단위 테스트가
어렵기 때문에, 판단이 필요한 로직만 여기로 뺐다(네트워크·브라우저 없음)."""
import json
import os
from datetime import datetime


def renumber(steps):
    """단계 id를 1부터 순서대로 다시 매긴다 - 삭제/이동 뒤에도 화면 번호와
    파일 안의 id가 어긋나지 않게 한다. 돌려주는 값은 다음에 쓸 seed."""
    for i, step in enumerate(steps):
        step['id'] = i + 1
    return len(steps)


def delete_step(steps, index):
    if not isinstance(index, int) or not 0 <= index < len(steps):
        return False
    steps.pop(index)
    renumber(steps)
    return True


def move_step(steps, index, delta):
    """index 위치의 단계를 delta(-1=위로, +1=아래로)만큼 옮긴다. 범위를
    벗어나면 아무것도 안 하고 False."""
    if not isinstance(index, int) or not isinstance(delta, int):
        return False
    target = index + delta
    if not (0 <= index < len(steps) and 0 <= target < len(steps)) or delta == 0:
        return False
    steps[index], steps[target] = steps[target], steps[index]
    renumber(steps)
    return True


def is_recording_format(data):
    """record.py가 저장한 형식인지 - /macro 웹에서 내려받은 실행 설정
    (steps에 action 필드가 있고 context가 없음)과 구분한다."""
    if not isinstance(data, dict) or not isinstance(data.get('steps'), list):
        return False
    return all(isinstance(s, dict) and 'context' in s for s in data['steps'])


def list_saved(directory):
    """directory 바로 아래의 녹화 파일(.json)을 최근 수정 순으로 돌려준다.
    읽기 실패·다른 형식 파일은 조용히 건너뛴다."""
    found = []
    for entry in os.listdir(directory):
        if not entry.lower().endswith('.json'):
            continue
        path = os.path.join(directory, entry)
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if not is_recording_format(data):
                continue
            mtime = os.path.getmtime(path)
        except (OSError, ValueError):
            continue
        found.append({
            'file': entry,
            'name': entry[:-5],
            'url': data.get('url') or '',
            'stepCount': len(data['steps']),
            'modified': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M'),
            '_mtime': mtime,
        })
    found.sort(key=lambda item: item['_mtime'], reverse=True)
    for item in found:
        del item['_mtime']
    return found


def load_saved(directory, filename):
    """저장된 녹화 하나를 읽어 dict로 돌려준다. 경로 조작(../ 등)이나 다른
    형식이면 ValueError - 제어판은 로컬 전용이지만 파일명은 요청 본문에서
    오므로 디렉터리 밖은 읽지 않는다."""
    if (not isinstance(filename, str) or not filename.lower().endswith('.json')
            or filename != os.path.basename(filename) or filename in ('.', '..')):
        raise ValueError('잘못된 파일 이름입니다')
    try:
        with open(os.path.join(directory, filename), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError('파일을 읽을 수 없습니다: {}'.format(e))
    if not is_recording_format(data):
        raise ValueError('녹화 파일 형식이 아닙니다')
    return data
