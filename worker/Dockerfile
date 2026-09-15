# 예약 스크래핑 워커 이미지. 빌드 컨텍스트는 리포 루트여야 한다
# (Cloud Build 트리거 설정: Dockerfile 경로 worker/Dockerfile, 컨텍스트
# 리포 루트) - 그래야 src/services/reservation_checker.py 와 src/config/
# 를 그대로 복사해 넣을 수 있다. 파싱 로직 원본은 하나뿐이고(worker/app.py
# 주석 참고) 이 이미지는 그 원본을 복사해서 실행할 뿐이다.
FROM python:3.12-slim

WORKDIR /app

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/services/reservation_checker.py ./services/reservation_checker.py
COPY src/config/ ./config/
COPY worker/app.py .

ENV PORT=8080

# --timeout 90: check_single_boat 의 403 재시도 체인(정상 헤더 -> 대체
# 헤더 -> http 폴백)이 최악의 경우 순차로 최대 3번 fetch 할 수 있고,
# 각 fetch 는 REQUEST_TIMEOUT_SECONDS(connect=5, read=10)까지 걸릴 수
# 있어 최악 케이스가 약 45초다 - 그보다 넉넉히 위로 잡는다.
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 90 app:app
