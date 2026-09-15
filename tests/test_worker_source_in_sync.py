"""
worker/ 의 파싱 코드 사본이 src/ 원본과 어긋나지 않았는지 검사한다.

배경: Cloud Run의 "GitHub 연결 + Dockerfile" 배포 방식은 Dockerfile이
있는 폴더 자체를 빌드 컨텍스트로 쓴다(리포 루트를 컨텍스트로 지정하는
옵션이 없다 - 실측: worker/Dockerfile이 src/services/... 를 COPY하려다
"file not found in build context"로 실패했다, 빌드 컨텍스트 크기가
worker/ 폴더 크기와 일치하는 7KB였다). 그래서 worker/ 폴더 안에
services/reservation_checker.py, config/ 를 실제로 복사해 뒀다
(worker/Dockerfile 주석 참고).

복사본을 두면 원본을 고치고 복사를 깜빡할 위험이 생긴다 - 여기서 그
위험을 테스트로 막는다("규칙은 문맥이 아니라 테스트로 강제한다").
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def test_worker_reservation_checker_matches_source_of_truth():
    original = ROOT / 'src' / 'services' / 'reservation_checker.py'
    copy = ROOT / 'worker' / 'services' / 'reservation_checker.py'
    assert _read(copy) == _read(original), (
        'worker/services/reservation_checker.py 가 src/services/reservation_checker.py'
        ' 와 어긋났다 - 원본을 고쳤다면 worker/ 쪽 사본도 그대로 다시 복사해야 한다'
        '(cp src/services/reservation_checker.py worker/services/reservation_checker.py).'
    )


def test_worker_config_constants_matches_source_of_truth():
    original = ROOT / 'src' / 'config' / 'constants.py'
    copy = ROOT / 'worker' / 'config' / 'constants.py'
    assert _read(copy) == _read(original), (
        'worker/config/constants.py 가 src/config/constants.py 와 어긋났다 - '
        '원본을 고쳤다면 worker/ 쪽 사본도 그대로 다시 복사해야 한다.'
    )


def test_worker_config_init_matches_source_of_truth():
    original = ROOT / 'src' / 'config' / '__init__.py'
    copy = ROOT / 'worker' / 'config' / '__init__.py'
    assert _read(copy) == _read(original), (
        'worker/config/__init__.py 가 src/config/__init__.py 와 어긋났다.'
    )
