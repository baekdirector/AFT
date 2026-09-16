"""1회성 조사 스크립트 - 두 선사 예약 페이지의 공지 마크업 구조를 눈으로
확인하려고 만들었다. `if __name__` 가드 없이 모듈 최상위에서 바로 외부
사이트를 때리던 버전은 이 파일을 다른 스크립트가 import만 해도 즉시
네트워크 요청이 나가는 사고 위험이 있었다 - 가드를 추가해
`python inspect_html.py`로 직접 실행할 때만 동작하게 한다."""
import requests
from bs4 import BeautifulSoup

URLS = [
    "https://teammansu.kr/index.php?mid=bk&year=2025&month=11&day=22&mode=list&won=1&PA_N_UID=0&sel=day",
    "http://www.kumkangho.co.kr/index.php?mid=bk&year=2025&month=11&day=22&mode=list&won=1&PA_N_UID=0&sel=day",
]


def main():
    for url in URLS:
        print(f"\n==== {url}")
        try:
            resp = requests.get(url, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')

            # 공지 이미지가 있는 모든 태그 찾기
            notice_imgs = soup.find_all('img', alt='공지')
            print(f"Found {len(notice_imgs)} notice images")

            for i, img in enumerate(notice_imgs[:3]):  # 최대 3개만
                parent_tr = img.find_parent('tr')
                if parent_tr:
                    tds = parent_tr.find_all('td')
                    print(f"\nNotice {i+1}:")
                    print(f"  Number of tds: {len(tds)}")
                    if len(tds) >= 2:
                        right_text = tds[1].get_text(' ', strip=True)[:200]
                        print(f"  Right td text: {right_text}")

            # admin-right div도 확인
            adm_divs = soup.select('div[id^="admin-right-"]')
            print(f"\nFound {len(adm_divs)} admin-right divs")

        except Exception as e:
            print(f"Error: {e}")


if __name__ == '__main__':
    main()
