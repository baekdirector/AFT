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


def test_board_pattern_parses_teammansu_row(monkeypatch):
    html = """
    <div id="new-div-20260330" class="new-divs">
      <table>
        <tr><td>2026년 03월 30일, 월요일, 3물</td><td></td></tr>
        <tr>
          <td>팀만수 예약하기</td>
          <td>- 라이트지깅 (우럭,광어) -</td>
          <td><div id="admin-right-1">남은자리 7명</div></td>
        </tr>
      </table>
    </div>
    """

    def fake_get(*args, **kwargs):
        return DummyResponse(html)

    monkeypatch.setattr(reservation_checker.requests, "get", fake_get)

    result = reservation_checker.check_single_boat(
        "https://teammansu.kr/index.php?mid=bk",
        2026,
        3,
        30,
    )

    assert result.get("error") is None
    assert len(result["entries"]) == 1
    assert result["entries"][0]["ship_name"] == "팀만수"
    assert result["entries"][0]["status"] == "open"
    assert result["entries"][0]["available"] == 7
