"""
홈 화면(배 목록) 카드 정렬/등록일 표시 테스트.

get_all_boats() 자체는 id(등록 순서) 오름차순을 그대로 유지한다(엑셀
다운로드 등 다른 화면이 그 순서를 쓰고 있어서) - 홈 화면(index 라우트)
에서만 최신 등록순으로 다시 정렬하고, 각 카드에 등록일(KST)을 붙인다
(사용자 요청).
"""
import datetime

from db import add_boat_instance


def _boat(name, created_at):
    boat = add_boat_instance(name=name, url=f'https://example.com/{name}',
                             city='인천', port='남항(인천항)', note='', is_shared=False)
    boat.created_at = created_at
    from db import db
    db.session.commit()
    return boat


def test_home_page_orders_boats_newest_first(app, client):
    with app.app_context():
        _boat('오래된호', datetime.datetime(2026, 1, 1))
        _boat('중간호', datetime.datetime(2026, 6, 1))
        _boat('최신호', datetime.datetime(2026, 9, 1))

    html = client.get('/').get_data(as_text=True)
    pos_newest = html.index('최신호')
    pos_mid = html.index('중간호')
    pos_oldest = html.index('오래된호')
    assert pos_newest < pos_mid < pos_oldest


def test_home_page_shows_registered_date_per_card(app, client):
    with app.app_context():
        _boat('날짜표시호', datetime.datetime(2026, 3, 15, 1, 0))  # UTC 01:00 -> KST 10:00, 같은 날짜

    html = client.get('/').get_data(as_text=True)
    assert '2026-03-15' in html


def test_home_page_shifts_late_utc_time_to_next_kst_day(app, client):
    """UTC 23:00은 KST로 다음날 08:00이라 등록일이 하루 밀려 보여야 한다."""
    with app.app_context():
        _boat('자정넘김호', datetime.datetime(2026, 3, 15, 23, 0))

    html = client.get('/').get_data(as_text=True)
    assert '2026-03-16' in html
    assert '2026-03-15' not in html.split('자정넘김호')[0][-200:]


def test_boat_without_created_at_sorts_last_and_shows_dash(app, client):
    with app.app_context():
        _boat('최신호2', datetime.datetime(2026, 9, 1))
        boat = add_boat_instance(name='날짜없음호', url='https://example.com/no-date',
                                 city='인천', port='남항(인천항)', note='', is_shared=False)
        boat.created_at = None
        from db import db
        db.session.commit()

    html = client.get('/').get_data(as_text=True)
    assert html.index('최신호2') < html.index('날짜없음호')
