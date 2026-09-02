"""
등록된 배를 한 척씩 순차 조회해서 "왜 안 나오는지"를 CSV 로 덤프하는 진단 도구.

Phase A0 의 1단계. 조회 누락의 원인이
  - 타임아웃/연결 실패 (http_error)
  - 차단          (http_status:403 등)
  - 파싱 실패     (200 인데 entries 가 비어 있음)
중 무엇인지 확정하기 위한 것이다. 추측 대신 측정으로 처방을 고른다.

원본 사이트 배려: 순차 실행 + 요청 간 지연(기본 1.0초). 동시 요청을 내지 않는다.
HTML 본문은 저장하지 않는다 (fixture 캡처는 Phase A 의 capture_fixture.py 담당).

사용법:
    python src/scripts/probe_boats.py                       # 라이브 API 에서 목록을 받아 오늘+3일 조회
    python src/scripts/probe_boats.py --date 2026-09-13
    python src/scripts/probe_boats.py --source db           # 로컬 DB 목록 사용
    python src/scripts/probe_boats.py --delay 2.0 --out probe.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import sys
import time
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # -> src/
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import requests  # noqa: E402

from services.reservation_checker import (  # noqa: E402
    build_query_url,
    check_single_boat,
    clear_cache,
)

LIVE_SHIPS_API = "https://aft-hcwf.onrender.com/api/ships"

CSV_COLUMNS = [
    "name", "city", "port", "host", "platform",
    "elapsed_ms", "verdict", "error", "matched", "entries",
    "statuses", "final_url",
]


def classify_platform(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if "sunsang24.com" in host:
        return "sunsang24"
    if "thefishing.kr" in host:
        return "thefishing"
    return "independent"


def load_boats(source: str, api_url: str) -> list[dict]:
    """(name, city, port, url) dict 리스트를 돌려준다."""
    if source == "api":
        resp = requests.get(api_url, timeout=180)
        resp.raise_for_status()
        return [
            {"name": s.get("name"), "city": s.get("region"),
             "port": s.get("port"), "url": s.get("url")}
            for s in resp.json()
        ]

    from app import create_app  # noqa: WPS433 - DB 를 쓸 때만 Flask 를 띄운다
    from db import get_all_boats

    app = create_app()
    with app.app_context():
        return [
            {"name": b.name, "city": b.city, "port": b.port, "url": b.url}
            for b in get_all_boats()
        ]


def verdict_for(error: str, matched, entries: list) -> str:
    """조회 결과를 한 단어짜리 진단명으로 요약한다."""
    if error.startswith("http_error"):
        return "NETWORK"          # 타임아웃 / 연결 실패
    if error.startswith("http_status"):
        return "BLOCKED"          # 403 등 - 차단 또는 경로 오류
    if matched is False:
        return "NO_DAY_BLOCK"     # 200 인데 해당 날짜 블록을 못 찾음
    if not entries:
        return "PARSE_EMPTY"      # 200 인데 배를 하나도 못 뽑음
    return "OK"


def probe_one(boat: dict, year: int, month: int, day: int) -> dict:
    started = time.monotonic()
    try:
        info = check_single_boat(
            boat["url"], year, month, day, known_ship_name=boat["name"],
        )
    except Exception as exc:  # 실패 격리: 한 척이 전체를 멈추지 않는다
        info = {"error": f"exception:{type(exc).__name__}: {exc}"}
    elapsed_ms = int((time.monotonic() - started) * 1000)

    entries = info.get("entries") or []
    error = str(info.get("error") or "")
    matched = info.get("matched")

    return {
        "name": boat["name"],
        "city": boat["city"],
        "port": boat["port"],
        "host": (urlparse(boat["url"]).netloc or "").lower(),
        "platform": classify_platform(boat["url"]),
        "elapsed_ms": elapsed_ms,
        "verdict": verdict_for(error, matched, entries),
        "error": error,
        "matched": "" if matched is None else str(matched),
        "entries": len(entries),
        "statuses": "|".join(sorted({str(e.get("status")) for e in entries})),
        "final_url": info.get("used_url") or info.get("source_url")
                     or build_query_url(boat["url"], year, month, day),
    }


def main() -> int:
    default_date = datetime.date.today() + datetime.timedelta(days=3)

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=default_date.isoformat(),
                    help="조회할 날짜 YYYY-MM-DD (기본: 오늘+3일)")
    ap.add_argument("--source", choices=["api", "db"], default="api",
                    help="배 목록 출처 (기본: 라이브 API)")
    ap.add_argument("--api-url", default=LIVE_SHIPS_API)
    ap.add_argument("--delay", type=float, default=1.0,
                    help="요청 간 지연 초 (기본: 1.0)")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N척만 (0=전체)")
    ap.add_argument("--out", default="probe_boats.csv")
    args = ap.parse_args()

    target = datetime.date.fromisoformat(args.date)
    boats = load_boats(args.source, args.api_url)
    if args.limit:
        boats = boats[: args.limit]

    clear_cache()  # 캐시가 측정을 오염시키지 않게
    print(f"조회 날짜 {target.isoformat()} / 대상 {len(boats)}척 / 지연 {args.delay}s", flush=True)

    rows = []
    for i, boat in enumerate(boats, 1):
        row = probe_one(boat, target.year, target.month, target.day)
        rows.append(row)
        print(
            f"[{i:>3}/{len(boats)}] {row['verdict']:<13} "
            f"{row['elapsed_ms']:>6}ms  entries={row['entries']:<3} "
            f"{row['name']}  {row['error'][:60]}",
            flush=True,
        )
        if i < len(boats) and args.delay > 0:
            time.sleep(args.delay)

    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n--- 요약 ---  (저장: {args.out})", flush=True)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    for verdict, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:<13} {n:>3}척", flush=True)

    times = sorted(r["elapsed_ms"] for r in rows)
    if times:
        print(f"\n  소요시간  중앙값 {times[len(times) // 2]}ms  "
              f"최대 {times[-1]}ms  합계 {sum(times) / 1000:.1f}s", flush=True)
        print(f"  (동시성 N 으로 나누면 대략적인 벽시계 시간이 나온다)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
