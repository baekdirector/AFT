"""
Snapshot 표의 읽기/쓰기. DB 를 아는 유일한 곳이다.

전환 판정 규칙은 services/snapshot.py 에 순수 함수로 있고, 여기는 그 함수에
Observation 을 먹이고 결과를 저장하는 배관만 담당한다. 이렇게 갈라두면
규칙은 DB 없이 테스트하고, 배관은 배관대로 테스트할 수 있다.
"""
from __future__ import annotations

from datetime import datetime

from db import db
from models import Snapshot
from services.snapshot import Observation, Transition, diff


def _to_observation(row: Snapshot) -> Observation:
    return Observation(
        boat_id=row.boat_id,
        target_date=row.target_date,
        ship_name=row.ship_name,
        status=row.status,
        available=row.available,
        display_status=row.display_status or '',
        fish=row.fish,
        source_url=row.source_url or '',
    )


def load_observations(boat_id: int, target_date: str) -> list[Observation]:
    """저장된 최신 상태를 Observation 으로 읽어온다."""
    rows = Snapshot.query.filter_by(boat_id=boat_id, target_date=target_date).all()
    return [_to_observation(row) for row in rows]


def load_for_dates(target_dates) -> list[Snapshot]:
    """여러 날짜의 스냅샷을 한 번에 읽는다. /status 가 DB 만 읽을 때 쓴다."""
    dates = list(target_dates)
    if not dates:
        return []
    return (Snapshot.query
            .filter(Snapshot.target_date.in_(dates))
            .order_by(Snapshot.boat_id, Snapshot.target_date, Snapshot.ship_name)
            .all())


def apply_many(target_date: str,
               observations_by_boat: dict[int, list[Observation]]) -> list[Transition]:
    """여러 배의 관측을 한 날짜에 대해 한꺼번에 저장한다.

    라이브 조회(/api/status)가 71척을 긁고 나서 그 결과를 캐시로 남길 때 쓴다.
    배마다 apply_observations 를 부르면 SELECT 와 COMMIT 이 71번씩 붙는데,
    DB 가 다른 대륙에 있으면(Neon 싱가포르) 왕복 지연만으로 십수 초가 늘어난다.
    그래서 해당 날짜의 기존 스냅샷을 한 번에 읽고, 메모리에서 비교한 뒤,
    한 트랜잭션으로 쓴다.

    저장 규칙은 apply_observations 와 같다. 특히 신뢰할 수 없는 관측(unknown)은
    기존 행을 덮지 않는다.
    """
    if not observations_by_boat:
        return []

    boat_ids = list(observations_by_boat)
    rows = (Snapshot.query
            .filter(Snapshot.target_date == target_date,
                    Snapshot.boat_id.in_(boat_ids))
            .all())
    existing = {(r.boat_id, r.target_date, r.ship_name): r for r in rows}

    previous_by_boat: dict[int, list[Observation]] = {}
    for row in rows:
        previous_by_boat.setdefault(row.boat_id, []).append(_to_observation(row))

    now = datetime.utcnow()
    transitions: list[Transition] = []

    for boat_id in sorted(observations_by_boat):
        observations = observations_by_boat[boat_id]
        transitions.extend(diff(previous_by_boat.get(boat_id, []), observations))

        for obs in observations:
            row = existing.get(obs.key)

            if row is not None and not obs.is_reliable:
                row.checked_at = now
                continue

            if row is None:
                row = Snapshot(boat_id=obs.boat_id, target_date=obs.target_date,
                               ship_name=obs.ship_name)
                db.session.add(row)
                existing[obs.key] = row

            row.status = obs.status
            row.available = obs.available
            row.display_status = obs.display_status
            row.fish = obs.fish
            row.source_url = obs.source_url
            row.checked_at = now

    db.session.commit()
    return transitions


def apply_observations(boat_id: int, target_date: str,
                       observations: list[Observation],
                       commit: bool = True) -> list[Transition]:
    """새 관측을 저장하고, 이전 상태와의 전환 목록을 돌려준다.

    저장은 upsert 다. (배,날짜,선박)당 1행을 유지하며 덮어쓴다.

    신뢰할 수 없는 관측(unknown)은 기존 행을 덮어쓰지 않는다. 수집이 한 번
    실패했다고 마지막으로 알던 멀쩡한 상태를 지워버리면, 다음 수집 때 그
    실패를 기준으로 비교하게 되어 변화를 놓치거나 가짜로 만들어낸다.
    """
    previous = load_observations(boat_id, target_date)
    transitions = diff(previous, observations)

    existing = {
        (row.boat_id, row.target_date, row.ship_name): row
        for row in Snapshot.query.filter_by(boat_id=boat_id, target_date=target_date).all()
    }
    now = datetime.utcnow()

    for obs in observations:
        row = existing.get(obs.key)

        if row is not None and not obs.is_reliable:
            # 실패한 수집으로 멀쩡한 기록을 덮지 않는다. 확인 시각만 갱신한다.
            row.checked_at = now
            continue

        if row is None:
            row = Snapshot(boat_id=obs.boat_id, target_date=obs.target_date,
                           ship_name=obs.ship_name)
            db.session.add(row)

        row.status = obs.status
        row.available = obs.available
        row.display_status = obs.display_status
        row.fish = obs.fish
        row.source_url = obs.source_url
        row.checked_at = now

    if commit:
        db.session.commit()
    return transitions
