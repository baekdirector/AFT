import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services import reservation_checker


class DummyResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


def test_schedule_fleet_hanchi_falls_back_from_day_block(monkeypatch):
    html = """
    <div id="d2026-07-02" class="shipsinfo_daywarp weekday">
      <div class="date_info2">1물</div>
      <div id="fish">한치</div>

      <table class="ship_unit">
        <tr>
          <td class="ship_info"><div class="title">힐링1호</div><div class="fish">한치</div></td>
          <td class="ship_info2"><span class="number">20</span></td>
        </tr>
      </table>

      <table class="ship_unit">
        <tr>
          <td class="ship_info"><div class="title">힐링2호</div><div class="fish">&#xfeff;&#8203;</div></td>
          <td class="ship_info2"><span class="number">20</span></td>
        </tr>
      </table>
    </div>
    """

    def fake_get(*args, **kwargs):
        return DummyResponse(html)

    monkeypatch.setattr(reservation_checker.requests, "get", fake_get)

    result = reservation_checker.check_single_boat(
        "https://hl.sunsang24.com/ship/schedule_fleet/202607",
        2026,
        7,
        2,
    )

    entries = result["entries"]
    assert len(entries) == 2
    assert entries[0]["fish"] == "한치"
    assert entries[1]["fish"] == "한치"


def test_schedule_fleet_accepts_capacity_suffix_for_known_fleet_names(monkeypatch):
    html = """
    <div id="d2026-05-24" class="shipsinfo_daywarp weekday">
      <div id="fish">한치</div>

      <table class="ship_unit">
        <tr>
          <td class="ship_info"><div class="title">레드헌터(22인승)</div></td>
          <td class="ship_info2"><span class="shipping_status">예약마감</span></td>
        </tr>
      </table>
    </div>
    """

    def fake_get(*args, **kwargs):
        return DummyResponse(html)

    monkeypatch.setattr(reservation_checker.requests, "get", fake_get)

    result = reservation_checker.check_single_boat(
        "https://redhunter.sunsang24.com/ship/schedule_fleet",
        2026,
        5,
        24,
    )

    entries = result["entries"]
    assert len(entries) == 1
    assert entries[0]["ship_name"] == "레드헌터"
    assert entries[0]["status"] == "full"


def test_schedule_fleet_detects_bad_weather_status(monkeypatch):
    html = """
    <div id="d2026-07-24" class="shipsinfo_daywarp weekday">
      <div id="fish">한치</div>

      <table class="ship_unit">
        <tr>
          <td class="ship_info"><div class="title">불꽃호</div></td>
          <td class="ship_info2"><span class="shipping_status">기상악화</span></td>
        </tr>
      </table>
    </div>
    """

    def fake_get(*args, **kwargs):
        return DummyResponse(html)

    monkeypatch.setattr(reservation_checker.requests, "get", fake_get)

    result = reservation_checker.check_single_boat(
        "https://chf.sunsang24.com/ship/schedule_fleet/202607",
        2026,
        7,
        24,
    )

    entries = result["entries"]
    assert len(entries) == 1
    # 기상악화는 'unknown' 이 아니라 전용 상태로 분류된다.
    # PLAN.md 4 상태표의 WEATHER 에 해당하며, 기존 어휘로는 'cancelled' 이다.
    # (status.html 이 cancelled -> danger 클래스로 렌더링한다)
    assert entries[0]["status"] == "cancelled"
    assert entries[0]["display_status"] == "기상악화"
    assert entries[0]["raw_status_text"] == "기상악화"


def test_build_query_url_uses_month_pattern_for_normal_sunsang24():
    url = reservation_checker.build_query_url(
        "https://redhunter.sunsang24.com/ship/schedule_fleet", 2026, 9, 9)
    assert url == "https://redhunter.sunsang24.com/ship/schedule_fleet/202609"


def test_build_query_url_uses_day_ajax_pattern_for_schedule_fleet_simple():
    """schedule_fleet_simple(실측: 24마린낚시)은 월 페이지가 달력 뷰일 뿐 배별
    상태가 없다 - 날짜 클릭 시 JS가 부르는 일별 조각을 직접 요청해야 한다."""
    url = reservation_checker.build_query_url(
        "https://24marine.sunsang24.com/ship/schedule_fleet_simple", 2026, 9, 9)
    assert url == "https://24marine.sunsang24.com/ship/schedule_fleet/20260909/0/simple_day"


