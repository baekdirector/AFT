"""
등록된 배를 한 척씩 순차 조회해서 "왜 안 나오는지"를 CSV 로 덤프하는 진단 도구.

Phase A0 의 1단계. 추측 대신 측정으로 처방을 고른다. 판정값은 다음과 같다.

  OK              정상적으로 배를 뽑았다
  NETWORK         타임아웃 / 연결 실패
  BLOCKED         403 등 - 차단 또는 경로 오류
  NO_SCHEDULE     정상. 선사가 그 달 일정을 아직 안 올렸다 (페이지에 일정 구조가 없음)
  DATE_NOT_LISTED 일정은 있는데 그 날짜만 없다
  PARSE_FAIL      일정이 버젓이 있는데 못 뽑았다 = 진짜 버그
  EMPTY_RESPONSE  응답이 사실상 비어 있다 (사이트 또는 URL 패턴 문제)

0건을 전부 파싱 실패로 뭉뚱그리면 안 된다. 일정 미등록은 정상 상태이고, 그걸
버그로 오인하면 없는 문제를 쫓게 된다. 그래서 0건일 때만 원본 구조를 한 번 더
확인해 둘을 갈라낸다.

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
import re
import time
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # -> src/
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import requests  # noqa: E402

from services.reservation_checker import (  # noqa: E402
    _headers_for,
    build_query_url,
    check_single_boat,
    clear_cache,
)

LIVE_SHIPS_API = "https://aft-hcwf.onrender.com/api/ships"

CSV_COLUMNS = [
    "name", "city", "port", "host", "platform",
    "elapsed_ms", "verdict", "error", "matched", "entries",
    "statuses", "structure", "final_url",
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


def inspect_structure(url: str, year: int, month: int, day: int) -> dict:
    """빈 결과가 나온 배에 한해 원본 HTML 구조를 한 번 더 확인한다.

    조회 결과가 0건이라고 해서 파서가 틀린 것이 아니다. 선사가 그 달의 배 일정을
    아직 사이트에 올리지 않았으면 페이지는 200 이면서 일정 표 자체가 없다.
    (실례: https://0simi.sunsang24.com/ship/schedule_fleet/202610)
    그 정상 케이스와 진짜 파싱 실패를 갈라내려면 페이지에 일정 구조가 있는지를
    봐야 한다. 요청을 아끼려고 빈 결과일 때만 호출한다.
    """
    from bs4 import BeautifulSoup

    final = build_query_url(url, year, month, day)
    try:
        resp = requests.get(final, headers=_headers_for(final), timeout=15)
    except requests.RequestException as exc:
        return {"ok": False, "note": f"refetch_failed:{exc}"}

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    return {
        "ok": True,
        "bytes": len(html),
        # sunsang24: 날짜 블록과 배 단위 표
        "day_blocks": len(soup.select(".shipsinfo_daywarp")),
        "ship_units": len(soup.select("table.ship_unit")),
        # thefishing 계열: 잔여석/정비 아이콘
        "seat_gifs": len(re.findall(r"r_x_\d+\.gif", html)),
        "fix_gifs": len(re.findall(r"icon_fix_\d+\.gif", html)),
    }


def verdict_for(error: str, matched, entries: list, structure: dict | None) -> str:
    """조회 결과를 한 단어짜리 진단명으로 요약한다."""
    if error.startswith("http_error"):
        return "NETWORK"          # 타임아웃 / 연결 실패
    if error.startswith("http_status"):
        return "BLOCKED"          # 403 등 - 차단 또는 경로 오류
    if entries:
        return "OK"

    # 여기부터는 결과가 0건인 경우. 파서 탓인지 아닌지를 구조로 가른다.
    if not structure or not structure.get("ok"):
        return "EMPTY_UNCHECKED"

    if structure["bytes"] < 1000:
        return "EMPTY_RESPONSE"   # 응답이 사실상 비어 있음 (사이트/URL 문제)

    has_schedule = (structure["day_blocks"] or structure["ship_units"]
                    or structure["seat_gifs"] or structure["fix_gifs"])
    if not has_schedule:
        return "NO_SCHEDULE"      # 정상: 선사가 아직 일정을 안 올렸다

    if matched is False:
        return "DATE_NOT_LISTED"  # 일정은 있는데 그 날짜만 없다
    return "PARSE_FAIL"           # 일정이 버젓이 있는데 못 뽑았다 = 진짜 버그


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

    # 0건일 때만 구조를 한 번 더 본다 (원본 사이트에 불필요한 요청을 늘리지 않는다)
    structure = None
    if not entries and not error:
        time.sleep(0.5)
        structure = inspect_structure(boat["url"], year, month, day)

    return {
        "name": boat["name"],
        "city": boat["city"],
        "port": boat["port"],
        "host": (urlparse(boat["url"]).netloc or "").lower(),
        "platform": classify_platform(boat["url"]),
        "elapsed_ms": elapsed_ms,
        "verdict": verdict_for(error, matched, entries, structure),
        "error": error,
        "matched": "" if matched is None else str(matched),
        "entries": len(entries),
        "statuses": "|".join(sorted({str(e.get("status")) for e in entries})),
        "structure": "" if not structure else ",".join(
            f"{k}={v}" for k, v in structure.items() if k != "ok"),
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
