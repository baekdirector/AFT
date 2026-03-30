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
