"""1회성 조사 스크립트 - 팀만수 예약 페이지의 공지 행 구조를 눈으로 확인하려고
만들었다. `if __name__` 가드 없이 모듈 최상위에서 바로 외부 사이트를 때리던
버전은 이 파일을 다른 스크립트가 import만 해도 즉시 네트워크 요청이 나가는
사고 위험이 있었다 - 가드를 추가해 `python find_notice.py`로 직접 실행할
때만 동작하게 한다."""
import requests
from bs4 import BeautifulSoup


def main():
    url = 'https://teammansu.kr/index.php?mid=bk'
    resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.content, 'html.parser')

    all_trs = soup.find_all('tr')
    print(f'Total TRs: {len(all_trs)}')
    print()

    # Find TRs containing notice images or text
    for i, tr in enumerate(all_trs):
        tr_str = str(tr)
        imgs = tr.find_all('img')

        # Check for notice patterns
        has_notice_text = '공지' in tr_str
        has_notice_img = any('myfishmap.kr' in img.get('src', '') and '20190709' in img.get('src', '') for img in imgs)

        if has_notice_text or has_notice_img:
            tds = tr.find_all('td')
            print(f'TR {i}: tds={len(tds)}, imgs={len(imgs)}')
            for img in imgs:
                print(f'  IMG: alt={img.get("alt")}, src={img.get("src", "")[:80]}')

            # Show text content
            text = tr.get_text(strip=True)[:200]
            print(f'  Text: {text}')
            print()


if __name__ == '__main__':
    main()