def _ship_unit_html(ship_name: str, status_text: str = "예약마감", status_code: str = "END") -> str:
    return f"""
    <table class="ship_unit">
      <tr>
        <td class="ship_info"><div class="title">{ship_name}</div></td>
        <td class="ship_info2">
          <span class="shipping_status" data-status_code="{status_code}">{status_text}</span>
        </td>
      </tr>
    </table>
    """


def test_schedule_fleet_simple_day_fragment_only_keeps_the_registered_ship(monkeypatch):
    """simple_day 조각은 이 배만이 아니라 그날 플랫폼 전체 배 목록을 돌려준다
    (실측: 24마린낚시 요청인데 응답에 다른 배 15척이 같이 왔다). 등록된 이름과
    정확히 일치하는 배만 남고, 남의 배는 구조 신호가 있어도 걸러져야 한다."""
    html = f"""
    <table id="d2026-09-09" class="shipsinfo_daywarp weekday">
      {_ship_unit_html("24마린낚시", "출조공지", "NOTICE")}
      {_ship_unit_html("전혀다른배호", "예약마감", "END")}
      {_ship_unit_html("또다른낚시배호", "예약마감", "END")}
    </table>
    """
    monkeypatch.setattr(reservation_checker.requests, "get",
                        lambda *a, **kw: DummyResponse(html))
    reservation_checker.clear_cache()

    result = reservation_checker.check_single_boat(
        "https://24marine.sunsang24.com/ship/schedule_fleet_simple", 2026, 9, 9,
        known_ship_name="24마린낚시")

    assert [e["ship_name"] for e in result["entries"]] == ["24마린낚시"]


def test_schedule_fleet_simple_source_url_points_to_calendar_page_not_ajax_fragment(monkeypatch):
    """simple_day 조각 URL은 스타일 없는 AJAX 응답이라 사용자에게 보여줄
    "예약 페이지" 링크로는 부적절하다 - 원래 등록한 달력 페이지를 써야 한다."""
    html = f"""
    <table id="d2026-09-09" class="shipsinfo_daywarp weekday">
      {_ship_unit_html("24마린낚시", "출조공지", "NOTICE")}
    </table>
    """
    monkeypatch.setattr(reservation_checker.requests, "get",
                        lambda *a, **kw: DummyResponse(html))
    reservation_checker.clear_cache()

    result = reservation_checker.check_single_boat(
        "https://24marine.sunsang24.com/ship/schedule_fleet_simple", 2026, 9, 9,
        known_ship_name="24마린낚시")

    assert result["source_url"] == "https://24marine.sunsang24.com/ship/schedule_fleet_simple"


def test_schedule_fleet_simple_without_known_ship_name_yields_no_entries(monkeypatch):
    """known_ship_name이 없으면 어떤 행도 이 배 것이라고 확신할 수 없다(플랫폼
    전체 목록이므로) - 아무것도 반환하지 않는 것이 남의 배 데이터를 잘못
    저장하는 것보다 안전하다."""
    html = f"""
    <table id="d2026-09-09" class="shipsinfo_daywarp weekday">
      {_ship_unit_html("24마린낚시", "출조공지", "NOTICE")}
    </table>
    """
    monkeypatch.setattr(reservation_checker.requests, "get",
                        lambda *a, **kw: DummyResponse(html))
    reservation_checker.clear_cache()

    result = reservation_checker.check_single_boat(
        "https://24marine.sunsang24.com/ship/schedule_fleet_simple", 2026, 9, 9,
        known_ship_name=None)

    assert result["entries"] == []


def test_check_single_boat_uses_cache_for_repeated_queries(monkeypatch):
    calls = []
    html = "<div></div>"

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return DummyResponse(html)

    monkeypatch.setattr(reservation_checker.requests, "get", fake_get)
    reservation_checker.clear_cache()

    first = reservation_checker.check_single_boat("https://example.com/boat", 2026, 7, 11)
    second = reservation_checker.check_single_boat("https://example.com/boat", 2026, 7, 11)

    assert first["entries"] == []
    assert second["entries"] == []
    assert len(calls) == 1
