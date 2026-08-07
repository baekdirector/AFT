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
    assert entries[0]["status"] == "unknown"
    assert entries[0]["display_status"] == "기상악화"
    assert entries[0]["raw_status_text"] == "기상악화"


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
