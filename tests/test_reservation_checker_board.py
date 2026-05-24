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


def test_board_pattern_reads_embedded_notice_fish(monkeypatch):
    html = """
    <div id="new-div-20260912" class="new-divs">
      <table>
        <tr>
          <td><span>명성호</span><a>대기하기</a></td>
          <td>
            <table>
              <tr>
                <td><img alt="공지" src="notice.gif"></td>
                <td><p><span><b>쭈&amp;갑</b></span></p></td>
              </tr>
            </table>
          </td>
          <td><div id="admin-right-1">예약마감</div></td>
        </tr>
        <tr>
          <td><span>금강7호</span></td>
          <td>
            <table>
              <tr>
                <td><img alt="공지" src="notice.gif"></td>
                <td>
                  <p><span>쭈꾸미 &amp; 갑오징어</span></p>
                  <p><span>(예약전 공지사항 참고)</span></p>
                </td>
              </tr>
            </table>
          </td>
          <td><div id="admin-right-2">예약마감</div></td>
        </tr>
        <tr>
          <td><span>팀만수</span><a>대기하기</a></td>
          <td>
            <table>
              <tr>
                <td><img alt="공지" src="notice.gif"></td>
                <td><p><span> - 쭈꾸미 &amp; 갑오징어 - </span></p></td>
              </tr>
            </table>
          </td>
          <td><div id="admin-right-3">예약마감</div></td>
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
        9,
        12,
    )

    entries = result["entries"]
    assert [entry["fish"] for entry in entries] == [
        "쭈&갑",
        "쭈꾸미 & 갑오징어",
        "쭈꾸미 & 갑오징어",
    ]
