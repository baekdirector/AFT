"""배포(빌드) 시각 표시용. 코드 파일 중 가장 늦게 바뀐 시각(mtime)을 KST 로 돌려준다.

Render 는 배포 때마다 리포를 받아 빌드하므로, 소스 파일 mtime 의 최댓값 = 그 배포가 받은
최신 코드 시각이다. 화면에 찍어 두면 "캐시가 아니라 새 배포가 맞는지" 눈으로 확인할 수 있다.
"""
import os
from datetime import datetime, timedelta

_SRC = os.path.dirname(os.path.abspath(__file__))
_KST_OFFSET = timedelta(hours=9)   # 한국은 서머타임이 없어 고정 오프셋으로 충분하다
_cached = None


def build_time_kst() -> str:
    """'yyyy-mm-dd hh:mm:ss' (KST). 프로세스당 한 번만 계산한다."""
    global _cached
    if _cached is None:
        latest = 0.0
        for root, dirs, files in os.walk(_SRC):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', 'instance', 'node_modules')]
            for name in files:
                if name.endswith(('.py', '.html', '.js', '.json')):
                    try:
                        latest = max(latest, os.path.getmtime(os.path.join(root, name)))
                    except OSError:
                        pass
        stamp = datetime.utcfromtimestamp(latest or datetime.utcnow().timestamp()) + _KST_OFFSET
        _cached = stamp.strftime('%Y-%m-%d %H:%M:%S')
    return _cached
