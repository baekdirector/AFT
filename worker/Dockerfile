# 예약 스크래핑 워커 이미지.
#
# 빌드 컨텍스트는 이 폴더(worker/) 자체다 - Cloud Run의 "GitHub 연결 +
# Dockerfile" 방식(간편 설정 화면)은 Dockerfile이 있는 디렉터리를 그대로
# 빌드 컨텍스트로 쓰고, 리포 루트를 따로 지정하는 옵션이 없다(실측:
# 최초 시도 때 src/services/... 를 COPY하려다 "file not found in build
# context" 로 실패했다 - 그때 로그의 빌드 컨텍스트 크기가 7KB로,
# worker/ 폴더 내용물 크기와 일치했다). 그래서 이 폴더가 자급자족하도록
# services/reservation_checker.py 와 config/ 를 이 폴더 안에 실제로
# 복사해 두었다(원본은 src/services/reservation_checker.py, src/config/
# 그대로다 - 둘이 어긋나지 않는지는 tests/test_worker_source_in_sync.py
# 가 pytest로 매번 검사한다).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ ./services/
COPY config/ ./config/
COPY app.py .

ENV PORT=8080

# --timeout 90: check_single_boat 의 403 재시도 체인(정상 헤더 -> 대체
# 헤더 -> http 폴백)이 최악의 경우 순차로 최대 3번 fetch 할 수 있고,
# 각 fetch 는 REQUEST_TIMEOUT_SECONDS(connect=5, read=10)까지 걸릴 수
# 있어 최악 케이스가 약 45초다 - 그보다 넉넉히 위로 잡는다.
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 90 app:app
