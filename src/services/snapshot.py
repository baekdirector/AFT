"""
스냅샷 비교 = 이전 관측과 현재 관측을 견줘 '알릴 만한 변화'를 뽑아낸다.

Phase B. 이 모듈에는 DB 도 네트워크도 없다. 순수 함수만 둔다.
저장/조회는 snapshot_repository 가, 수집은 스케줄러가 담당한다.
그래야 전환 규칙을 fixture 없이도 단위 테스트로 100% 덮을 수 있다.

핵심 원칙 두 가지:

1. 알림은 '의미 있는 전환'에만 낸다 (PLAN.md 6).
   자리가 없다가 생긴 것은 알린다. 자리가 6명에서 5명으로 준 것은 알리지 않는다.

2. UNKNOWN 은 절대 알림 대상이 아니다.
   조회 실패나 파싱 실패는 status 가 unknown 으로 떨어지는데, 이걸 상태 변화로
   취급하면 사이트가 잠깐 흔들릴 때마다 가짜 알림이 쏟아진다. unknown 이 끼어드는
   전환은 양방향 모두 무시하고, 마지막으로 확인된 실제 상태를 기준으로 판단한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# 자리가 있다고 보는 상태. 기존 코드/화면이 쓰는 어휘를 그대로 따른다.
# (PLAN.md 4 의 정규화 enum 으로 옮기는 것은 Phase A 어댑터 작업이다)
OPEN_STATUSES = frozenset({'open'})

# 자리가 없다고 보는 상태
CLOSED_STATUSES = frozenset({'full', 'reserved', 'maintenance', 'cancelled'})

# 신뢰할 수 없는 상태. 전환 판단에서 제외한다.
UNRELIABLE_STATUSES = frozenset({'unknown', '', None})

# 전환 종류
SEAT_OPEN = 'SEAT_OPEN'          # 자리 없음 -> 자리 생김 (알림 1순위)
SEAT_GONE = 'SEAT_GONE'          # 자리 있음 -> 자리 없음
STATUS_CHANGE = 'STATUS_CHANGE'  # 그 외 의미 있는 상태 변경


@dataclass(frozen=True)
class Observation:
    """한 시점에 관측한 (배, 날짜, 선박) 하나의 상태.

    DB 행이든 방금 긁은 결과든 이 모양으로 바꿔서 비교한다.
    """
    boat_id: int
    target_date: str          # 'YYYY-MM-DD'
    ship_name: str
    status: str
    available: int | None = None
    display_status: str = ''
    fish: str | None = None
    source_url: str = ''

    @property
    def key(self) -> tuple:
        return (self.boat_id, self.target_date, self.ship_name)

    @property
    def is_reliable(self) -> bool:
        return self.status not in UNRELIABLE_STATUSES

    @property
    def has_seat(self) -> bool:
        """자리가 있다고 볼 수 있는가.

        상태가 open 이면 자리 있음으로 본다. available 숫자가 함께 오면
        그 숫자를 우선한다(0명이면 open 표기여도 자리가 없는 것이다).
        """
        if not self.is_reliable:
            return False

        # 상태가 '자리 없음'을 뜻하면 숫자와 무관하게 자리가 없다.
        # 기존 파서는 예약마감일 때 available 에 잔여석이 아니라 정원을 남긴다
        # (실측: 항성2호 status=full, available=19). 숫자를 먼저 보면 만석을
        # '자리 19개'로 읽어 가짜 알림이 나간다. 기존 화면도 같은 이유로
        # status.html 에서 마감 상태의 잔여석을 0 으로 덮어쓰고 있었다.
        # 파서가 이 값을 바로잡는 것은 Phase A(하네스) 몫이다.
        if self.status in CLOSED_STATUSES:
            return False

        if self.available is not None:
            return self.available > 0
        return self.status in OPEN_STATUSES

    @property
    def effective_status(self) -> str:
        """표기 흔들림을 걷어낸 상태.

        사이트에 따라 만석을 '예약마감'으로도 '남은자리 0명'으로도 쓴다.
        문자열만 보고 비교하면 실제로는 아무 일도 없었는데 상태가 바뀐 것처럼
        보여 가짜 알림이 나간다. 자리 0명인 open 은 full 과 같게 취급한다.
        """
        if self.status in OPEN_STATUSES and self.available == 0:
            return 'full'
        return self.status


@dataclass(frozen=True)
class Transition:
    """알릴 만하다고 판정된 변화 하나."""
    kind: str
    boat_id: int
    target_date: str
    ship_name: str
    previous_status: str
    current_status: str
    previous_available: int | None = None
    current_available: int | None = None
    display_status: str = ''
    source_url: str = ''

    @property
    def dedup_key(self) -> tuple:
        """같은 전환을 두 번 알리지 않기 위한 키 (PLAN.md 6).

        상태가 원복했다가 다시 열리면 다시 알려야 하므로, 키에 시각은 넣지 않고
        '무엇이 무엇으로 바뀌었나'만 넣는다. 중복 방지는 Notification 이력이
        이 키로 판단한다(Phase C).
        """
        return (self.boat_id, self.target_date, self.ship_name,
                self.kind, self.previous_status, self.current_status)


def compare(previous: Observation | None, current: Observation) -> Transition | None:
    """관측 하나를 이전 관측과 견줘 전환을 판정한다.

    돌려주는 값이 None 이면 '알릴 것 없음'이다.
    """
    # 현재가 신뢰할 수 없으면(조회/파싱 실패) 판단하지 않는다.
    if not current.is_reliable:
        return None

    # 처음 보는 (배,날짜,선박) 은 비교 대상이 없다. 첫 관측만으로 알리면
    # 감시를 새로 걸 때마다 이미 열려 있던 자리까지 전부 알림이 나간다.
    if previous is None:
        return None

    # 이전이 신뢰할 수 없으면(직전 수집이 실패했던 경우) 그 실패를 변화로 보지
    # 않는다. 더 과거의 신뢰할 수 있는 관측과 비교하는 것은 호출자 몫이다.
    if not previous.is_reliable:
        return None

    was_open, is_open = previous.has_seat, current.has_seat

    if not was_open and is_open:
        kind = SEAT_OPEN
    elif was_open and not is_open:
        kind = SEAT_GONE
    elif previous.effective_status != current.effective_status:
        # 둘 다 자리는 없지만 사유가 바뀐 경우(정비일 -> 기상악화 등).
        # 표기 흔들림은 effective_status 가 이미 걸러낸다.
        kind = STATUS_CHANGE
    else:
        # 상태도 같고 자리 유무도 같다. 잔여석 숫자만 흔들린 것은 알리지 않는다.
        return None

    return Transition(
        kind=kind,
        boat_id=current.boat_id,
        target_date=current.target_date,
        ship_name=current.ship_name,
        previous_status=previous.status,
        current_status=current.status,
        previous_available=previous.available,
        current_available=current.available,
        display_status=current.display_status,
        source_url=current.source_url,
    )


def diff(previous: Iterable[Observation],
         current: Iterable[Observation]) -> list[Transition]:
    """관측 묶음 두 개를 견줘 전환 목록을 돌려준다.

    출력 순서는 결정론적이다(키 정렬). 같은 입력은 항상 같은 출력을 낸다.
    """
    before = {obs.key: obs for obs in previous}
    transitions = []
    for obs in sorted(current, key=lambda o: o.key):
        change = compare(before.get(obs.key), obs)
        if change is not None:
            transitions.append(change)
    return transitions


def entries_to_observations(boat_id: int, target_date: str,
                            entries: Iterable[dict]) -> list[Observation]:
    """check_single_boat() 의 entries 를 Observation 으로 옮긴다.

    Phase A 에서 어댑터가 Slot 을 내놓게 되면 이 어댑터 함수만 갈아끼우면 된다.
    """
    observations = []
    for entry in entries:
        ship_name = (entry.get('ship_name') or '').strip()
        if not ship_name:
            continue
        available = entry.get('available')
        if isinstance(available, str):
            available = int(available) if available.isdigit() else None
        observations.append(Observation(
            boat_id=boat_id,
            target_date=target_date,
            ship_name=ship_name,
            status=entry.get('status') or 'unknown',
            available=available,
            display_status=entry.get('display_status') or entry.get('raw_status_text') or '',
            fish=entry.get('fish'),
            source_url=entry.get('source_url') or entry.get('url_path') or '',
        ))
    return observations
