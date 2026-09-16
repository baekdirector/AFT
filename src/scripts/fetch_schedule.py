import sys
import os
import requests
from datetime import datetime

def fetch_and_save(final_url: str, out_name: str | None = None):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; fetch-schedule/1.0)"}
    print(f"[HTTP] GET {final_url}")
    resp = requests.get(final_url, headers=headers, timeout=20)
    resp.raise_for_status()
    # ensure encoding
    resp.encoding = resp.apparent_encoding or "utf-8"

    # choose filename: log_HH_MM_SS.txt if not provided
    if not out_name:
        now = datetime.now().strftime("%H_%M_%S")
        out_name = f"log_{now}.txt"

    out_path = os.path.join(os.path.dirname(__file__), out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        # write some metadata then full body
        f.write(f"실행 시간: {datetime.now().isoformat()}\n")
        f.write(f"요청 URL: {final_url}\n")
        f.write(f"최종 URL: {resp.url}\n")
        f.write(f"상태 코드: {resp.status_code}\n\n")
        f.write(resp.text)
    print(f"[OK] status={resp.status_code} saved -> {out_path}")
    # print small preview to terminal
    preview = resp.text[:2000]
    print("------ response preview (first 2000 chars) ------")
    print(preview)
    print("-------------------------------------------------")

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        url = sys.argv[1]
    else:
        url = input("final_url: ").strip()
    try:
        fetch_and_save(url)
    except Exception as e:
        print(f"[ERROR] {e}")